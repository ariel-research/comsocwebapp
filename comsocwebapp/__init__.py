"""comsocwebapp -- a Flask boilerplate for computational social choice apps.

Typical use::

    from comsocwebapp import create_app
    app = create_app()

or, from the shell::

    flask --app comsocwebapp init-db
    flask --app comsocwebapp run --debug
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import click
from flask import Flask

from . import adapters, admin, auth, db, dummy, participant, rules, security

__version__ = "0.1.0"

__all__ = ["create_app", "adapters", "admin", "auth", "db", "dummy",
           "participant", "rules", "security", "__version__"]


def create_app(test_config: dict | None = None, instance_path: str | None = None) -> Flask:
    """Application factory.

    :param test_config: config values overriding the defaults (tests pass
        ``{"TESTING": True, "DATABASE": ":memory:"}``).
    :param instance_path: where ``comsocwebapp.sqlite`` and the instance
        config live; defaults to Flask's ``<cwd>/instance``.
    """
    app = Flask(__name__, instance_relative_config=True, instance_path=instance_path)
    app.config.from_mapping(
        # Overridden in production via COMSOCWEBAPP_SECRET_KEY; the dev default
        # exists only so that `flask run` works out of the box.
        SECRET_KEY=os.environ.get("COMSOCWEBAPP_SECRET_KEY", "dev"),
        DATABASE=os.environ.get(
            "COMSOCWEBAPP_DATABASE",
            os.path.join(app.instance_path, "comsocwebapp.sqlite"),
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    if test_config is None:
        app.config.from_pyfile("config.py", silent=True)
    else:
        app.config.from_mapping(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    security.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(participant.bp)
    app.add_url_rule("/", endpoint="index")
    app.cli.add_command(create_admin_command)

    @app.context_processor
    def template_globals():
        return {"now": datetime.now(timezone.utc), "version": __version__}

    return app


@click.command("create-admin")
@click.option("--email", prompt=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def create_admin_command(email: str, password: str) -> None:
    """flask create-admin -- create the first administrator account."""
    email = email.strip().lower()
    if auth.find_user_by_email(email) is not None:
        raise click.ClickException(f"{email} is already registered.")
    auth.create_user(email, password, is_admin=True)
    click.echo(f"Administrator {email} created.")
