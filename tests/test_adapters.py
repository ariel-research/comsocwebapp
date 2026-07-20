"""The library-independent adapter shapes, plus the three library bridges."""

import pytest

from comsocwebapp import adapters, auth, db, rules


def _ballots(app, setting, ballots):
    """ballots: list of {option_index: value} -- one dict per user."""
    with app.app_context():
        for index, ballot in enumerate(ballots):
            user_id = auth.create_user(f"u{index}@example.com", "pw")
            for option_index, value in ballot.items():
                db.upsert_preference(user_id, setting["id"],
                                     setting["option_ids"][option_index], value)


def test_preference_matrix_is_rectangular(app, setting):
    _ballots(app, setting, [{0: 5}, {1: 3, 2: 7}])
    with app.app_context():
        matrix = adapters.preference_matrix(setting["id"])
    assert len(matrix) == 2
    for prefs in matrix.values():
        assert set(prefs) == {"Alpha", "Beta", "Gamma"}
    assert list(matrix.values())[0]["Beta"] == 0  # untouched option filled with 0


def test_approval_sets_keep_positive_values_only(app, setting):
    _ballots(app, setting, [{0: 1, 1: 0, 2: 1}])
    with app.app_context():
        sets = adapters.approval_sets(setting["id"])
    assert list(sets.values())[0] == {setting["option_ids"][0], setting["option_ids"][2]}


def test_rankings_sort_best_first(app, setting):
    with app.app_context():
        db.execute("UPDATE settings SET pref_format = 'ranking' WHERE id = ?",
                   (setting["id"],))
    _ballots(app, setting, [{0: 2, 1: 1, 2: 3}])
    with app.app_context():
        ranking = list(adapters.rankings(setting["id"]).values())[0]
    a, b, c = setting["option_ids"]
    assert ranking == [b, a, c]


def test_option_costs(app, setting):
    with app.app_context():
        assert adapters.option_costs(setting["id"]) == {
            "Alpha": 30, "Beta": 50, "Gamma": 60}


# --------------------------------------------------------------------------
# Bridges to the solver libraries -- skipped when the extra is not installed.
# --------------------------------------------------------------------------

def test_fairpyx_instance_and_rule(app, setting):
    pytest.importorskip("fairpyx")
    _ballots(app, setting, [{0: 9, 1: 1, 2: 5}, {0: 2, 1: 8, 2: 4}])
    with app.app_context():
        instance = adapters.to_fairpyx_instance(setting["id"])
        assert set(instance.items) == {"Alpha", "Beta", "Gamma"}
        result = rules.run_rule("fairpyx_round_robin", setting["id"])
    assert result.outcome and "round-robin" in result.log_text()


def test_abcvoting_profile_and_rule(app, setting):
    pytest.importorskip("abcvoting")
    _ballots(app, setting, [{0: 1, 1: 1}, {0: 1, 2: 1}, {0: 1, 1: 1}])
    with app.app_context():
        profile, option_ids = adapters.to_abcvoting_profile(setting["id"])
        assert len(profile) == 3
        assert option_ids == setting["option_ids"]  # position -> real option id
        result = rules.run_rule("abcvoting_pav", setting["id"], committee_size=2)
    # The winners are option ids from our table, not abcvoting's 0-based indices.
    assert set(result.outcome) <= set(setting["option_ids"])
    assert len(result.outcome) == 2


def test_pabutools_instance_and_rule(app, setting):
    pytest.importorskip("pabutools")
    _ballots(app, setting, [{0: 1, 1: 1}, {0: 1}, {0: 1, 2: 1}])
    with app.app_context():
        instance, profile = adapters.to_pabutools_instance(setting["id"])
        # Integer costs and budget: pabutools' exact rationals reject floats.
        assert isinstance(instance.budget_limit, int)
        assert all(isinstance(project.cost, int) for project in instance)
        assert len(profile) == 3
        result = rules.run_rule("pabutools_mes", setting["id"])
        costs = adapters.option_costs(setting["id"], by_name=False)
    assert sum(costs[oid] for oid in result.outcome) <= 100


def test_ranking_values_are_inverted_for_fairpyx(app, setting):
    """fairpyx maximises, so rank 1 must become the *highest* utility."""
    pytest.importorskip("fairpyx")
    with app.app_context():
        db.execute("UPDATE settings SET pref_format = 'ranking' WHERE id = ?",
                   (setting["id"],))
    _ballots(app, setting, [{0: 1, 1: 2, 2: 3}])
    with app.app_context():
        instance = adapters.to_fairpyx_instance(setting["id"])
        agent = list(instance.agents)[0]
        assert instance.agent_item_value(agent, "Alpha") > \
               instance.agent_item_value(agent, "Gamma")


def test_unknown_scope_is_rejected(app, setting):
    with app.app_context():
        try:
            adapters.fetch_preference_rows(setting["id"], "everyone")
        except ValueError as error:
            assert "everyone" in str(error)
        else:
            raise AssertionError("expected a ValueError")
