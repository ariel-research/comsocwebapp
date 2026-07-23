"""Build a database for the load test: one setting, many registered voters.

    python stress/seed_stress.py --users 1000

Creates ``stress/instance/stress.sqlite`` with

* an admin account            ``admin@example.com`` / ``admin``
* ``--users`` participants    ``voter<N>@example.com`` / ``stress-password``
* one open approval setting with ``--options`` candidates
* ``--dummies`` dummy voters, so the rules have data to chew on even before
  the load test casts a single ballot.

Run this once, then start the server against the same database and point
locust at it -- see README.md in this folder.
"""

import argparse
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from comsocwebapp import auth, create_app, db, dummy, setting  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

#: The load test logs in with these.  Keep them in step with locustfile.py.
PASSWORD = "stress-password"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin"
VOTER_EMAIL = "voter{index}@example.com"

CONFIG = {
    "DATABASE": os.path.join(HERE, "instance", "stress.sqlite"),
    "SECRET_KEY": "stress-test",
    # The load test drives the app through a real browser-less client that
    # cannot read a CSRF token out of the HTML, so the guard is off here.
    # Never do this in a deployment that faces the internet.
    "CSRF_ENABLED": False,
}


def build_app():
    return create_app(CONFIG, instance_path=os.path.dirname(CONFIG["DATABASE"]))


def seed(users: int, options: int, dummies: int, fresh: bool) -> None:
    if fresh:
        shutil.rmtree(os.path.dirname(CONFIG["DATABASE"]), ignore_errors=True)

    app = build_app()
    with app.app_context():
        if not db.ensure_db() and not fresh:
            print("A stress database already exists; pass --fresh to rebuild it.")
            return

        started = time.time()
        auth.create_user(ADMIN_EMAIL, ADMIN_PASSWORD, is_admin=True)

        setting_id = setting.create_setting(
            "Load test election",
            pref_format="approval",
            status="open",
            options=[(f"Candidate {n}", f"Candidate number {n}", 0)
                     for n in range(1, options + 1)],
        )

        # The password is hashed once and reused.  Hashing 1000 passwords
        # properly would take minutes and prove nothing: what the load test
        # measures is the application under concurrent traffic, not PBKDF2.
        shared_hash = generate_password_hash(PASSWORD)
        now = db.utcnow_text()
        db.execute_many(
            "INSERT INTO users (email, password_hash, is_admin, is_dummy, created_at)"
            " VALUES (?, ?, 0, 0, ?)",
            [(VOTER_EMAIL.format(index=n), shared_hash, now)
             for n in range(1, users + 1)],
        )

        if dummies:
            dummy.generate_dummy_users(setting_id, dummies, approval_rate=0.4, seed=7)

        elapsed = time.time() - started

    print(f"Seeded {CONFIG['DATABASE']} in {elapsed:.1f}s")
    print(f"  setting id     : {setting_id}")
    print(f"  candidates     : {options}")
    print(f"  voter accounts : {users}  ({VOTER_EMAIL.format(index=1)} … "
          f"{VOTER_EMAIL.format(index=users)}, password '{PASSWORD}')")
    print(f"  dummy voters   : {dummies}")
    print(f"  admin          : {ADMIN_EMAIL} / {ADMIN_PASSWORD}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=1000,
                        help="participant accounts to create (default 1000)")
    parser.add_argument("--options", type=int, default=10,
                        help="candidates in the setting (default 10)")
    parser.add_argument("--dummies", type=int, default=100,
                        help="dummy voters to pre-generate (default 100)")
    parser.add_argument("--fresh", action="store_true",
                        help="delete any existing stress database first")
    arguments = parser.parse_args()
    seed(arguments.users, arguments.options, arguments.dummies, arguments.fresh)
