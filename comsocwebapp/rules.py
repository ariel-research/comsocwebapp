"""Resolution rules and their execution log.

A rule is a callable ``(setting_id, scope, **params) -> RuleResult``.  It is
registered under a name, listed in the admin GUI, and its result is written to
``execution_logs`` verbatim -- outcome and step-by-step log -- so that both the
admin and the participants can audit how the outcome was derived
(design.md, "Audit & Transparency").

Three rules are built in and depend on nothing but the standard library, so a
fresh install can run end-to-end.  The wrappers for ``fairpyx``, ``abcvoting``
and ``pabutools`` register themselves only when their library is importable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import adapters, db

__all__ = ["RuleResult", "register_rule", "available_rules", "run_rule", "record_execution"]


@dataclass
class RuleResult:
    """What a rule returns: the winners plus a human-readable trace."""
    outcome: list          # option ids (or (user, item) pairs, as strings)
    log_lines: list[str] = field(default_factory=list)

    def outcome_text(self) -> str:
        """Serialise for ``execution_logs.outcome`` (VARCHAR(4000))."""
        return ", ".join(str(item) for item in self.outcome)[:4000]

    def log_text(self) -> str:
        """Serialise for ``execution_logs.run_log`` (VARCHAR(4000))."""
        return "\n".join(self.log_lines)[:4000]


_REGISTRY: dict[str, Callable[..., RuleResult]] = {}


def register_rule(name: str):
    """Decorator registering a rule under ``name``.

    Applications extend the package by importing it and decorating their own
    function -- no subclassing, no configuration file.
    """
    def decorator(func):
        _REGISTRY[name] = func
        return func
    return decorator


def available_rules() -> list[str]:
    return sorted(_REGISTRY)


def run_rule(rule_name: str, setting_id: int,
             scope: str = adapters.SCOPE_ALL, **params) -> RuleResult:
    if rule_name not in _REGISTRY:
        raise ValueError(f"Unknown rule: {rule_name!r}. Available: {available_rules()}")
    return _REGISTRY[rule_name](setting_id, scope, **params)


def record_execution(setting_id: int, rule_name: str, result: RuleResult) -> int:
    """Persist a rule run and return the ``execution_logs.id``."""
    return db.insert_returning_id(
        "INSERT INTO execution_logs (setting_id, rule_name, outcome, run_log)"
        " VALUES (?, ?, ?, ?)",
        (setting_id, rule_name, result.outcome_text(), result.log_text()),
    )


# --------------------------------------------------------------------------
# Built-in rules (no external dependencies)
# --------------------------------------------------------------------------

@register_rule("approval_scoring")
def approval_scoring(setting_id: int, scope: str = adapters.SCOPE_ALL,
                     committee_size: int = 1, **_) -> RuleResult:
    """Elect the ``committee_size`` options with the most approvals."""
    options = {o["id"]: o["name"] for o in adapters.fetch_options(setting_id)}
    scores = {oid: 0 for oid in options}
    for approved in adapters.approval_sets(setting_id, scope).values():
        for oid in approved:
            scores[oid] += 1

    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    winners = [oid for oid, _ in ordered[:committee_size]]

    log = [f"Rule: approval_scoring (committee size {committee_size}, scope '{scope}').",
           "Approval counts:"]
    log += [f"  {options[oid]}: {score}" for oid, score in ordered]
    log.append("Winners: " + ", ".join(options[oid] for oid in winners))
    return RuleResult(outcome=winners, log_lines=log)


@register_rule("borda")
def borda(setting_id: int, scope: str = adapters.SCOPE_ALL,
          committee_size: int = 1, **_) -> RuleResult:
    """Borda count over the ``ranking`` format: rank 1 earns n-1 points."""
    options = {o["id"]: o["name"] for o in adapters.fetch_options(setting_id)}
    size = len(options)
    scores = {oid: 0 for oid in options}
    for ranking in adapters.rankings(setting_id, scope).values():
        for position, oid in enumerate(ranking):
            scores[oid] += size - 1 - position

    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    winners = [oid for oid, _ in ordered[:committee_size]]

    log = [f"Rule: borda (scope '{scope}'), {size} options.", "Borda scores:"]
    log += [f"  {options[oid]}: {score}" for oid, score in ordered]
    log.append("Winners: " + ", ".join(options[oid] for oid in winners))
    return RuleResult(outcome=winners, log_lines=log)


@register_rule("greedy_budget")
def greedy_budget(setting_id: int, scope: str = adapters.SCOPE_ALL, **_) -> RuleResult:
    """Greedy participatory budgeting: best approvals-per-currency first."""
    setting = adapters.fetch_setting(setting_id)
    budget = setting["budget_limit"] if setting else 0
    options = {o["id"]: o for o in adapters.fetch_options(setting_id)}

    support = {oid: 0 for oid in options}
    for approved in adapters.approval_sets(setting_id, scope).values():
        for oid in approved:
            support[oid] += 1

    def efficiency(oid: int) -> float:
        cost = options[oid]["cost"]
        return support[oid] / cost if cost > 0 else float("inf")

    log = [f"Rule: greedy_budget (scope '{scope}'), budget limit {budget}.",
           "Ranking projects by support / cost:"]
    winners, spent = [], 0
    for oid in sorted(options, key=lambda oid: (-efficiency(oid), oid)):
        cost = options[oid]["cost"]
        name = options[oid]["name"]
        if spent + cost <= budget:
            winners.append(oid)
            spent += cost
            log.append(f"  SELECT {name}: support {support[oid]}, cost {cost},"
                       f" total spent {spent}.")
        else:
            log.append(f"  skip   {name}: support {support[oid]}, cost {cost}"
                       f" exceeds remaining budget {budget - spent}.")
    log.append(f"Funded {len(winners)} projects for {spent} of {budget}.")
    return RuleResult(outcome=winners, log_lines=log)


# --------------------------------------------------------------------------
# Library-backed rules -- registered only if the library is installed
# --------------------------------------------------------------------------

def _register_optional_rules() -> None:
    try:  # fair item allocation
        import fairpyx  # noqa: F401,PLC0415

        @register_rule("fairpyx_round_robin")
        def fairpyx_round_robin(setting_id: int, scope: str = adapters.SCOPE_ALL, **_):
            from fairpyx.algorithms import round_robin  # noqa: PLC0415
            from fairpyx import divide  # noqa: PLC0415

            instance = adapters.to_fairpyx_instance(setting_id, scope)
            allocation = divide(round_robin, instance)
            log = ["Rule: fairpyx round-robin.",
                   f"Agents: {len(allocation)}.", "Allocation:"]
            log += [f"  agent {agent}: {', '.join(map(str, bundle))}"
                    for agent, bundle in allocation.items()]
            outcome = [f"{agent}:{'|'.join(map(str, bundle))}"
                       for agent, bundle in allocation.items()]
            return RuleResult(outcome=outcome, log_lines=log)
    except ImportError:
        pass

    try:  # approval-based committee voting
        import abcvoting  # noqa: F401,PLC0415

        @register_rule("abcvoting_pav")
        def abcvoting_pav(setting_id: int, scope: str = adapters.SCOPE_ALL,
                          committee_size: int = 3, **_):
            from abcvoting import abcrules  # noqa: PLC0415

            profile, option_ids = adapters.to_abcvoting_profile(setting_id, scope)
            committees = abcrules.compute("pav", profile, committeesize=committee_size)
            winners = [option_ids[index] for index in sorted(committees[0])]
            log = ["Rule: abcvoting Proportional Approval Voting (PAV).",
                   f"Voters: {len(profile)}, candidates: {len(option_ids)},"
                   f" committee size: {committee_size}.",
                   f"Tied optimal committees found: {len(committees)}.",
                   "Elected: " + ", ".join(str(w) for w in winners)]
            return RuleResult(outcome=winners, log_lines=log)
    except ImportError:
        pass

    try:  # participatory budgeting
        import pabutools  # noqa: F401,PLC0415

        @register_rule("pabutools_mes")
        def pabutools_mes(setting_id: int, scope: str = adapters.SCOPE_ALL, **_):
            from pabutools.rules import method_of_equal_shares  # noqa: PLC0415
            from pabutools.election import Cost_Sat  # noqa: PLC0415

            instance, profile = adapters.to_pabutools_instance(setting_id, scope)
            budget_allocation = method_of_equal_shares(
                instance, profile, sat_class=Cost_Sat)
            winners = [int(project.name) for project in budget_allocation]
            log = ["Rule: pabutools Method of Equal Shares (Cost satisfaction).",
                   f"Budget limit: {instance.budget_limit}.",
                   f"Ballots: {len(profile)}, projects: {len(instance)}.",
                   "Funded project ids: " + ", ".join(map(str, winners))]
            return RuleResult(outcome=winners, log_lines=log)
    except ImportError:
        pass


_register_optional_rules()
