"""Invitation tokens, registration and login."""

from comsocwebapp import auth, db


def test_tokens_are_unique_and_url_safe(app):
    with app.app_context():
        tokens = {auth.generate_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(token.isascii() and "/" not in token and "+" not in token
               for token in tokens)


def test_personal_invitation_is_single_use(app, setting):
    with app.app_context():
        token = auth.create_invitation(setting["id"], is_generic=False)
        invitation = auth.find_invitation(token)
        auth.consume_invitation(invitation)
        assert auth.find_invitation(token) is None


def test_generic_invitation_stays_reusable(app, setting):
    with app.app_context():
        token = auth.create_invitation(setting["id"], is_generic=True)
        auth.consume_invitation(auth.find_invitation(token))
        assert auth.find_invitation(token) is not None


def test_register_via_invitation_then_login(client, app, setting):
    with app.app_context():
        token = auth.create_invitation(setting["id"])

    response = client.post(f"/auth/register?token={token}",
                           data={"email": "Voter@Example.com", "password": "pw"})
    assert response.status_code == 302
    assert f"/vote/{setting['id']}" in response.headers["Location"]

    with app.app_context():
        user = auth.find_user_by_email("voter@example.com")
        assert user is not None and user["is_admin"] == 0
        assert user["password_hash"] != "pw", "password must be hashed"
        # The personal token is now spent.
        assert auth.find_invitation(token) is None

    client.get("/auth/logout")
    assert client.post("/auth/login",
                       data={"email": "voter@example.com", "password": "pw"}
                       ).status_code == 302


def test_generic_link_rejects_a_second_registration_of_the_same_email(client, app, setting):
    with app.app_context():
        token = auth.create_invitation(setting["id"], is_generic=True)

    client.post(f"/auth/register?token={token}",
                data={"email": "same@example.com", "password": "pw"})
    client.get("/auth/logout")
    client.post(f"/auth/register?token={token}",
                data={"email": "same@example.com", "password": "pw2"})

    with app.app_context():
        count = db.query_one("SELECT COUNT(*) AS n FROM users WHERE email = ?",
                             ("same@example.com",))
    assert count["n"] == 1


def test_admin_pages_reject_participants(client, app, setting):
    with app.app_context():
        auth.create_user("plain@example.com", "pw")
    client.post("/auth/login", data={"email": "plain@example.com", "password": "pw"})
    assert client.get("/admin/").status_code == 403


def test_admin_pages_redirect_anonymous(client):
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
