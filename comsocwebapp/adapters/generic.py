"""Library-independent view of the data: SQL rows in, plain Python out.

Everything here returns ``dict``, ``list``, ``set`` and ``int`` only.  No
solver library is imported, so this module works on a bare ``pip install
comsocwebapp``.  The per-library files in this package build on these shapes;
see ``README.md`` next door for how to add one.

The canonical query is the one documented in ``database.md``: join
``users``/``preferences``/``options`` and read ``value`` per (user, option).
Its interpretation depends on ``settings.pref_format``:

===========  =====================================================
pref_format  meaning of ``preferences.value``
===========  =====================================================
``approval`` 1 = approved, 0 = not approved
``ranking``  1 = most preferred, 2 = next, ...  (lower is better)
``points``   utility assigned to the option (higher is better)
``budget``   currency assigned to the project (higher is better)
===========  =====================================================
"""

from typing import Any

from .. import db

__all__ = [
    "SCOPE_ALL", "SCOPE_REAL", "SCOPE_DUMMY", "SCOPES",
    "fetch_setting", "fetch_options", "fetch_participants", "fetch_preference_rows",
    "fetch_user_preferences", "preference_matrix", "approval_sets", "rankings",
    "option_costs", "option_label",
]

# Execution scope: the admin may run a rule on real users only, dummy users
# only, or both (design.md, "Execution Scope").
SCOPE_ALL = "all"
SCOPE_REAL = "real"
SCOPE_DUMMY = "dummy"
SCOPES = (SCOPE_ALL, SCOPE_REAL, SCOPE_DUMMY)

_SCOPE_CLAUSE = {
    SCOPE_ALL: "",
    SCOPE_REAL: " AND u.is_dummy = 0",
    SCOPE_DUMMY: " AND u.is_dummy = 1",
}


def _scope_clause(scope: str) -> str:
    """Return the SQL fragment restricting rows to ``scope``.

    The fragment is chosen from a fixed dictionary rather than built from the
    caller's string, so no user-supplied text ever reaches the SQL text.
    """
    try:
        return _SCOPE_CLAUSE[scope]
    except KeyError:
        raise ValueError(f"Unknown execution scope: {scope!r}") from None


# --------------------------------------------------------------------------
# Raw fetches
# --------------------------------------------------------------------------

def fetch_setting(setting_id: int) -> dict[str, Any] | None:
    return db.query_one(
        "SELECT id, title, pref_format, status, budget_limit"
        " FROM settings WHERE id = ?",
        (setting_id,),
    )


def fetch_options(setting_id: int) -> list[dict[str, Any]]:
    """The setting's options, in the order the admin numbered them."""
    return db.query_all(
        "SELECT id, setting_id, position, name, description, cost"
        " FROM options WHERE setting_id = ? ORDER BY position, id",
        (setting_id,),
    )


def fetch_participants(setting_id: int, scope: str = SCOPE_ALL) -> list[dict[str, Any]]:
    """Return the users who have cast at least one preference in the setting."""
    return db.query_all(
        "SELECT DISTINCT u.id AS user_id, u.email, u.is_dummy"
        " FROM users u JOIN preferences p ON u.id = p.user_id"
        " WHERE p.setting_id = ?" + _scope_clause(scope) +
        " ORDER BY u.id",
        (setting_id,),
    )


def fetch_preference_rows(setting_id: int, scope: str = SCOPE_ALL) -> list[dict[str, Any]]:
    """The join from ``database.md``, one row per (user, option) preference."""
    return db.query_all(
        "SELECT u.id AS user_id, u.is_dummy, o.id AS option_id,"
        "       o.position AS option_position, o.name AS option_name,"
        "       o.cost AS option_cost, p.value"
        " FROM users u"
        " JOIN preferences p ON u.id = p.user_id"
        " JOIN options o ON p.option_id = o.id"
        " WHERE p.setting_id = ?" + _scope_clause(scope) +
        " ORDER BY u.id, p.value DESC",
        (setting_id,),
    )


def fetch_user_preferences(user_id: int, setting_id: int) -> list[dict[str, Any]]:
    """One user's ballot, every option of the setting included.

    A LEFT JOIN from ``options`` rather than from ``preferences``, so options
    the user never answered come back with a NULL value the caller can show as
    an empty field.
    """
    return db.query_all(
        "SELECT o.id AS option_id, o.position, o.name AS option_name,"
        "       o.description, o.cost, p.value"
        " FROM options o"
        " LEFT JOIN preferences p ON p.option_id = o.id AND p.user_id = ?"
        " WHERE o.setting_id = ? ORDER BY o.position, o.id",
        (user_id, setting_id),
    )


# --------------------------------------------------------------------------
# Generic (library-independent) shapes
# --------------------------------------------------------------------------

def preference_matrix(setting_id: int, scope: str = SCOPE_ALL,
                      by_name: bool = True) -> dict[Any, dict[Any, int]]:
    """``{user_id: {option: value}}`` -- the universal starting point.

    ``by_name=True`` keys the inner dicts by option *name* (what the solver
    libraries print in their output); ``False`` keys them by ``option_id``.
    Options a user never touched are filled in with 0 so that every inner dict
    has the same keys -- solvers generally require rectangular input.
    """
    options = fetch_options(setting_id)
    keys = [o["name"] if by_name else o["id"] for o in options]
    by_option_id = {o["id"]: (o["name"] if by_name else o["id"]) for o in options}

    matrix: dict[Any, dict[Any, int]] = {}
    for row in fetch_preference_rows(setting_id, scope):
        user = matrix.setdefault(row["user_id"], {key: 0 for key in keys})
        user[by_option_id[row["option_id"]]] = row["value"]
    return matrix


def approval_sets(setting_id: int, scope: str = SCOPE_ALL,
                  by_name: bool = False) -> dict[Any, set]:
    """``{user_id: {approved options}}`` -- every option with ``value > 0``."""
    return {
        user: {option for option, value in prefs.items() if value > 0}
        for user, prefs in preference_matrix(setting_id, scope, by_name).items()
    }


def rankings(setting_id: int, scope: str = SCOPE_ALL,
             by_name: bool = False) -> dict[Any, list]:
    """``{user_id: [best, ..., worst]}`` for the ``ranking`` format.

    Rank 1 is best, so options sort ascending; unranked options (value 0) are
    dropped rather than being treated as top-ranked.
    """
    result: dict[Any, list] = {}
    for user, prefs in preference_matrix(setting_id, scope, by_name).items():
        ranked = [(value, option) for option, value in prefs.items() if value > 0]
        ranked.sort(key=lambda pair: pair[0])
        result[user] = [option for _, option in ranked]
    return result


def option_costs(setting_id: int, by_name: bool = True) -> dict[Any, int]:
    """``{option: cost}`` -- used by participatory-budgeting rules."""
    return {
        (o["name"] if by_name else o["id"]): o["cost"]
        for o in fetch_options(setting_id)
    }


def option_label(option: dict[str, Any]) -> str:
    """Human-readable label for one option row: ``'3. Bike lanes -- 2 km'``.

    Position first (so it matches the number the admin and voters see), then
    the name, then the description when there is one.  Used to make execution
    logs and results readable instead of printing bare ids.
    """
    if option.get("description"):
        return f"{option['position']}. {option['name']} — {option['description']}"
    return f"{option['position']}. {option['name']}"
