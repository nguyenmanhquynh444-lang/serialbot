"""
Ba tối ưu của một serial, và cái giá phải trả để chúng an toàn.

Đo trên máy thật (log 758 dòng + đo lệnh trên chính máy ảo đang chạy): một dòng
chạy trót lọt tốn ~2700ms, chia làm ba khoản - soi cửa sổ trước khi gõ (~130ms),
lệnh gõ (~1670ms, trong đó mỗi lần gọi `input` là một lần máy ảo dựng tiến trình
Java), và khoảng chờ hộp thoại lỗi hiện ra (~870ms mà dòng nào cũng phải gánh).

1. Gộp Enter vào chính chuỗi của `input text`: bớt một lần gọi `input`. Nhưng
   dịch hụt thì serial nằm nguyên trong ô mà bot vẫn ghi OK, nên phải nhìn tận
   mắt một dòng rồi mới được tin.
2. Soi cửa sổ và gõ đi chung một lệnh: bớt một lượt đi-về ADB, và khép kẽ hở
   ~130ms mà hộp thoại lọt vào là serial biến mất trong im lặng.
3. Nhờ (2) mới siết được khoảng chờ hộp thoại xuống, và lưới bắt hộp thoại tới
   muộn phải đọc được nó, gán về đúng dòng đã gõ ra nó rồi đóng lại - chứ không
   dừng cả phiên chạy như trước.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from automation_backend import (
    GUARD_FAIL_MARKER,
    GUARD_FOCUS_MARKER,
    GUARD_SKIP_MARKER,
    GUARD_STAGE_MARKER,
    GUARD_TYPED_MARKER,
    AdbBackend,
    parse_guarded,
)
from bot_worker import (
    DIALOG_GRACE_SECONDS,
    DIALOG_GRACE_UNGUARDED_SECONDS,
    BotWorker,
    SerialItem,
)

FOCUS_MAIN = "  mCurrentFocus=Window{abcd u0 com.app/com.app.MainActivity}"
FOCUS_DIALOG = "  mCurrentFocus=Window{efgh u0 com.app/com.app.AlertDialog}"

CLEAN_SCREEN = (
    '<?xml version="1.0"?><hierarchy>'
    '<node text="" resource-id="app:id/input" class="android.widget.EditText" '
    'bounds="[0,100][720,180]"/>'
    "</hierarchy>"
)
LEFTOVER_SCREEN = CLEAN_SCREEN.replace('text=""', 'text="BSS-000111"')
DIALOG_SCREEN = (
    '<?xml version="1.0"?><hierarchy>'
    '<node class="LinearLayout" bounds="[30,380][690,900]">'
    '<node text="Lỗi" bounds="[30,380][690,450]"/>'
    '<node text="Sản phẩm không tồn tại" bounds="[60,470][660,520]"/>'
    '<node text="OK" bounds="[280,820][440,890]" clickable="true"/>'
    "</node></hierarchy>"
)


class FakeDevice:
    """
    Máy ảo giả, hiểu đúng cái lệnh gộp mà `guarded_script` dựng ra.

    Không diễn giải shell thật; chỉ nhận ra các nhãn và cửa sổ mong đợi, đủ để
    kiểm tra bot xử lý cả hai nhánh (gõ / bỏ qua) cho đúng.
    """

    def __init__(self, focus=FOCUS_MAIN, xml=CLEAN_SCREEN, input_fails=False):
        self.instance_name = "LDPlayer"
        self.focus = focus
        self.xml = xml
        self.input_fails = input_fails
        self.commands = []
        self.typed = []

    def run_shell(self, command, timeout=None):
        self.commands.append(command)
        if GUARD_FOCUS_MARKER in command:
            return self._run_guarded(command)
        if "uiautomator dump" in command:
            return self.xml
        if "dumpsys window" in command:
            return self.focus
        if command.startswith("input tap"):
            self.focus, self.xml = FOCUS_MAIN, CLEAN_SCREEN
        if "input text" in command:
            self.typed.append(_typed_text(command))
        return ""

    def _run_guarded(self, command):
        lines = [GUARD_FOCUS_MARKER + self.focus]
        expected = re.search(r"\[ -n '([^']*)' \]", command).group(1)
        if expected and expected != self.focus:
            return "\n".join(lines + [GUARD_SKIP_MARKER])

        if GUARD_STAGE_MARKER in command:
            lines.extend(f"{GUARD_STAGE_MARKER}{1000 + i}" for i in range(3))
        if self.input_fails and "input " in command:
            return "\n".join(lines + [GUARD_FAIL_MARKER])

        if "input text" in command:
            self.typed.append(_typed_text(command))
        return "\n".join(lines + [GUARD_TYPED_MARKER])

    def run_exec_out_binary(self, command, timeout=None):
        return None


def _typed_text(command: str) -> str:
    return re.search(r"input text '([^']*)'", command).group(1)


def make_backend(device) -> AdbBackend:
    backend = AdbBackend(device)
    assert backend.probe_guard()
    device.commands.clear()
    return backend


def make_worker(device, backend=None, **overrides) -> BotWorker:
    kwargs = dict(
        serials=[SerialItem(row=2, value="A1")],
        instance_name="LDPlayer",
        delay_seconds=0.0,
        verify_result=True,
        error_keywords="loi",
        not_found_keywords="không tồn tại",
        response_timeout=0.2,
    )
    kwargs.update(overrides)
    worker = BotWorker(**kwargs)
    worker.adb_client = device
    worker.backend = backend if backend is not None else make_backend(device)
    return worker


# --- gộp Enter vào lệnh gõ --------------------------------------------------

def test_enter_stays_a_separate_keyevent_until_it_is_proven(qapp):
    """Mặc định vẫn là cách cũ: lối tắt chưa được nhìn tận mắt thì chưa dùng."""
    device = FakeDevice()
    AdbBackend(device).type_and_submit("ABC123", "enter", clear_first=False)

    assert device.commands == ["input text 'ABC123' && input keyevent 66"]


def test_enabling_text_submit_folds_enter_into_the_typed_string(qapp):
    device = FakeDevice()
    backend = AdbBackend(device)
    backend.enable_text_submit()
    backend.type_and_submit("ABC123", "enter", clear_first=False)

    assert device.commands == ["input text 'ABC123\n'"]
    assert "keyevent 66" not in device.commands[0]


def test_text_submit_is_only_offered_once_the_app_is_known_to_clear_its_field(qapp):
    """
    Dò được "Enter có tới nơi không" là nhờ ô nhập: app tự dọn ô thì ô còn nguyên
    serial nghĩa là app chưa quét. App KHÔNG tự dọn thì dấu hiệu đó vô nghĩa, mà
    đoán bừa rồi bấm Enter bù là quét thành hai lần - nên đừng bật lối tắt.
    """
    device = FakeDevice(xml=LEFTOVER_SCREEN)
    worker = make_worker(device)
    worker._previous_serial = "S0"

    for i in range(5):
        worker._process_serial(2 + i, f"S{i}")

    assert worker._field_self_clears is False
    assert worker.backend.submits_with_text is False


def test_unsettled_newline_submission_never_sends_an_extra_enter(qapp):
    """A field that still holds text cannot prove the scan wasn't delivered."""
    device = FakeDevice(xml=LEFTOVER_SCREEN)
    worker = make_worker(device)
    worker.backend.enable_text_submit()

    verdict = worker._confirm_text_submit(
        "BSS-000111", {"status": "OK", "response_text": "Typed successfully"}
    )

    assert worker.backend.submits_with_text is False
    assert "input keyevent 66" not in device.commands
    assert verdict["status"] == "UNKNOWN"
    assert verdict["adb_failed"] is True


