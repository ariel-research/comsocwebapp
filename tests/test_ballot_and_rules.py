"""End-to-end: cast ballots, run a rule, read the log back."""

from comsocwebapp import adapters, auth, db, rules


def _voter(client, app, setting_id, email):
    with app.app_context():
        token = auth.create_invitation(setting_id)
    client.post(f"/auth/register?token={token}", data={"email": email, "password": "pw"})


def test_casting_a_ballot_writes_preferences(client, app, setting):
    _voter(client, app, setting["id"], "a@example.com")
    a, b, c = setting["option_ids"]

    response = client.post(f"/vote/{setting['id']}", data={
        f"option_{a}": ["0", "1"],   # ticked checkbox posts hidden 0 then 1
        f"option_{b}": "0",
        f"option_{c}": ["0", "1"],
    })
    assert response.status_code == 302

    with app.app_context():
        stored = {row["option_id"]: row["value"]
                  for row in db.query_all("SELECT option_id, value FROM preferences")}
    assert stored == {a: 1, b: 0, c: 1}


def test_editing_a_ballot_replaces_it(client, app, setting):
    _voter(client, app, setting["id"], "b@example.com")
    a, b, c = setting["option_ids"]
    for value in ("1", "0"):
        client.post(f"/vote/{setting['id']}",
                    data={f"option_{a}": ["0", value] if value == "1" else "0",
                          f"option_{b}": "0", f"option_{c}": "0"})

    with app.app_context():
        rows = db.query_all("SELECT value FROM preferences WHERE option_id = ?", (a,))
    assert rows == [{"value": 0}]


def test_closed_ballot_cannot_be_changed(client, app, setting):
    _voter(client, app, setting["id"], "c@example.com")
    with app.app_context():
        db.execute("UPDATE settings SET status = 'closed' WHERE id = ?", (setting["id"],))

    a = setting["option_ids"][0]
    client.post(f"/vote/{setting['id']}", data={f"option_{a}": ["0", "1"]})

    with app.app_context():
        assert db.query_one("SELECT COUNT(*) AS n FROM preferences")["n"] == 0


def test_invalid_ranking_is_rejected(client, app, setting):
    with app.app_context():
        db.execute("UPDATE settings SET pref_format = 'ranking' WHERE id = ?",
                   (setting["id"],))
    _voter(client, app, setting["id"], "d@example.com")
    a, b, c = setting["option_ids"]

    response = client.post(f"/vote/{setting['id']}",
                           data={f"option_{a}": "1", f"option_{b}": "1",
                                 f"option_{c}": "3"})
    assert response.status_code == 200  # re-rendered with an error, not a redirect
    with app.app_context():
        assert db.query_one("SELECT COUNT(*) AS n FROM preferences")["n"] == 0


def test_approval_scoring_and_execution_log(app, setting, logged_in_admin):
    a, b, c = setting["option_ids"]
    with app.app_context():
        for index, approved in enumerate([{a, b}, {a, b}, {a, c}]):
            user_id = auth.create_user(f"v{index}@example.com", "pw")
            for option_id in approved:
                db.upsert_preference(user_id, setting["id"], option_id, 1)

    logged_in_admin.post(f"/admin/settings/{setting['id']}/run",
                         data={"rule_name": "approval_scoring", "scope": "all",
                               "committee_size": "2"})

    with app.app_context():
        log = db.query_one("SELECT rule_name, outcome, run_log FROM execution_logs"
                           " ORDER BY id DESC")
    assert log["rule_name"] == "approval_scoring"
    assert log["outcome"] == f"{a}, {b}"          # Alpha 3 approvals, Beta 2
    assert "Approval counts" in log["run_log"]


def test_scope_separates_real_and_dummy_voters(app, setting):
    with app.app_context():
        from comsocwebapp import dummy
        real = auth.create_user("real@example.com", "pw")
        db.upsert_preference(real, setting["id"], setting["option_ids"][0], 1)
        dummy.generate_dummy_users(setting["id"], 5, seed=1)

        assert len(adapters.fetch_participants(setting["id"], adapters.SCOPE_REAL)) == 1
        assert len(adapters.fetch_participants(setting["id"], adapters.SCOPE_DUMMY)) == 5
        assert len(adapters.fetch_participants(setting["id"], adapters.SCOPE_ALL)) == 6


def test_greedy_budget_respects_the_limit(app, setting):
    a, b, c = setting["option_ids"]   # costs 30, 50, 60; budget 100
    with app.app_context():
        user_id = auth.create_user("e@example.com", "pw")
        for option_id in (a, b, c):
            db.upsert_preference(user_id, setting["id"], option_id, 1)
        result = rules.run_rule("greedy_budget", setting["id"])
        costs = adapters.option_costs(setting["id"], by_name=False)
    assert sum(costs[oid] for oid in result.outcome) <= 100
    assert result.outcome  # something was funded


def test_failed_rule_is_still_logged(app, setting, logged_in_admin):
    logged_in_admin.post(f"/admin/settings/{setting['id']}/run",
                         data={"rule_name": "no_such_rule", "scope": "all"})
    with app.app_context():
        log = db.query_one("SELECT rule_name, outcome, run_log FROM execution_logs"
                           " ORDER BY id DESC")
    assert log["rule_name"] == "no_such_rule"
    assert log["outcome"] == ""
    assert "failed" in log["run_log"]
