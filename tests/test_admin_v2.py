"""Version-2 admin GUI: option editing, dummy-voter view/edit/delete."""

from comsocwebapp import adapters, auth, db, dummy


def test_edit_option_through_the_gui(app, setting, logged_in_admin):
    with app.app_context():
        option = adapters.fetch_options(setting["id"])[0]
    response = logged_in_admin.post(
        f"/admin/settings/{setting['id']}/options/{option['id']}/edit",
        data={"name": "Renamed", "description": "new", "cost": "42"})
    assert response.status_code == 302

    with app.app_context():
        after = db.query_one("SELECT name, cost, position FROM options WHERE id = ?",
                             (option["id"],))
    assert after["name"] == "Renamed"
    assert after["cost"] == 42
    assert after["position"] == option["position"]   # numbering unchanged


def test_delete_option_via_gui_renumbers(app, setting, logged_in_admin):
    with app.app_context():
        options = adapters.fetch_options(setting["id"])
    logged_in_admin.post(
        f"/admin/settings/{setting['id']}/options/{options[0]['id']}/delete")
    with app.app_context():
        positions = [o["position"] for o in adapters.fetch_options(setting["id"])]
    assert positions == [1, 2]


def test_dummy_list_shows_generated_ballots(app, setting, logged_in_admin):
    """Dummy ballots appear in the single Participation table (V4 Admin #1)."""
    with app.app_context():
        dummy.generate_dummy_users(setting["id"], 4, seed=1)
    response = logged_in_admin.get(f"/admin/settings/{setting['id']}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Participation (4 ballots cast)" in body
    assert body.count("dummy") >= 4    # every dummy row is labelled
    assert body.count("edit") >= 4     # and carries an edit control


def test_admin_can_edit_a_dummy_ballot(app, setting, logged_in_admin):
    with app.app_context():
        [user_id] = dummy.generate_dummy_users(setting["id"], 1, seed=1)
    a, b, c = setting["option_ids"]

    response = logged_in_admin.post(
        f"/admin/settings/{setting['id']}/dummies/{user_id}/edit",
        data={f"option_{a}": "1", f"option_{b}": "0", f"option_{c}": "1"})
    assert response.status_code == 302

    with app.app_context():
        stored = {row["option_id"]: row["value"] for row in db.query_all(
            "SELECT option_id, value FROM preferences WHERE user_id = ?", (user_id,))}
    assert stored == {a: 1, b: 0, c: 1}


def test_admin_can_delete_a_single_dummy(app, setting, logged_in_admin):
    with app.app_context():
        created = dummy.generate_dummy_users(setting["id"], 3, seed=1)
    logged_in_admin.post(
        f"/admin/settings/{setting['id']}/dummies/{created[0]}/delete")
    with app.app_context():
        remaining = db.query_one(
            "SELECT COUNT(*) AS n FROM users WHERE is_dummy = 1")["n"]
        orphan = db.query_one(
            "SELECT COUNT(*) AS n FROM preferences WHERE user_id = ?",
            (created[0],))["n"]
    assert remaining == 2
    assert orphan == 0


def test_admin_cannot_edit_a_real_participants_ballot(app, setting, logged_in_admin):
    """The dummy-edit route must refuse a real user."""
    with app.app_context():
        real_id = auth.create_user("real@example.com", "pw")
    a = setting["option_ids"][0]
    resp_get = logged_in_admin.get(
        f"/admin/settings/{setting['id']}/dummies/{real_id}/edit")
    resp_del = logged_in_admin.post(
        f"/admin/settings/{setting['id']}/dummies/{real_id}/delete")
    assert resp_get.status_code == 404
    # delete route redirects with a flashed error, leaving the user in place
    with app.app_context():
        assert db.query_one("SELECT id FROM users WHERE id = ?", (real_id,)) is not None


def test_set_dummy_preferences_rejects_real_user(app, setting):
    with app.app_context():
        import pytest
        real_id = auth.create_user("r@example.com", "pw")
        with pytest.raises(ValueError):
            dummy.set_dummy_preferences(real_id, setting["id"],
                                        {setting["option_ids"][0]: 1})
