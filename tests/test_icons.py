import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from tools.make_icons import ICO_SIZES, SIMPLIFY_BELOW, _draw, build_app_ico

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

MAX_COLORS = 1 << 24


def colors_of(img) -> list:
    return [color for _count, color in img.convert("RGB").getcolors(MAX_COLORS)]


def has_near(img, target, tol=30) -> bool:
    return any(
        abs(c[0] - target[0]) < tol and abs(c[1] - target[1]) < tol and abs(c[2] - target[2]) < tol
        for c in colors_of(img)
    )


def test_every_declared_size_is_embedded(tmp_path):
    path = str(tmp_path / "app.ico")
    build_app_ico(path)
    with Image.open(path) as im:
        assert sorted(im.info["sizes"]) == sorted((s, s) for s in ICO_SIZES)


def test_drawn_icon_has_requested_pixel_size():
    for size in (16, 48, 256):
        img = _draw(size, "#00d2ff", simplified=size < SIMPLIFY_BELOW)
        assert img.size == (size, size)


def test_icon_is_not_blank():
    """A silently-failing draw would still produce a valid but empty image."""
    assert len(colors_of(_draw(64, "#00d2ff", simplified=False))) > 5


def test_small_sizes_drop_the_rows():
    """At 16 px the row bars turn to mush, so they are omitted - the purple
    'active row' accent must therefore be absent from the simplified art."""
    purple = (123, 47, 247)
    assert has_near(_draw(64, "#00d2ff", simplified=False), purple)
    assert not has_near(_draw(64, "#00d2ff", simplified=True), purple)


def test_check_color_is_applied_for_tray_states():
    assert has_near(_draw(64, "#ff5c72", simplified=False), (255, 92, 114))
    assert has_near(_draw(64, "#f1c40f", simplified=False), (241, 196, 15))
    assert not has_near(_draw(64, "#ff5c72", simplified=False), (0, 210, 255))
