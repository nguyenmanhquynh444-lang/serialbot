"""
Ô "Chạy trên" trên trang Cấu hình.

Chọn nhầm đích chạy là hỏng cả lượt: đang ở chế độ trình duyệt mà mấy ô của
LDPlayer vẫn sửa được thì người dùng tưởng chúng có tác dụng. Và ngược lại,
quay về LDPlayer mà không trả các ô đó lại là mất luôn phần cấu hình cũ.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from bot_gui import (
    MODE_INBOUND,
    MODE_PICK,
    MODE_SERIAL,
    TARGET_ADB,
    TARGET_BROWSER,
    BotGUI,
)


@pytest.fixture
def gui(qapp, tmp_path, monkeypatch):
    import bot_gui

    monkeypatch.setattr(bot_gui, "SCREENSHOT_DIR", str(tmp_path))
    window = BotGUI()
    yield window
    window.close()


def set_target(window, target):
    window.run_target_combo.setCurrentIndex(window.run_target_combo.findData(target))


def set_mode(window, mode):
    window.run_mode_combo.setCurrentIndex(window.run_mode_combo.findData(mode))


def test_ldplayer_is_the_default(gui):
    assert gui.run_target() == TARGET_ADB
    assert not gui.browser_box.isVisible()


def test_browser_mode_locks_everything_that_only_means_something_on_android(gui):
    set_target(gui, TARGET_BROWSER)

    for widget in (
        gui.instances_list,
        gui.window_title_input,
        gui.adb_input_check,
        gui.background_check,
        gui.enter_mode_combo,
        gui.product_code_input,
    ):
        assert not widget.isEnabled()


def test_going_back_to_ldplayer_hands_the_fields_and_their_tooltips_back(gui):
    before = gui.enter_mode_combo.toolTip()
    set_target(gui, TARGET_BROWSER)
    set_target(gui, TARGET_ADB)

    assert gui.adb_input_check.isEnabled()
    assert gui.enter_mode_combo.isEnabled()
    assert gui.enter_mode_combo.toolTip() == before


@pytest.mark.parametrize("mode", [MODE_PICK, MODE_INBOUND])
def test_session_modes_are_dropped_because_they_are_android_screens(gui, mode):
    """
    Luồng theo phiên bấm đúng từng nút của app Android (Nhận hàng, thẻ phiên, ô
    quét vị trí). Để nguyên chế độ đó rồi chạy trên web là chạy vào hư không.
    """
    set_mode(gui, mode)
    set_target(gui, TARGET_BROWSER)

    assert gui.run_mode() == MODE_SERIAL
    assert not gui.run_mode_combo.isEnabled()

    set_target(gui, TARGET_ADB)
    assert gui.run_mode_combo.isEnabled()


def test_the_browser_settings_survive_a_profile_round_trip(gui):
    set_target(gui, TARGET_BROWSER)
    gui.browser_port_input.setValue(9333)
    gui.browser_url_input.setText("ntl.ops.vnfai.com")

    values = gui._collect_profile_values()
    set_target(gui, TARGET_ADB)
    gui._apply_profile_values(values)

    assert gui.run_target() == TARGET_BROWSER
    assert gui.browser_port_input.value() == 9333
    assert gui.browser_url_input.text() == "ntl.ops.vnfai.com"


def test_an_old_profile_without_the_new_keys_still_opens_on_ldplayer(gui):
    """Profile lưu trước khi có chế độ này không được tự nhảy sang trình duyệt."""
    values = gui._collect_profile_values()
    for key in ("run_target", "browser_port", "browser_url"):
        values.pop(key)

    gui._apply_profile_values(values)

    assert gui.run_target() == TARGET_ADB
    assert gui.browser_port_input.value() == 9222


def test_start_refuses_when_no_chrome_is_listening(gui, monkeypatch):
    import bot_gui

    monkeypatch.setattr(bot_gui.browser_backend, "debugger_answers", lambda port: False)
    shown = []
    monkeypatch.setattr(bot_gui.QMessageBox, "critical",
                        lambda *a, **k: shown.append(a[1:]))

    set_target(gui, TARGET_BROWSER)
    assert gui._preflight_browser_check() is False
    assert shown and "Chrome" in shown[0][0]


def test_start_refuses_when_no_recipe_is_selected(gui, monkeypatch):
    """Luồng 'như cũ' đọc cây view Android - trên web nó chạy mà chẳng làm gì đúng."""
    import bot_gui

    monkeypatch.setattr(bot_gui.browser_backend, "debugger_answers", lambda port: True)
    monkeypatch.setattr(BotGUI, "_selected_recipe_steps", lambda self: None)
    shown = []
    monkeypatch.setattr(bot_gui.QMessageBox, "critical",
                        lambda *a, **k: shown.append(a[1:]))

    set_target(gui, TARGET_BROWSER)
    assert gui._preflight_browser_check() is False
    assert shown and "kịch bản" in shown[0][0].lower()


def test_it_passes_when_chrome_answers_and_a_recipe_is_picked(gui, monkeypatch):
    import bot_gui
    from actions import Step

    monkeypatch.setattr(bot_gui.browser_backend, "debugger_answers", lambda port: True)
    monkeypatch.setattr(
        BotGUI, "_selected_recipe_steps",
        lambda self: [Step("web_click", {"selector": "#x"})],
    )

    set_target(gui, TARGET_BROWSER)
    assert gui._preflight_browser_check() is True
