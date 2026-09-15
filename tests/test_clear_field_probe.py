"""
Hai tối ưu dựa trên số đo thật (2036 dòng log + đo lệnh trên máy ảo):

1. Lệnh xóa ô là 22 keyevent, tốn ~605ms mỗi serial - gần bằng cả phần gõ chữ
   (581ms). App tự dọn ô thì bỏ được. Nhưng bỏ nhầm là serial sau nối vào serial
   trước, gửi đi một mã không có thật mà file kết quả nhìn vẫn bình thường.

2. Độ trễ hộp thoại có đuôi dài: đa số 200-400ms nhưng đo được cả mẫu 1220ms.
   Hộp thoại hiện muộn hơn thời gian chờ thì dòng đó đã bị chấm OK oan - và nếu
   cứ gõ tiếp, phím Enter sẽ bấm luôn nút mặc định của hộp thoại, làm serial kế
   tiếp biến mất mà vẫn được ghi thành công.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from bot_worker import CLEAR_PROBE_ROWS, BotWorker, SerialItem

CLEAN_SCREEN = (
    '<?xml version="1.0"?><hierarchy>'
    '<node text="" resource-id="app:id/input" class="android.widget.EditText" '
    'bounds="[0,100][720,180]"/>'
    '</hierarchy>'
)
LEFTOVER_SCREEN = (
    '<?xml version="1.0"?><hierarchy>'
    '<node text="BSS-000111" resource-id="app:id/input" class="android.widget.EditText" '
    'bounds="[0,100][720,180]"/>'
    '</hierarchy>'
)
FOCUS_MAIN = "abcd u0 com.app/com.app.MainActivity"
FOCUS_DIALOG = "efgh u0 com.app/com.app.AlertDialog"


class Recorder:
    """Backend giả chỉ ghi lại có được yêu cầu xóa ô hay không."""

    def __init__(self):
        self.calls = []

    def is_available(self):
        return True

    def type_serial(self, serial):
        self.calls.append((serial, True))

    def send_enter(self, mode):
        pass

    def type_and_submit(self, serial, mode, clear_first=True):
        self.calls.append((serial, clear_first))


class Screen:
    """ScreenReader giả: trả bản dump đặt sẵn và đếm số lần bị hỏi."""

    def __init__(self, xml, focus=FOCUS_MAIN, adb=None):
        self.xml = xml
        self.focus = focus
        # BotWorker.screen dựng lại ScreenReader nếu thuộc tính này lệch với
        # adb_client, nên phải khớp thì bản giả mới sống sót.
        self.adb = adb
        self.dump_count = 0
        self.dump_seconds = 0.0

    def dump_xml(self):
        self.dump_count += 1
        return self.xml

    def focused_window(self):
        return self.focus


def make_worker(screen, backend=None):
    worker = BotWorker(
        serials=[SerialItem(row=2, value="A")], instance_name="LD",
        delay_seconds=0, verify_result=True,
    )
    worker.backend = backend or Recorder()
    screen.adb = worker.adb_client
    worker._screen = screen
    # Bỏ qua phần chấm điểm: các test này chỉ quan tâm lệnh gõ đi ra sao.
    worker._read_result = lambda serial="": {"status": "OK", "response_text": "ok"}
    worker._verdict_by_focus = lambda base: {"status": "OK", "response_text": "ok"}
    return worker


# --- bỏ lệnh xóa ô ----------------------------------------------------------

def test_first_row_always_clears(tmp_path, qapp):
    """Chưa quét gì thì ô trống là đương nhiên - không kết luận được."""
    worker = make_worker(Screen(CLEAN_SCREEN))
    worker._process_serial(2, "S1")

    assert worker.backend.calls == [("S1", True)]
    assert worker._field_self_clears is None


def test_clear_is_dropped_after_enough_clean_probes(qapp):
    worker = make_worker(Screen(CLEAN_SCREEN))

    for i in range(CLEAR_PROBE_ROWS + 2):
        worker._process_serial(2 + i, f"S{i}")
        worker._previous_serial = f"S{i}"

    assert worker._field_self_clears is True
    # Những dòng cuối không còn phải xóa ô nữa.
    assert worker.backend.calls[-1] == (f"S{CLEAR_PROBE_ROWS + 1}", False)


def test_leftover_text_keeps_the_clear_forever(qapp):
    """App để lại chữ trong ô -> bỏ lệnh xóa là nối serial, tuyệt đối không bỏ."""
    worker = make_worker(Screen(LEFTOVER_SCREEN))

    for i in range(CLEAR_PROBE_ROWS + 3):
        worker._process_serial(2 + i, f"S{i}")
        worker._previous_serial = f"S{i}"

    assert worker._field_self_clears is False
    assert all(clear for _, clear in worker.backend.calls)


def test_screen_without_an_input_field_stays_undecided(qapp):
    """Không thấy ô nhập thì chưa kết luận được - giữ lệnh xóa."""
    worker = make_worker(Screen('<?xml version="1.0"?><hierarchy></hierarchy>'))
    worker._previous_serial = "S0"

    worker._process_serial(2, "S1")

    assert worker._field_self_clears is None
    assert worker.backend.calls == [("S1", True)]


# --- lưới bắt hộp thoại hiện muộn -------------------------------------------

def test_late_dialog_is_caught_before_typing_the_next_serial(qapp):
    """
    Hộp thoại hiện sau khi dòng trước đã bị chấm OK. Nếu cứ gõ tiếp, Enter sẽ
    bấm nút mặc định của hộp thoại - serial này mất mà vẫn ghi là thành công.
    """
    screen = Screen(CLEAN_SCREEN, focus=FOCUS_DIALOG)
    worker = make_worker(screen)
    worker._dialog_seen_by_dumpsys = True
    worker._clean_focus = FOCUS_MAIN

    result = worker._process_serial(2, "S1")

    assert result["status"] == "UNKNOWN"
    assert "CHƯA được gõ" in result["message"]
    assert result["dismiss_failed"] is True
    assert worker.backend.calls == []          # không gõ gì cả


def test_unchanged_focus_lets_the_row_run_normally(qapp):
    screen = Screen(CLEAN_SCREEN, focus=FOCUS_MAIN)
    worker = make_worker(screen)
    worker._dialog_seen_by_dumpsys = True
    worker._clean_focus = FOCUS_MAIN

    result = worker._process_serial(2, "S1")

    assert result["status"] == "OK"
    assert worker.backend.calls == [("S1", True)]
