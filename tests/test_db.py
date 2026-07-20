"""The database layer: schema creation and the portable UPSERT idiom."""

import sqlite3

import pytest

from comsocwebapp import db


def test_init_db_creates_every_table(app):
    with app.app_context():
        names = {
            row["name"] for row in db.query_all(
                "SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"users", "settings", "options", "invitations",
            "preferences", "execution_logs"} <= names


def test_upsert_preference_inserts_then_updates(app, setting):
    with app.app_context():
        user_id = db.insert_returning_id(
            "INSERT INTO users (email, is_admin, is_dummy) VALUES (?, 0, 0)",
            ("voter@example.com",))
        option_id = setting["option_ids"][0]

        db.upsert_preference(user_id, setting["id"], option_id, 1)
        db.upsert_preference(user_id, setting["id"], option_id, 0)

        rows = db.query_all(
            "SELECT value FROM preferences WHERE user_id = ? AND option_id = ?",
            (user_id, option_id))
    assert rows == [{"value": 0}], "the second write must replace, not duplicate"


def test_parameters_are_bound_not_interpolated(app, setting):
    """A quote-heavy title must survive verbatim -- no injection, no error."""
    nasty = "Robert'); DROP TABLE settings;--"
    with app.app_context():
        db.execute(
            "INSERT INTO settings (title, pref_format, status, budget_limit)"
            " VALUES (?, 'approval', 'draft', 0)", (nasty,))
        stored = db.query_one("SELECT title FROM settings WHERE title = ?", (nasty,))
        still_there = db.query_all("SELECT id FROM settings")
    assert stored["title"] == nasty
    assert len(still_there) == 2


def test_unique_email_blocks_double_registration(app):
    with app.app_context():
        db.execute("INSERT INTO users (email, is_admin, is_dummy) VALUES (?, 0, 0)",
                   ("dup@example.com",))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO users (email, is_admin, is_dummy) VALUES (?, 0, 0)",
                       ("dup@example.com",))
