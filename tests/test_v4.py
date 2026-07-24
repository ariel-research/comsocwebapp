"""Version-4 behaviour: one Participation table for all votes, budget-aware
rule selection, and the extra fair-allocation rules."""

import pytest

from comsocwebapp import auth, db, dummy, rules, setting as setting_api


# --------------------------------------------------------------------------
# Participation shows every vote in one table (Admin #1)
# --------------------------------------------------------------------------

def test_participation_lists_real_and_dummy_votes_together(app, setting, logged_in_admin):
    a, b, c = setting["option_ids"]
    with app.app_context():
        real = auth.create_user("real@example.com", "pw")
        db.upsert_preference(real, setting["id"], a, 1)
        dummy.generate_dummy_users(setting["id"], 2, seed=1)

    body = logged_in_admin.get(f"/admin/settings/{setting['id']}").get_data(as_text=True)
    # One combined table: three ballots, both kinds shown, no separate section.
    assert "Participation (3 ballots cast)" in body
    assert "real@example.com" in body
    assert body.count("real") >= 1 and body.count("dummy") >= 2
    assert "Dummy voters (" not in body        # the old sub-section is gone


def test_only_dummy_rows_are_editable(app, setting, logged_in_admin):
    """Real participants get no edit/delete controls; dummies do."""
    with app.app_context():
        auth.create_user("real@example.com", "pw")  # a real voter...
        real = db.query_one("SELECT id FROM users WHERE email = 'real@example.com'")["id"]
        db.upsert_preference(real, setting["id"], setting["option_ids"][0], 1)
        [d] = dummy.generate_dummy_users(setting["id"], 1, seed=1)

    body = logged_in_admin.get(f"/admin/settings/{setting['id']}").get_data(as_text=True)
    assert f"dummies/{d}/edit" in body          # dummy is editable
    assert f"dummies/{real}/edit" not in body   # real voter is not


# --------------------------------------------------------------------------
# Budget-aware rule selection (Admin #2) -- the PB bug
# --------------------------------------------------------------------------

def test_pb_setting_offers_budgeting_not_committee_rules(app, logged_in_admin):
    """An approval setting *with a budget* is participatory budgeting: it must
    offer budgeting rules and hide committee rules."""
    with app.app_context():
        sid = setting_api.create_setting(
            "City budget", "approval", budget_limit=800_000, status="open",
            options=[("Park", "", 250_000), ("Library", "", 120_000)])
    names = rules.available_rules(
        {"pref_format": "approval", "budget_limit": 800_000})
    assert "greedy_budget" in names
    assert "approval_scoring" not in names
    assert "abcvoting_pav" not in names

    body = logged_in_admin.get(f"/admin/settings/{sid}").get_data(as_text=True)
    assert "greedy_budget" in body
    assert 'value="approval_scoring"' not in body


def test_committee_setting_offers_committee_not_budgeting_rules():
    names = rules.available_rules({"pref_format": "approval", "budget_limit": 0})
    assert "approval_scoring" in names
    assert "greedy_budget" not in names


def test_pb_page_shows_costs_and_budget_and_hides_committee(app, logged_in_admin):
    """PB is approval + budget, so its costs and budget must be visible while
    committee size is not (V3 Specific #1/#2, now applied via the budget)."""
    with app.app_context():
        sid = setting_api.create_setting(
            "City budget", "approval", budget_limit=800_000, status="open",
            options=[("Park", "green space", 250_000)])
    body = logged_in_admin.get(f"/admin/settings/{sid}").get_data(as_text=True)
    assert "<th>Cost</th>" in body          # project costs visible
    assert "budget limit" in body           # spending budget visible
    assert "committee size" not in body     # irrelevant for budgeting


# --------------------------------------------------------------------------
# Extra fair-allocation rules (Examples #1)
# --------------------------------------------------------------------------

def test_fair_allocation_offers_three_fairpyx_rules():
    pytest.importorskip("fairpyx")
    names = rules.available_rules({"pref_format": "points", "budget_limit": 100})
    for name in ("fairpyx_round_robin", "fairpyx_bidirectional_round_robin",
                 "fairpyx_serial_dictatorship"):
        assert name in names


def test_new_fairpyx_rules_run(app):
    pytest.importorskip("fairpyx")
    with app.app_context():
        sid = setting_api.create_setting(
            "Estate", "points", budget_limit=100, status="open",
            options=[("House", "", 0), ("Car", "", 0), ("Piano", "", 0)])
        oids = [o["id"] for o in db.query_all(
            "SELECT id FROM options WHERE setting_id = ? ORDER BY position", (sid,))]
        for i in range(3):
            uid = auth.create_user(f"h{i}@example.com", "pw")
            for j, oid in enumerate(oids):
                db.upsert_preference(uid, sid, oid, 10 * ((i + j) % 3 + 1))
        for name in ("fairpyx_bidirectional_round_robin",
                     "fairpyx_serial_dictatorship"):
            result = rules.run_rule(name, sid)
            assert result.outcome  # produced an allocation
