# comsocwebapp

A Flask boilerplate for building web applications that solve **computational
social choice** problems: fair allocation, voting and participatory budgeting.

You bring the problem; the package brings the admin dashboard, the participant
ballot GUI, invitations and authentication, dummy-user simulation, rule
execution with a full audit log, and CSV export.

* **No ORM.** Every statement is hand-written, parameterised, portable SQL
  (see [`comsocwebapp/db.py`](comsocwebapp/db.py) and
  [`comsocwebapp/schema.sql`](comsocwebapp/schema.sql)).
* **Solver-agnostic.** [`adapters.py`](comsocwebapp/adapters.py) turns the SQL
  rows into plain dicts and lists, and bridges them into `fairpyx`,
  `abcvoting` and `pabutools`.
* **Flask-shaped.** `create_app()` is an ordinary application factory; the
  three blueprints are ordinary blueprints.

---

## Prerequisites

* **Python 3.10 or newer** (`python --version`).
* No database server: the default backend is the standard library's `sqlite3`.
* The solver libraries are optional — the package ships three built-in rules
  (`approval_scoring`, `borda`, `greedy_budget`) that depend on nothing.

## Installation

```bash
git clone https://github.com/erelsgl/comsocwebapp.git
cd comsocwebapp

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e .                 # core: Flask only
pip install -e ".[all]"          # plus fairpyx, abcvoting and pabutools
pip install -e ".[dev]"          # plus pytest
```

Individual extras are `allocation` (fairpyx), `voting` (abcvoting) and
`budgeting` (pabutools).

## Getting started in three commands

```bash
export FLASK_APP=comsocwebapp    # Windows PowerShell: $env:FLASK_APP="comsocwebapp"

flask init-db                    # 1. create the tables
flask create-admin               # 2. create the first admin (prompts for email + password)
flask run --debug                # 3. serve on http://127.0.0.1:5000/
```

Then open <http://127.0.0.1:5000/admin/> and log in with the account you just
created.

> `flask init-db` **drops and recreates every table** — it is the "start a
> fresh event" command, not a migration.

Without shell variables:

```bash
flask --app comsocwebapp init-db
flask --app comsocwebapp create-admin
flask --app comsocwebapp run --debug
```

The database file lands in `instance/comsocwebapp.sqlite`. Override the
location and the session key with environment variables:

```bash
export COMSOCWEBAPP_DATABASE=/var/lib/comsoc/event.sqlite
export COMSOCWEBAPP_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
```

Setting `COMSOCWEBAPP_SECRET_KEY` is **required in production** — the default
`"dev"` key exists only so `flask run` works out of the box.

## Runnable examples

Each example seeds its own database and starts a server, so you can see a
complete application in one command:

```bash
python examples/participatory_budgeting.py   # city budget, approval ballots
python examples/committee_voting.py          # board election, approval ballots
python examples/fair_allocation.py           # estate division, point ballots
```

They all print an admin login (`admin@example.com` / `admin`) and an invitation
link you can open in a private window to see the participant side.

## The admin workflow

1. **New setting** — give it a title, a preference format (`approval`,
   `ranking`, `points`, `budget`) and a budget/point limit.
2. **Add options** one by one, or bulk-upload a CSV with the columns
   `name,description,cost`.
3. **Generate invitations** — *personal* links die once redeemed; *generic*
   links can be mailed to a list, and the unique index on `users.email` is what
   stops anyone voting twice.
4. **Generate dummy users** to test a rule before real people arrive; choose
   the distribution (`uniform`, `normal`, `exponential`), the bounds and a seed
   for reproducibility. Delete them all with one button.
5. **Set the status to `open`** so participants can vote (`closed` locks it).
6. **Run a rule** over real users only, dummy users only, or both. The outcome
   and the step-by-step log are stored in `execution_logs` and shown to admins
   and participants alike.
7. **Export** anonymised preferences and execution logs as CSV.

## Using the package as a library

