"""
Background mode phải bật sẵn.

Đường lui gõ bàn phím không đem lại gì cho luồng kho - mọi thứ đã đi qua ADB -
nên để nó bật là đổi một lần ADB chớp tắt thành cả loạt serial gõ vào cửa sổ
người dùng đang mở, mà dòng nào cũng vẫn được ghi OK.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from bot_gui import BotGUI


@pytest.fixture
def gui(qapp, tmp_path, monkeypatch):
    import bot_gui

    monkeypatch.setattr(bot_gui, "SCREENSHOT_DIR", str(tmp_path))
    window = BotGUI()
    yield window
    window.close()


def test_background_mode_is_on_out_of_the_box(gui):
    assert gui.background_check.isChecked() is True


def test_adb_input_is_locked_on_from_the_start(gui):
    """Bật sẵn mà quên khóa ô ADB thì hai ô nói ngược nhau ngay lúc mở app."""
    assert gui.adb_input_check.isChecked() is True
    assert gui.adb_input_check.isEnabled() is False


def test_profile_saved_before_this_key_existed_gets_background_on(gui):
    gui._apply_profile_values({"column": "H"})

    assert gui.background_check.isChecked() is True


def test_profile_that_explicitly_turned_it_off_is_still_respected(gui):
    """Người dùng tắt có chủ đích thì vẫn là lựa chọn của họ, không ép ngược lại."""
    gui._apply_profile_values({"column": "H", "background_mode": "false"})

    assert gui.background_check.isChecked() is False
