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

    def _allocation_rule(name: str, headline: str, algorithm_import):
        """Register one ``divide``-based fair-allocation rule.

        ``algorithm_import`` is a zero-argument callable that imports and
        returns the fairpyx algorithm, so nothing is imported until the rule
        runs (keeping this module importable without fairpyx).  Bundles hold
        option *names* (to_fairpyx_instance builds the valuation matrix by
        name), so an allocation already reads in human terms; a per-item
        position cannot be attached to a whole bundle, which is the
        "show the name instead" fallback of design.md V3 Admin #7.
        """
        @rules.register_rule(name, formats=("points", "ranking"))
        def _rule(setting_id: int, scope: str = generic.SCOPE_ALL, **_):
            from fairpyx import divide

            allocation = divide(algorithm_import(),
                                to_fairpyx_instance(setting_id, scope))
            log = [headline, f"Agents: {len(allocation)}.", "Allocation:"]
            log += [f"  agent {agent}: {', '.join(map(str, bundle)) or '(nothing)'}"
                    for agent, bundle in allocation.items()]
            outcome = [f"{agent}:{'|'.join(map(str, bundle))}"
                       for agent, bundle in allocation.items()]
            return rules.RuleResult(outcome=outcome, log_lines=log)
        return _rule

    _allocation_rule(
        "fairpyx_round_robin",
        "Rule: fairpyx round-robin (envy-free up to one item).",
        lambda: __import__("fairpyx.algorithms", fromlist=["round_robin"]).round_robin)
    _allocation_rule(
        "fairpyx_bidirectional_round_robin",
        "Rule: fairpyx bidirectional round-robin (reduces the last-picker penalty).",
        lambda: __import__("fairpyx.algorithms",
                           fromlist=["bidirectional_round_robin"]).bidirectional_round_robin)
    _allocation_rule(
        "fairpyx_serial_dictatorship",
        "Rule: fairpyx serial dictatorship (each agent in turn takes all it wants).",
        lambda: __import__("fairpyx.algorithms",
                           fromlist=["serial_dictatorship"]).serial_dictatorship)
