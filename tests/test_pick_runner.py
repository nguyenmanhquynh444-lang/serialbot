"""
Luồng xuất kho theo mã OR.

Nguyên tắc xuyên suốt: thà dừng còn hơn đoán. Một phiên lấy hàng động vào hàng
thật trong kho, nên mọi tình huống mơ hồ - lọc ra hai đơn, app báo số lượng khác
Excel, app đòi lấy ở vị trí khác, serial bị từ chối - đều phải dừng chứ không
"bỏ qua rồi chạy tiếp".
"""
import os
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from automation_backend import AdbBackend
from fake_pick_device import FakePickDevice, Session
from pick_runner import OrNotFoundError, PickConfig, PickRunner, PickStopped, parse_counter


def make_runner(device, **config_kwargs):
    config_kwargs.setdefault("step_timeout", 2.0)
    config_kwargs.setdefault("capture_screenshot", False)
    config = PickConfig(**config_kwargs)
    return PickRunner(device, AdbBackend(device), config, on_log=None)


def rows(*serials, start=2):
    return [{"row": start + i, "value": s} for i, s in enumerate(serials)]


# --- đọc số đếm --------------------------------------------------------------

def test_parse_counter_reads_progress():
    assert parse_counter("0/10") == (0, 10)
    assert parse_counter(" 7 / 10 ") == (7, 10)
    assert parse_counter("") is None
    assert parse_counter("xong") is None


# --- đường chạy trọn vẹn -----------------------------------------------------

def test_full_bill_runs_through_every_screen():
    device = FakePickDevice([Session("ORVINEKGK4T1560", "PL_001", 3)])
    outcome = make_runner(device).run_bill("ORVINEKGK4T1560", rows("S1", "S2", "S3"))

    assert outcome.status == "OK"
    assert outcome.picked == 3
    assert outcome.session_code == "PL_001"
    assert [s.serial for s in outcome.serials] == ["S1", "S2", "S3"]
    # App trả về màn hình tìm mã OR chứ không về menu chính - đó là chỗ mã OR
    # tiếp theo được gõ vào.
    assert device.state == "list"


def test_every_input_goes_to_the_right_screen():
    """
    Ba bước quét dùng chung một ô nhập, nên thứ tự sai là mã tote rơi vào ô
    serial. Kiểm từng giá trị vào đúng màn hình nào.
    """
    device = FakePickDevice([Session("VD1", "PL_001", 2)])
    make_runner(device).run_bill("VD1", rows("S1", "S2"))

    assert device.typed == [
        ("list", "VD1"),
        ("tote", "T001"),
        ("bin", "PYTES"),
        ("serial", "S1"),
        ("serial", "S2"),
    ]


def test_mvd_is_carried_through_without_being_typed():
    """Mã vận đơn đi kèm để tra ngược; gõ nó vào app là tìm nhầm chỗ."""
    device = FakePickDevice([Session("OR1", "PL_001", 1)])
    outcome = make_runner(device).run_bill("OR1", rows("S1"), "581PIPTE03082026")

    assert outcome.ref == "581PIPTE03082026"
    assert all(text != "581PIPTE03082026" for _, text in device.typed)


def test_second_bill_starts_from_the_search_screen():
    """
    Từ đơn thứ hai trở đi bot xuất phát ở màn hình tìm mã OR chứ không phải menu
    chính, và ô tìm kiếm còn nguyên mã cũ - nối thêm vào là ra mã không có thật.
    """
    device = FakePickDevice([
        Session("OR1", "PL_001", 1),
        Session("OR2", "PL_002", 1),
    ])
    runner = make_runner(device)

    runner.run_bill("OR1", rows("S1"))
    runner.run_bill("OR2", rows("S2"))

    assert [text for state, text in device.typed if state == "list"] == ["OR1", "OR2"]
    assert device.state == "list"


def test_tote_is_scanned_once_then_skipped_on_later_bills():
    """App nhớ tote giữa các phiên; gõ lại là đăng ký chồng một thiết bị nữa."""
    device = FakePickDevice([
        Session("OR1", "PL_001", 1),
        Session("OR2", "PL_002", 1),
    ])
    runner = make_runner(device)

    runner.run_bill("OR1", rows("S1"))
    runner.run_bill("OR2", rows("S2"))

    assert [text for state, text in device.typed if state == "tote"] == ["T001"]
    assert device.totes_registered == 1


