"""
app_icons.py
Loads the generated icon set, resolving paths for both a normal run and a
PyInstaller one-file bundle (where assets live in the extraction dir).

Every getter degrades to a null QIcon rather than raising, so a missing assets
folder makes the app look plain instead of refusing to start.
"""
import os
import sys

from PyQt6.QtGui import QIcon


def assets_dir() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets")


def _icon(filename: str) -> QIcon:
    path = os.path.join(assets_dir(), filename)
    return QIcon(path) if os.path.isfile(path) else QIcon()


def app_icon() -> QIcon:
    return _icon("app.ico")


def tray_icon(state: str = "idle") -> QIcon:
    """state: idle | running | paused | error"""
    icon = _icon(f"tray_{state}.png")
    return icon if not icon.isNull() else app_icon()
