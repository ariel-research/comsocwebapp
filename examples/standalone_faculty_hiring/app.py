"""A complete comsocwebapp application in a single file.

A faculty hiring committee shortlists candidates by approval voting.

Run it::

    pip install "comsocwebapp @ git+https://github.com/ariel-research/comsocwebapp"
    python app.py

Then open http://127.0.0.1:5010/ and log in as admin@example.com / admin.

Everything this application needs is in this folder: the configuration, the
problem definition, one custom rule and one overridden template.  Copy the
folder into a repository of your own and it keeps working -- see README.md.
"""

import os

from comsocwebapp import adapters, auth, create_app, db, dummy, rules, setting

# --------------------------------------------------------------------------
# 1. Configuration
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))

#: Port for the development server.
PORT = 5010

CONFIG = {
    # This application's own database, kept next to the code.
    "DATABASE": os.path.join(HERE, "instance", "faculty_hiring.sqlite"),

    # Change this before deploying anywhere real; it signs the session cookie.
    "SECRET_KEY": os.environ.get("SECRET_KEY", "change-me-before-deploying"),

    # Our templates win; whatever we do not provide falls back to the ones
    # inside comsocwebapp.  Set to None to use the package's templates only.
    "TEMPLATE_FOLDER": os.path.join(HERE, "templates"),

    # Our own CSS and images, served at /static.  None uses the package's.
    "STATIC_FOLDER": os.path.join(HERE, "static"),
}

# --------------------------------------------------------------------------
# 2. The problem
# --------------------------------------------------------------------------
COMMITTEE_SIZE = 3

CANDIDATES = [
    ("Dr. Adeyemi", "Algorithmic game theory; 12 papers, 3 in top venues", 0),
    ("Dr. Bianchi", "Machine learning for healthcare; strong teaching record", 0),
    ("Dr. Chen", "Distributed systems; brings an industry collaboration", 0),
    ("Dr. Duarte", "Formal verification; two funded grants", 0),
    ("Dr. Eriksen", "Human-computer interaction; runs a large lab", 0),
    ("Dr. Farouk", "Cryptography; best-paper award last year", 0),
]


# --------------------------------------------------------------------------
# 3. A rule of our own
# --------------------------------------------------------------------------

@rules.register_rule("shortlist_by_approval")
def shortlist_by_approval(setting_id, scope=adapters.SCOPE_ALL, **_):
    """Shortlist the COMMITTEE_SIZE most-approved candidates.

    A rule is any function returning a RuleResult.  Its ``log_lines`` are what
    the committee -- and every candidate -- can read afterwards, which is the
    whole point of running the process in the open.
    """
    names = {o["id"]: o["name"] for o in adapters.fetch_options(setting_id)}
    approvals = {oid: 0 for oid in names}
    for approved in adapters.approval_sets(setting_id, scope).values():
        for oid in approved:
            approvals[oid] += 1

    ranked = sorted(approvals.items(), key=lambda pair: (-pair[1], names[pair[0]]))
    shortlist = [oid for oid, _ in ranked[:COMMITTEE_SIZE]]

    log = [f"Shortlisting the top {COMMITTEE_SIZE} candidates by approvals.",
           "Approvals received:"]
    log += [f"  {names[oid]}: {count}" for oid, count in ranked]
    log.append("Shortlisted: " + ", ".join(names[oid] for oid in shortlist))
    return rules.RuleResult(outcome=shortlist, log_lines=log)


# --------------------------------------------------------------------------
# 4. Seeding -- runs once, on the first start
# --------------------------------------------------------------------------

def seed(app):
    """Create the database only if it does not exist yet.

    Restarting the app must never throw away ballots that were already cast.
    To start over, delete the file at CONFIG["DATABASE"] and run again.
    """
    with app.app_context():
        if not db.ensure_db():
            print(f"Using the existing database at {app.config['DATABASE']}.")
            return

        auth.create_user("admin@example.com", "admin", is_admin=True)
        setting_id = setting.create_setting(
            "Faculty hiring 2026",
            pref_format="approval",
            status="open",
            options=CANDIDATES,
        )
        # A few simulated committee members, so there is something to look at.
        dummy.generate_dummy_users(setting_id, 7, approval_rate=0.45, seed=11)
        token = auth.create_invitation(setting_id, is_generic=True)

        print("Admin login: admin@example.com / admin")
        print(f"Committee invitation: http://127.0.0.1:{PORT}/auth/invite/{token}")


def build_app():
    """Application factory -- also usable as `flask --app app:build_app run`."""
    return create_app(CONFIG, instance_path=os.path.dirname(CONFIG["DATABASE"]))


if __name__ == "__main__":
    application = build_app()
    seed(application)
    application.run(port=PORT, debug=True)
