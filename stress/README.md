# Stress testing `comsocwebapp`

Infrastructure for verifying that the application holds up with **1000
simultaneous participants** casting and editing ballots.

The load is generated with [locust](https://locust.io/). Three pieces:

| File | Role |
| --- | --- |
| `seed_stress.py` | builds a database with an admin, N voter accounts and a setting |
| `serve_stress.py` | serves that database on a real WSGI server (waitress) |
| `locustfile.py` | the simulated participants and the pass/fail thresholds |

## Install

```bash
pip install -e ".[dev]"     # from the repo root; installs locust + waitress
```

(Or `pip install locust waitress` on their own.)

## Run the 1000-user test

Three terminals — or backgrounds — from the repository root.

**1. Seed the database** (once):

```bash
python stress/seed_stress.py --users 1000 --options 10 --dummies 100 --fresh
```

**2. Serve it:**

```bash
python stress/serve_stress.py --port 5000 --threads 32
```

`serve_stress.py` uses waitress, a multi-threaded WSGI server. Do **not** use
`flask run --debug` for load testing — the reloader and debugger serialise
requests, so you would be measuring them, not the app.

**3. Drive the load:**

```bash
# Interactive: open http://localhost:8089 and set 1000 users, spawn rate 50.
locust -f stress/locustfile.py --host http://127.0.0.1:5000

# Headless, with a hard stop and a CI-friendly exit code:
locust -f stress/locustfile.py --host http://127.0.0.1:5000 \
       --headless --users 1000 --spawn-rate 50 --run-time 3m
```

A `--spawn-rate` of 50 reaches 1000 users in 20 seconds; give the run at least
a couple of minutes so the numbers settle.

## What counts as passing

`locustfile.py` checks two thresholds when the run ends and sets the process
exit code accordingly — so `--headless` fails CI automatically:

* **failure ratio ≤ 1%**
* **95th-percentile response time ≤ 2000 ms**

It prints one line:

```
STRESS TEST PASSED: 148230 requests, 0.03% failed, p95 380 ms
```

or `STRESS TEST FAILED: ...` with the reason. Adjust the numbers in the
`_assert_thresholds` listener at the bottom of `locustfile.py` to match your
own service-level target.

## What the simulated users do

* **Participants** (weight 20) log in once, then loop over the real cycle: view
  the ballot, submit a random approval ballot, check the receipt, view the
  results. Each locust user takes a distinct `voter<N>@example.com` account, so
  they exercise separate ballot rows rather than colliding on one.
* **Admins** (weight 1) poll the dashboard and the setting page, and
  occasionally export the CSV — the way a returning officer watches turnout.

Rule execution is intentionally **not** in the hot loop: it is a heavy
synchronous call, and hammering it would benchmark the solver library instead
of the web application. Trigger it by hand from the admin GUI during a run if
you want to see its effect.

## Notes on the numbers

* **SQLite and concurrency.** The app enables WAL mode and a busy-timeout (see
  `comsocwebapp/db.py`), which is what makes hundreds of concurrent writers
  viable on a single file. WAL keeps readers running while one writer commits;
  the writer is still serialised, so at very high write rates the right move is
  to point `get_db()` at PostgreSQL — no query changes, as the queries are
  portable ANSI SQL. See the main README's "Using another engine".
* **CSRF is disabled in the stress config** (`CSRF_ENABLED = False` in
  `seed_stress.py`): the headless client cannot read a per-form token out of
  the HTML. This is a test-harness concession, never a deployment setting.
* **Passwords are hashed once** in the seed. Hashing 1000 PBKDF2 passwords
  would take minutes and measure nothing useful — the load test is about the
  app under concurrent traffic, not the KDF.
* **Client machine limits.** Simulating 1000 users needs ~1000 open sockets;
  on Linux raise the file-descriptor limit (`ulimit -n 65535`) if you see
  connection errors on the *client* side. For more than a few thousand users,
  distribute locust with `--master` / `--worker`.

## Environment overrides

`locustfile.py` reads these if the seed used non-default values:

| Variable | Default |
| --- | --- |
| `STRESS_SETTING_ID` | `1` |
| `STRESS_VOTER_EMAIL` | `voter{index}@example.com` |
| `STRESS_PASSWORD` | `stress-password` |
| `STRESS_ADMIN_EMAIL` | `admin@example.com` |
| `STRESS_ADMIN_PASSWORD` | `admin` |
