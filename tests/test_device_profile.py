"""
Nhớ qua từng phiên chạy - và cái giá phải trả để nhớ mà không nhớ nhầm.

Đường nhanh (hỏi cửa sổ ~130ms thay vì dump cả cây view ~1330ms) chỉ mở khi bot
đã tận mắt thấy một hộp thoại làm đổi cửa sổ focus. Phiên nào chạy sạch không
lỗi thì không bao giờ thấy - log 21/08 là đúng một phiên như thế: 502 dòng, 0
lỗi, nhịp 2.33s mỗi dòng, trong khi những phiên gặp lỗi sớm chạy 1.78s. Nên câu
trả lời đó phải sống qua lúc đóng chương trình.

Cái giá: nhớ nhầm thì mọi dòng đều được chấm "OK" mà không ai đọc màn hình -
kiểu sai không nhìn ra được qua file kết quả. Nên khóa nhớ gồm cả versionCode
của app, và không đọc được versionCode thì thà dò lại từ đầu.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

import device_profile
from automation_backend import (
    GUARD_FOCUS_MARKER,
    GUARD_TYPED_MARKER,
    AdbBackend,
)
from bot_worker import BotWorker, SerialItem, _package_of_focus

FOCUS_MAIN = "  mCurrentFocus=Window{abcd u0 com.app/com.app.MainActivity}"
FOCUS_DIALOG = "  mCurrentFocus=Window{efgh u0 com.app/com.app.AlertDialog}"
VERSION_LINE = "    versionCode=1042 minSdk=24 targetSdk=33"

CLEAN_SCREEN = (
    '<?xml version="1.0"?><hierarchy>'
    '<node text="" resource-id="app:id/input" class="android.widget.EditText" '
    'bounds="[0,100][720,180]"/>'
    "</hierarchy>"
)
DIALOG_SCREEN = (
    '<?xml version="1.0"?><hierarchy>'
    '<node class="LinearLayout" bounds="[30,380][690,900]">'
    '<node text="Lỗi" bounds="[30,380][690,450]"/>'
    '<node text="Serial không tồn tại" bounds="[60,470][660,520]"/>'
    '<node text="OK" bounds="[280,820][440,890]" clickable="true"/>'
    "</node></hierarchy>"
)


class FakeDevice:
    """Máy ảo giả biết trả lời cả `dumpsys package` lẫn lệnh gõ gộp."""

    def __init__(self, focus=FOCUS_MAIN, xml=CLEAN_SCREEN, version_line=VERSION_LINE):
        self.instance_name = "LDPlayer"
        self.focus = focus
        self.xml = xml
        self.version_line = version_line
        self.commands = []

    def run_shell(self, command, timeout=None):
        self.commands.append(command)
        if "dumpsys package" in command:
            return self.version_line
        if GUARD_FOCUS_MARKER in command:
            return "\n".join([GUARD_FOCUS_MARKER + self.focus, GUARD_TYPED_MARKER])
        if "uiautomator dump" in command:
            return self.xml
        if "dumpsys window" in command:
            return self.focus
        if command.startswith("input tap"):
            # Bấm OK: hộp thoại đóng, cửa sổ focus quay về màn hình chính.
            self.focus, self.xml = FOCUS_MAIN, CLEAN_SCREEN
        return ""

    def run_exec_out_binary(self, command, timeout=None):
        return None

    def dumps(self) -> int:
        return sum(1 for c in self.commands if "uiautomator dump" in c)


def make_worker(device) -> BotWorker:
    worker = BotWorker(
        serials=[SerialItem(row=2, value="A1")],
        instance_name="LDPlayer",
        delay_seconds=0.0,
        verify_result=True,
        error_keywords="loi",
        not_found_keywords="không tồn tại",
        response_timeout=0.2,
    )
    worker.adb_client = device
    backend = AdbBackend(device)
    assert backend.probe_guard()
    worker.backend = backend
    # Bỏ qua bước dò "app có tự dọn ô không": nó cũng dump màn hình, mà ở đây
    # đang đếm số lần dump để biết đường nhanh có mở hay không.
    worker._field_self_clears = False
    device.commands.clear()
    return worker


# --- khóa nhớ ---------------------------------------------------------------

def test_the_package_name_is_what_identifies_the_app_not_the_window_handle():
    """Phần hash đầu chuỗi đổi mỗi lần mở lại app - nhớ theo nó là nhớ hụt."""
    assert _package_of_focus("abcd u0 vn.abc.app/vn.abc.app.MainActivity") == "vn.abc.app"
    assert _package_of_focus("efgh u0 vn.abc.app/vn.abc.app.MainActivity") == "vn.abc.app"
    assert _package_of_focus("NotificationShade") == ""
    assert _package_of_focus("") == ""


def test_a_key_missing_any_of_its_three_parts_is_no_key_at_all():
    assert device_profile.device_key("LDPlayer", "com.app", "1042")
    assert device_profile.device_key("", "com.app", "1042") == ""
    assert device_profile.device_key("LDPlayer", "", "1042") == ""
    assert device_profile.device_key("LDPlayer", "com.app", "") == ""


def test_saving_one_answer_leaves_the_others_alone():
    key = device_profile.device_key("LDPlayer", "com.app", "1042")
    device_profile.save(key, {"dialog_seen_by_dumpsys": True})
    device_profile.save(key, {"ghi_chu": "x"})

    assert device_profile.load(key) == {"dialog_seen_by_dumpsys": True, "ghi_chu": "x"}
    assert device_profile.load("khac") == {}


def test_a_corrupt_file_is_ignored_instead_of_stopping_the_run(tmp_path, monkeypatch):
    path = tmp_path / "hong.json"
    path.write_text("{ chưa đóng ngoặc", encoding="utf-8")
    monkeypatch.setattr(device_profile, "profile_path", lambda: str(path))

    assert device_profile.load("LDPlayer|com.app|1042") == {}


# --- đường đi thật ----------------------------------------------------------

def test_the_answer_learned_from_one_dialog_is_written_down(qapp):
    device = FakeDevice(focus=FOCUS_DIALOG, xml=DIALOG_SCREEN)
    worker = make_worker(device)

    result = worker._process_serial(2, "A1")

    assert result["status"] == "ERROR"
    assert worker._dialog_seen_by_dumpsys is True
    assert device_profile.load("LDPlayer|com.app|1042") == {"dialog_seen_by_dumpsys": True}


def test_the_next_run_starts_fast_instead_of_waiting_for_another_error(qapp):
    """
    Chính là chỗ ăn tiền: phiên sau không cần gặp lỗi nào vẫn đi đường nhanh
    ngay từ dòng đầu - không đọc cả cây view lần nào.
    """
    device_profile.save("LDPlayer|com.app|1042", {"dialog_seen_by_dumpsys": True})
    device = FakeDevice()
    worker = make_worker(device)

    result = worker._process_serial(2, "A1")

    assert result["status"] == "OK"
    assert worker._dialog_seen_by_dumpsys is True
    assert device.dumps() == 0


def test_without_a_remembered_answer_the_run_still_reads_the_whole_screen(qapp):
    device = FakeDevice()
    worker = make_worker(device)

    worker._process_serial(2, "A1")

    assert worker._dialog_seen_by_dumpsys is None
    assert device.dumps() == 1


def test_an_app_update_throws_the_old_answer_away(qapp):
    """
    Bản mới có thể tự vẽ hộp thoại (kiểu Flutter) chứ không mở cửa sổ riêng nữa.
    Tin theo bản cũ là mọi dòng đều 'OK' mà chẳng ai đọc màn hình.
    """
    device_profile.save("LDPlayer|com.app|1042", {"dialog_seen_by_dumpsys": True})
    device = FakeDevice(version_line="    versionCode=1100 minSdk=24")
    worker = make_worker(device)

    worker._process_serial(2, "A1")

    assert worker._dialog_seen_by_dumpsys is None
    assert device.dumps() == 1


def test_an_unreadable_version_means_no_remembering_at_all(qapp):
    device_profile.save("LDPlayer|com.app|1042", {"dialog_seen_by_dumpsys": True})
    device = FakeDevice(version_line="")
    worker = make_worker(device)

    worker._process_serial(2, "A1")

    assert worker._device_key == ""
    assert worker._dialog_seen_by_dumpsys is None


def test_the_app_is_asked_for_its_version_once_per_run(qapp):
    device_profile.save("LDPlayer|com.app|1042", {"dialog_seen_by_dumpsys": True})
    device = FakeDevice()
    worker = make_worker(device)

    for row in range(2, 6):
        worker._process_serial(row, f"A{row}")

    assert sum(1 for c in device.commands if "dumpsys package" in c) == 1
