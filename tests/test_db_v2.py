"""Version-2 database behaviour: non-destructive init and adapter package."""

from comsocwebapp import db, setting as setting_api


def test_ensure_db_creates_then_preserves(app):
    """ensure_db must not wipe an existing database on a second call."""
    with app.app_context():
        # The `app` fixture already ran init_db(); add a row to detect a wipe.
        setting_id = setting_api.create_setting("Keep me", "approval")
        created = db.ensure_db()          # schema already there
        assert created is False
        assert db.query_one("SELECT id FROM settings WHERE id = ?",
                            (setting_id,)) is not None


def test_ensure_db_creates_when_missing(app):
    with app.app_context():
        db.execute("DROP TABLE settings", commit=True)
        # settings is gone, so the schema counts as missing.
        assert db.schema_exists() is False
        assert db.ensure_db() is True
        assert db.schema_exists() is True


def test_init_db_if_missing_keeps_data(app):
    runner = app.test_cli_runner()
    with app.app_context():
        setting_api.create_setting("survivor", "approval")
    result = runner.invoke(args=["init-db", "--if-missing"])
    assert "Kept the existing database" in result.output
    with app.app_context():
        assert db.query_one("SELECT COUNT(*) AS n FROM settings")["n"] == 1


def test_adapters_generic_names_are_reexported():
    """The adapters package presents the flat API the app code relies on."""
    from comsocwebapp import adapters
    for name in ("preference_matrix", "approval_sets", "fetch_options",
                 "SCOPE_DUMMY", "to_fairpyx_instance", "fetch_user_preferences"):
        assert hasattr(adapters, name), name