def test_an_empty_field_after_typing_confirms_the_newline_arrived(qapp):
    device = FakeDevice(xml=CLEAN_SCREEN)
    worker = make_worker(device)
    worker.backend.enable_text_submit()
    worker._last_screen_xml = CLEAN_SCREEN

    worker._confirm_text_submit("BSS-000111", {"status": "OK", "response_text": "ok"})

    assert worker.backend.submits_with_text is True
    assert "input keyevent 66" not in device.commands


def test_a_failing_guarded_input_is_not_replayed(qapp):
    device = FakeDevice(input_fails=True)
    backend = make_backend(device)
    backend.enable_text_submit()

    with pytest.raises(Exception):
        backend.type_and_submit_guarded("ABC123", "enter", clear_first=False)

    assert len(device.commands) == 1                  # a failure can follow delivery


# --- soi cửa sổ và gõ trong cùng một lệnh -----------------------------------

def test_the_probe_never_types_anything(qapp):
    """Dò bằng thân lệnh rỗng: hụt thì cũng không có serial nào bị gửi đi."""
    device = FakeDevice()
    assert AdbBackend(device).probe_guard() is True
    assert device.typed == []


def test_looking_at_the_window_costs_no_extra_adb_call(qapp):
    device = FakeDevice()
    worker = make_worker(device)
    worker._dialog_seen_by_dumpsys = True
    worker._clean_focus_raw = FOCUS_MAIN

    worker._send_serial(2, "A1", clear_first=False)

    assert len(device.commands) == 1                   # đúng một lượt đi-về
    assert device.typed == ["A1\n"] or device.typed == ["A1"]


