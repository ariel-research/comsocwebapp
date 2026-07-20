"""Bulk generation of dummy users with randomised preferences.

Dummy users (``users.is_dummy = 1``) let an admin demo or stress-test a rule
before real participants arrive.  They have no email and no password hash, so
they can never authenticate; they exist purely as carriers of preferences.

Randomisation is parameterised (distribution, bounds, seed) as required by
design.md, and the generated values respect the setting's ``pref_format``:

* ``approval`` -- Bernoulli(``approval_rate``) over the options, 0/1.
* ``ranking``  -- a uniformly random permutation, values 1..n.
* ``points``   -- draws from ``distribution`` clipped to [low, high].
* ``budget``   -- draws rescaled so each ballot sums to ``budget_limit``.
"""

from __future__ import annotations

import random

from . import adapters, db

__all__ = ["generate_preferences", "generate_dummy_users", "delete_dummy_users"]

DISTRIBUTIONS = ("uniform", "normal", "exponential")


def _draw(rng: random.Random, distribution: str, low: int, high: int) -> int:
    """Draw one integer in [low, high] from the named distribution."""
    if distribution == "uniform":
        value = rng.uniform(low, high)
    elif distribution == "normal":
        # Centre the bell in the interval and let 3 sigma reach the bounds.
        mu, sigma = (low + high) / 2.0, max((high - low) / 6.0, 1e-9)
        value = rng.gauss(mu, sigma)
    elif distribution == "exponential":
        # Mean at one quarter of the range: many small values, few large ones.
        value = low + rng.expovariate(1.0 / max((high - low) / 4.0, 1e-9))
    else:
        raise ValueError(f"Unknown distribution: {distribution!r}"
                         f" (expected one of {DISTRIBUTIONS})")
    return int(round(min(max(value, low), high)))


def generate_preferences(pref_format: str, option_ids: list[int], *,
                         rng: random.Random | None = None,
                         distribution: str = "uniform",
                         low: int = 0, high: int = 100,
                         approval_rate: float = 0.4,
                         budget_limit: int = 0) -> dict[int, int]:
    """Return ``{option_id: value}`` for one simulated ballot.

    Pure function -- it touches neither the database nor global random state,
    which is what makes the generator reproducible from a seed and directly
    unit-testable.
    """
    rng = rng or random.Random()

    if pref_format == "approval":
        return {oid: (1 if rng.random() < approval_rate else 0) for oid in option_ids}

    if pref_format == "ranking":
        shuffled = list(option_ids)
        rng.shuffle(shuffled)
        return {oid: rank for rank, oid in enumerate(shuffled, start=1)}

    if pref_format == "budget":
        raw = {oid: _draw(rng, distribution, low, high) for oid in option_ids}
        total = sum(raw.values())
        if budget_limit <= 0 or total == 0:
            return raw
        # Rescale to the budget, then hand any rounding remainder to the
        # option that received the most, so each ballot sums exactly.
        scaled = {oid: int(value * budget_limit // total) for oid, value in raw.items()}
        remainder = budget_limit - sum(scaled.values())
        if remainder:
            scaled[max(scaled, key=lambda oid: scaled[oid])] += remainder
        return scaled

    # 'points' and any custom format: independent draws.
    return {oid: _draw(rng, distribution, low, high) for oid in option_ids}


def generate_dummy_users(setting_id: int, count: int, *,
                         distribution: str = "uniform",
                         low: int = 0, high: int = 100,
                         approval_rate: float = 0.4,
                         seed: int | None = None) -> list[int]:
    """Create ``count`` dummy users with random ballots; return their ids."""
    setting = adapters.fetch_setting(setting_id)
    if setting is None:
        raise ValueError(f"No such setting: {setting_id}")
    option_ids = [option["id"] for option in adapters.fetch_options(setting_id)]
    if not option_ids:
        raise ValueError("Add options to the setting before generating dummy users.")

    rng = random.Random(seed)
    now = db.utcnow_text()
    created: list[int] = []

    for _ in range(count):
        user_id = db.insert_returning_id(
            "INSERT INTO users (email, password_hash, is_admin, is_dummy, created_at)"
            " VALUES (?, ?, 0, 1, ?)",
            (None, None, now),
            commit=False,
        )
        ballot = generate_preferences(
            setting["pref_format"], option_ids, rng=rng,
            distribution=distribution, low=low, high=high,
            approval_rate=approval_rate, budget_limit=setting["budget_limit"],
        )
        db.execute_many(
            "INSERT INTO preferences (user_id, setting_id, option_id, value)"
            " VALUES (?, ?, ?, ?)",
            [(user_id, setting_id, oid, value) for oid, value in ballot.items()],
            commit=False,
        )
        created.append(user_id)

    db.get_db().commit()
    return created


def delete_dummy_users(setting_id: int) -> int:
    """Remove every dummy user of a setting, ballots first.

    Children are deleted before parents so the foreign keys hold at every
    step; ``DELETE ... USING`` and multi-table DELETE are not portable, hence
    the sub-query.
    """
    db.execute(
        "DELETE FROM preferences WHERE setting_id = ? AND user_id IN"
        " (SELECT id FROM users WHERE is_dummy = 1)",
        (setting_id,),
        commit=False,
    )
    removed = db.execute(
        "DELETE FROM users WHERE is_dummy = 1 AND id NOT IN"
        " (SELECT user_id FROM preferences)",
        (),
        commit=False,
    )
    db.get_db().commit()
    return removed