def test_assistant_dialog_is_dismissed_every_bill():
    """Hộp trợ lý hiện mỗi lần pick - không đóng được là kẹt ngay bill đầu."""
    device = FakePickDevice([Session("VD1", "PL_001", 1)])
    make_runner(device).run_bill("VD1", rows("S1"))
    assert device.state == "list"


def test_runs_fine_when_the_assistant_dialog_does_not_appear():
    device = FakePickDevice([Session("VD1", "PL_001", 1)], skip_assistant=True)
    outcome = make_runner(device).run_bill("VD1", rows("S1"))
    assert outcome.picked == 1


# --- những chỗ bắt buộc phải dừng -------------------------------------------

def test_stops_when_the_filter_leaves_more_than_one_session():
    """Hai phiên cùng khớp thì bấm cái nào cũng có thể là nhầm đơn."""
    device = FakePickDevice([
        Session("VD1", "PL_001", 1),
        Session("VD1-B", "PL_002", 1),      # cũng chứa chuỗi "VD1"
    ])

    with pytest.raises(PickStopped, match="không dám bấm"):
        make_runner(device).run_bill("VD1", rows("S1"))

    assert device.state == "list"           # chưa mở phiên nào


def test_raises_or_not_found_when_the_bill_is_not_in_the_list():
    """
    Ngoại lệ duy nhất trong file này: OrNotFoundError không phải PickStopped
    thường - PickWorker bắt riêng nó để ghi lỗi cho mã này rồi gõ mã OR kế tiếp,
    vì tại đây chưa mở phiên nào (an toàn để bỏ qua). Vẫn là PickStopped (raise
    lên là dừng nếu ai đó gọi run_bill trực tiếp mà không qua worker).
    """
    device = FakePickDevice([Session("VD1", "PL_001", 1)])

    with pytest.raises(OrNotFoundError, match="Không tìm thấy mã OR"):
        make_runner(device).run_bill("VD-KHONG-CO", rows("S1"))

    assert device.state == "list"           # chưa mở phiên nào


def test_stops_when_the_search_box_does_not_hold_what_was_sent():
    """
    Thẻ phiên không in mã OR, nên lớp chặn duy nhất còn lại là ô tìm kiếm phải
    đang giữ đúng mã bot gửi. ADB gõ hụt ký tự thì mã cụt vẫn lọc ra một thẻ
    trông rất bình thường - của đơn khác.
    """
    device = FakePickDevice([Session("OR12345", "PL_001", 1)])
    original_type = device._type

    def truncating_type(text):
        original_type(text[:-1] if device.state == "list" else text)

    device._type = truncating_type

    with pytest.raises(PickStopped, match="Ô tìm kiếm đang là"):
        make_runner(device).run_bill("OR12345", rows("S1"))

    assert device.state == "list"            # chưa mở phiên nào


def test_stops_before_opening_when_the_count_does_not_match():
    """
    App bảo cần 5, Excel có 3. Phát hiện trước khi mở phiên thì chưa động vào
    kho; chạy tiếp thì kẹt giữa chừng với một phiên mở dở.
    """
    device = FakePickDevice([Session("VD1", "PL_001", 5)])

    with pytest.raises(PickStopped, match="app báo cần 5 sản phẩm nhưng Excel có 3"):
        make_runner(device).run_bill("VD1", rows("S1", "S2", "S3"))

    assert device.state == "list"
    assert device.active is None            # không mở phiên


def test_count_check_can_be_turned_off():
    device = FakePickDevice([Session("VD1", "PL_001", 2)])
    runner = make_runner(device, check_expected_count=False)

    # App cần 2, Excel có 1 -> mở phiên, quét 1 rồi kẹt vì phiên chưa đóng.
    with pytest.raises(PickStopped):
        runner.run_bill("VD1", rows("S1"))

    assert device.active is not None        # đã mở phiên - đúng cái rủi ro


def test_stops_when_the_app_rejects_a_serial():
    device = FakePickDevice([Session("VD1", "PL_001", 3)], reject_serials=["S2"])

    with pytest.raises(PickStopped, match="Không tìm được sản phẩm S2"):
        make_runner(device).run_bill("VD1", rows("S1", "S2", "S3"))


def test_stops_on_an_unexpected_dialog_when_opening_the_session():
    device = FakePickDevice(
        [Session("VD1", "PL_001", 1)], stuck_dialog="Phiên đã có người nhận"
    )

    with pytest.raises(PickStopped, match="Phiên đã có người nhận"):
        make_runner(device).run_bill("VD1", rows("S1"))


