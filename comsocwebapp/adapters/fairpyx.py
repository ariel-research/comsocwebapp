"""Adapter for `fairpyx <https://pypi.org/project/fairpyx/>`_ -- fair allocation
of indivisible items.

Nothing here is imported at module load time, so the file is safe to import on
an installation without ``fairpyx``; the library is pulled in when a function
actually runs.  (Despite this module also being called ``fairpyx``, ``import
fairpyx`` inside it resolves to the *installed library*: Python 3 imports are
absolute, and this module's full name is ``comsocwebapp.adapters.fairpyx``.)
"""

from . import generic

LIBRARY = "fairpyx"

__all__ = ["LIBRARY", "available", "to_fairpyx_instance", "register_rules"]


def available() -> bool:
    """True if the library is installed."""
    try:
        import fairpyx  # noqa: F401
    except ImportError:
        return False
    return True


def to_fairpyx_instance(setting_id: int, scope: str = generic.SCOPE_ALL):
    """Build a ``fairpyx.Instance`` from the stored preferences.

    ``fairpyx`` takes valuations as ``{agent: {item: value}}``, exactly the
    shape :func:`generic.preference_matrix` produces, so no reshaping is needed
    for the ``points`` / ``budget`` formats.  For ``ranking`` the values are
    inverted (rank 1 becomes the highest utility) because fairpyx maximises.
    """
    import fairpyx

    setting = generic.fetch_setting(setting_id)
    matrix = generic.preference_matrix(setting_id, scope, by_name=True)
    if setting and setting["pref_format"] == "ranking":
        size = len(generic.fetch_options(setting_id))
        matrix = {
            agent: {item: (size - value + 1 if value > 0 else 0)
                    for item, value in prefs.items()}
            for agent, prefs in matrix.items()
        }
    return fairpyx.Instance(valuations=matrix)


def register_rules() -> None:
    """Register this library's rules.  Called by :mod:`comsocwebapp.adapters`.

    ``rules`` is imported here rather than at module level to keep the import
    graph acyclic: ``rules`` depends on the adapters, not the other way round.
    """
    from .. import rules

    @rules.register_rule("fairpyx_round_robin", formats=("points", "ranking"))
    def fairpyx_round_robin(setting_id: int, scope: str = generic.SCOPE_ALL, **_):
        """Round-robin: agents take turns picking their most valued free item."""
        from fairpyx import divide
        from fairpyx.algorithms import round_robin

        allocation = divide(round_robin, to_fairpyx_instance(setting_id, scope))
        # Bundles hold option *names* (to_fairpyx_instance builds the valuation
        # matrix by name), so the allocation already reads in human terms; a
        # per-item position cannot be attached to a whole bundle, which is the
        # "show the name instead" fallback of design.md V3 Admin #7.
        log = ["Rule: fairpyx round-robin (envy-free up to one item).",
               f"Agents: {len(allocation)}.", "Allocation:"]
        log += [f"  agent {agent}: {', '.join(map(str, bundle)) or '(nothing)'}"
                for agent, bundle in allocation.items()]
        outcome = [f"{agent}:{'|'.join(map(str, bundle))}"
                   for agent, bundle in allocation.items()]
        return rules.RuleResult(outcome=outcome, log_lines=log)
