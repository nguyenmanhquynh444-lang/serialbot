import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from bot_worker import BotWorker, SerialItem


def make_worker(**overrides):
    kwargs = dict(
        serials=[SerialItem(row=2, value="ABC123")],
        instance_name="LDPlayer",
        delay_seconds=0.0,
        verify_result=True,
        success_keywords="",
        error_keywords="error,invalid",
    )
    kwargs.update(overrides)
    return BotWorker(**kwargs)


def test_normalize_match_text_strips_accents_and_case():
    worker = make_worker()
    assert worker._normalize_match_text("Không hợp lệ") == "khong hop le"


def test_normalize_match_text_collapses_whitespace():
    worker = make_worker()
    assert worker._normalize_match_text("  a   b  ") == "a b"


def test_extract_xml_finds_hierarchy_tag():
    worker = make_worker()
    text = "garbage before<hierarchy rotation=\"0\"><node/></hierarchy>"
    assert worker._extract_xml(text).startswith("<hierarchy")


def test_extract_xml_returns_empty_when_no_xml():
    worker = make_worker()
    assert worker._extract_xml("no xml here") == ""


def test_current_focus_window_parses_dumpsys_output():
    worker = make_worker()
    dump = "Some header\n  mCurrentFocus=Window{abcd u0 com.example/.MainActivity}\nmore text"
    assert worker._current_focus_window(dump) == "abcd u0 com.example/.MainActivity"


def test_xml_attr_extracts_value():
    worker = make_worker()
    node = '<node text="OK" bounds="[10,20][30,40]" />'
    assert worker._xml_attr(node, "text") == "OK"
    assert worker._xml_attr(node, "bounds") == "[10,20][30,40]"
    assert worker._xml_attr(node, "missing") == ""


def test_parse_keywords_normalizes_and_splits():
    worker = make_worker(error_keywords="Error, Khong Hop Le ,")
    assert worker.error_keywords == ["error", "khong hop le"]
