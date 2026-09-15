"""
Tốc độ gõ và tính đúng đắn của phản hồi.

Hai thứ này đi cùng nhau: nhanh lên bằng cách bỏ sleep cứng chỉ an toàn nếu bot
thật sự biết app đã xử lý xong serial vừa gửi hay chưa.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from automation_backend import CLEAR_DEL_COUNT, AdbBackend, AutomationBackend
from bot_worker import RESPONSE_STALE, BotWorker, SerialItem
from screen_reader import ScreenReader


def dialog_xml(serial: str, message: str = "Sản phẩm không tồn tại") -> str:
    return (
        '<hierarchy><node class="FrameLayout" bounds="[0,0][720,1280]">'
        '<node class="LinearLayout" bounds="[30,380][690,900]">'
        f'<node text="Lỗi" bounds="[30,380][690,450]"/>'
        f'<node text="{message}" bounds="[60,470][660,520]"/>'
        f'<node text="Mã vừa quét" bounds="[60,540][300,580]"/>'
        f'<node text="{serial}" bounds="[320,540][660,580]"/>'
        '<node text="OK" bounds="[280,820][440,890]" clickable="true"/>'
        '</node></node></hierarchy>'
    )


IDLE_XML = (
    '<hierarchy><node text="Nhập serial" resource-id="com.app:id/input" '
    'bounds="[0,100][720,180]"/></hierarchy>'
)


class RecordingAdb:
    """Ghi lại mọi lệnh; trả về `xml` cho lệnh đọc màn hình."""

    def __init__(self, xml=IDLE_XML, fast_dump_supported=True):
        self.instance_name = "LDPlayer"
        self.xml = xml
        self.fast_dump_supported = fast_dump_supported
        self.commands = []

    def run_shell(self, command, timeout=None):
        self.commands.append(command)
        if "uiautomator dump" in command:
            if "/dev/tty" in command and not self.fast_dump_supported:
                return "Error: Could not get idle state."
            return self.xml
        if "dumpsys window" in command:
            return "mCurrentFocus=Window{abcd u0 com.app/com.app.MainActivity}"
        if command.startswith("input tap"):
            self.xml = IDLE_XML          # bấm OK là hộp thoại đóng
        return ""

    def run_exec_out_binary(self, command, timeout=None):
        return None

    def dumps(self):
        return [c for c in self.commands if "uiautomator dump" in c]


class SilentBackend(AutomationBackend):
    def is_available(self):
        return True

    def type_serial(self, text):
        pass

    def send_enter(self, mode):
        pass


def make_worker(adb, **overrides):
    kwargs = dict(
        serials=[SerialItem(row=2, value="A1")],
        instance_name="LDPlayer",
        delay_seconds=0.0,
        verify_result=True,
        error_keywords="loi",
        not_found_keywords="không tồn tại",
        response_timeout=0.4,
    )
    kwargs.update(overrides)
    worker = BotWorker(**kwargs)
    worker.adb_client = adb
    worker.backend = SilentBackend()
    return worker


# --- ít lệnh hơn cho mỗi serial --------------------------------------------

def test_clear_type_and_enter_go_out_as_one_adb_call():
    """Mỗi vòng đi-về ADB tốn cả trăm ms, gộp được thì gộp."""
    adb = RecordingAdb()
    AdbBackend(adb).type_and_submit("ABC123", "enter")

    assert len(adb.commands) == 1
    command = adb.commands[0]
    assert "input text 'ABC123'" in command
    assert command.rstrip().endswith("input keyevent 66")


def test_clearing_the_field_uses_a_single_input_invocation():
    """
    Mỗi lệnh `input` là một lần máy ảo dựng tiến trình Java. 22 keycode trong
    một lệnh nhanh hơn hẳn 3 lệnh riêng.
    """
    adb = RecordingAdb()
    AdbBackend(adb).type_serial("X")

    clear_part = adb.commands[0].split("; input text")[0]
    assert clear_part.count("input keyevent") == 1
    assert clear_part.split().count("67") == CLEAR_DEL_COUNT


def test_tab_enter_is_also_one_invocation():
    adb = RecordingAdb()
    AdbBackend(adb).send_enter("tab_enter")
    assert adb.commands == ["input keyevent 61 66"]


def test_no_enter_sends_nothing():
    adb = RecordingAdb()
    AdbBackend(adb).send_enter("none")
    assert adb.commands == []


def test_old_devices_fall_back_to_one_keycode_per_command():
    """
    Bản `input` quá cũ không hiểu nhiều keycode một lượt. Không được để nó bị
    hiểu nhầm thành máy ảo chết - đó là lỗi sẽ dừng cả phiên chạy.
    """
    class PickyAdb(RecordingAdb):
        def run_shell(self, command, timeout=None):
            self.commands.append(command)
            first = command.split(";")[0].split()
            if first[:2] == ["input", "keyevent"] and len(first) > 3:
                return None            # `input` báo sai cú pháp
            return ""

    adb = PickyAdb()
    backend = AdbBackend(adb)
    backend.type_and_submit("ABC123", "enter")

    assert len(adb.commands) == 2                    # thử gộp, hụt, gửi lại kiểu cũ
    assert "input keyevent 123; input keyevent 28" in adb.commands[1]

    adb.commands.clear()
    backend.type_and_submit("DEF456", "enter")
    assert len(adb.commands) == 1                    # nhớ luôn, không thử gộp nữa


# --- đọc màn hình rẻ hơn ----------------------------------------------------

def test_dump_skips_the_sdcard_round_trip():
    adb = RecordingAdb()
    assert ScreenReader(adb).dump_xml()
    assert adb.commands == ["uiautomator dump /dev/tty"]


def test_dump_falls_back_once_on_devices_without_dev_tty():
    adb = RecordingAdb(fast_dump_supported=False)
    reader = ScreenReader(adb)

    assert reader.dump_xml()
    assert len(adb.dumps()) == 2          # thử nhanh, hụt, quay về cách cũ

    adb.commands.clear()
    assert reader.dump_xml()
    assert len(adb.dumps()) == 1          # lần sau đi thẳng cách cũ


def test_clean_screen_costs_one_dump_and_no_dumpsys(qapp):
    adb = RecordingAdb(xml=IDLE_XML)
    worker = make_worker(adb, response_timeout=0.0)

    assert worker._read_result("A1")["status"] == "OK"
    assert len(adb.dumps()) == 1
    assert not any("dumpsys" in c for c in adb.commands)


def test_a_silent_app_is_never_waited_on(qapp):
    """
    App xử lý xong mà không hiện gì thì mọi dòng đều "chưa thấy phản hồi". Chờ
    thêm cho từng dòng chỉ cộng thời gian chứ không biết thêm điều gì.
    """
    adb = RecordingAdb(xml=IDLE_XML)
    worker = make_worker(adb, response_timeout=5.0)

    import time

    started = time.monotonic()
    for row in range(3):
        worker._read_result(f"A{row}")
    elapsed = time.monotonic() - started

    assert elapsed < 0.5
    assert len(adb.dumps()) == 3        # đúng một lượt đọc cho mỗi serial


def test_an_app_that_does_answer_gets_the_benefit_of_the_doubt(qapp):
    """Ngược lại: đã biết app có trả lời thì màn hình trống nghĩa là chưa xong."""
    # Hộp thoại không in lại mã, nên app "có trả lời" được nhận ra qua chính
    # hộp thoại chứ không qua tiếng vọng của serial.
    answering = RecordingAdb(xml=dialog_xml("mã khác"))
    worker = make_worker(answering, response_timeout=5.0)
    worker._read_result("A1")

    assert worker._verdict_seen is True
    assert worker._echo_seen is False

    answering.xml = IDLE_XML
    import time

    started = time.monotonic()
    worker._read_result("A2")
    assert time.monotonic() - started >= 0.5   # có chờ thêm trước khi kết luận


# --- không chấm dòng này bằng kết quả của dòng trước ------------------------

def test_response_that_still_names_the_previous_serial_is_refused(qapp):
    """
    Đúng cái lỗi cần tránh: app chưa kịp ghi nhận serial mới, màn hình vẫn là
    kết quả của serial trước. Chấm theo màn hình đó là chép kết quả dòng trên
    xuống dòng dưới - file kết quả trông vẫn bình thường nên không ai phát hiện.
    """
    adb = RecordingAdb(xml=dialog_xml("A1"))
    worker = make_worker(adb, response_timeout=0.3)
    worker._previous_serial = "A1"

    result = worker._read_result("A2")

    assert result["status"] == "UNKNOWN"
    assert "chưa phản hồi kịp" in result["response_text"]
    assert "A1" in result["response_text"]


def test_the_same_screen_is_accepted_once_it_names_the_new_serial(qapp):
    adb = RecordingAdb(xml=dialog_xml("A2"))
    worker = make_worker(adb, response_timeout=0.3)
    worker._previous_serial = "A1"

    result = worker._read_result("A2")

    assert result["status"] == "ERROR"
    assert result["response_text"].startswith("Sản phẩm không tồn tại")


def test_seeing_the_serial_echoed_back_confirms_the_characters_arrived(qapp):
    adb = RecordingAdb(xml=dialog_xml("BSS-26072141000044"))
    worker = make_worker(adb)

    worker._read_result("BSS-26072141000044")

    assert worker._echo_seen is True


def test_a_garbled_serial_is_not_taken_as_this_row_result(qapp):
    """App in lại mã khác hẳn mã đã gửi -> không thể coi là kết quả của dòng này."""
    adb = RecordingAdb(xml=dialog_xml("BSS-26072141000099"))
    worker = make_worker(adb, response_timeout=0.3)
    worker._echo_seen = True
    worker._previous_serial = "BSS-26072141000099"

    assert worker._response_state(adb.xml, "BSS-26072141000044") == RESPONSE_STALE


def test_waiting_stops_as_soon_as_the_fresh_answer_appears(qapp):
    """Trả lời rồi thì đi tiếp ngay, không nằm chờ hết thời gian cho phép."""
    adb = RecordingAdb(xml=dialog_xml("A1"))
    worker = make_worker(adb, response_timeout=5.0)

    import time

    started = time.monotonic()
    worker._read_result("A1")
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert len(adb.dumps()) <= 2          # 1 lần đọc kết quả + 1 lần xác nhận đã đóng
