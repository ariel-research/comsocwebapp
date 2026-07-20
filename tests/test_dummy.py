"""Dummy-user generation: formats, reproducibility, deletion."""

import random

from comsocwebapp import adapters, db, dummy


def test_ranking_is_a_permutation():
    ballot = dummy.generate_preferences("ranking", [7, 8, 9], rng=random.Random(0))
    assert sorted(ballot.values()) == [1, 2, 3]


def test_approval_values_are_binary():
    ballot = dummy.generate_preferences("approval", list(range(20)),
                                        rng=random.Random(1))
    assert set(ballot.values()) <= {0, 1}


def test_points_respect_bounds():
    ballot = dummy.generate_preferences("points", list(range(30)),
                                        rng=random.Random(2),
                                        distribution="normal", low=10, high=20)
    assert all(10 <= value <= 20 for value in ballot.values())


def test_budget_ballot_sums_to_the_limit():
    ballot = dummy.generate_preferences("budget", [1, 2, 3, 4],
                                        rng=random.Random(3), budget_limit=1000)
    assert sum(ballot.values()) == 1000


def test_seed_makes_generation_reproducible():
    kwargs = {"distribution": "uniform", "low": 0, "high": 50}
    first = dummy.generate_preferences("points", [1, 2, 3], rng=random.Random(42), **kwargs)
    second = dummy.generate_preferences("points", [1, 2, 3], rng=random.Random(42), **kwargs)
    assert first == second


def test_generate_and_delete_dummy_users(app, setting):
    with app.app_context():
        created = dummy.generate_dummy_users(setting["id"], 12, seed=7)
        assert len(created) == 12

        rows = adapters.fetch_preference_rows(setting["id"], adapters.SCOPE_DUMMY)
        assert len(rows) == 12 * len(setting["option_ids"])
        assert adapters.fetch_preference_rows(setting["id"], adapters.SCOPE_REAL) == []

        removed = dummy.delete_dummy_users(setting["id"])
        assert removed == 12
        assert db.query_one("SELECT COUNT(*) AS n FROM users")["n"] == 0
        assert db.query_one("SELECT COUNT(*) AS n FROM preferences")["n"] == 0


def test_unknown_distribution_is_rejected():
    try:
        dummy.generate_preferences("points", [1], distribution="cauchy")
    except ValueError as error:
        assert "cauchy" in str(error)
    else:
        raise AssertionError("expected a ValueError")