```python
from comsocwebapp import create_app, db, dummy, adapters, rules

app = create_app()

with app.app_context():
    db.init_db()
    setting_id = db.insert_returning_id(
        "INSERT INTO settings (title, pref_format, status, budget_limit)"
        " VALUES (?, 'approval', 'open', 1000)",
        ("My election",))
    db.execute("INSERT INTO options (setting_id, name, description, cost)"
               " VALUES (?, ?, ?, ?)", (setting_id, "Park", "A new park", 400))

    dummy.generate_dummy_users(setting_id, 50, seed=1)

    result = rules.run_rule("approval_scoring", setting_id,
                            adapters.SCOPE_DUMMY, committee_size=2)
    rules.record_execution(setting_id, "approval_scoring", result)
    print(result.outcome, result.log_lines, sep="\n")
```

### Adding your own rule

```python
from comsocwebapp import adapters, rules

@rules.register_rule("my_rule")
def my_rule(setting_id, scope=adapters.SCOPE_ALL, **params):
    matrix = adapters.preference_matrix(setting_id, scope)   # {user: {option: value}}
    winners = ...
    return rules.RuleResult(outcome=winners,
                            log_lines=["why these winners were chosen"])
```

The rule appears in the admin's dropdown as soon as the module is imported.

### Bridging to the solver libraries

```python
instance          = adapters.to_fairpyx_instance(setting_id)      # fairpyx
profile, ids      = adapters.to_abcvoting_profile(setting_id)     # abcvoting
instance, profile = adapters.to_pabutools_instance(setting_id)    # pabutools
```

Each imports its library lazily, so an install without that extra still runs.

## Database

Six tables — `users`, `settings`, `options`, `invitations`, `preferences`,
`execution_logs` — defined in
[`comsocwebapp/schema.sql`](comsocwebapp/schema.sql) exactly as specified in
[`database.md`](database.md). Only `VARCHAR`, `INTEGER` and `TIMESTAMP` are
used; booleans are `INTEGER` 0/1; there are no JSON columns, arrays or ENUMs.

**Using another engine.** Point `get_db()` at your driver (psycopg, MySQLdb,
cx_Oracle) and adapt the primary-key declarations at the top of `schema.sql`.
Nothing else changes: `db.py` rewrites the `?` placeholders to the driver's
paramstyle, and the runtime queries avoid `RETURNING`, `ON CONFLICT`, `MERGE`
and every other dialect-specific construct. Where an UPSERT would normally be
used, `db.upsert_preference()` does a portable UPDATE-then-INSERT.

## Security

* Passwords are stored as Werkzeug PBKDF2 hashes; login errors never reveal
  whether an email is registered.
* Every SQL parameter is bound, never interpolated.
* Session cookies are signed, `HttpOnly` and `SameSite=Lax`.
* A dependency-free CSRF token guards every POST (disable with
  `CSRF_ENABLED = False` if your app already uses Flask-WTF).
* Personal invitation tokens are 32 URL-safe characters from `secrets`, and are
  consumed on first use.

## Running the tests

```bash
pip install -e ".[dev]"
pytest
```

## Project layout

```
comsocwebapp/
├── __init__.py       application factory, `create-admin` CLI command
├── db.py             connections, parameterised queries, portable UPSERT
├── schema.sql        the six tables
├── auth.py           invitation tokens, registration, login, guards
├── admin.py          admin blueprint  (/admin/...)
├── participant.py    participant blueprint (/, /vote/..., /results/...)
├── adapters.py       SQL rows -> dicts -> fairpyx / abcvoting / pabutools
├── dummy.py          bulk dummy users with randomised preferences
├── rules.py          rule registry, built-in rules, execution logging
├── security.py       CSRF protection
├── templates/        Jinja templates for both GUIs
└── static/style.css  responsive, dependency-free styling
examples/             three runnable reference applications
tests/                pytest suite
```

## License

See [LICENSE](LICENSE).
