"""Admin blueprint: define the problem, invite people, simulate, run rules."""

from __future__ import annotations

import csv
import io

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, url_for, Response,
)

from . import adapters, db, dummy, rules
from .auth import admin_required, create_invitations

bp = Blueprint("admin", __name__, url_prefix="/admin")

PREF_FORMATS = ("approval", "ranking", "points", "budget")
STATUSES = ("draft", "open", "closed")


# --------------------------------------------------------------------------
# Dashboard and settings
# --------------------------------------------------------------------------

@bp.route("/")
@admin_required
def dashboard():
    """List every setting with live participation counts.

    The counts come from correlated sub-queries rather than
    ``COUNT(DISTINCT ...) FILTER`` or a lateral join, both of which are
    dialect-specific.
    """
    settings = db.query_all(
        "SELECT s.id, s.title, s.pref_format, s.status, s.budget_limit,"
        "       (SELECT COUNT(*) FROM options o WHERE o.setting_id = s.id)"
        "           AS option_count,"
        "       (SELECT COUNT(DISTINCT p.user_id) FROM preferences p"
        "           WHERE p.setting_id = s.id) AS voter_count,"
        "       (SELECT COUNT(*) FROM invitations i WHERE i.setting_id = s.id)"
        "           AS invitation_count"
        " FROM settings s ORDER BY s.id DESC"
    )
    return render_template("admin/dashboard.html", settings=settings)


@bp.route("/settings/new", methods=("GET", "POST"))
@admin_required
def create_setting():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        pref_format = request.form.get("pref_format") or "approval"
        budget_limit = request.form.get("budget_limit") or "0"

        if not title:
            flash("A title is required.", "error")
        elif pref_format not in PREF_FORMATS:
            flash(f"Preference format must be one of {', '.join(PREF_FORMATS)}.", "error")
        else:
            setting_id = db.insert_returning_id(
                "INSERT INTO settings (title, pref_format, status, budget_limit)"
                " VALUES (?, ?, 'draft', ?)",
                (title, pref_format, int(budget_limit or 0)),
            )
            return redirect(url_for("admin.setting_detail", setting_id=setting_id))

    return render_template("admin/setting_form.html", pref_formats=PREF_FORMATS)


@bp.route("/settings/<int:setting_id>")
@admin_required
def setting_detail(setting_id: int):
    setting = adapters.fetch_setting(setting_id)
    if setting is None:
        return render_template("admin/not_found.html"), 404

    return render_template(
        "admin/setting_detail.html",
        setting=setting,
        options=adapters.fetch_options(setting_id),
        invitations=db.query_all(
            "SELECT id, token, is_generic, is_used FROM invitations"
            " WHERE setting_id = ? ORDER BY id",
            (setting_id,),
        ),
        participants=adapters.fetch_participants(setting_id),
        logs=db.query_all(
            "SELECT id, rule_name, outcome, run_log FROM execution_logs"
            " WHERE setting_id = ? ORDER BY id DESC",
            (setting_id,),
        ),
        rule_names=rules.available_rules(),
        scopes=(adapters.SCOPE_ALL, adapters.SCOPE_REAL, adapters.SCOPE_DUMMY),
        statuses=STATUSES,
        distributions=dummy.DISTRIBUTIONS,
    )


@bp.route("/settings/<int:setting_id>/status", methods=("POST",))
@admin_required
def set_status(setting_id: int):
    """Open or lock the ballot ('Monitoring & Deadlines' in design.md)."""
    status = request.form.get("status")
    if status not in STATUSES:
        flash(f"Status must be one of {', '.join(STATUSES)}.", "error")
    else:
        db.execute("UPDATE settings SET status = ? WHERE id = ?", (status, setting_id))
        flash(f"Setting is now '{status}'.", "success")
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------

@bp.route("/settings/<int:setting_id>/options", methods=("POST",))
@admin_required
def add_option(setting_id: int):
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("An option needs a name.", "error")
    else:
        db.execute(
            "INSERT INTO options (setting_id, name, description, cost)"
            " VALUES (?, ?, ?, ?)",
            (setting_id, name, (request.form.get("description") or "").strip(),
             int(request.form.get("cost") or 0)),
        )
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


@bp.route("/settings/<int:setting_id>/options/upload", methods=("POST",))
@admin_required
def upload_options(setting_id: int):
    """Bulk-upload options from a CSV with columns name, description, cost."""
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        flash("Choose a CSV file first.", "error")
        return redirect(url_for("admin.setting_detail", setting_id=setting_id))

    text = io.StringIO(uploaded.read().decode("utf-8-sig"))
    rows = [
        (setting_id, (row.get("name") or "").strip(),
         (row.get("description") or "").strip(), int(row.get("cost") or 0))
        for row in csv.DictReader(text)
        if (row.get("name") or "").strip()
    ]
    if rows:
        db.execute_many(
            "INSERT INTO options (setting_id, name, description, cost)"
            " VALUES (?, ?, ?, ?)",
            rows,
        )
    flash(f"Imported {len(rows)} options.", "success")
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


