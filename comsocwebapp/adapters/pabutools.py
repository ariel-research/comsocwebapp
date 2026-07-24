"""Adapter for `pabutools <https://pypi.org/project/pabutools/>`_ --
participatory budgeting.

Nothing here is imported at module load time, so the file is safe to import on
an installation without ``pabutools``.
"""

from . import generic

LIBRARY = "pabutools"

__all__ = ["LIBRARY", "available", "to_pabutools_instance", "register_rules"]


def available() -> bool:
    """True if the library is installed."""
    try:
        import pabutools  # noqa: F401
    except ImportError:
        return False
    return True


def to_pabutools_instance(setting_id: int, scope: str = generic.SCOPE_ALL):
    """Build an ``(Instance, ApprovalProfile)`` pair from the stored ballots.

    Projects carry their ``options.cost`` and are named by ``options.id`` so
    the winners can be mapped straight back to our table; the budget comes from
    ``settings.budget_limit``.  Any option with a positive value counts as
    approved.
    """
    from pabutools.election import (
        ApprovalBallot, ApprovalProfile, Instance, Project,
    )

    setting = generic.fetch_setting(setting_id)
    instance = Instance()
    # Costs and the budget stay *integers*: pabutools computes with exact
    # rationals (gmpy2's mpq), and mpq() rejects a float numerator.
    instance.budget_limit = int(setting["budget_limit"]) if setting else 0

    projects = {}
    for option in generic.fetch_options(setting_id):
        project = Project(str(option["id"]), cost=int(option["cost"]))
        projects[option["id"]] = project
        instance.add(project)

    profile = ApprovalProfile()
    for approved in generic.approval_sets(setting_id, scope, by_name=False).values():
        profile.append(ApprovalBallot({projects[oid] for oid in approved}))
    return instance, profile


def register_rules() -> None:
    """Register this library's rules.  Called by :mod:`comsocwebapp.adapters`."""
    from .. import rules

    def _funding_log(headline: str, instance, profile, setting_id, winners):
        """Shared log body for the budgeting rules below."""
        options = {o["id"]: o for o in generic.fetch_options(setting_id)}
        spent = sum(options[oid]["cost"] for oid in winners)
        return [headline,
                f"Budget limit: {instance.budget_limit}.",
                f"Ballots: {len(profile)}, projects: {len(instance)}.",
                f"Funded {len(winners)} projects for {spent} of"
                f" {instance.budget_limit}:",
                *(f"  {generic.option_label(options[oid])}" for oid in winners)]

    @rules.register_rule("pabutools_mes", formats=("approval", "budget"),
                         needs_budget=True)
    def pabutools_mes(setting_id: int, scope: str = generic.SCOPE_ALL, **_):
        """Method of Equal Shares over cost satisfaction."""
        from pabutools.election import Cost_Sat
        from pabutools.rules import method_of_equal_shares

        instance, profile = to_pabutools_instance(setting_id, scope)
        allocation = method_of_equal_shares(instance, profile, sat_class=Cost_Sat)
        winners = [int(project.name) for project in allocation]
        log = _funding_log("Rule: pabutools Method of Equal Shares (Cost"
                           " satisfaction).", instance, profile, setting_id, winners)
        return rules.RuleResult(outcome=winners, log_lines=log)

    @rules.register_rule("pabutools_phragmen", formats=("approval", "budget"),
                         needs_budget=True)
    def pabutools_phragmen(setting_id: int, scope: str = generic.SCOPE_ALL, **_):
        """Sequential Phragmén: a load-balancing participatory-budgeting rule."""
        from pabutools.rules import sequential_phragmen

        instance, profile = to_pabutools_instance(setting_id, scope)
        allocation = sequential_phragmen(instance, profile)
        winners = [int(project.name) for project in allocation]
        log = _funding_log("Rule: pabutools sequential Phragmén.",
                           instance, profile, setting_id, winners)
        return rules.RuleResult(outcome=winners, log_lines=log)
