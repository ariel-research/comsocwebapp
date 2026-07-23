"""Participant blueprint: cast a ballot, get a receipt, read the results."""

from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for,
)

from . import adapters, db
from .auth import login_required

bp = Blueprint("participant", __name__)


@bp.route("/")
def index():
    """List the settings that are currently accepting ballots."""
    open_settings = db.query_all(
        "SELECT id, title, pref_format, status FROM settings"
        " WHERE status = 'open' ORDER BY id DESC"
    )
    return render_template("participant/index.html", settings=open_settings)


def _validate(pref_format: str, values: dict[int, int], budget_limit: int) -> str | None:
    """Return an error message if the ballot violates its format, else None."""
    if pref_format == "approval":
        if any(value not in (0, 1) for value in values.values()):
            return "Approval ballots accept only 0 or 1."
    elif pref_format == "ranking":
        ranks = [value for value in values.values() if value > 0]
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            return ("A ranking must use each of 1, 2, 3, ... exactly once"
                    " (leave unranked options at 0).")
    elif pref_format == "budget":
        if budget_limit and sum(values.values()) > budget_limit:
            return f"Your allocation exceeds the budget of {budget_limit}."
    elif pref_format == "points":
        if any(value < 0 for value in values.values()):
            return "Points must not be negative."
    return None


@bp.route("/vote/<int:setting_id>", methods=("GET", "POST"))
@login_required
def ballot(setting_id: int):
    """Show the ballot and store a submission in the ``preferences`` table."""
    setting = adapters.fetch_setting(setting_id)
    if setting is None:
        return render_template("admin/not_found.html"), 404

    options = adapters.fetch_options(setting_id)
    # Existing answers, so the participant can edit until the deadline.
    current = {
        row["option_id"]: row["value"]
        for row in db.query_all(
            "SELECT option_id, value FROM preferences"
            " WHERE user_id = ? AND setting_id = ?",
            (g.user["id"], setting_id),
        )
    }

    if request.method == "POST":
        if setting["status"] != "open":
            flash("This ballot is closed; preferences can no longer be changed.",
                  "error")
            return redirect(url_for("participant.results", setting_id=setting_id))

        submitted: dict[int, int] = {}
        for option in options:
            # Approval rows post a hidden "0" *and*, when ticked, the checkbox's
            # "1"; taking the last value makes an unticked box read as 0.
            values = request.form.getlist(f"option_{option['id']}")
            raw = (values[-1] if values else "0").strip() or "0"
            try:
                submitted[option["id"]] = int(raw)
            except ValueError:
                flash(f"'{raw}' is not a whole number.", "error")
                return render_template("participant/ballot.html", setting=setting,
                                       options=options, current=current)

        error = _validate(setting["pref_format"], submitted, setting["budget_limit"])
        if error:
            flash(error, "error")
            return render_template("participant/ballot.html", setting=setting,
                                   options=options, current=submitted)

        # One UPSERT-equivalent per option; see db.upsert_preference for why
        # this is an UPDATE-then-INSERT rather than a dialect-specific UPSERT.
        for option_id, value in submitted.items():
            db.upsert_preference(g.user["id"], setting_id, option_id, value)

        return redirect(url_for("participant.receipt", setting_id=setting_id))

    return render_template("participant/ballot.html", setting=setting,
                           options=options, current=current)


@bp.route("/vote/<int:setting_id>/receipt")
@login_required
def receipt(setting_id: int):
    """Confirmation that the ballot was recorded, read back from the table."""
    setting = adapters.fetch_setting(setting_id)
    recorded = db.query_all(
        "SELECT o.name AS option_name, p.value FROM preferences p"
        " JOIN options o ON p.option_id = o.id"
        " WHERE p.user_id = ? AND p.setting_id = ? ORDER BY o.id",
        (g.user["id"], setting_id),
    )
    return render_template("participant/receipt.html", setting=setting,
                           recorded=recorded)


@bp.route("/results/<int:setting_id>")
@login_required
def results(setting_id: int):
    """Latest outcome plus the execution log, alongside the user's own ballot."""
    setting = adapters.fetch_setting(setting_id)
    if setting is None:
        return render_template("admin/not_found.html"), 404

    latest = db.query_one(
        "SELECT id, rule_name, outcome, run_log FROM execution_logs"
        " WHERE setting_id = ? ORDER BY id DESC",
        (setting_id,),
    )
    names = {str(o["id"]): o["name"] for o in adapters.fetch_options(setting_id)}
    winners = []
    if latest and latest["outcome"]:
        winners = [names.get(part.strip(), part.strip())
                   for part in latest["outcome"].split(",") if part.strip()]

    my_ballot = db.query_all(
        "SELECT o.name AS option_name, p.value FROM preferences p"
        " JOIN options o ON p.option_id = o.id"
        " WHERE p.user_id = ? AND p.setting_id = ? ORDER BY o.id",
        (g.user["id"], setting_id),
    )
    return render_template("participant/results.html", setting=setting,
                           latest=latest, winners=winners, my_ballot=my_ballot)
