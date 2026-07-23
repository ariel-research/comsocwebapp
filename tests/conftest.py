"""Shared fixtures: a fresh app + database per test."""

import os
import tempfile

import pytest

from comsocwebapp import auth, create_app, db, setting as setting_api


@pytest.fixture
def app():
    handle, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(handle)
    application = create_app({
        "TESTING": True,
        "DATABASE": path,
        "SECRET_KEY": "test",
        "CSRF_ENABLED": False,  # forms are exercised directly, without a browser
        "WTF_CSRF_ENABLED": False,
    })
    with application.app_context():
        db.init_db()
    yield application
    os.unlink(path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def setting(app):
    """An open approval-format setting with three options."""
    with app.app_context():
        setting_id = setting_api.create_setting(
            "Test election", "approval", budget_limit=100, status="open",
            options=[("Alpha", "", 30), ("Beta", "", 50), ("Gamma", "", 60)],
        )
        option_ids = [o["id"] for o in db.query_all(
            "SELECT id FROM options WHERE setting_id = ? ORDER BY position",
            (setting_id,))]
    return {"id": setting_id, "option_ids": option_ids}


@pytest.fixture
def admin_user(app):
    with app.app_context():
        return auth.create_user("admin@example.com", "adminpw", is_admin=True)


@pytest.fixture
def logged_in_admin(client, admin_user):
    client.post("/auth/login",
                data={"email": "admin@example.com", "password": "adminpw"})
    return client
