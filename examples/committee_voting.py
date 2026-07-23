"""Reference implementation: approval-based committee voting.

    python examples/committee_voting.py

Seeds eight candidates and thirty dummy voters, then serves the app on
http://127.0.0.1:5002/.  If ``abcvoting`` is installed, the ``abcvoting_pav``
rule appears in the admin's rule list next to the built-in ``approval_scoring``.
"""

import os

from comsocwebapp import auth, create_app, db, dummy, setting

# --------------------------------------------------------------------------
# Configuration for this example
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))

#: Change this if the port is busy, or to run several examples at once.
PORT = 5002

CONFIG = {
    "DATABASE": os.path.join(HERE, "instance-cv", "committee_voting.sqlite"),
    "SECRET_KEY": "committee-voting-example",
    # None means "use the templates and static files that ship with the
    # package"; point them at your own folder to restyle the application.
    "TEMPLATE_FOLDER": None,
    "STATIC_FOLDER": None,
}

CANDIDATES = ["Avery", "Blake", "Casey", "Devon", "Emery", "Finley", "Gray", "Harper"]


def seed(app):
    """Create the database and its demo content, but only the first time.

    To start over, delete the file at CONFIG["DATABASE"] and run again.
    """
    with app.app_context():
        if not db.ensure_db():
            print(f"Using the existing database at {app.config['DATABASE']}.")
            return

        auth.create_user("admin@example.com", "admin", is_admin=True)
        setting_id = setting.create_setting(
            "Board election 2026",
            pref_format="approval",
            status="open",
            options=[(name, f"Candidate {name}", 0) for name in CANDIDATES],
        )
        dummy.generate_dummy_users(setting_id, 30, approval_rate=0.35, seed=1)
        token = auth.create_invitation(setting_id, is_generic=True)

        print("Admin login: admin@example.com / admin")
        print(f"Shareable invitation:"
              f" http://127.0.0.1:{PORT}/auth/invite/{token}")


def build_app():
    """The application factory for this example (also usable via `flask --app`)."""
    return create_app(CONFIG, instance_path=os.path.dirname(CONFIG["DATABASE"]))


if __name__ == "__main__":
    application = build_app()
    seed(application)
    application.run(port=PORT, debug=True)
