import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from bot_gui import BotGUI, split_serials
from bot_worker import SerialItem


# --- QSettings stores booleans as 'true'/'false' strings on Windows ---------

def test_to_bool_parses_qsettings_false_string():
    """bool('false') is True in Python - the exact trap this helper exists for."""
    assert BotGUI._to_bool("false") is False


def test_to_bool_parses_qsettings_true_string():
    assert BotGUI._to_bool("true") is True


def test_to_bool_passes_through_real_bools():
    assert BotGUI._to_bool(True) is True
    assert BotGUI._to_bool(False) is False


def test_to_bool_uses_default_when_missing():
    assert BotGUI._to_bool(None, True) is True
    assert BotGUI._to_bool(None, False) is False


# --- Parallel split ---------------------------------------------------------

def _items(n):
    return [SerialItem(row=i + 2, value=f"S{i}") for i in range(n)]


def test_split_serials_even_division():
    chunks = split_serials(_items(6), 3)
    assert [len(c) for c in chunks] == [2, 2, 2]


def test_split_serials_uneven_division_spreads_remainder():
    chunks = split_serials(_items(7), 3)
    assert [len(c) for c in chunks] == [3, 2, 2]
    assert sum(len(c) for c in chunks) == 7


def test_split_serials_drops_empty_chunks_when_more_workers_than_items():
    chunks = split_serials(_items(2), 5)
    assert [len(c) for c in chunks] == [1, 1]


def test_split_serials_single_worker_returns_everything():
    items = _items(4)
    assert split_serials(items, 1) == [items]


def test_split_serials_preserves_every_item_exactly_once():
    items = _items(10)
    chunks = split_serials(items, 4)
    flattened = [item for chunk in chunks for item in chunk]
    assert flattened == items