@bp.route("/settings/<int:setting_id>/options/<int:option_id>/delete", methods=("POST",))
@admin_required
def delete_option(setting_id: int, option_id: int):
    db.execute("DELETE FROM preferences WHERE option_id = ?", (option_id,), commit=False)
    db.execute("DELETE FROM options WHERE id = ? AND setting_id = ?",
               (option_id, setting_id), commit=False)
    db.get_db().commit()
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


# --------------------------------------------------------------------------
# Invitations
# --------------------------------------------------------------------------

@bp.route("/settings/<int:setting_id>/invitations", methods=("POST",))
@admin_required
def make_invitations(setting_id: int):
    count = max(1, min(int(request.form.get("count") or 1), 10_000))
    is_generic = request.form.get("is_generic") == "1"
    tokens = create_invitations(setting_id, count, is_generic)
    flash(f"Generated {len(tokens)} {'generic' if is_generic else 'personal'}"
          f" invitation link(s).", "success")
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


# --------------------------------------------------------------------------
# Dummy users
# --------------------------------------------------------------------------

@bp.route("/settings/<int:setting_id>/dummies", methods=("POST",))
@admin_required
def make_dummies(setting_id: int):
    try:
        created = dummy.generate_dummy_users(
            setting_id,
            count=max(1, min(int(request.form.get("count") or 10), 10_000)),
            distribution=request.form.get("distribution") or "uniform",
            low=int(request.form.get("low") or 0),
            high=int(request.form.get("high") or 100),
            approval_rate=float(request.form.get("approval_rate") or 0.4),
            seed=int(request.form["seed"]) if request.form.get("seed") else None,
        )
        flash(f"Generated {len(created)} dummy users with random preferences.",
              "success")
    except ValueError as error:
        flash(str(error), "error")
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


@bp.route("/settings/<int:setting_id>/dummies/delete", methods=("POST",))
@admin_required
def drop_dummies(setting_id: int):
    removed = dummy.delete_dummy_users(setting_id)
    flash(f"Deleted {removed} dummy users.", "success")
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


# --------------------------------------------------------------------------
# Running a rule
# --------------------------------------------------------------------------

@bp.route("/settings/<int:setting_id>/run", methods=("POST",))
@admin_required
def run(setting_id: int):
    """Execute the chosen rule and store outcome + log in ``execution_logs``."""
    rule_name = request.form.get("rule_name") or ""
    scope = request.form.get("scope") or adapters.SCOPE_ALL
    committee_size = max(1, int(request.form.get("committee_size") or 1))

    try:
        result = rules.run_rule(rule_name, setting_id, scope,
                                committee_size=committee_size)
    except Exception as error:  # a failed run is itself auditable information
        current_app.logger.exception("Rule %s failed on setting %s", rule_name, setting_id)
        result = rules.RuleResult(
            outcome=[],
            log_lines=[f"Rule '{rule_name}' failed on scope '{scope}'.",
                       f"{type(error).__name__}: {error}"],
        )
        flash(f"The rule failed: {error}", "error")
    else:
        flash(f"Rule '{rule_name}' completed.", "success")

    rules.record_execution(setting_id, rule_name, result)
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

@bp.route("/settings/<int:setting_id>/export/preferences.csv")
@admin_required
def export_preferences(setting_id: int):
    """Export anonymised preferences as CSV (emails are never included)."""
    rows = adapters.fetch_preference_rows(setting_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["user_id", "is_dummy", "option_id", "option_name", "value"])
    for row in rows:
        writer.writerow([row["user_id"], row["is_dummy"], row["option_id"],
                         row["option_name"], row["value"]])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition":
                 f"attachment; filename=preferences_{setting_id}.csv"},
    )


@bp.route("/settings/<int:setting_id>/export/logs.csv")
@admin_required
def export_logs(setting_id: int):
    rows = db.query_all(
        "SELECT id, rule_name, outcome, run_log FROM execution_logs"
        " WHERE setting_id = ? ORDER BY id",
        (setting_id,),
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "rule_name", "outcome", "run_log"])
    for row in rows:
        writer.writerow([row["id"], row["rule_name"], row["outcome"], row["run_log"]])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition":
                 f"attachment; filename=execution_logs_{setting_id}.csv"},
    )
