"""Bridge between the raw SQL rows and the social-choice solver libraries.

Everything here returns plain Python containers -- ``dict``, ``list``, ``set``,
``int`` -- so the module has no import-time dependency on ``fairpyx``,
``abcvoting`` or ``pabutools``.  The three ``to_*`` functions at the bottom
import their library lazily, which keeps ``pip install comsocwebapp`` light and
lets an application ship with only the libraries it actually uses.

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

from __future__ import annotations

from typing import Any

from . import db

__all__ = [
    "SCOPE_ALL", "SCOPE_REAL", "SCOPE_DUMMY",
    "fetch_setting", "fetch_options", "fetch_participants", "fetch_preference_rows",
    "preference_matrix", "approval_sets", "rankings", "option_costs",
    "to_fairpyx_instance", "to_abcvoting_profile", "to_pabutools_instance",
]

# Execution scope: the admin may run a rule on real users only, dummy users
# only, or both (design.md, "Execution Scope").
SCOPE_ALL = "all"
SCOPE_REAL = "real"
SCOPE_DUMMY = "dummy"

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
    return db.query_all(
        "SELECT id, setting_id, name, description, cost"
        " FROM options WHERE setting_id = ? ORDER BY id",
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
        "       o.name AS option_name, o.cost AS option_cost, p.value"
        " FROM users u"
        " JOIN preferences p ON u.id = p.user_id"
        " JOIN options o ON p.option_id = o.id"
        " WHERE p.setting_id = ?" + _scope_clause(scope) +
        " ORDER BY u.id, p.value DESC",
        (setting_id,),
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


# --------------------------------------------------------------------------
# Library-specific adapters (imported lazily)
# --------------------------------------------------------------------------

def to_fairpyx_instance(setting_id: int, scope: str = SCOPE_ALL):
    """Build a ``fairpyx.Instance`` for fair-item-allocation rules.

    ``fairpyx`` takes valuations as ``{agent: {item: value}}``, exactly the
    shape :func:`preference_matrix` produces, so no reshaping is needed for
    the ``points`` / ``budget`` formats.  For ``ranking`` the values are
    inverted (rank 1 becomes the highest utility) because fairpyx maximises.
    """
    import fairpyx  # noqa: PLC0415 -- optional dependency, imported on demand

    setting = fetch_setting(setting_id)
    matrix = preference_matrix(setting_id, scope, by_name=True)
    if setting and setting["pref_format"] == "ranking":
        size = len(fetch_options(setting_id))
        matrix = {
            agent: {item: (size - value + 1 if value > 0 else 0)
                    for item, value in prefs.items()}
            for agent, prefs in matrix.items()
        }
    return fairpyx.Instance(valuations=matrix)


def to_abcvoting_profile(setting_id: int, scope: str = SCOPE_ALL):
    """Build an ``abcvoting.preferences.Profile`` for committee-voting rules.

    ``abcvoting`` identifies candidates by consecutive integers starting at 0,
    which our ``options.id`` values are not, so the mapping from position to
    ``option_id`` is returned alongside the profile.
    """
    from abcvoting.preferences import Profile  # noqa: PLC0415

    options = fetch_options(setting_id)
    index_of = {o["id"]: position for position, o in enumerate(options)}

    profile = Profile(len(options), cand_names=[o["name"] for o in options])
    for approved in approval_sets(setting_id, scope, by_name=False).values():
        if approved:  # abcvoting rejects empty ballots
            profile.add_voter([index_of[option_id] for option_id in sorted(approved)])
    return profile, [o["id"] for o in options]


def to_pabutools_instance(setting_id: int, scope: str = SCOPE_ALL):
    """Build a ``(Instance, Profile)`` pair for participatory budgeting.

    Projects carry their ``options.cost``; the instance budget comes from
    ``settings.budget_limit``.  Ballots are approval ballots -- any option with
    a positive value counts as approved.
    """
    from pabutools.election import (  # noqa: PLC0415
        ApprovalBallot, ApprovalProfile, Instance, Project,
    )

    setting = fetch_setting(setting_id)
    instance = Instance()
    # Costs and the budget stay *integers*: pabutools computes with exact
    # rationals (gmpy2's mpq), and mpq() rejects a float numerator.
    instance.budget_limit = int(setting["budget_limit"]) if setting else 0

    projects = {}
    for option in fetch_options(setting_id):
        project = Project(str(option["id"]), cost=int(option["cost"]))
        projects[option["id"]] = project
        instance.add(project)

    profile = ApprovalProfile()
    for approved in approval_sets(setting_id, scope, by_name=False).values():
        profile.append(ApprovalBallot({projects[oid] for oid in approved}))
    return instance, profile
