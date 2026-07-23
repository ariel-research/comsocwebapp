"""High-level wrappers for creating and editing settings and their options.

Applications, examples and the admin blueprint all go through this module
rather than issuing their own INSERTs, so the rules that keep a setting
coherent live in exactly one place:

* ``options.position`` is 1, 2, 3, ... within each setting, independently of
  the global ``options.id``;
* deleting an option renumbers the survivors, so the numbering stays
  consecutive;
* deleting an option also deletes the preferences that referenced it.

Typical use when seeding an application::

    setting_id = create_setting(
        "City budget 2026",
        pref_format="approval",
        budget_limit=800_000,
        status="open",
        options=[
            ("New playground", "Slides and swings", 250_000),
            {"name": "Bike lanes", "description": "3 km", "cost": 400_000},
        ],
    )
"""

from typing import Any, Iterable, Mapping, Sequence

from . import db

__all__ = [
    "PREF_FORMATS", "STATUSES",
    "create_setting", "update_setting", "delete_setting",
    "add_option", "add_options", "update_option", "delete_option",
    "next_position", "renumber_options", "get_option",
]

PREF_FORMATS = ("approval", "ranking", "points", "budget")
STATUSES = ("draft", "open", "closed")


def _normalise_option(option: Any) -> tuple[str, str, int]:
    """Accept an option as a string, a ``(name, description, cost)`` tuple or a
    mapping, and return the canonical triple."""
    if isinstance(option, str):
        return option, "", 0
    if isinstance(option, Mapping):
        return (str(option["name"]),
                str(option.get("description") or ""),
                int(option.get("cost") or 0))
    if isinstance(option, Sequence):
        parts = list(option)
        name = str(parts[0])
        description = str(parts[1]) if len(parts) > 1 and parts[1] else ""
        cost = int(parts[2]) if len(parts) > 2 and parts[2] is not None else 0
        return name, description, cost
    raise TypeError(f"Cannot read an option from {option!r}")


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def create_setting(title: str, pref_format: str = "approval", *,
                   budget_limit: int = 0, status: str = "draft",
                   options: Iterable[Any] = ()) -> int:
    """Create a setting together with its options; return the setting id.

    This is the wrapper the examples and applications use instead of writing
    their own INSERTs -- it validates the enumerated columns and numbers the
    options for you.
    """
    if not title or not title.strip():
        raise ValueError("A setting needs a title.")
    if pref_format not in PREF_FORMATS:
        raise ValueError(f"pref_format must be one of {PREF_FORMATS}, got {pref_format!r}")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")

    setting_id = db.insert_returning_id(
        "INSERT INTO settings (title, pref_format, status, budget_limit)"
        " VALUES (?, ?, ?, ?)",
        (title.strip(), pref_format, status, int(budget_limit)),
    )
    add_options(setting_id, options)
    return setting_id


def update_setting(setting_id: int, *, title: str | None = None,
                   pref_format: str | None = None, status: str | None = None,
                   budget_limit: int | None = None) -> None:
    """Update the given fields of a setting, leaving the others alone."""
    if pref_format is not None and pref_format not in PREF_FORMATS:
        raise ValueError(f"pref_format must be one of {PREF_FORMATS}")
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")

    # Each column is updated by its own statement: building a variable SET
    # clause would mean assembling SQL from Python, which this package avoids.
    for column, value in (("title", title), ("pref_format", pref_format),
                          ("status", status), ("budget_limit", budget_limit)):
        if value is None:
            continue
        db.execute(f"UPDATE settings SET {column} = ? WHERE id = ?",  # noqa: S608
                   (value, setting_id), commit=False)                # column is a literal
    db.get_db().commit()


def delete_setting(setting_id: int) -> None:
    """Delete a setting and everything hanging off it, children first."""
    db.execute("DELETE FROM preferences WHERE setting_id = ?", (setting_id,), commit=False)
    db.execute("DELETE FROM execution_logs WHERE setting_id = ?", (setting_id,), commit=False)
    db.execute("DELETE FROM invitations WHERE setting_id = ?", (setting_id,), commit=False)
    db.execute("DELETE FROM options WHERE setting_id = ?", (setting_id,), commit=False)
    db.execute("DELETE FROM settings WHERE id = ?", (setting_id,), commit=False)
    db.get_db().commit()


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------

def next_position(setting_id: int) -> int:
    """Return the number the next option of this setting should carry.

    ``MAX(position) + 1`` rather than ``COUNT(*) + 1``: the two agree while the
    numbering is consecutive, but MAX still yields a free number if a caller
    ever leaves a gap.
    """
    row = db.query_one(
        "SELECT MAX(position) AS top FROM options WHERE setting_id = ?", (setting_id,))
    return int(row["top"] or 0) + 1


def add_option(setting_id: int, name: str, description: str = "",
               cost: int = 0) -> int:
    """Append one option to a setting and return its id."""
    if not name or not name.strip():
        raise ValueError("An option needs a name.")
    return db.insert_returning_id(
        "INSERT INTO options (setting_id, position, name, description, cost)"
        " VALUES (?, ?, ?, ?, ?)",
        (setting_id, next_position(setting_id), name.strip(),
         (description or "").strip(), int(cost or 0)),
    )


def add_options(setting_id: int, options: Iterable[Any]) -> list[int]:
    """Append several options at once; return their ids in order."""
    return [add_option(setting_id, *_normalise_option(option)) for option in options]


def get_option(option_id: int) -> dict[str, Any] | None:
    return db.query_one(
        "SELECT id, setting_id, position, name, description, cost"
        " FROM options WHERE id = ?", (option_id,))


def update_option(option_id: int, *, name: str | None = None,
                  description: str | None = None, cost: int | None = None) -> None:
    """Edit an option in place.  The position and the id never change, so
    ballots already cast against this option stay valid."""
    if name is not None and not name.strip():
        raise ValueError("An option needs a name.")
    for column, value in (("name", name.strip() if name is not None else None),
                          ("description", description),
                          ("cost", None if cost is None else int(cost))):
        if value is None:
            continue
        db.execute(f"UPDATE options SET {column} = ? WHERE id = ?",  # noqa: S608
                   (value, option_id), commit=False)                # column is a literal
    db.get_db().commit()


def delete_option(option_id: int) -> None:
    """Delete an option, its preferences, and renumber what remains."""
    option = get_option(option_id)
    if option is None:
        return
    db.execute("DELETE FROM preferences WHERE option_id = ?", (option_id,), commit=False)
    db.execute("DELETE FROM options WHERE id = ?", (option_id,), commit=False)
    db.get_db().commit()
    renumber_options(option["setting_id"])


def renumber_options(setting_id: int) -> None:
    """Rewrite the positions of a setting's options as 1, 2, 3, ...

    Existing order is preserved.  The rows are first pushed into a negative
    range and then into their final numbers: a single pass could otherwise
    collide with a position that has not been rewritten yet, and the unique
    index ``ux_options_position`` would reject it.
    """
    rows = db.query_all(
        "SELECT id FROM options WHERE setting_id = ? ORDER BY position, id",
        (setting_id,))
    for offset, row in enumerate(rows, start=1):
        db.execute("UPDATE options SET position = ? WHERE id = ?",
                   (-offset, row["id"]), commit=False)
    for offset, row in enumerate(rows, start=1):
        db.execute("UPDATE options SET position = ? WHERE id = ?",
                   (offset, row["id"]), commit=False)
    db.get_db().commit()
