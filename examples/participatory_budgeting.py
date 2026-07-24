"""Reference implementation: a participatory-budgeting app.

    python examples/participatory_budgeting.py

Seeds five city projects, an admin account (admin@example.com / admin) and
twenty dummy citizens, then serves the app on http://127.0.0.1:5001/.

Each example carries its own PORT and its own database, so several of them can
run side by side on one machine.
"""

import os

from comsocwebapp import adapters, auth, create_app, db, dummy, rules, setting

# --------------------------------------------------------------------------
# Configuration for this example
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))

#: Change this if the port is busy, or to run several examples at once.
PORT = 5001

#: Everything this application does not share with the other examples.
CONFIG = {
    # A database of its own, so the examples never collide.
    "DATABASE": os.path.join(HERE, "instance-pb", "participatory_budgeting.sqlite"),
    "SECRET_KEY": "participatory-budgeting-example",
    # Templates and static files: None means "use the ones that ship with
    # comsocwebapp".  Point them at your own folder to restyle the app -- any
    # template you do not provide still falls back to the package's.
    "TEMPLATE_FOLDER": None,
    "STATIC_FOLDER": None,
}

BUDGET = 800_000

PROJECTS = [
    ("New playground", "Slides and swings in the central park", 250_000),
    ("Bike lanes", "Three kilometres of protected bike lane", 400_000),
    ("Library hours", "Keep the public library open until 22:00", 120_000),
    ("Street trees", "Plant 300 trees along the main avenue", 180_000),
    ("Sports hall roof", "Repair the leaking roof of the sports hall", 500_000),
]


# --------------------------------------------------------------------------
# A rule of this application's own
# --------------------------------------------------------------------------

@rules.register_rule("utilitarian_greedy_pb", formats=("approval", "budget"),
                     needs_budget=True)
def utilitarian_greedy_pb(setting_id, scope=adapters.SCOPE_ALL, **_):
    """Fund projects by raw approval count until the budget runs out.

    A custom rule is just a function returning a :class:`rules.RuleResult`;
    whatever it puts in ``log_lines`` is what admins and participants read on
    the results page.  ``needs_budget=True`` marks it a budgeting rule, so it
    appears for this participatory-budgeting setting but not for a plain
    committee vote (design.md V4 Admin #2).
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


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------

def seed(app):
    """Create the database and its demo content, but only the first time.

    Re-running the example keeps whatever has been collected so far -- votes
    cast against this database survive a restart.

    To start over, delete the database file (its path is CONFIG["DATABASE"])
    and run the example again; or, from a shell::

        flask --app examples.participatory_budgeting:build_app init-db
    """
    with app.app_context():
        if not db.ensure_db():
            print(f"Using the existing database at {app.config['DATABASE']}.")
            return

        auth.create_user("admin@example.com", "admin", is_admin=True)
        # One wrapper call creates the setting and numbers its options 1..5.
        setting_id = setting.create_setting(
            "City budget 2026",
            pref_format="approval",
            budget_limit=BUDGET,
            status="open",
            options=PROJECTS,
        )
        dummy.generate_dummy_users(setting_id, 20, approval_rate=0.5, seed=2026)
        token = auth.create_invitation(setting_id, is_generic=True)

        print(f"Admin login: admin@example.com / admin")
        print(f"Shareable invitation:"
              f" http://127.0.0.1:{PORT}/auth/invite/{token}")


def build_app():
    """The application factory for this example (also usable via `flask --app`)."""
    return create_app(CONFIG, instance_path=os.path.dirname(CONFIG["DATABASE"]))


if __name__ == "__main__":
    application = build_app()
    seed(application)
    application.run(port=PORT, debug=True)
