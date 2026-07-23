"""Admin blueprint: define the problem, invite people, simulate, run rules."""

import csv
import io

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, url_for, Response,
)

from . import adapters, db, dummy, rules, setting as setting_api
from .auth import admin_required, create_invitations

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Re-exported from comsocwebapp.setting so that the whole package agrees on
# what the enumerated columns may contain.
PREF_FORMATS = setting_api.PREF_FORMATS
STATUSES = setting_api.STATUSES


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

        try:
            setting_id = setting_api.create_setting(
                title, pref_format, budget_limit=int(budget_limit or 0))
        except ValueError as error:
            flash(str(error), "error")
        else:
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
    try:
        setting_api.update_setting(setting_id, status=request.form.get("status"))
    except ValueError as error:
        flash(str(error), "error")
    else:
        flash(f"Setting is now '{request.form.get('status')}'.", "success")
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------

@bp.route("/settings/<int:setting_id>/options", methods=("POST",))
@admin_required
def add_option(setting_id: int):
    """Append an option; it gets the next free number within this setting."""
    try:
        setting_api.add_option(
            setting_id,
            request.form.get("name") or "",
            request.form.get("description") or "",
            int(request.form.get("cost") or 0),
        )
    except ValueError as error:
        flash(str(error), "error")
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


@bp.route("/settings/<int:setting_id>/options/<int:option_id>/edit",
          methods=("GET", "POST"))
@admin_required
def edit_option(setting_id: int, option_id: int):
    """Edit an option in place, keeping its number and any ballots cast on it."""
    option = setting_api.get_option(option_id)
    if option is None or option["setting_id"] != setting_id:
        return render_template("admin/not_found.html"), 404
    setting = adapters.fetch_setting(setting_id)

    if request.method == "POST":
        try:
            setting_api.update_option(
                option_id,
                name=request.form.get("name") or "",
                description=request.form.get("description") or "",
                cost=int(request.form.get("cost") or 0),
            )
        except ValueError as error:
            flash(str(error), "error")
            return render_template("admin/option_form.html", setting=setting,
                                   option=option)
        flash(f"Option {option['position']} updated.", "success")
        return redirect(url_for("admin.setting_detail", setting_id=setting_id))

    return render_template("admin/option_form.html", setting=setting, option=option)


@bp.route("/settings/<int:setting_id>/options/upload", methods=("POST",))
@admin_required
def upload_options(setting_id: int):
    """Bulk-upload options from a CSV with columns name, description, cost."""
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        flash("Choose a CSV file first.", "error")
        return redirect(url_for("admin.setting_detail", setting_id=setting_id))

    text = io.StringIO(uploaded.read().decode("utf-8-sig"))
    rows = [row for row in csv.DictReader(text) if (row.get("name") or "").strip()]
    # add_options numbers each new option, continuing from whatever is already
    # in the setting.
    setting_api.add_options(setting_id, rows)
    flash(f"Imported {len(rows)} options.", "success")
    return redirect(url_for("admin.setting_detail", setting_id=setting_id))


@bp.route("/settings/<int:setting_id>/options/<int:option_id>/delete", methods=("POST",))
@admin_required
def delete_option(setting_id: int, option_id: int):
    """Delete an option; the remaining ones are renumbered 1..n."""
    option = setting_api.get_option(option_id)
    if option is not None and option["setting_id"] == setting_id:
        setting_api.delete_option(option_id)
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


@bp.route("/settings/<int:setting_id>/dummies/list")
@admin_required
def list_dummies(setting_id: int):
    """Show every dummy voter of this setting with the ballot it carries."""
    setting = adapters.fetch_setting(setting_id)
    if setting is None:
        return render_template("admin/not_found.html"), 404

    options = adapters.fetch_options(setting_id)
    ballots = []
    for voter in adapters.fetch_participants(setting_id, adapters.SCOPE_DUMMY):
        values = {
            row["option_id"]: row["value"]
            for row in adapters.fetch_user_preferences(voter["user_id"], setting_id)
        }
        # Keyed "ballot" not "values": in Jinja, ballot.values would resolve to
        # the dict's .values() method rather than to our data.
        ballots.append({"user_id": voter["user_id"], "ballot": values,
                        "total": sum(value or 0 for value in values.values())})

    return render_template("admin/dummies.html", setting=setting,
                           options=options, ballots=ballots)


@bp.route("/settings/<int:setting_id>/dummies/<int:user_id>/edit",
          methods=("GET", "POST"))
@admin_required
def edit_dummy(setting_id: int, user_id: int):
    """Hand-edit one dummy voter's preferences.

    Only dummy users may be edited here: a real participant's ballot is theirs
    alone, and an admin must never be able to rewrite it.
    """
    setting = adapters.fetch_setting(setting_id)
    voter = db.query_one("SELECT id, is_dummy FROM users WHERE id = ?", (user_id,))
    if setting is None or voter is None or not voter["is_dummy"]:
        return render_template("admin/not_found.html"), 404

    if request.method == "POST":
        submitted = {}
        for option in adapters.fetch_options(setting_id):
            raw = (request.form.get(f"option_{option['id']}") or "0").strip() or "0"
            try:
                submitted[option["id"]] = int(raw)
            except ValueError:
                flash(f"'{raw}' is not a whole number.", "error")
                submitted = None
                break
        if submitted is not None:
            dummy.set_dummy_preferences(user_id, setting_id, submitted)
            flash(f"Updated the ballot of dummy user {user_id}.", "success")
            return redirect(url_for("admin.list_dummies", setting_id=setting_id))

    return render_template(
        "admin/dummy_form.html", setting=setting, user_id=user_id,
        preferences=adapters.fetch_user_preferences(user_id, setting_id))


@bp.route("/settings/<int:setting_id>/dummies/<int:user_id>/delete", methods=("POST",))
@admin_required
def delete_dummy(setting_id: int, user_id: int):
    """Delete a single dummy voter and its ballot."""
    if dummy.delete_dummy_user(user_id):
        flash(f"Deleted dummy user {user_id}.", "success")
    else:
        flash("That user is not a dummy user.", "error")
    return redirect(url_for("admin.list_dummies", setting_id=setting_id))


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
    writer.writerow(["user_id", "is_dummy", "option_id", "option_number",
                     "option_name", "value"])
    for row in rows:
        writer.writerow([row["user_id"], row["is_dummy"], row["option_id"],
                         row["option_position"], row["option_name"], row["value"]])
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
