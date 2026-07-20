"""Reference implementation: approval-based committee voting.

    python examples/committee_voting.py

Seeds eight candidates and thirty dummy voters, then serves the app.  If
``abcvoting`` is installed the ``abcvoting_pav`` rule appears in the admin's
rule list next to the built-in ``approval_scoring``.
"""

import os

from comsocwebapp import auth, create_app, db, dummy

CANDIDATES = ["Avery", "Blake", "Casey", "Devon", "Emery", "Finley", "Gray", "Harper"]


def seed(app):
    with app.app_context():
        db.init_db()
        auth.create_user("admin@example.com", "admin", is_admin=True)
        setting_id = db.insert_returning_id(
            "INSERT INTO settings (title, pref_format, status, budget_limit)"
            " VALUES (?, 'approval', 'open', 0)",
            ("Board election 2026",),
        )
        for name in CANDIDATES:
            db.execute(
                "INSERT INTO options (setting_id, name, description, cost)"
                " VALUES (?, ?, ?, 0)",
                (setting_id, name, f"Candidate {name}"),
            )
        dummy.generate_dummy_users(setting_id, 30, approval_rate=0.35, seed=1)
        token = auth.create_invitation(setting_id, is_generic=True)

    print("Admin login: admin@example.com / admin")
    print(f"Shareable invitation: http://127.0.0.1:5000/auth/invite/{token}")


if __name__ == "__main__":
    instance = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance-cv")
    application = create_app(instance_path=instance)
    seed(application)
    application.run(debug=True)
