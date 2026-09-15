"""
recipes.py
Load and save automation recipes (a named list of steps) as JSON.

Recipes live in a recipes/ folder that can be copied between machines - next to
the project when running from source, in %LOCALAPPDATA%\\SerialBot once installed
(see paths.py).
"""
import json
import os
from dataclasses import dataclass, field

from actions import ON_FAIL_CONTINUE, ON_FAIL_ERROR, Step
from paths import recipes_dir as _user_recipes_dir
from paths import seed_bundled_recipes

RECIPE_EXT = ".json"
CLASSIC_NAME = "classic"


def recipes_dir() -> str:
    return _user_recipes_dir()


@dataclass
class Recipe:
    name: str = "Kịch bản mới"
    steps: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": 1,
            "steps": [s.to_dict() for s in self.steps],
        }

    @staticmethod
    def from_dict(data: dict) -> "Recipe":
        return Recipe(
            name=data.get("name", "Kịch bản"),
            steps=[Step.from_dict(s) for s in data.get("steps", [])],
        )


def classic_recipe(
    enter_mode: str = "enter",
    error_keywords: str = "",
    success_keywords: str = "",
) -> Recipe:
    """
    Reproduces the built-in behaviour: clear the field, type the serial, confirm,
    then verify. Used as the default so existing setups keep working unchanged.
    """
    steps = [
        Step("clear_field", {}, on_fail=ON_FAIL_ERROR),
        Step("type", {"text": "{serial}"}, on_fail=ON_FAIL_ERROR),
    ]

    if enter_mode == "tab_enter":
        steps.append(Step("key", {"key": "tab"}, on_fail=ON_FAIL_CONTINUE))
        steps.append(Step("key", {"key": "enter"}, on_fail=ON_FAIL_ERROR))
    elif enter_mode != "none":
        steps.append(Step("key", {"key": "enter"}, on_fail=ON_FAIL_ERROR))

    steps.append(Step("wait", {"seconds": 0.2}, on_fail=ON_FAIL_CONTINUE))
    steps.append(
        Step(
            "check",
            {"success_keywords": success_keywords, "error_keywords": error_keywords},
            on_fail=ON_FAIL_CONTINUE,
        )
    )
    return Recipe(name="Classic", steps=steps)


def list_recipes() -> list[str]:
    directory = recipes_dir()
    if not os.path.isdir(directory):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(directory)
        if f.lower().endswith(RECIPE_EXT)
    )


def recipe_path(name: str) -> str:
    return os.path.join(recipes_dir(), f"{name}{RECIPE_EXT}")


def load_recipe(name: str) -> Recipe:
    with open(recipe_path(name), "r", encoding="utf-8") as f:
        return Recipe.from_dict(json.load(f))


def save_recipe(recipe: Recipe, name: str | None = None) -> str:
    directory = recipes_dir()
    os.makedirs(directory, exist_ok=True)
    path = recipe_path(name or _slugify(recipe.name))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(recipe.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def delete_recipe(name: str):
    try:
        os.remove(recipe_path(name))
    except OSError:
        pass


def ensure_classic_on_disk():
    """Write the built-in recipe once so users have a working example to copy."""
    seed_bundled_recipes()
    path = recipe_path(CLASSIC_NAME)
    if os.path.isfile(path):
        return
    save_recipe(
        classic_recipe(error_keywords="error,invalid,loi,khong hop le"),
        CLASSIC_NAME,
    )


def _slugify(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip())
    return safe.lower() or "recipe"
