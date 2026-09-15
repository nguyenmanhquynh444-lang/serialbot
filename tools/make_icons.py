"""
tools/make_icons.py
Generates the application icon set from code (no binary assets in the repo).

Run:  python tools/make_icons.py

Design "rows to check": a dark tile holding three spreadsheet rows (the last one
highlighted as the row being processed) and a check mark for the verified result.

Small sizes drop the rows entirely - at 16 px three 1 px bars turn into mush, so
those sizes keep only the check mark drawn with a heavier stroke. Every size is
drawn at 4x and downsampled, which antialiases far better than scaling one large
master image down.
"""
import os
import sys

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")

DESIGN = 96.0
SUPERSAMPLE = 4

TILE = "#16213e"
TILE_EDGE = "#26314f"
ROW_IDLE = "#4a5878"
ROW_ACTIVE = "#7b2ff7"

CHECK_DEFAULT = "#00d2ff"
TRAY_COLORS = {
    "idle": "#8a8fa3",
    "running": "#00d2ff",
    "paused": "#f1c40f",
    "error": "#ff5c72",
}

ICO_SIZES = (16, 24, 32, 48, 64, 256)
SIMPLIFY_BELOW = 32


def _draw(size: int, check_color: str, simplified: bool) -> Image.Image:
    canvas = size * SUPERSAMPLE
    scale = canvas / DESIGN

    def s(v: float) -> float:
        return v * scale

    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle(
        [0, 0, canvas - 1, canvas - 1],
        radius=s(20),
        fill=TILE,
        outline=TILE_EDGE,
        width=max(1, int(s(1))),
    )

    if simplified:
        check_points = [(s(20), s(50)), (s(40), s(70)), (s(78), s(24))]
        check_width = int(s(14))
    else:
        for y, color in ((30, ROW_IDLE), (42, ROW_IDLE), (54, ROW_ACTIVE)):
            d.rounded_rectangle(
                [s(14), s(y), s(14 + 24), s(y + 6)],
                radius=s(3),
                fill=color,
            )
        check_points = [(s(46), s(57)), (s(55), s(67)), (s(78), s(33))]
        check_width = int(s(9))

    d.line(check_points, fill=check_color, width=max(2, check_width), joint="curve")
    # `joint="curve"` rounds the elbow but leaves the two ends square.
    r = max(1, check_width // 2)
    for x, y in (check_points[0], check_points[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=check_color)

    return img.resize((size, size), Image.LANCZOS)


def build_app_ico(path: str):
    frames = [
        _draw(size, CHECK_DEFAULT, simplified=size < SIMPLIFY_BELOW)
        for size in ICO_SIZES
    ]
    # Pillow writes every requested size from the base image, so hand it the
    # largest frame and let append_images carry the individually drawn ones.
    frames[-1].save(
        path,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[:-1],
    )


def build_tray_pngs(out_dir: str):
    for state, color in TRAY_COLORS.items():
        img = _draw(64, color, simplified=False)
        img.save(os.path.join(out_dir, f"tray_{state}.png"), format="PNG")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    ico_path = os.path.join(OUT_DIR, "app.ico")
    build_app_ico(ico_path)
    build_tray_pngs(OUT_DIR)

    _draw(256, CHECK_DEFAULT, simplified=False).save(
        os.path.join(OUT_DIR, "app_256.png"), format="PNG"
    )

    print(f"Wrote {ico_path} ({', '.join(str(s) for s in ICO_SIZES)})")
    for state in TRAY_COLORS:
        print(f"Wrote {os.path.join(OUT_DIR, f'tray_{state}.png')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
