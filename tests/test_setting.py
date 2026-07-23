"""The setting/option wrapper: consecutive numbering, in-place edits, cascades."""

import pytest

from comsocwebapp import adapters, db, setting as setting_api


def test_create_setting_numbers_options_from_one(app):
    with app.app_context():
        setting_id = setting_api.create_setting(
            "Election", "approval",
            options=["Alpha", "Beta", "Gamma"])
        positions = [o["position"] for o in adapters.fetch_options(setting_id)]
    assert positions == [1, 2, 3]


def test_positions_are_per_setting(app):
    """Two settings each number their options from 1, independently."""
    with app.app_context():
        first = setting_api.create_setting("A", "approval", options=["a1", "a2"])
        second = setting_api.create_setting("B", "approval", options=["b1", "b2", "b3"])
        first_pos = [o["position"] for o in adapters.fetch_options(first)]
        second_pos = [o["position"] for o in adapters.fetch_options(second)]
    assert first_pos == [1, 2]
    assert second_pos == [1, 2, 3]


def test_added_option_continues_the_numbering(app):
    with app.app_context():
        setting_id = setting_api.create_setting("S", "approval", options=["one", "two"])
        setting_api.add_option(setting_id, "three")
        positions = [o["position"] for o in adapters.fetch_options(setting_id)]
    assert positions == [1, 2, 3]


def test_option_accepts_string_tuple_and_mapping(app):
    with app.app_context():
        setting_id = setting_api.create_setting("S", "budget", options=[
            "just a name",
            ("named tuple", "desc", 40),
            {"name": "mapping", "cost": 70},
        ])
        options = adapters.fetch_options(setting_id)
    assert [o["name"] for o in options] == ["just a name", "named tuple", "mapping"]
    assert [o["cost"] for o in options] == [0, 40, 70]


def test_delete_option_renumbers_the_survivors(app):
    with app.app_context():
        setting_id = setting_api.create_setting(
            "S", "approval", options=["one", "two", "three", "four"])
        options = adapters.fetch_options(setting_id)
        setting_api.delete_option(options[1]["id"])   # remove "two"
        remaining = adapters.fetch_options(setting_id)
    assert [o["name"] for o in remaining] == ["one", "three", "four"]
    assert [o["position"] for o in remaining] == [1, 2, 3]


def test_deleting_an_option_removes_its_preferences(app):
    with app.app_context():
        setting_id = setting_api.create_setting("S", "approval", options=["a", "b"])
        a, b = adapters.fetch_options(setting_id)
        from comsocwebapp import auth
        user = auth.create_user("v@example.com", "pw")
        db.upsert_preference(user, setting_id, a["id"], 1)
        db.upsert_preference(user, setting_id, b["id"], 1)

        setting_api.delete_option(a["id"])
        leftover = db.query_all("SELECT option_id FROM preferences")
    assert [row["option_id"] for row in leftover] == [b["id"]]


def test_update_option_keeps_id_and_position(app):
    with app.app_context():
        setting_id = setting_api.create_setting("S", "budget", options=[("x", "", 10)])
        option = adapters.fetch_options(setting_id)[0]
        setting_api.update_option(option["id"], name="X renamed", cost=99)
        after = setting_api.get_option(option["id"])
    assert after["id"] == option["id"]
    assert after["position"] == option["position"]
    assert after["name"] == "X renamed"
    assert after["cost"] == 99


def test_create_setting_validates_enumerations(app):
    with app.app_context():
        with pytest.raises(ValueError):
            setting_api.create_setting("S", "nonsense-format")
        with pytest.raises(ValueError):
            setting_api.create_setting("", "approval")


def test_renumber_is_a_no_op_when_already_consecutive(app):
    with app.app_context():
        setting_id = setting_api.create_setting("S", "approval", options=["a", "b", "c"])
        setting_api.renumber_options(setting_id)
        positions = [o["position"] for o in adapters.fetch_options(setting_id)]
    assert positions == [1, 2, 3]