def test_a_changed_window_stops_the_serial_before_it_is_typed(qapp):
    device = FakeDevice(focus=FOCUS_DIALOG)
    worker = make_worker(device)
    worker._dialog_seen_by_dumpsys = True
    worker._clean_focus_raw = FOCUS_MAIN

    _, typed = worker._send_serial(2, "A1", clear_first=False)

    assert typed is False
    assert device.typed == []


def test_the_shortened_wait_only_applies_when_the_command_can_guard(qapp):
    device = FakeDevice()
    guarded = make_worker(device)
    assert guarded._dialog_grace() == DIALOG_GRACE_SECONDS

    class OldBackend:
        guards_focus = False

    guarded.backend = OldBackend()
    assert guarded._dialog_grace() == DIALOG_GRACE_UNGUARDED_SECONDS


def test_garbled_output_is_never_read_as_a_successful_keystroke(qapp):
    assert parse_guarded("random noise") is None
    assert parse_guarded(f"{GUARD_FOCUS_MARKER}{FOCUS_MAIN}") is None


# --- hộp thoại tới muộn ------------------------------------------------------

def test_a_late_dialog_is_read_dismissed_and_charged_to_the_row_that_caused_it(qapp):
    """
    Hộp thoại hiện sau khi dòng trước đã bị chấm OK. Bản trước bỏ qua dòng này
    rồi dừng cả phiên sau ba lần; giờ phải gán đúng chỗ, đóng lại, chạy tiếp.
    """
    device = FakeDevice(focus=FOCUS_DIALOG, xml=DIALOG_SCREEN)
    worker = make_worker(device)
    worker._dialog_seen_by_dumpsys = True
    worker._clean_focus_raw = FOCUS_MAIN
    worker._clean_focus = "abcd u0 com.app/com.app.MainActivity"
    worker._previous_row = 2
    worker._previous_serial = "A1"

    result = worker._process_serial(3, "A2")

    row, verdict = worker._pending_correction
    assert row == 2
    assert verdict["status"] == "ERROR"
    assert "không tồn tại" in verdict["response_text"]
    assert any(c.startswith("input tap") for c in device.commands)   # đã đóng
    assert device.typed[-1].startswith("A2")                         # vẫn gõ tiếp
    assert result["status"] != "UNKNOWN"


def test_a_screen_that_is_not_a_dialog_stops_the_row_instead_of_typing_blind(qapp):
    device = FakeDevice(focus=FOCUS_DIALOG, xml=CLEAN_SCREEN)
    worker = make_worker(device)
    worker._dialog_seen_by_dumpsys = True
    worker._clean_focus_raw = FOCUS_MAIN
    worker._clean_focus = "abcd u0 com.app/com.app.MainActivity"

    result = worker._process_serial(3, "A2")

    assert result["status"] == "UNKNOWN"
    assert "CHƯA được gõ" in result["message"]
    assert device.typed == []


def test_the_correction_reaches_excel_on_the_row_that_was_wrongly_marked_ok(qapp):
    """
    Kết quả được giữ lại một nhịp trước khi công bố, đúng để sửa được trường hợp
    này - chứ công bố ngay thì dòng OK oan nằm lại trong file kết quả.
    """
    device = FakeDevice()
    worker = make_worker(
        device,
        serials=[SerialItem(row=2, value="A1"), SerialItem(row=3, value="A2")],
    )
    worker._dialog_seen_by_dumpsys = True

    real_process = worker._process_serial

    def process(row, serial):
        if row == 3:
            device.focus, device.xml = FOCUS_DIALOG, DIALOG_SCREEN
        return real_process(row, serial)

    worker._process_serial = process

    results = []
    worker.result_ready.connect(results.append)
    worker.run()

    assert [r["row"] for r in results] == [2, 3]
    assert results[0]["status"] == "ERROR"           # dòng 2 được sửa lại
    assert "không tồn tại" in results[0]["response_text"]


def test_every_row_is_still_published_exactly_once(qapp):
    device = FakeDevice()
    worker = make_worker(
        device,
        serials=[SerialItem(row=r, value=f"A{r}") for r in range(2, 6)],
    )

    results = []
    stats = []
    worker.result_ready.connect(results.append)
    worker.stats_update.connect(lambda *args: stats.append(args))
    worker.run()

    assert [r["row"] for r in results] == [2, 3, 4, 5]
    assert stats[-1][0] == 4
