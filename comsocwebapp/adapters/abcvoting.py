"""Adapter for `abcvoting <https://pypi.org/project/abcvoting/>`_ --
approval-based committee voting.

Nothing here is imported at module load time, so the file is safe to import on
an installation without ``abcvoting``.
"""

from . import generic

LIBRARY = "abcvoting"

__all__ = ["LIBRARY", "available", "to_abcvoting_profile", "register_rules"]


def available() -> bool:
    """True if the library is installed."""
    try:
        import abcvoting  # noqa: F401
    except ImportError:
        return False
    return True


def to_abcvoting_profile(setting_id: int, scope: str = generic.SCOPE_ALL):
    """Build ``(Profile, option_ids)`` from the stored approvals.

    ``abcvoting`` identifies candidates by consecutive integers starting at 0,
    which our ``options.id`` values are not, so the list mapping position back
    to ``option_id`` is returned alongside the profile.
    """
    from abcvoting.preferences import Profile

    options = generic.fetch_options(setting_id)
    index_of = {o["id"]: position for position, o in enumerate(options)}

    profile = Profile(len(options), cand_names=[o["name"] for o in options])
    for approved in generic.approval_sets(setting_id, scope, by_name=False).values():
        if approved:  # abcvoting rejects empty ballots
            profile.add_voter([index_of[option_id] for option_id in sorted(approved)])
    return profile, [o["id"] for o in options]


def register_rules() -> None:
    """Register this library's rules.  Called by :mod:`comsocwebapp.adapters`."""
    from .. import rules

    @rules.register_rule("abcvoting_pav")
    def abcvoting_pav(setting_id: int, scope: str = generic.SCOPE_ALL,
                      committee_size: int = 3, **_):
        """Proportional Approval Voting."""
        from abcvoting import abcrules

        profile, option_ids = to_abcvoting_profile(setting_id, scope)
        committees = abcrules.compute("pav", profile, committeesize=committee_size)
        winners = [option_ids[index] for index in sorted(committees[0])]
        log = ["Rule: abcvoting Proportional Approval Voting (PAV).",
               f"Voters: {len(profile)}, candidates: {len(option_ids)},"
               f" committee size: {committee_size}.",
               f"Tied optimal committees found: {len(committees)}.",
               "Elected: " + ", ".join(str(winner) for winner in winners)]
        return rules.RuleResult(outcome=winners, log_lines=log)
