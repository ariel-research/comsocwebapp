# Faculty hiring — a standalone `comsocwebapp` application

A hiring committee shortlists candidates by approval voting. Every committee
member approves the candidates they consider hirable; the three most-approved
are shortlisted, and everyone can read exactly how that was computed.

This folder is self-contained. Copy it into a repository of your own, rename
things, and it keeps working — it depends on `comsocwebapp` from PyPI and on
nothing else in this repository.

## Install and run

Requires **Python 3.10+**.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install comsocwebapp

python app.py
```

Open <http://127.0.0.1:5010/>, and log in as `admin@example.com` / `admin`.
The console also prints an invitation link — open it in a private window to see
what a committee member sees.

That is the whole installation. There is no database server to set up: the app
creates an SQLite file under `instance/` on first run.

## What is in here

```
app.py               the entire application: config, candidates, rule, seeding
templates/
└── participant/
    └── index.html   one page replaced; every other page comes from the package
static/
└── style.css        this application's own styling
instance/            created on first run; holds the SQLite database
```

`app.py` is organised in the four steps you will edit:

1. **Configuration** — `PORT`, the database path, the secret key, and the
   template/static folders.
2. **The problem** — the list of candidates. Swap in projects with costs for
   participatory budgeting, or items for a fair division.
3. **A rule of our own** — `@rules.register_rule` makes it appear in the
   admin's dropdown. Delete it and use the built-in rules if you prefer.
4. **Seeding** — `db.ensure_db()` creates the schema only when it is missing,
   so restarting never destroys collected ballots.

## Making it yours

* **Different problem?** Change `pref_format` in the `create_setting(...)` call
  to `ranking`, `points` or `budget`, and give the options a `cost` if they
  have one.
* **Different look?** Every template in `comsocwebapp/templates/` can be
  overridden by putting a file with the same path under `templates/` here.
  This app overrides `participant/index.html`; everything else falls back to
  the package.
* **Real solver libraries?** `pip install "comsocwebapp[all]"` adds rules from
  `fairpyx`, `abcvoting` and `pabutools`. They show up in the admin's rule list
  automatically.
* **Sign-in with Google / GitHub / ORCID?** `pip install "comsocwebapp[oauth]"`
  and set the client id/secret in `CONFIG`, for example
  `OAUTH_GITHUB_CLIENT_ID` and `OAUTH_GITHUB_CLIENT_SECRET`.

## Starting over

Delete the database and re-run:

```bash
rm -rf instance/            # Windows: rmdir /s /q instance
python app.py
```

## Deploying

Set a real secret key and run behind a WSGI server:

```bash
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
pip install gunicorn
gunicorn "app:build_app()" --bind 0.0.0.0:8000 --workers 4
```

Serve it over HTTPS: invitation tokens and session cookies travel in the
request.
