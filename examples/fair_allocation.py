"""Reference implementation: fair allocation of indivisible items.

    python examples/fair_allocation.py

Heirs divide an estate: each declares how much each item is worth to them
(``points`` format, 0-100).  With ``fairpyx`` installed, the admin can run
``fairpyx_round_robin`` on the collected valuations.  Serves on
http://127.0.0.1:5003/.

This example also demonstrates **overriding a template**: it points
TEMPLATE_FOLDER at ``templates-fa/``, which contains a single file --
``participant/index.html``.  That page is replaced; every other page still
comes from the package.
"""

import os

from comsocwebapp import auth, create_app, db, dummy, setting

# --------------------------------------------------------------------------
# Configuration for this example
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))

#: Change this if the port is busy, or to run several examples at once.
PORT = 5003

CONFIG = {
    "DATABASE": os.path.join(HERE, "instance-fa", "fair_allocation.sqlite"),
    "SECRET_KEY": "fair-allocation-example",
    # Our own templates take precedence; anything missing falls back to the
    # package's own copies.
    "TEMPLATE_FOLDER": os.path.join(HERE, "templates-fa"),
    # Leave the package's static files in place.
    "STATIC_FOLDER": None,
}

ITEMS = ["The house", "The car", "The piano", "The paintings",
         "The summer cabin", "The book collection"]

HEIRS = 4


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
            "Estate division",
            pref_format="points",
            budget_limit=100,
            status="open",
            options=[(name, "How much is this worth to you (0-100)?", 0)
                     for name in ITEMS],
        )
        dummy.generate_dummy_users(setting_id, HEIRS, distribution="normal",
                                   low=0, high=100, seed=5)

        print("Admin login: admin@example.com / admin")
        for _ in range(HEIRS):
            token = auth.create_invitation(setting_id)
            print(f"Personal invitation:"
                  f" http://127.0.0.1:{PORT}/auth/invite/{token}")


def build_app():
    """The application factory for this example (also usable via `flask --app`)."""
    return create_app(CONFIG, instance_path=os.path.dirname(CONFIG["DATABASE"]))


if __name__ == "__main__":
    application = build_app()
    seed(application)
    application.run(port=PORT, debug=True)
