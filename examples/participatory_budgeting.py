"""Reference implementation: a participatory-budgeting app.

Run it with::

    python examples/participatory_budgeting.py

It creates its own database in ``instance-pb/``, seeds a setting with five
projects, an admin account (admin@example.com / admin) and twenty dummy
citizens, and then serves the app on http://127.0.0.1:5000/.

The pattern shown here -- ``create_app()``, then a few raw INSERTs inside an
app context, then a custom rule registered with ``@rules.register_rule`` -- is
all a developer needs to adapt the boilerplate to another problem domain.
"""

import os

from comsocwebapp import adapters, auth, create_app, db, dummy, rules

PROJECTS = [
    ("New playground", "Slides and swings in the central park", 250_000),
    ("Bike lanes", "Three kilometres of protected bike lane", 400_000),
    ("Library hours", "Keep the public library open until 22:00", 120_000),
    ("Street trees", "Plant 300 trees along the main avenue", 180_000),
    ("Sports hall roof", "Repair the leaking roof of the sports hall", 500_000),
]

BUDGET = 800_000


@rules.register_rule("utilitarian_greedy_pb")
def utilitarian_greedy_pb(setting_id, scope=adapters.SCOPE_ALL, **_):
    """Fund projects by raw approval count until the budget runs out.

    A custom rule is just a function returning a :class:`rules.RuleResult`;
    whatever it puts in ``log_lines`` is what admins and participants read on
    the results page.
    """
    options = {o["id"]: o for o in adapters.fetch_options(setting_id)}
    support = {oid: 0 for oid in options}
    for approved in adapters.approval_sets(setting_id, scope).values():
        for oid in approved:
            support[oid] += 1

    log = [f"Utilitarian greedy over a budget of {BUDGET}."]
    funded, spent = [], 0
    for oid in sorted(options, key=lambda oid: (-support[oid], oid)):
        cost = options[oid]["cost"]
        if spent + cost <= BUDGET:
            funded.append(oid)
            spent += cost
            log.append(f"  fund {options[oid]['name']}"
                       f" ({support[oid]} approvals, {cost}) -> spent {spent}")
        else:
            log.append(f"  skip {options[oid]['name']}: {cost} does not fit in"
                       f" the remaining {BUDGET - spent}")
    return rules.RuleResult(outcome=funded, log_lines=log)


def seed(app):
    """Create the schema and a ready-to-explore setting."""
    with app.app_context():
        db.init_db()
        auth.create_user("admin@example.com", "admin", is_admin=True)
        setting_id = db.insert_returning_id(
            "INSERT INTO settings (title, pref_format, status, budget_limit)"
            " VALUES (?, 'approval', 'open', ?)",
            ("City budget 2026", BUDGET),
        )
        for name, description, cost in PROJECTS:
            db.execute(
                "INSERT INTO options (setting_id, name, description, cost)"
                " VALUES (?, ?, ?, ?)",
                (setting_id, name, description, cost),
            )
        dummy.generate_dummy_users(setting_id, 20, approval_rate=0.5, seed=2026)
        token = auth.create_invitation(setting_id, is_generic=True)

    print(f"Admin login: admin@example.com / admin")
    print(f"Shareable invitation: http://127.0.0.1:5000/auth/invite/{token}")


if __name__ == "__main__":
    instance = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance-pb")
    application = create_app(instance_path=instance)
    seed(application)
    application.run(debug=True)
