"""Every page renders, and CSRF protection is active when enabled."""

import pytest

from comsocwebapp import auth, create_app, db, dummy


def test_all_admin_and_participant_pages_render(app, setting, logged_in_admin):
    with app.app_context():
        auth.create_invitation(setting["id"], is_generic=True)
        dummy.generate_dummy_users(setting["id"], 3, seed=1)
        logged_in_admin.post(f"/admin/settings/{setting['id']}/run",
                             data={"rule_name": "approval_scoring", "scope": "dummy",
                                   "committee_size": "2"})

    for path in ("/", "/admin/", "/admin/settings/new",
                 f"/admin/settings/{setting['id']}",
                 f"/admin/settings/{setting['id']}/export/preferences.csv",
                 f"/admin/settings/{setting['id']}/export/logs.csv",
                 f"/vote/{setting['id']}",
                 f"/vote/{setting['id']}/receipt",
                 f"/results/{setting['id']}",
                 "/auth/login"):
        response = logged_in_admin.get(path)
        assert response.status_code == 200, f"{path} returned {response.status_code}"


def test_missing_setting_returns_404(logged_in_admin):
    assert logged_in_admin.get("/admin/settings/999").status_code == 404
    assert logged_in_admin.get("/vote/999").status_code == 404


def test_results_page_names_the_winners(client, app, setting):
    a, b, _ = setting["option_ids"]
    with app.app_context():
        user_id = auth.create_user("v@example.com", "pw")
        db.upsert_preference(user_id, setting["id"], a, 1)
        db.execute("INSERT INTO execution_logs (setting_id, rule_name, outcome, run_log)"
                   " VALUES (?, 'approval_scoring', ?, 'because')",
                   (setting["id"], f"{a}, {b}"))
    client.post("/auth/login", data={"email": "v@example.com", "password": "pw"})

    body = client.get(f"/results/{setting['id']}").get_data(as_text=True)
    assert "Alpha" in body and "Beta" in body   # ids resolved to option names
    assert "because" in body                    # the log is shown to participants


@pytest.fixture
def csrf_app(tmp_path):
    """A second app with CSRF left on, to prove the guard actually fires."""
    application = create_app({"TESTING": True, "SECRET_KEY": "test",
                              "DATABASE": str(tmp_path / "csrf.sqlite")})
    with application.app_context():
        db.init_db()
        auth.create_user("admin@example.com", "pw", is_admin=True)
    return application


def test_post_without_csrf_token_is_rejected(csrf_app):
    client = csrf_app.test_client()
    assert client.post("/auth/login",
                       data={"email": "admin@example.com", "password": "pw"}
                       ).status_code == 400


def test_post_with_the_form_token_succeeds(csrf_app):
    client = csrf_app.test_client()
    with client:
        client.get("/auth/login")
        from flask import session
        token = session["_csrf_token"]
    assert client.post("/auth/login",
                       data={"email": "admin@example.com", "password": "pw",
                             "csrf_token": token}).status_code == 302
