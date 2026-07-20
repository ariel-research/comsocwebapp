"""Shared fixtures: a fresh app + database per test."""

import os
import tempfile

import pytest

from comsocwebapp import auth, create_app, db


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
        setting_id = db.insert_returning_id(
            "INSERT INTO settings (title, pref_format, status, budget_limit)"
            " VALUES (?, ?, ?, ?)",
            ("Test election", "approval", "open", 100),
        )
        option_ids = [
            db.insert_returning_id(
                "INSERT INTO options (setting_id, name, description, cost)"
                " VALUES (?, ?, ?, ?)",
                (setting_id, name, "", cost),
            )
            for name, cost in (("Alpha", 30), ("Beta", 50), ("Gamma", 60))
        ]
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
