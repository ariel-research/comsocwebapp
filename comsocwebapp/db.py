"""Database access layer -- raw, parameterised, ANSI SQL only.

Design rules enforced throughout this module:

* **No ORM.**  Every statement is a hand-written string executed through the
  DB-API.  What you read is what the database runs.
* **Always parameterised.**  User input never reaches a SQL string by
  concatenation; it is passed as a bound parameter.  The module rewrites the
  qmark placeholder ``?`` into whatever ``paramstyle`` the active driver
  advertises (see :func:`_adapt_placeholders`), so the same query text works on
  sqlite3 (``?``), psycopg/MySQLdb (``%s``) and cx_Oracle (``:1``).
* **Portable SQL only.**  No ``RETURNING``, no ``ON CONFLICT``, no ``LIMIT``
  inside sub-queries, no JSON functions.  Where a dialect-specific feature
  would be convenient (UPSERT, last-insert-id) a portable idiom is used
  instead and documented at the call site.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import click
from flask import current_app, g
from flask.cli import with_appcontext

__all__ = [
    "get_db",
    "close_db",
    "init_db",
    "ensure_db",
    "schema_exists",
    "query_all",
    "query_one",
    "execute",
    "insert_returning_id",
    "upsert_preference",
    "execute_many",
    "utcnow_text",
    "init_app",
]


def utcnow_text() -> str:
    """Current UTC time as ``'YYYY-MM-DD HH:MM:SS'``.

    Timestamps are bound as strings rather than ``datetime`` objects: that
    literal form is accepted by every engine's TIMESTAMP column, whereas each
    driver adapts ``datetime`` differently (and sqlite3's own adapter is
    deprecated since Python 3.12).
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# Connection handling
# --------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    """Return the request-scoped connection, opening one on first use.

    The connection lives on Flask's ``g`` object, so every view function in a
    request shares a single transaction and a single commit.
    """
    if "db" not in g:
        location = current_app.config["DATABASE"]
        connection = sqlite3.connect(
            location,
            # Under load several requests wait on the single writer instead of
            # failing immediately with "database is locked".
            timeout=current_app.config.get("DATABASE_TIMEOUT", 15.0),
        )
        # Rows behave like dicts *and* like tuples, which keeps the adapter
        # layer free of positional indexing.
        connection.row_factory = sqlite3.Row
        # SQLite ignores FOREIGN KEY clauses unless asked not to.  Other
        # engines enforce them unconditionally, so this is a no-op elsewhere.
        connection.execute("PRAGMA foreign_keys = ON")
        if current_app.config.get("SQLITE_WAL", True) and location != ":memory:":
            # Write-ahead logging lets readers run while a write is in flight,
            # which is what makes a few hundred concurrent voters viable on
            # SQLite.  It is a durable property of the file, so setting it on
            # every connection is cheap and idempotent.
            connection.execute("PRAGMA journal_mode = WAL")
        g.db = connection
    return g.db


def close_db(e: BaseException | None = None) -> None:
    """Close the request-scoped connection, if one was opened."""
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


# --------------------------------------------------------------------------
# Placeholder adaptation
# --------------------------------------------------------------------------

def _adapt_placeholders(sql: str, connection: Any) -> str:
    """Translate ``?`` placeholders to the driver's ``paramstyle``.

    Queries in this package are written once with the qmark style because it is
    the least ambiguous.  Swapping sqlite3 for psycopg2 then only requires
    changing :func:`get_db`; the query text stays untouched.
    """
    module = getattr(connection, "__module__", "") or ""
    paramstyle = "qmark"
    if "psycopg" in module or "mysql" in module or "MySQLdb" in module:
        paramstyle = "format"

    if paramstyle == "qmark":
        return sql
    if paramstyle == "format":
        return sql.replace("?", "%s")
    raise RuntimeError(f"Unsupported paramstyle: {paramstyle}")


def _execute(sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    connection = get_db()
    return connection.execute(_adapt_placeholders(sql, connection), tuple(params))


# --------------------------------------------------------------------------
# Query helpers
# --------------------------------------------------------------------------

def query_all(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """Run a SELECT and return every row as a plain ``dict``.

    Returning dicts rather than driver-specific row objects is what lets
    :mod:`comsocwebapp.adapters` stay independent of the database in use.
    """
    return [dict(row) for row in _execute(sql, params).fetchall()]


def query_one(sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
    """Run a SELECT and return the first row as a ``dict``, or ``None``."""
    row = _execute(sql, params).fetchone()
    return dict(row) if row is not None else None


def execute(sql: str, params: Sequence[Any] = (), commit: bool = True) -> int:
    """Run an INSERT/UPDATE/DELETE and return the affected row count."""
    cursor = _execute(sql, params)
    if commit:
        get_db().commit()
    return cursor.rowcount


def execute_many(sql: str, seq_of_params: Iterable[Sequence[Any]], commit: bool = True) -> None:
    """Run one statement against many parameter tuples (bulk insert)."""
    connection = get_db()
    connection.executemany(
        _adapt_placeholders(sql, connection),
        [tuple(p) for p in seq_of_params],
    )
    if commit:
        connection.commit()


def insert_returning_id(sql: str, params: Sequence[Any] = (), commit: bool = True) -> int:
    """INSERT one row and return its generated primary key.

    ``RETURNING id`` is not portable (Oracle and MySQL spell it differently, and
    old SQLite lacks it entirely), so the generated key is read back from the
    DB-API cursor instead -- ``lastrowid`` on SQLite/MySQL, ``lastval()`` style
    helpers elsewhere.  Callers therefore never see dialect-specific SQL.
    """
    cursor = _execute(sql, params)
    new_id = cursor.lastrowid
    if commit:
        get_db().commit()
    return int(new_id)


def upsert_preference(user_id: int, setting_id: int, option_id: int, value: int) -> None:
    """Store one ballot entry, replacing any previous value for that option.

    ANSI SQL has no UPSERT and each engine invented its own (``ON CONFLICT``,
    ``ON DUPLICATE KEY``, ``MERGE``).  The portable idiom is to attempt the
    UPDATE first and only INSERT when it touched no rows -- correct on every
    engine, and race-free here because the unique index
    ``ux_preferences_ballot`` would reject a duplicating INSERT anyway.
    """
    updated = execute(
        "UPDATE preferences SET value = ? WHERE user_id = ? AND option_id = ?",
        (value, user_id, option_id),
        commit=False,
    )
    if updated == 0:
        execute(
            "INSERT INTO preferences (user_id, setting_id, option_id, value)"
            " VALUES (?, ?, ?, ?)",
            (user_id, setting_id, option_id, value),
            commit=False,
        )
    get_db().commit()


# --------------------------------------------------------------------------
# Schema initialisation
# --------------------------------------------------------------------------

def init_db() -> None:
    """Drop and recreate every table from ``schema.sql``.

    Destructive by design: this is the "start a fresh event" command.  Call
    :func:`ensure_db` instead to keep whatever is already there.
    """
    connection = get_db()
    with current_app.open_resource("schema.sql") as handle:
        connection.executescript(handle.read().decode("utf8"))
    connection.commit()


def schema_exists() -> bool:
    """Return True if the schema has already been created.

    Probing with a trivial SELECT is the portable test: ``sqlite_master`` is
    SQLite-only, ``information_schema`` does not exist on SQLite or Oracle, and
    every engine raises when a table is missing.
    """
    try:
        get_db().execute("SELECT id FROM settings WHERE 1 = 0").fetchall()
    except Exception:
        return False
    return True


def ensure_db() -> bool:
    """Create the schema only if it is missing.  True if it was created.

    This is what long-lived applications and the examples call on start-up:
    re-running them must never discard the data collected so far.
    """
    if schema_exists():
        return False
    init_db()
    return True


@click.command("init-db")
@click.option("--if-missing", is_flag=True,
              help="Keep an existing database instead of recreating it.")
@with_appcontext
def init_db_command(if_missing: bool) -> None:
    """flask init-db -- create the tables, erasing any existing data."""
    location = current_app.config["DATABASE"]
    if if_missing:
        if ensure_db():
            click.echo(f"Initialised the database at {location}.")
        else:
            click.echo(f"Kept the existing database at {location}.")
        return
    init_db()
    click.echo(f"Initialised the database at {location}.")


def init_app(app) -> None:
    """Register the teardown hook and the ``flask init-db`` CLI command."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
