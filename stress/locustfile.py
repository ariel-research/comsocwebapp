"""Load test for comsocwebapp: 1000 participants voting at once.

Run the server against the seeded stress database, then::

    locust -f stress/locustfile.py --host http://127.0.0.1:5000

See README.md in this folder for the full procedure, including the headless
one-liner and the pass/fail thresholds.

Two user classes:

* :class:`Participant` -- the load that matters.  Logs in once, then loops over
  the realistic cycle: read the ballot, submit it, check the receipt, look at
  the results.  Weighted 20:1 against the admin.
* :class:`Admin` -- one or two of them, polling the dashboard the way a
  returning officer watches turnout.  Rule execution is deliberately rare: it
  is a heavy synchronous operation and firing it constantly would measure the
  solver library rather than the web application.
"""

from __future__ import annotations

import itertools
import os
import random
import re

from locust import HttpUser, between, events, task

# Keep these in step with seed_stress.py.
PASSWORD = os.environ.get("STRESS_PASSWORD", "stress-password")
VOTER_EMAIL = os.environ.get("STRESS_VOTER_EMAIL", "voter{index}@example.com")
ADMIN_EMAIL = os.environ.get("STRESS_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("STRESS_ADMIN_PASSWORD", "admin")
SETTING_ID = int(os.environ.get("STRESS_SETTING_ID", "1"))

#: Hands out a distinct account to each simulated user, so no two locust users
#: fight over the same ballot row.
_account_numbers = itertools.count(1)

#: option_<id> field names, discovered from the ballot page on first load.
_OPTION_FIELD = re.compile(r'name="(option_\d+)"')


class Participant(HttpUser):
    """A voter: logs in, votes, edits, checks the outcome."""

    weight = 20
    wait_time = between(1, 5)

    def on_start(self):
        """Log in once; the session cookie is reused for every later request.

        Real voters log in once per session too, and it keeps the test from
        degenerating into a PBKDF2 benchmark.
        """
        self.email = VOTER_EMAIL.format(index=next(_account_numbers))
        self.option_fields: list[str] = []

        with self.client.post(
            "/auth/login",
            data={"email": self.email, "password": PASSWORD},
            allow_redirects=False,
            catch_response=True,
            name="/auth/login",
        ) as response:
            if response.status_code != 302:
                response.failure(
                    f"login for {self.email} returned {response.status_code};"
                    " is the stress database seeded with enough accounts?")
            else:
                response.success()

    @task(4)
    def view_ballot(self):
        """Load the ballot page and remember which fields it contains."""
        with self.client.get(f"/vote/{SETTING_ID}", catch_response=True,
                             name="/vote/[id]") as response:
            if response.status_code == 200:
                self.option_fields = _OPTION_FIELD.findall(response.text)
                if not self.option_fields:
                    response.failure("ballot page carried no option fields")

    @task(3)
    def cast_ballot(self):
        """Submit a random approval ballot."""
        if not self.option_fields:
            self.view_ballot()
            if not self.option_fields:
                return

        # Approval rows post a hidden 0 and, when ticked, an extra 1.
        payload = [(field, "0") for field in self.option_fields]
        payload += [(field, "1") for field in self.option_fields
                    if random.random() < 0.4]

        with self.client.post(f"/vote/{SETTING_ID}", data=payload,
                              allow_redirects=False, catch_response=True,
                              name="/vote/[id] (POST)") as response:
            if response.status_code == 302:
                response.success()
            elif response.status_code == 200:
                # Re-rendered form: the ballot was rejected, not an outage.
                response.failure("ballot rejected by validation")

    @task(2)
    def view_receipt(self):
        self.client.get(f"/vote/{SETTING_ID}/receipt", name="/vote/[id]/receipt")

    @task(2)
    def view_results(self):
        self.client.get(f"/results/{SETTING_ID}", name="/results/[id]")

    @task(1)
    def view_index(self):
        self.client.get("/", name="/")


class Admin(HttpUser):
    """A returning officer watching participation come in."""

    weight = 1
    wait_time = between(5, 15)

    def on_start(self):
        self.client.post("/auth/login",
                         data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                         allow_redirects=False, name="/auth/login (admin)")

    @task(10)
    def dashboard(self):
        self.client.get("/admin/", name="/admin/")

    @task(5)
    def setting_detail(self):
        self.client.get(f"/admin/settings/{SETTING_ID}",
                        name="/admin/settings/[id]")

    @task(1)
    def export(self):
        self.client.get(f"/admin/settings/{SETTING_ID}/export/preferences.csv",
                        name="/admin/settings/[id]/export")


@events.quitting.add_listener
def _assert_thresholds(environment, **_):
    """Fail the process when the run misses the targets.

    This is what makes `locust --headless` usable in CI: a non-zero exit code
    when the application did not hold up.  The numbers are the ones documented
    in README.md.
    """
    stats = environment.stats.total
    failures = []

    if stats.num_requests == 0:
        failures.append("no requests were made at all")
    else:
        if stats.fail_ratio > 0.01:
            failures.append(f"failure ratio {stats.fail_ratio:.2%} exceeds 1%")
        p95 = stats.get_response_time_percentile(0.95)
        if p95 and p95 > 2000:
            failures.append(f"95th percentile {p95:.0f} ms exceeds 2000 ms")

    if failures:
        for failure in failures:
            print(f"STRESS TEST FAILED: {failure}")
        environment.process_exit_code = 1
    else:
        print("STRESS TEST PASSED: "
              f"{stats.num_requests} requests, {stats.fail_ratio:.2%} failed, "
              f"p95 {stats.get_response_time_percentile(0.95):.0f} ms")
        environment.process_exit_code = 0
