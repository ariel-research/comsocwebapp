"""Adapters: the bridge from our SQL rows to the social-choice libraries.

``generic`` holds everything that is library-independent; each supported
library gets one file of its own.  See ``README.md`` in this folder for how to
add another one.

Importing this package is cheap and never fails: the per-library modules defer
their ``import`` statements to call time, so a bare installation can still load
:mod:`comsocwebapp.adapters` and use the generic half.

For convenience the generic names are re-exported here, so application code can
keep writing ``adapters.preference_matrix(...)`` or ``adapters.SCOPE_DUMMY``
without knowing which file they live in.
"""

from __future__ import annotations

from . import abcvoting, fairpyx, generic, pabutools
from .abcvoting import to_abcvoting_profile
from .fairpyx import to_fairpyx_instance
from .generic import (  # noqa: F401 -- re-exported for convenience
    SCOPE_ALL, SCOPE_DUMMY, SCOPE_REAL, SCOPES,
    approval_sets, fetch_options, fetch_participants, fetch_preference_rows,
    fetch_setting, fetch_user_preferences, option_costs, preference_matrix,
    rankings,
)
from .pabutools import to_pabutools_instance

#: Every library-specific adapter module.  Adding a file to this tuple is the
#: last step of supporting a new library.
LIBRARY_ADAPTERS = (fairpyx, abcvoting, pabutools)

__all__ = [
    "generic", "fairpyx", "abcvoting", "pabutools",
    "LIBRARY_ADAPTERS", "register_library_rules", "installed_libraries",
    "SCOPE_ALL", "SCOPE_REAL", "SCOPE_DUMMY", "SCOPES",
    "fetch_setting", "fetch_options", "fetch_participants",
    "fetch_preference_rows", "fetch_user_preferences",
    "preference_matrix", "approval_sets", "rankings", "option_costs",
    "to_fairpyx_instance", "to_abcvoting_profile", "to_pabutools_instance",
]


def installed_libraries() -> list[str]:
    """Names of the solver libraries that are actually importable here."""
    return [adapter.LIBRARY for adapter in LIBRARY_ADAPTERS if adapter.available()]


def register_library_rules() -> None:
    """Let every installed library register its rules.

    Called once from :mod:`comsocwebapp.rules`.  Adapters whose library is
    missing are skipped, so the rule list an admin sees always matches what
    this installation can actually run.
    """
    for adapter in LIBRARY_ADAPTERS:
        if adapter.available():
            adapter.register_rules()
