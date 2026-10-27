"""
Hộp thoại cuối phiên xuất OR của bản app mới.

Bản cũ chỉ có câu "Công việc lấy hàng đã kết thúc" cùng hai nút. Bản mới thêm bảng
chi tiết (mã phiên, tài khoản, thời gian) và gom hai nút [Lịch sử][OK] vào một hàng
riêng. Bot đọc ra mỗi chữ "Lịch sử", không nhận ra phiên đã kết thúc nên dừng cả
lượt chạy ngay sau serial cuối của mỗi mã OR.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from automation_backend import AdbBackend
from fake_pick_device import FakePickDevice, Session
from pick_runner import PickConfig, PickRunner, PickStopped
from screen_reader import dialog_marker, dialog_message, find_dismiss_button, parse_bounds
from verification import classify_session_dialog


def _card(ok_attrs):
    return (
        '<node class="android.widget.LinearLayout" bounds="[54,645][1026,1347]">'
        '  <node class="android.widget.LinearLayout" bounds="[54,645][1026,790]">'
        '    <node class="android.widget.ImageView" bounds="[108,690][162,744]"/>'
        '    <node text="Thông báo" class="android.widget.TextView" bounds="[192,690][450,750]"/>'
        '  </node>'
        '  <node class="android.widget.LinearLayout" bounds="[54,790][1026,1197]">'
        '    <node text="Công việc lấy hàng đã kết thúc" class="android.widget.TextView" '
        'bounds="[102,835][1000,895]"/>'
        '    <node class="android.widget.TableLayout" bounds="[102,940][1000,1150]">'
        '      <node text="Mã phiên" bounds="[102,945][380,1000]"/>'
        '      <node text="PL00000000TEST_001" bounds="[390,945][1000,1000]"/>'
        '      <node text="Tài khoản" bounds="[102,1015][380,1070]"/>'
        '      <node text="ntl.0000000" bounds="[390,1015][1000,1070]"/>'
        '      <node text="Thời gian" bounds="[102,1085][380,1140]"/>'
        '      <node text="09:41:11 23/10/2026" bounds="[390,1085][1000,1140]"/>'
        '    </node>'
        '  </node>'
        '  <node class="android.widget.LinearLayout" bounds="[54,1197][1026,1347]">'
        '    <node text="Lịch sử" class="android.widget.Button" clickable="true" '
        'bounds="[54,1197][540,1347]"/>'
        f'    <node text="OK" class="android.widget.Button" clickable="true" {ok_attrs} '
        'bounds="[540,1197][1026,1347]"/>'
        '  </node>'
        '</node>'
    )


# uiautomator chỉ dump cửa sổ hộp thoại: mọi thẻ bao ngoài đều to đúng bằng bản dump,
# chỉ riêng hàng nút là nhỏ hơn - đó là chỗ phép khoanh vùng theo diện tích hụt.
FINISH_DIALOG_ONLY_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
    '<node class="android.widget.FrameLayout" bounds="[54,645][1026,1347]">'
    + _card('resource-id="vn.aipacific.fai.prod:id/btnOk"')
    + '</node></hierarchy>'
)

# Cùng hộp thoại nhưng nằm trên cả màn hình phía sau (dump đủ các cửa sổ).
FINISH_OVER_PAGE_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
    '<node class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">'
    '  <node text="Quét sản phẩm/serial" bounds="[246,525][834,585]"/>'
    '  <node text="SL sản phẩm đã lấy" bounds="[60,335][520,385]"/>'
    + _card('resource-id="vn.aipacific.fai.prod:id/btnOk"')
    + '</node></hierarchy>'
)

# Nút OK không có resource-id: bot vẫn phải tìm ra để bấm.
FINISH_OK_WITHOUT_ID_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
    '<node class="android.widget.FrameLayout" bounds="[54,645][1026,1347]">'
    + _card('')
    + '</node></hierarchy>'
)

# Chữ nút nằm trong TextView con KHÔNG bấm được của một LinearLayout cha bấm được.
# Máy nào báo `clickable` ở cha thì bản sửa đầu tiên vẫn khoanh nhầm vào hàng nút
# và bot báo "hộp thoại unknown - Lịch sử" y như lỗi cũ.
FINISH_CLICKABLE_PARENT_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
    '<node class="android.widget.FrameLayout" bounds="[54,645][1026,1347]">'
    '<node class="android.widget.LinearLayout" bounds="[54,645][1026,1347]">'
    '<node text="Thông báo" bounds="[192,681][450,754]"/>'
    '<node text="Công việc lấy hàng đã kết thúc" bounds="[102,832][978,893]"/>'
    '<node text="Mã phiên" bounds="[102,944][390,997]"/>'
    '<node text="PL00000000TEST_001" bounds="[390,944][978,997]"/>'
    '<node text="Tài khoản" bounds="[102,1015][390,1068]"/>'
    '<node text="ntl.0000000" bounds="[390,1015][978,1068]"/>'
    '<node text="Thời gian" bounds="[102,1086][390,1139]"/>'
    '<node text="09:41:11 23/10/2026" bounds="[390,1086][978,1139]"/>'
    '<node class="android.widget.LinearLayout" bounds="[54,1198][1026,1347]">'
    '<node class="android.widget.LinearLayout" clickable="true" bounds="[54,1198][539,1347]">'
    '<node class="android.widget.TextView" text="Lịch sử" clickable="false" '
    'bounds="[200,1240][400,1300]"/></node>'
    '<node class="android.widget.LinearLayout" clickable="true" bounds="[541,1198][1026,1347]">'
    '<node class="android.widget.TextView" text="OK" clickable="false" '
    'bounds="[700,1240][860,1300]"/></node>'
    '</node></node></node></hierarchy>'
)

ALL_LAYOUTS = [
    pytest.param(FINISH_CLICKABLE_PARENT_XML, id="clickable-parent"),
    pytest.param(FINISH_DIALOG_ONLY_XML, id="dialog-only"),
    pytest.param(FINISH_OVER_PAGE_XML, id="over-page"),
    pytest.param(FINISH_OK_WITHOUT_ID_XML, id="ok-without-id"),
]


# --- đọc hộp thoại -------------------------------------------------------------


@pytest.mark.parametrize("xml", ALL_LAYOUTS)
def test_message_has_the_sentence_and_the_evidence_not_just_the_history_button(xml):
    message = dialog_message(xml)

    assert message.startswith("Công việc lấy hàng đã kết thúc")
    for evidence in ("PL00000000TEST_001", "ntl.0000000", "09:41:11 23/10/2026"):
        assert evidence in message
    assert "OK" not in message.split(" | ")
    # Không lẫn chữ của màn hình phía sau.
    assert "Quét sản phẩm/serial" not in message


@pytest.mark.parametrize("xml", ALL_LAYOUTS)
def test_the_session_end_is_classified_as_complete(xml):
    assert classify_session_dialog(xml, "pick") == "complete"


@pytest.mark.parametrize("xml", ALL_LAYOUTS)
def test_ok_is_the_button_to_dismiss_never_history(xml):
    button = find_dismiss_button(xml)

    assert button["text"] == "OK"
    # Chạm vào giữa nhãn phải rơi vào nửa phải của hàng nút (OK), không phải nửa
    # trái (Lịch sử). Với ô chữ con trong ô cha bấm được, nhãn nhỏ hơn cả nút.
    x1, y1, x2, y2 = parse_bounds(button["bounds"])
    assert (x1 + x2) // 2 > 540 and 1197 <= (y1 + y2) // 2 <= 1347


def test_classification_does_not_depend_on_where_the_dialog_was_cut_out(monkeypatch):
    """
    Dù cách khoanh hộp thoại đọc sai (ở đây ép nó chỉ trả "Lịch sử"), câu báo kết
    thúc phiên vẫn nằm trên màn hình nên vẫn phải nhận ra là kết thúc.
    """
    import verification

    monkeypatch.setattr(verification, "dialog_message", lambda xml, max_len=300: "Lịch sử")

    assert verification.classify_session_dialog(FINISH_DIALOG_ONLY_XML, "pick") == "complete"


def test_the_whole_screen_fallback_does_not_turn_other_dialogs_into_complete():
    xml = FINISH_CLICKABLE_PARENT_XML.replace("Công việc lấy hàng đã kết thúc", "Chờ xác nhận")

    assert classify_session_dialog(xml, "pick") == "unknown"


def test_marker_is_the_end_sentence():
    assert dialog_marker(FINISH_DIALOG_ONLY_XML) == "Công việc lấy hàng đã kết thúc"


def test_a_different_dialog_with_the_history_button_is_still_not_complete():
    xml = FINISH_DIALOG_ONLY_XML.replace("Công việc lấy hàng đã kết thúc", "Serial đã được sử dụng")

    assert classify_session_dialog(xml, "pick") == "unknown"


def test_an_error_dialog_is_not_rescued_by_the_whole_screen_fallback():
    xml = FINISH_OVER_PAGE_XML.replace("Công việc lấy hàng đã kết thúc", "Lỗi: serial không thuộc đơn")

    assert classify_session_dialog(xml, "pick") == "error"


# --- chạy trọn một mã OR -------------------------------------------------------

def make_runner(device):
    config = PickConfig(step_timeout=2.0, capture_screenshot=False)
    return PickRunner(device, AdbBackend(device), config, on_log=None)


@pytest.mark.parametrize("layout", ["new", "new_ok_without_id", "new_clickable_parent"])
def test_bill_closes_on_the_new_end_of_session_dialog(layout):
    device = FakePickDevice([Session("OR1", "PL_001", 2)], finish_layout=layout)

    outcome = make_runner(device).run_bill("OR1", [
        {"row": 2, "value": "S1"}, {"row": 3, "value": "S2"},
    ])

    assert outcome.picked == 2
    assert device.state == "list"
    # Bấm OK để về màn hình tìm mã OR, không đụng tới "Lịch sử".
    assert not device.history_opened


def test_second_bill_runs_after_the_new_dialog():
    device = FakePickDevice([
        Session("OR1", "PL_001", 1), Session("OR2", "PL_002", 1),
    ], finish_layout="new")
    runner = make_runner(device)

    runner.run_bill("OR1", [{"row": 2, "value": "S1"}])
    second = runner.run_bill("OR2", [{"row": 3, "value": "S2"}])

    assert second.picked == 1
    assert not device.history_opened


def test_the_new_dialog_before_the_last_serial_still_stops_the_run():
    """Kết thúc sớm là app báo phiên đóng trước khi đủ hàng: không được coi là xong."""
    device = FakePickDevice([Session("OR1", "PL_001", 3)], finish_layout="new")
    device.finish_after = 1

    with pytest.raises(PickStopped):
        make_runner(device).run_bill("OR1", [
            {"row": 2, "value": "S1"}, {"row": 3, "value": "S2"}, {"row": 4, "value": "S3"},
        ])


def test_unknown_dialog_stop_lists_the_screen_elements_for_the_bug_report():
    device = FakePickDevice([Session("OR1", "PL_001", 1)], finish_layout="new")
    original = device._finish_dialog_xml
    device._finish_dialog_xml = lambda: original().replace(
        "Công việc lấy hàng đã kết thúc", "Hộp thoại lạ chưa gặp bao giờ"
    )

    with pytest.raises(PickStopped) as stopped:
        make_runner(device).run_bill("OR1", [{"row": 2, "value": "S1"}])

    assert "hộp thoại unknown" in stopped.value.message
    assert "Phần tử trên màn hình:" in stopped.value.message
    assert "Hộp thoại lạ chưa gặp bao giờ" in stopped.value.message
