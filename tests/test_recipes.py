import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recipes as recipes_mod
from actions import Step
from recipes import Recipe, classic_recipe


def use_tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(recipes_mod, "recipes_dir", lambda: str(tmp_path))


def test_roundtrip_preserves_steps(tmp_path, monkeypatch):
    use_tmp_dir(tmp_path, monkeypatch)
    original = Recipe(
        name="Thử",
        steps=[
            Step("type", {"text": "{serial}"}),
            Step("key", {"key": "enter"}, on_fail="continue"),
            Step("wait", {"seconds": 1.5}, enabled=False),
        ],
    )
    recipes_mod.save_recipe(original, "thu")
    loaded = recipes_mod.load_recipe("thu")

    assert [s.type for s in loaded.steps] == ["type", "key", "wait"]
    assert loaded.steps[0].params["text"] == "{serial}"
    assert loaded.steps[1].on_fail == "continue"
    assert loaded.steps[2].enabled is False


def test_list_recipes_finds_saved_file(tmp_path, monkeypatch):
    use_tmp_dir(tmp_path, monkeypatch)
    recipes_mod.save_recipe(Recipe(name="A", steps=[Step("wait", {"seconds": 1})]), "a")
    assert "a" in recipes_mod.list_recipes()


def test_delete_recipe_removes_it(tmp_path, monkeypatch):
    use_tmp_dir(tmp_path, monkeypatch)
    recipes_mod.save_recipe(Recipe(name="B", steps=[Step("wait", {})]), "b")
    recipes_mod.delete_recipe("b")
    assert "b" not in recipes_mod.list_recipes()


def test_ensure_classic_is_idempotent(tmp_path, monkeypatch):
    use_tmp_dir(tmp_path, monkeypatch)
    recipes_mod.ensure_classic_on_disk()
    path = recipes_mod.recipe_path(recipes_mod.CLASSIC_NAME)
    first_mtime = os.path.getmtime(path)

    recipes_mod.ensure_classic_on_disk()
    assert os.path.getmtime(path) == first_mtime


# --- the classic recipe must mirror the built-in behaviour ------------------

def test_classic_recipe_types_the_serial_then_confirms():
    steps = classic_recipe().steps
    assert [s.type for s in steps][:3] == ["clear_field", "type", "key"]
    assert steps[1].params["text"] == "{serial}"
    assert steps[2].params["key"] == "enter"


def test_classic_recipe_honours_tab_enter_mode():
    keys = [s.params.get("key") for s in classic_recipe("tab_enter").steps if s.type == "key"]
    assert keys == ["tab", "enter"]


def test_classic_recipe_sends_no_key_in_none_mode():
    assert not any(s.type == "key" for s in classic_recipe("none").steps)


def test_classic_recipe_carries_keywords_into_check_step():
    recipe = classic_recipe(error_keywords="loi,hong", success_keywords="ok")
    check = [s for s in recipe.steps if s.type == "check"][0]
    assert check.params["error_keywords"] == "loi,hong"
    assert check.params["success_keywords"] == "ok"
