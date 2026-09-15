"""
Luồng "serial không có trong hệ thống": đọc câu app báo -> bấm OK -> chạy tiếp,
và lý do phải đi được tới Excel chứ không tan biến thành chữ 'dialog'.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from automation_backend import AdbBackend, AutomationBackend
from actions import (
    DEFAULT_NOT_FOUND_KEYWORDS,
    REASON_APP_ERROR,
    REASON_DIALOG,
    REASON_NOT_FOUND,
)
from bot_worker import MAX_CONSECUTIVE_DISMISS_FAILURES, BotWorker, SerialItem
from screen_reader import dialog_marker, dialog_message, find_dismiss_button

NOT_FOUND_XML = (
    '<?xml version="1.0"?><hierarchy>'
    '<node text="Tra cứu" resource-id="com.app:id/toolbar_title" bounds="[0,0][720,80]"/>'
    '<node text="Không tìm thấy serial trong hệ thống" resource-id="android:id/message" '
    'bounds="[40,300][660,420]" clickable="false"/>'
    '<node text="OK" resource-id="android:id/button1" bounds="[500,460][620,540]" '
    'clickable="true"/>'
    '</hierarchy>'
)
OTHER_ERROR_XML = (
    '<?xml version="1.0"?><hierarchy>'
    '<node text="Serial đã được sử dụng" resource-id="android:id/message" '
    'bounds="[40,300][660,420]" clickable="false"/>'
    '<node text="Đồng ý" resource-id="android:id/button1" bounds="[500,460][620,540]" '
    'clickable="true"/>'
    '</hierarchy>'
)
NO_DIALOG_XML = (
    '<?xml version="1.0"?><hierarchy>'
    '<node text="Nhập serial" resource-id="com.app:id/input" bounds="[0,100][720,180]"/>'
    '</hierarchy>'
)

# Dựng lại đúng hộp thoại app đang dùng: tiêu đề "Lỗi", câu lỗi, rồi bảng chi
# tiết - chứ không phải một dòng chữ duy nhất.
REAL_DIALOG_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<hierarchy rotation="0">'
    '<node class="android.widget.FrameLayout" bounds="[0,0][720,1280]">'
    '  <node class="android.widget.FrameLayout" bounds="[0,0][720,1280]">'
    '    <node text="Nhập serial" bounds="[20,100][700,180]"/>'
    '  </node>'
    '  <node class="android.widget.LinearLayout" bounds="[30,380][690,900]">'
    '    <node text="Lỗi" bounds="[30,380][690,450]"/>'
    '    <node text="Sản phẩm đã được ghi nhận" bounds="[60,470][660,520]"/>'
    '    <node class="android.widget.TableLayout" bounds="[60,540][660,780]">'
    '      <node text="Mã vừa quét" bounds="[60,540][300,580]"/>'
    '      <node text="BSS-26072141000044" bounds="[320,540][660,580]"/>'
    '      <node text="Mã phiên" bounds="[60,600][300,640]"/>'
    '      <node text="CCS28072026CW60294" bounds="[320,600][660,640]"/>'
    '      <node text="Tài khoản" bounds="[60,660][300,700]"/>'
    '      <node text="ntl.5004672" bounds="[320,660][660,700]"/>'
    '      <node text="Thời gian" bounds="[60,720][300,760]"/>'
    '      <node text="06:56:35 28/07/2026" bounds="[320,720][660,760]"/>'
    '    </node>'
    '    <node text="OK" bounds="[280,820][440,890]" clickable="true"/>'
    '  </node>'
    '</node>'
    '</hierarchy>'
)


# uiautomator nhiều lúc chỉ dump riêng cửa sổ hộp thoại chứ không dump cả màn
# hình: mọi thẻ bao ngoài đều to đúng bằng bản dump. Đây là bản rút gọn của dump
# thật lấy từ máy (vn.aipacific.fai.prod).
DIALOG_ONLY_WINDOW_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<hierarchy rotation="0">'
    '<node class="android.widget.FrameLayout" bounds="[45,618][855,1017]">'
    '  <node class="android.widget.LinearLayout" bounds="[45,618][855,1017]">'
    '    <node class="android.widget.LinearLayout" bounds="[45,618][855,691]">'
    '      <node text="Lỗi" bounds="[114,636][151,673]"/>'
    '    </node>'
    '    <node class="android.widget.ScrollView" bounds="[45,691][855,941]">'
    '      <node text="Không tìm được sản phẩm" resource-id="vn.app:id/tvMessage" '
    'bounds="[69,712][831,744]"/>'
    '      <node class="android.widget.LinearLayout" bounds="[69,765][831,917]">'
    '        <node text="Mã vừa quét" bounds="[69,770][213,798]"/>'
    '        <node text="BSS-26070841000855" bounds="[213,770][831,798]"/>'
    '        <node text="Mã phiên" bounds="[69,808][213,836]"/>'
    '        <node text="CCS28072026BRK9725" bounds="[213,808][831,836]"/>'
    '        <node text="Tài khoản" bounds="[69,846][213,874]"/>'
    '        <node text="ntl.5004918" bounds="[213,846][831,874]"/>'
    '        <node text="Thời gian" bounds="[69,884][213,912]"/>'
    '        <node text="11:25:10 28/07/2026" bounds="[213,884][831,912]"/>'
    '      </node>'
    '    </node>'
    '    <node text="OK" resource-id="vn.app:id/btnClose" bounds="[45,942][855,1017]" '
    'clickable="true"/>'
    '  </node>'
    '</node>'
    '</hierarchy>'
)


class FakeAdb:
    """
    Máy ảo giả lập: Enter (gửi serial) làm hiện hộp thoại, chạm nút làm nó đóng.

    Phân biệt được hai việc đó mới đúng app thật - lệnh gõ serial của AdbBackend
    cũng toàn là 'input keyevent', và nếu coi mọi phím là cú bấm OK thì hộp thoại
    biến mất trước cả khi bot kịp đọc.

    sticky=True   - hộp thoại bấm mãi không chịu đóng
    window_is_dialog - dumpsys có gọi cửa sổ đó là dialog không (dialog tự vẽ
                       kiểu Flutter/WebView thì không)
    """

    def __init__(
        self,
        xml=NO_DIALOG_XML,
        dialog_focused=False,
        sticky=False,
        adb_dead=False,
        window_is_dialog=None,
    ):
        self.instance_name = "LDPlayer"
        self.dialog_xml = xml
        self.clean_xml = NO_DIALOG_XML
        self.dialog_open = dialog_focused
        self.window_is_dialog = dialog_focused if window_is_dialog is None else window_is_dialog
        self.sticky = sticky
        self.adb_dead = adb_dead
        self.commands = []

    def run_shell(self, command, timeout=None):
        self.commands.append(command)

        if "dumpsys window" in command:
            window = (
                "abcd u0 com.app/com.app.AlertDialog"
                if self.dialog_open and self.window_is_dialog
                else "abcd u0 com.app/com.app.MainActivity"
            )
            return f"  mCurrentFocus=Window{{{window}}}"

        if "uiautomator dump" in command:
            return self.dialog_xml if self.dialog_open else self.clean_xml

        if self.adb_dead and command.startswith("input "):
            return None

        if "input text" in command:
            # Gõ serial. Nếu lệnh gộp luôn phím xác nhận thì app phản hồi ngay.
            if "66" in command.split("input text", 1)[1]:
                self.dialog_open = True
        elif command.startswith("input keyevent 66"):
            # Cùng một phím: đang có hộp thoại thì là bấm đóng, không thì là gửi
            # serial và app trả lời.
            if self.dialog_open:
                if not self.sticky:
                    self.dialog_open = False
            else:
                self.dialog_open = True
        elif command.startswith("input tap") and not self.sticky:
            self.dialog_open = False      # bấm OK -> đóng

        return ""

    def run_exec_out_binary(self, command, timeout=None):
        return None

    def taps(self):
        return [c for c in self.commands if c.startswith("input tap")]


def make_worker(adb, **overrides):
    kwargs = dict(
        serials=[SerialItem(row=2, value="ABC123")],
        instance_name="LDPlayer",
        delay_seconds=0.0,
        verify_result=True,
        error_keywords="loi,invalid,not found",
        not_found_keywords="không tìm thấy,not found",
    )
    kwargs.update(overrides)
    worker = BotWorker(**kwargs)
    worker.adb_client = adb
    # Backend thật chạy trên FakeAdb: các test gọi `_process_serial` cần nó, mà
    # dùng backend thật thì phần gõ serial cũng được kiểm luôn.
    worker.backend = AdbBackend(adb)
    return worker


# --- đọc màn hình -----------------------------------------------------------

def test_dialog_message_prefers_the_dialog_body_over_the_toolbar_title():
    assert dialog_message(NOT_FOUND_XML) == "Không tìm thấy serial trong hệ thống"


def test_dialog_message_falls_back_to_the_longest_text_without_known_ids():
    xml = (
        '<hierarchy>'
        '<node text="Tra cứu" bounds="[0,0][100,50]"/>'
        '<node text="Serial này không tồn tại trên hệ thống" bounds="[0,60][700,120]"/>'
        '<node text="OK" bounds="[500,200][600,260]" clickable="true"/>'
        '</hierarchy>'
    )
    assert dialog_message(xml) == "Serial này không tồn tại trên hệ thống"


def test_real_dialog_keeps_the_reason_first_and_the_evidence_after():
    """
    Hộp thoại thật gồm tiêu đề + câu lỗi + bảng chi tiết. Câu lỗi phải đứng đầu
    (đó là thứ người ta đọc), mã phiên/tài khoản/thời gian giữ lại làm bằng
    chứng, còn tiêu đề "Lỗi" bỏ đi vì cột Trạng thái đã nói rồi.
    """
    message = dialog_message(REAL_DIALOG_XML)

    assert message.startswith("Sản phẩm đã được ghi nhận")
    assert "CCS28072026CW60294" in message
    assert "ntl.5004672" in message
    assert not message.startswith("Lỗi")
    # Không lẫn chữ của màn hình phía sau hộp thoại.
    assert "Nhập serial" not in message
    # Nhãn nút không phải nội dung.
    assert "OK" not in message.split(" | ")


def test_real_dialog_marker_is_the_error_sentence_not_the_title():
    assert dialog_marker(REAL_DIALOG_XML) == "Sản phẩm đã được ghi nhận"


def test_dialog_only_dump_keeps_the_whole_evidence_block():
    """
    Khi bản dump chỉ có mỗi cửa sổ hộp thoại, không thẻ bao nào nhỏ hơn "màn
    hình" nên phép khoanh vùng theo diện tích không chọn được gì. Trước đây rơi
    về nhánh đọc phẳng và chỉ giữ đúng dòng dài nhất - mất sạch mã vừa quét, mã
    phiên, tài khoản, thời gian, tức là mất bằng chứng để tra lại sau.
    """
    message = dialog_message(DIALOG_ONLY_WINDOW_XML)

    assert message.startswith("Không tìm được sản phẩm")
    for evidence in ("BSS-26070841000855", "CCS28072026BRK9725", "ntl.5004918"):
        assert evidence in message
    assert not message.startswith("Lỗi")
    assert "OK" not in message.split(" | ")


def test_khong_tim_duoc_counts_as_not_found_by_default():
    """
    App viết "không tìm được", bộ từ khóa mặc định chỉ có "không tìm thấy" thì
    dòng này bị xếp thành lỗi chung chung thay vì lý do thật.
    """
    from screen_reader import normalize_match_text

    haystack = normalize_match_text(DIALOG_ONLY_WINDOW_XML)
    keywords = [normalize_match_text(k) for k in DEFAULT_NOT_FOUND_KEYWORDS.split(",")]

    assert any(kw in haystack for kw in keywords)


def test_real_dialog_ok_button_is_found_under_the_nested_layout():
    node = find_dismiss_button(REAL_DIALOG_XML)
    assert node and node["bounds"] == "[280,820][440,890]"


def test_find_dismiss_button_matches_vietnamese_label():
    node = find_dismiss_button(OTHER_ERROR_XML)
    assert node and node["text"] == "Đồng ý"


def test_find_dismiss_button_returns_none_when_there_is_no_button():
    assert find_dismiss_button(NO_DIALOG_XML) is None


# --- phân loại + tự bấm OK --------------------------------------------------

def test_not_found_is_recorded_with_its_own_reason_and_the_app_wording(qapp):
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True)
    result = make_worker(adb)._read_result()

    assert result["status"] == "ERROR"
    assert result["reason"] == REASON_NOT_FOUND
    assert result["response_text"] == "Không tìm thấy serial trong hệ thống"
    assert not result["dismiss_failed"]


def test_ok_is_tapped_at_the_centre_of_the_button(qapp):
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True)
    make_worker(adb)._read_result()
    assert adb.taps() == ["input tap 560 500"]


def test_screen_is_read_before_ok_is_pressed(qapp):
    """Bấm trước thì hộp thoại biến mất và không còn gì để ghi vào Excel."""
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True)
    make_worker(adb)._read_result()

    dump_index = next(i for i, c in enumerate(adb.commands) if "uiautomator dump" in c)
    tap_index = next(i for i, c in enumerate(adb.commands) if c.startswith("input tap"))
    assert dump_index < tap_index


def test_run_continues_to_the_next_serial_after_a_not_found(qapp):
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True)
    worker = make_worker(
        adb,
        serials=[SerialItem(row=2, value="A1"), SerialItem(row=3, value="A2")],
    )
    worker.backend = _TypingBackend()

    results = []
    worker.result_ready.connect(results.append)
    worker.run()

    assert [r["row"] for r in results] == [2, 3]
    assert all(r["reason"] == REASON_NOT_FOUND for r in results)
    assert all(r["status"] == "ERROR" for r in results)


def test_not_found_beats_a_generic_error_keyword_matching_the_same_text(qapp):
    """'not found' nằm trong cả hai danh sách - lý do cụ thể phải thắng."""
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True)
    worker = make_worker(adb, error_keywords="không tìm thấy,loi")
    assert worker._read_result()["reason"] == REASON_NOT_FOUND


def test_other_errors_keep_the_generic_reason(qapp):
    adb = FakeAdb(xml=OTHER_ERROR_XML, dialog_focused=True)
    result = make_worker(adb, error_keywords="đã được sử dụng")._read_result()

    assert result["reason"] == REASON_APP_ERROR
    assert result["response_text"] == "Serial đã được sử dụng"


def test_unknown_dialog_is_still_an_error_and_still_dismissed(qapp):
    xml = (
        '<hierarchy>'
        '<node text="Máy chủ đang bận" resource-id="android:id/message" bounds="[0,0][700,80]"/>'
        '<node text="OK" bounds="[500,200][600,260]" clickable="true"/>'
        '</hierarchy>'
    )
    adb = FakeAdb(xml=xml, dialog_focused=True)
    result = make_worker(adb, error_keywords="loi", not_found_keywords="không tìm thấy")._read_result()

    assert result["status"] == "ERROR"
    assert result["reason"] == REASON_DIALOG
    assert adb.taps() == ["input tap 550 230"]


def test_clean_screen_stays_ok_and_nothing_is_tapped(qapp):
    adb = FakeAdb(xml=NO_DIALOG_XML, dialog_focused=False)
    result = make_worker(adb)._read_result()

    assert result["status"] == "OK"
    assert adb.taps() == []


# --- khi không bấm được OK --------------------------------------------------

def test_dialog_that_survives_the_tap_is_flagged(qapp):
    """Gửi lệnh thành công chưa chắc hộp thoại đã đóng - phải kiểm tra lại."""
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True, sticky=True)
    result = make_worker(adb)._read_result()

    assert result["reason"] == REASON_NOT_FOUND
    assert result["dismiss_failed"] is True


def test_custom_drawn_dialog_is_still_verified(qapp):
    """
    Hộp thoại tự vẽ (Flutter/WebView) nằm trong cửa sổ của app nên dumpsys không
    gọi nó là dialog. Việc kiểm tra "đã đóng chưa" phải dựa vào nội dung màn
    hình, nếu không bot luôn tưởng đã đóng xong.
    """
    stuck = FakeAdb(xml=REAL_DIALOG_XML, dialog_focused=True, window_is_dialog=False, sticky=True)
    assert make_worker(stuck, error_keywords="đã được ghi nhận")._read_result()["dismiss_failed"]

    closed = FakeAdb(xml=REAL_DIALOG_XML, dialog_focused=True, window_is_dialog=False)
    assert not make_worker(closed, error_keywords="đã được ghi nhận")._read_result()["dismiss_failed"]


def _screen_dumps(adb):
    return [c for c in adb.commands if "uiautomator dump" in c]


def test_dialog_in_its_own_window_skips_the_second_screen_dump(qapp):
    """
    Đo trên máy thật: `uiautomator dump` ~1200ms, `dumpsys window` ~130ms. Bước
    xác nhận "hộp thoại đóng chưa" chỉ cần biết còn hay hết, không cần đọc chữ.
    Hộp thoại là cửa sổ riêng thì chuỗi cửa sổ đang focus đổi ngay khi nó đóng -
    đủ để kết luận mà không phải dump lần hai.
    """
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True, window_is_dialog=True)
    result = make_worker(adb)._read_result("ABC123")

    assert result["dismiss_failed"] is False
    assert len(_screen_dumps(adb)) == 1


def test_self_drawn_dialog_still_pays_for_the_content_check(qapp):
    """
    Đánh đổi ngược lại: hộp thoại tự vẽ không làm đổi cửa sổ focus, nên vẫn phải
    dump để đối chiếu nội dung. Chậm nhưng đúng - không được kết luận bừa.
    """
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True, window_is_dialog=False)
    make_worker(adb)._read_result("ABC123")

    assert len(_screen_dumps(adb)) >= 2


def test_window_behaviour_is_probed_once_not_every_row(qapp):
    """Dò một lần rồi nhớ - hỏi lại mỗi dòng là tự thêm một lượt gọi ADB."""
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True, window_is_dialog=True)
    worker = make_worker(adb)

    for _ in range(3):
        adb.dialog_open = True
        worker._read_result("ABC123")

    assert worker._dialog_seen_by_dumpsys is True
    # 3 dòng, mỗi dòng đúng 1 lần đọc màn hình.
    assert len(_screen_dumps(adb)) == 3


# --- đường nhanh: phân loại bằng cửa sổ focus thay vì đọc cả màn hình ---------

def test_fast_path_is_off_until_a_dialog_has_proved_it_moves_focus(qapp):
    """
    Chưa tận mắt thấy hộp thoại làm đổi focus thì không được đi đường nhanh.
    Hộp thoại tự vẽ (Flutter/WebView) không đổi focus - tin bừa là mọi dòng đều
    thành 'thành công', đúng cái bug nguy hiểm nhất.
    """
    adb = FakeAdb(xml=NO_DIALOG_XML)
    worker = make_worker(adb)
    assert worker._dialog_seen_by_dumpsys is None

    worker._process_serial(2, "ABC123")

    assert len(_screen_dumps(adb)) == 1      # vẫn đọc màn hình như cũ


def test_fast_path_skips_the_screen_dump_on_a_clean_row(qapp):
    """Đã xác nhận rồi thì dòng trót lọt không phải dump lần nào."""
    adb = FakeAdb(xml=NO_DIALOG_XML)
    worker = make_worker(adb)
    worker._dialog_seen_by_dumpsys = True

    result = worker._process_serial(2, "ABC123")

    assert result["status"] == "OK"
    assert _screen_dumps(adb) == []


def test_fast_path_hands_over_to_the_full_read_when_a_dialog_appears(qapp):
    """
    Có hộp thoại thì vẫn phải đọc màn hình - đường nhanh chỉ biết 'có gì đó hiện
    ra', không đọc được lý do để ghi vào Excel.
    """
    adb = FakeAdb(xml=NOT_FOUND_XML, window_is_dialog=True)
    worker = make_worker(adb)
    worker._dialog_seen_by_dumpsys = True

    result = worker._process_serial(2, "ABC123")

    assert result["reason"] == REASON_NOT_FOUND
    assert "Không tìm thấy serial" in result["message"]
    assert len(_screen_dumps(adb)) >= 1


def test_fast_path_defers_when_adb_stops_answering(qapp):
    """ADB im lặng thì không được kết luận 'thành công' - nhường đường chắc chắn."""
    adb = FakeAdb(xml=NO_DIALOG_XML)
    worker = make_worker(adb)
    worker._dialog_seen_by_dumpsys = True

    adb.run_shell = lambda command, timeout=None: None
    assert worker._verdict_by_focus("abcd u0 com.app/com.app.MainActivity") is None


def test_dead_adb_during_dismiss_is_flagged(qapp):
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True, adb_dead=True)
    assert make_worker(adb)._read_result()["dismiss_failed"] is True


def test_run_pauses_after_repeated_dismiss_failures(qapp):
    """
    Kẹt hộp thoại mà chạy tiếp thì mọi dòng sau đều bị đánh dấu sai.

    Đúng 3 serial - bằng ngưỡng tạm dừng - để vòng lặp dừng ở dòng cuối; thêm
    dòng nữa là test treo thật vì bot đứng chờ người dùng bấm Resume.
    """
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True, sticky=True)
    worker = make_worker(
        adb,
        serials=[
            SerialItem(row=r, value=f"A{r}")
            for r in range(2, 2 + MAX_CONSECUTIVE_DISMISS_FAILURES)
        ],
    )
    worker.backend = _TypingBackend()

    errors = []
    worker.error_occurred.connect(errors.append)
    worker.run()

    assert errors and "không đóng được" in errors[0]
    assert not worker._pause_event.is_set()


def test_app_wording_not_found_beats_the_loi_title_with_default_keywords(qapp):
    """
    Câu thật của app là "Sản phẩm không tồn tại", trong hộp thoại có tiêu đề
    "Lỗi" - mà "loi" là từ khóa lỗi mặc định. Xét không-tìm-thấy trước nên lý do
    cụ thể vẫn thắng cái tiêu đề chung.
    """
    xml = REAL_DIALOG_XML.replace("Sản phẩm đã được ghi nhận", "Sản phẩm không tồn tại")
    adb = FakeAdb(xml=xml, dialog_focused=True, window_is_dialog=False)
    worker = make_worker(
        adb,
        error_keywords="error,product not found,invalid,failed,loi,khong hop le,that bai",
        not_found_keywords=DEFAULT_NOT_FOUND_KEYWORDS,
    )
    result = worker._read_result()

    assert result["reason"] == REASON_NOT_FOUND
    assert result["response_text"].startswith("Sản phẩm không tồn tại")
    assert adb.taps() == ["input tap 360 855"]


def test_real_dialog_end_to_end_is_dismissed_and_recorded(qapp):
    adb = FakeAdb(xml=REAL_DIALOG_XML, dialog_focused=True)
    worker = make_worker(adb, error_keywords="đã được ghi nhận")
    worker.backend = _TypingBackend()

    result = worker._process_serial(2, "BSS-26072141000044")

    assert result["status"] == "ERROR"
    assert result["reason"] == REASON_APP_ERROR
    assert result["response_text"].startswith("Sản phẩm đã được ghi nhận")
    assert not result["dismiss_failed"]
    assert adb.taps() == ["input tap 360 855"]


def test_message_says_ok_was_pressed(qapp):
    adb = FakeAdb(xml=NOT_FOUND_XML, dialog_focused=True)
    worker = make_worker(adb)
    worker.backend = _TypingBackend()

    result = worker._process_serial(2, "ABC123")

    assert "đã bấm OK" in result["message"]
    assert "Không tìm thấy serial trong hệ thống" in result["message"]


class _TypingBackend(AutomationBackend):
    """Backend giả cho các test gọi thẳng _process_serial, không qua ADB."""

    def is_available(self):
        return True

    def type_serial(self, text):
        pass

    def send_enter(self, mode):
        pass
