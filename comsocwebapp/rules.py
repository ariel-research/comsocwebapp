"""Resolution rules and their execution log.

A rule is a callable ``(setting_id, scope, **params) -> RuleResult``.  It is
registered under a name, listed in the admin GUI, and its result is written to
``execution_logs`` verbatim -- outcome and step-by-step log -- so that both the
admin and the participants can audit how the outcome was derived
(design.md, "Audit & Transparency").

Three rules are built in and depend on nothing but the standard library, so a
fresh install can run end-to-end.  The rules backed by ``fairpyx``,
``abcvoting`` and ``pabutools`` live next to their data bridges in
:mod:`comsocwebapp.adapters` and are registered from there -- only when the
library in question is importable.
"""

from dataclasses import dataclass, field
from typing import Callable

from . import adapters, db

__all__ = ["RuleResult", "register_rule", "available_rules", "run_rule",
           "record_execution", "describe_outcome"]


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
#: Which preference formats each rule applies to.  ``None`` means "any format";
#: otherwise only settings whose ``pref_format`` is in the tuple offer the rule.
_RULE_FORMATS: dict[str, tuple[str, ...] | None] = {}
#: Whether a rule needs a spending budget.  ``True`` = only offer it when the
#: setting has a budget limit (participatory budgeting); ``False`` = only offer
#: it when there is none (plain committee voting); ``None`` = do not care.
_RULE_NEEDS_BUDGET: dict[str, bool | None] = {}


def register_rule(name: str, formats: tuple[str, ...] | None = None,
                  needs_budget: bool | None = None):
    """Decorator registering a rule under ``name``.

    ``formats`` lists the preference formats the rule makes sense for (e.g.
    ``("approval",)`` for a committee-voting rule).  ``needs_budget`` further
    splits the approval ballots that committee voting and participatory
    budgeting share: budgeting rules take ``needs_budget=True`` so they surface
    only when the setting carries a budget, and committee rules take
    ``False`` so they step aside once one does.  Both drive the admin's rule
    picker (design.md V4 Admin #2); ``None`` means "always applicable".

    Applications extend the package by importing it and decorating their own
    function -- no subclassing, no configuration file.
    """
    def decorator(func):
        _REGISTRY[name] = func
        _RULE_FORMATS[name] = formats
        _RULE_NEEDS_BUDGET[name] = needs_budget
        return func
    return decorator


def available_rules(setting=None) -> list[str]:
    """Rule names, narrowed to those that fit ``setting``.

    ``setting`` is a mapping with ``pref_format`` and ``budget_limit`` (the row
    :func:`adapters.fetch_setting` returns), or ``None`` for the full list.  A
    rule fits when the setting's format is among its ``formats`` *and* the
    presence of a budget matches its ``needs_budget``.
    """
    if setting is None:
        return sorted(_REGISTRY)
    pref_format = setting["pref_format"]
    has_budget = bool(setting.get("budget_limit"))
    return sorted(
        name for name in _REGISTRY
        if (_RULE_FORMATS[name] is None or pref_format in _RULE_FORMATS[name])
        and (_RULE_NEEDS_BUDGET[name] is None
             or _RULE_NEEDS_BUDGET[name] == has_budget)
    )


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


def describe_outcome(setting_id: int, outcome_text: str) -> list[str]:
    """Turn a stored outcome string into human-readable winner labels.

    Outcomes are stored as machine-stable option ids so they never drift when
    an option is renamed.  For display we resolve each id to its position in
    the setting plus name and description ("3. Bike lanes -- 2 km of track").
    Tokens that are not a plain option id (e.g. a fairpyx allocation such as
    ``agent:item|item``) cannot be placed by position, so they fall back to
    whatever the rule stored -- satisfying design.md V3 Admin #7.
    """
    options = {o["id"]: o for o in adapters.fetch_options(setting_id)}
    labels = []
    for token in (part.strip() for part in outcome_text.split(",")):
        if not token:
            continue
        option = options.get(int(token)) if token.isdigit() else None
        # Not a plain option id (e.g. a fairpyx allocation) -> show it verbatim.
        labels.append(adapters.option_label(option) if option else token)
    return labels


def _winner_labels(setting_id: int, winner_ids) -> str:
    """Comma-joined 'position. name' for winners, for use inside a run log."""
    return ", ".join(describe_outcome(setting_id, ", ".join(map(str, winner_ids)))) \
        or "(none)"


# --------------------------------------------------------------------------
# Built-in rules (no external dependencies)
# --------------------------------------------------------------------------

@register_rule("approval_scoring", formats=("approval",), needs_budget=False)
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
    log.append("Winners: " + _winner_labels(setting_id, winners))
    return RuleResult(outcome=winners, log_lines=log)


@register_rule("borda", formats=("ranking",))
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
    log.append("Winners: " + _winner_labels(setting_id, winners))
    return RuleResult(outcome=winners, log_lines=log)


@register_rule("greedy_budget", formats=("approval", "budget"), needs_budget=True)
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
# Library-backed rules
# --------------------------------------------------------------------------
# Each supported solver library registers its own rules from its adapter
# module, so that everything specific to a library lives in one file.  Missing
# libraries are skipped: the rule list always matches what this installation
# can actually run.

adapters.register_library_rules()