def test_stop_flag_interrupts_between_serials():
    """Bấm Dừng thì ngắt ở ranh giới giữa hai serial, không cắt ngang một serial."""
    device = FakePickDevice([Session("VD1", "PL_001", 3)])
    runner = PickRunner(
        device, AdbBackend(device),
        PickConfig(step_timeout=2.0, capture_screenshot=False),
        should_stop=lambda: device.picked >= 1,
    )

    with pytest.raises(PickStopped, match="bấm Dừng"):
        runner.run_bill("VD1", rows("S1", "S2", "S3"))

    assert device.picked == 1               # dừng ngay sau serial đầu


# --- vị trí lấy hàng (bin) ---------------------------------------------------

def test_bin_from_config_is_typed_when_it_matches_the_screen():
    device = FakePickDevice([Session("VD1", "PL_001", 1, bins=("PYTES",))])
    make_runner(device, bin_code="PYTES").run_bill("VD1", rows("S1"))

    assert ("bin", "PYTES") in device.typed


def test_stops_when_the_app_asks_for_a_different_bin():
    """
    Ép cứng một vị trí mà app lại chỉ sang kệ khác: gõ đại là đi lấy nhầm kệ,
    còn đi theo app thì trái với thứ người dùng vừa điền. Nên dừng và hỏi.
    """
    device = FakePickDevice([Session("VD1", "PL_001", 1, bins=("PYTKHO2",))])

    with pytest.raises(PickStopped, match="App yêu cầu lấy ở vị trí 'PYTKHO2'"):
        make_runner(device, bin_code="PYTES").run_bill("VD1", rows("S1"))

    assert not any(state == "bin" for state, _ in device.typed)


def test_empty_bin_config_follows_the_screen():
    """Để trống là đi theo vị trí app chỉ - đúng cả với đơn trải nhiều kệ."""
    device = FakePickDevice([Session("VD1", "PL_001", 1, bins=("PYTKHO2",))])
    make_runner(device, bin_code="").run_bill("VD1", rows("S1"))

    assert ("bin", "PYTKHO2") in device.typed


def test_stops_when_the_tote_field_is_empty_but_the_app_asks_for_one():
    device = FakePickDevice([Session("VD1", "PL_001", 1)])

    with pytest.raises(PickStopped, match="'Mã tote' trong Cấu hình đang để trống"):
        make_runner(device, tote="").run_bill("VD1", rows("S1"))


# --- tốc độ: đọc màn hình là gần như toàn bộ chi phí --------------------------

def dumps_of(device):
    return [c for c in device.commands if "uiautomator dump" in c]


def test_a_bill_does_not_read_the_screen_more_than_it_needs_to():
    """
    Chốt ngân sách số lần đọc màn hình cho một mã OR một serial.

    Hai chỗ từng đọc thừa: `_scan_tote` dump lại để hỏi đúng câu
    `_pass_assistant_dialog` vừa trả lời xong, và `_finish_session` đi tìm lại
    hộp thoại mà `_wait_for_pick` vừa nhìn thấy. Mỗi lần thừa là ~1.46s cho mỗi
    mã OR - với 300 mã là hơn 7 phút. Test này để chúng không lặng lẽ quay lại.
    """
    device = FakePickDevice([Session("VD1", "PL_001", 1)])
    make_runner(device).run_bill("VD1", rows("S1"))

    # A lone unchanged card needs one extra observation to reject stale results.
    assert len(dumps_of(device)) <= 10


# --- mã không có thật: kết luận nhanh, nhưng không được kết luận ẩu -----------

def test_missing_bill_is_decided_in_about_two_seconds_not_the_full_timeout():
    """
    Mã không có trong danh sách là chuyện thường trong file. Chờ hết
    `step_timeout` cho mỗi mã như vậy thì 300 mã mất cả tiếng chỉ để đứng nhìn.
    """
    device = FakePickDevice([Session("VD1", "PL_001", 1)])
    runner = make_runner(device, step_timeout=15.0)

    started = time.monotonic()
    with pytest.raises(OrNotFoundError):
        runner.run_bill("VD-KHONG-CO", rows("S1"))
    elapsed = time.monotonic() - started

    assert elapsed < 6.0, f"mất {elapsed:.1f}s - đáng lẽ chốt quanh search_timeout"
    assert device.state == "list"           # chưa mở phiên nào


