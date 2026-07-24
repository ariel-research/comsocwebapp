"""Version-3 behaviour: format-aware rules, readable outcomes, points limit,
inline dummy voters, and the format-dependent parts of the admin page."""

from comsocwebapp import auth, db, rules, setting as setting_api


# --------------------------------------------------------------------------
# Rules filtered by preference format (Admin #5) + readable outcome (#7)
# --------------------------------------------------------------------------

def _fmt(pref_format, budget_limit=0):
    return {"pref_format": pref_format, "budget_limit": budget_limit}


def test_available_rules_are_narrowed_by_format_and_budget():
    committee = _fmt("approval", 0)          # plain committee voting
    budgeting = _fmt("approval", 800_000)    # participatory budgeting
    # Committee rules only for approval-without-budget.
    assert "approval_scoring" in rules.available_rules(committee)
    assert "approval_scoring" not in rules.available_rules(budgeting)
    # Budgeting rules only once there is a budget (design.md V4 Admin #2).
    assert "greedy_budget" in rules.available_rules(budgeting)
    assert "greedy_budget" not in rules.available_rules(committee)
    assert "borda" in rules.available_rules(_fmt("ranking"))
    # The unfiltered call still returns everything.
    assert set(rules.available_rules(committee)) <= set(rules.available_rules())


def test_describe_outcome_uses_position_name_and_description(app):
    with app.app_context():
        sid = setting_api.create_setting(
            "S", "approval",
            options=[("Ada", "logician", 0), ("Alan", "", 0)])
        ids = [o["id"] for o in db.query_all(
            "SELECT id FROM options WHERE setting_id = ? ORDER BY position", (sid,))]
        labels = rules.describe_outcome(sid, f"{ids[0]}, {ids[1]}")
    assert labels == ["1. Ada — logician", "2. Alan"]


def test_describe_outcome_falls_back_for_non_ids(app):
    with app.app_context():
        sid = setting_api.create_setting("S", "points",
                                         options=[("Item", "", 0)])
        # A fairpyx-style allocation token is not a bare id: shown verbatim.
        assert rules.describe_outcome(sid, "7:Item|Other") == ["7:Item|Other"]


# --------------------------------------------------------------------------
# Points limit (Participant #1)
# --------------------------------------------------------------------------

def _points_setting(app, limit):
    with app.app_context():
        sid = setting_api.create_setting(
            "Estate", "points", budget_limit=limit, status="open",
            options=[("House", "", 0), ("Car", "", 0), ("Piano", "", 0)])
        ids = [o["id"] for o in db.query_all(
            "SELECT id FROM options WHERE setting_id = ? ORDER BY position", (sid,))]
        token = auth.create_invitation(sid)
    return sid, ids, token


def _register(client, token, email):
    client.post(f"/auth/register?token={token}",
                data={"email": email, "password": "pw"})


def test_points_ballot_must_hit_the_limit(client, app):
    sid, ids, token = _points_setting(app, 100)
    _register(client, token, "heir@example.com")

    # Sum 90 != 100 -> rejected, re-rendered (200), nothing stored.
    bad = client.post(f"/vote/{sid}", data={f"option_{ids[0]}": "40",
                                            f"option_{ids[1]}": "30",
                                            f"option_{ids[2]}": "20"})
    assert bad.status_code == 200
    with app.app_context():
        assert db.query_one("SELECT COUNT(*) AS n FROM preferences")["n"] == 0

    # Sum exactly 100 -> accepted (redirect to receipt).
    good = client.post(f"/vote/{sid}", data={f"option_{ids[0]}": "40",
                                             f"option_{ids[1]}": "30",
                                             f"option_{ids[2]}": "30"})
    assert good.status_code == 302
    with app.app_context():
        assert db.query_one("SELECT SUM(value) AS s FROM preferences")["s"] == 100


def test_points_without_a_limit_are_unconstrained(app):
    """Zero limit means each value is independent (fair-allocation opt-out)."""
    from comsocwebapp.participant import _validate
    with app.app_context():
        assert _validate("points", {1: 80, 2: 55}, 0) is None


def test_points_ballot_shows_normalize_button(client, app):
    sid, ids, token = _points_setting(app, 100)
    _register(client, token, "heir2@example.com")
    body = client.get(f"/vote/{sid}").get_data(as_text=True)
    assert "Normalize" in body
    assert "Distribute exactly 100 points" in body


# --------------------------------------------------------------------------
# Admin page is shaped by the format (Specific #1, #2)
# --------------------------------------------------------------------------

def test_budget_setting_shows_cost_and_committee_hidden(app, logged_in_admin):
    with app.app_context():
        sid = setting_api.create_setting("PB", "budget", budget_limit=100,
                                         options=[("Park", "", 40)])
    body = logged_in_admin.get(f"/admin/settings/{sid}").get_data(as_text=True)
    assert "budget limit" in body           # shown for budgeting
    assert "committee size" not in body     # irrelevant for budgeting (#2)
    assert "<th>Cost</th>" in body          # cost column present


def test_committee_setting_hides_cost_shows_committee(app, logged_in_admin):
    """A plain approval vote (no budget) is committee voting: committee size is
    relevant, cost and budget are not (V3 Specific #1/#2)."""
    with app.app_context():
        sid = setting_api.create_setting("Board", "approval", budget_limit=0,
                                         options=[("Ada", "", 0)])
    body = logged_in_admin.get(f"/admin/settings/{sid}").get_data(as_text=True)
    assert "committee size" in body         # relevant for committee voting
    assert "<th>Cost</th>" not in body      # cost hidden (#1)
    assert "budget limit" not in body       # budget hidden (#1)


# --------------------------------------------------------------------------
# Run-a-rule keeps its selection and jumps back to the heading (Admin #2)
# --------------------------------------------------------------------------

def test_run_redirects_back_to_the_form_with_its_values(app, setting, logged_in_admin):
    # The fixture is approval + a budget, so it offers budgeting rules.
    response = logged_in_admin.post(
        f"/admin/settings/{setting['id']}/run",
        data={"rule_name": "greedy_budget", "scope": "dummy",
              "committee_size": "2"})
    assert response.status_code == 302
    location = response.headers["Location"]
    assert "rule_name=greedy_budget" in location
    assert "scope=dummy" in location
    assert location.endswith("#run")

    # Following it, the form is pre-selected with those values.
    body = logged_in_admin.get(location).get_data(as_text=True)
    assert 'value="greedy_budget" selected' in body
    assert 'value="dummy" selected' in body
