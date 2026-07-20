"""Reference implementation: fair allocation of indivisible items.

    python examples/fair_allocation.py

Heirs divide an estate: each declares how much each item is worth to them
(``points`` format, 0-100).  With ``fairpyx`` installed, the admin can run
``fairpyx_round_robin`` on the collected valuations.
"""

import os

from comsocwebapp import auth, create_app, db, dummy

ITEMS = ["The house", "The car", "The piano", "The paintings",
         "The summer cabin", "The book collection"]


def seed(app):
    with app.app_context():
        db.init_db()
        auth.create_user("admin@example.com", "admin", is_admin=True)
        setting_id = db.insert_returning_id(
            "INSERT INTO settings (title, pref_format, status, budget_limit)"
            " VALUES (?, 'points', 'open', 100)",
            ("Estate division",),
        )
        for name in ITEMS:
            db.execute(
                "INSERT INTO options (setting_id, name, description, cost)"
                " VALUES (?, ?, ?, 0)",
                (setting_id, name, "How much is this worth to you (0-100)?"),
            )
        dummy.generate_dummy_users(setting_id, 4, distribution="normal",
                                   low=0, high=100, seed=5)
        tokens = [auth.create_invitation(setting_id) for _ in range(4)]

    print("Admin login: admin@example.com / admin")
    for token in tokens:
        print(f"Personal invitation: http://127.0.0.1:5000/auth/invite/{token}")


if __name__ == "__main__":
    instance = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance-fa")
    application = create_app(instance_path=instance)
    seed(application)
    application.run(debug=True)