def test_a_slow_list_is_not_mistaken_for_a_missing_bill():
    """
    Chỗ nguy hiểm nhất của việc kết luận sớm: đơn có thật mà app trả danh sách
    chậm thì bị ghi 'không tìm thấy' rồi bỏ qua - tức là bỏ sót một đơn phải
    xuất.

    Chốt lại tính chất quan trọng nhất: **không kết luận ở lần đọc màn hình đầu
    tiên thấy danh sách trống**. Đồng hồ chỉ bắt đầu khi ô tìm kiếm đã giữ đúng
    mã, và phải trống liên tục hết `search_timeout` mới dám kết luận.
    """
    class SlowList(FakePickDevice):
        """Thẻ phiên chỉ hiện ra từ lần đọc màn hình thứ ba."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.dumps = 0

        def _visible_sessions(self):
            if self.state == "list" and self.dumps < 3:
                return []
            return super()._visible_sessions()

        def run_shell(self, command, timeout=None):
            if "uiautomator dump" in command:
                self.dumps += 1
            return super().run_shell(command, timeout)

    device = SlowList([Session("VD1", "PL_001", 1)])
    outcome = make_runner(device, step_timeout=15.0).run_bill("VD1", rows("S1"))

    assert outcome.picked == 1              # vẫn xuất, không bị bỏ sót


def test_a_search_box_stuck_on_the_previous_code_is_retyped_once():
    """
    Gặp thật trên máy: sau vài mã không tìm thấy liên tiếp, ô nhập mất focus nên
    `input text` không vào được ô nữa - ô còn nguyên mã của lần trước và cả lượt
    chạy dừng ở đó. Chạm vào ô rồi gõ lại là đủ để đi tiếp.

    Lớp đối chiếu "ô phải khớp mã bot gửi" vẫn giữ nguyên, nên gõ lại không thể
    làm mở nhầm đơn: khớp thì mới bấm, không khớp thì vẫn dừng.
    """
    class LostFocus(FakePickDevice):
        """Chữ gõ vào rơi vào hư không cho tới khi có người chạm vào ô nhập."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.focused = False

        def _type(self, text):
            if self.state == "list" and not self.focused:
                self.typed.append((self.state, text))   # lệnh gửi đi nhưng không tới ô
                return
            super()._type(text)

        def _tap(self, x, y):
            if self.state == "list" and self._hit(x, y, "textInput"):
                self.focused = True
                return
            super()._tap(x, y)

    device = LostFocus([Session("VD1", "PL_001", 1)])
    device.state = "list"
    device.filter_text = "VD-CU-CON-SOT-LAI"       # mã của lần trước còn kẹt lại

    outcome = make_runner(device, step_timeout=15.0).run_bill("VD1", rows("S1"))

    assert outcome.picked == 1
    # Gõ đúng hai lần: lần đầu rơi vào hư không, lần sau sau khi chạm vào ô.
    assert [text for state, text in device.typed if state == "list"] == ["VD1", "VD1"]


def test_the_next_bill_does_not_re_read_a_screen_just_confirmed():
    """
    `_finish_session` chỉ trả về khi đã nhìn thấy màn hình tìm mã OR. Mã kế tiếp
    dump lại để hỏi đúng câu đó là mất không 1.46s - với 300 mã là hơn 7 phút.

    An toàn vì hai chuyện xảy ra cách nhau vài mili giây và ở giữa bot không gõ,
    không bấm gì; hơn nữa `_search_and_open` ngay sau đó vẫn đối chiếu ô tìm
    kiếm với mã vừa gửi trước khi dám bấm.
    """
    device = FakePickDevice([
        Session("OR1", "PL_001", 1),
        Session("OR2", "PL_002", 1),
    ])
    runner = make_runner(device)

    runner.run_bill("OR1", rows("S1"))
    before = len([c for c in device.commands if "uiautomator dump" in c])
    runner.run_bill("OR2", rows("S2"))
    second = len([c for c in device.commands if "uiautomator dump" in c]) - before

    assert second <= 8
    assert device.state == "list"


def test_a_bill_that_stopped_makes_the_next_one_check_the_screen_again():
    """
    Đường tắt trên chỉ dùng được khi mã trước đóng phiên gọn ghẽ. Mã trước dừng
    giữa chừng thì không ai biết app đang ở đâu - phải đọc lại màn hình.
    """
    device = FakePickDevice([Session("OR2", "PL_002", 1)])
    runner = make_runner(device)

    with pytest.raises(OrNotFoundError):
        runner.run_bill("OR-KHONG-CO", rows("S1"))

    assert runner._at_search_xml == ""       # không còn kết luận cũ để dựa vào
    assert runner.run_bill("OR2", rows("S2")).picked == 1
