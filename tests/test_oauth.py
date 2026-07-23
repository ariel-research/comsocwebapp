"""OAuth wiring: graceful degradation, provider identity extraction, linking.

These tests never talk to a real provider.  They cover the parts that are our
responsibility -- configuration, availability, identity parsing, and how a
returning provider account maps onto the users table -- with the Authlib client
stubbed out.
"""

import pytest

from comsocwebapp import auth, create_app, db, oauth


def test_no_providers_without_credentials(app):
    """With no client ids configured, the feature is simply absent."""
    with app.test_request_context():
        assert oauth.configured_providers(app) == []


def test_login_page_has_no_provider_buttons_by_default(client):
    body = client.get("/auth/login").get_data(as_text=True)
    assert "Continue with" not in body


def test_oauth_route_is_safe_when_unconfigured(client):
    """Hitting the route without configuration redirects, never 500s."""
    response = client.get("/auth/oauth/github")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_configured_providers_needs_both_id_and_secret(tmp_path):
    application = create_app({
        "TESTING": True, "SECRET_KEY": "t",
        "DATABASE": str(tmp_path / "o.sqlite"),
        "OAUTH_GITHUB_CLIENT_ID": "id-only",   # secret missing on purpose
    })
    with application.app_context():
        db.init_db()
    with application.test_request_context():
        # Missing secret -> not offered.  (Also covers the Authlib-absent case,
        # since configured_providers() returns [] when Authlib is not present.)
        names = [p.name for p in oauth.configured_providers(application)]
    assert "github" not in names


def test_github_identity_reads_profile_and_falls_back_for_private_email():
    class FakeResponse:
        def __init__(self, payload): self._payload = payload
        def json(self): return self._payload

    class FakeClient:
        def get(self, path, token=None):
            if path == "user":
                return FakeResponse({"id": 4242, "login": "octocat", "email": None})
            if path == "user/emails":
                return FakeResponse([
                    {"email": "secondary@example.com", "primary": False, "verified": True},
                    {"email": "octocat@example.com", "primary": True, "verified": True},
                ])
            raise AssertionError(path)

    subject, email, name = oauth.fetch_identity("github", FakeClient(), token={})
    assert subject == "4242"
    assert email == "octocat@example.com"   # the primary, verified address
    assert name == "octocat"


def test_orcid_identity_has_no_email():
    subject, email, name = oauth.fetch_identity(
        "orcid", client=None, token={"orcid": "0000-0002-1825-0097", "name": "Josiah"})
    assert subject == "0000-0002-1825-0097"
    assert email is None          # ORCID does not release an address
    assert name == "Josiah"


def test_provider_account_maps_to_a_user(app):
    """A provider identity resolves to exactly one users row."""
    with app.app_context():
        user_id = auth.create_user("orcid-person@example.com", None,
                                   auth_provider="orcid", auth_subject="0000-0001")
        found = auth.find_user_by_provider("orcid", "0000-0001")
        assert found["id"] == user_id
        # A password login is impossible for this account.
        assert found["password_hash"] is None
        assert auth.find_user_by_provider("orcid", "does-not-exist") is None
