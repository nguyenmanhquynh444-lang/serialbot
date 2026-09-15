"""
Luồng nhập hàng theo mã check-in.

Cùng nguyên tắc với luồng xuất kho: thà dừng còn hơn đoán. Thêm một điểm riêng -
phần màn hình sau nút "Nhận hàng" chưa dò được hết trên máy thật, nên bot phải
dừng khi gặp màn hình lạ chứ không gõ serial vào bất cứ ô nhập nào nó thấy.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from automation_backend import AdbBackend
from fake_inbound_device import Checkin, FakeInboundDevice
from inbound_runner import InboundConfig, InboundRunner
from pick_runner import PickStopped

CODE = "CKSIRVIN89HN210210 - VIN"
INFO = "IRVIN89HN210 - ESO26070007-261_3200368076"


def make_runner(device, **config_kwargs):
    config = InboundConfig(step_timeout=2.0, capture_screenshot=False, **config_kwargs)
    return InboundRunner(device, AdbBackend(device), config, on_log=None)


def rows(*serials, start=2):
    return [{"row": start + i, "value": s} for i, s in enumerate(serials)]


def one_checkin(qty=3, **kwargs):
    return FakeInboundDevice([Checkin(CODE, INFO, qty)], **kwargs)


# --- đường chạy trọn vẹn -----------------------------------------------------

def test_full_checkin_runs_through_every_screen():
    device = one_checkin(3)
    outcome = make_runner(device).run_bill("CKSIRVIN89HN210210", rows("S1", "S2", "S3"))

    assert outcome.status == "OK"
    assert outcome.picked == 3
    assert [s.serial for s in outcome.serials] == ["S1", "S2", "S3"]
    assert device.state == "list"          # đã đóng phiếu, sẵn sàng phiếu sau


def test_warehouse_code_also_finds_the_card():
    """Ô tìm kiếm nhận cả mã check-in lẫn mã nhập kho, Excel điền cái nào cũng chạy."""
    device = one_checkin(2)
    outcome = make_runner(device).run_bill("IRVIN89HN210", rows("S1", "S2"))

    assert outcome.picked == 2


def test_second_checkin_starts_without_going_back_to_the_menu():
    """Đóng phiếu xong app đứng ở danh sách - phiếu sau phải chạy tiếp được."""
    device = FakeInboundDevice([
        Checkin(CODE, INFO, 1),
        Checkin("CKSIRVIN9NWS373102 - VIN", "IRVIN9NWS373 - BAT00000010AAIM163PCS3107", 1),
    ])
    runner = make_runner(device)

    runner.run_bill("CKSIRVIN89HN210210", rows("S1"))
    outcome = runner.run_bill("CKSIRVIN9NWS373102", rows("S2"))

    assert outcome.picked == 1


def test_app_returning_to_the_main_menu_also_works():
    """Chưa dò được app quay về đâu sau khi đóng phiếu, nên phải đỡ cả hai."""
    device = FakeInboundDevice(
        [Checkin(CODE, INFO, 1), Checkin("CKSIRVINX55B627372 - VIN", "IRVINX55B627 - x", 1)],
        back_to_menu=True,
    )
    runner = make_runner(device)

    runner.run_bill("CKSIRVIN89HN210210", rows("S1"))
    outcome = runner.run_bill("CKSIRVINX55B627372", rows("S2"))

    assert outcome.picked == 1


def test_enter_landing_straight_in_the_session_still_works():
    """
    Gõ mã + Enter là app tra luôn. Nếu nó đưa thẳng vào phiên thay vì dừng ở thẻ
    thì không còn nút nào để bấm - bot phải nhận ra và quét tiếp, không đứng chờ
    một thẻ sẽ không bao giờ hiện.
    """
    device = FakeInboundDevice([Checkin(CODE, INFO, 2)], enter_opens=True)

    outcome = make_runner(device).run_bill("CKSIRVIN89HN210210", rows("S1", "S2"))

    assert outcome.picked == 2
    assert outcome.session_code == CODE


# --- mã chưa có phiên check-in ----------------------------------------------

def test_missing_session_stops_by_default_and_backs_out():
    """
    Bấm 'Xác nhận' là tạo một phiên check-in thật trong hệ thống. Mặc định bot
    không tự làm: nó bấm 'Quay lại' rồi dừng, để người dùng quyết.
    """
    device = FakeInboundDevice([], new_session_qty=2)

    with pytest.raises(PickStopped) as excinfo:
        make_runner(device).run_bill("167PIVGR27072026", rows("S1", "S2"))

    assert "chưa có phiên check-in" in excinfo.value.message
    assert device.sessions_created == []        # không tạo gì cả
    assert device.state == "list"               # đã bấm Quay lại, không để treo


def test_missing_session_is_created_when_the_option_is_on():
    device = FakeInboundDevice([], new_session_qty=2)
    runner = make_runner(device, create_missing_session=True)

    outcome = runner.run_bill("167PIVGR27072026", rows("S1", "S2"))

    assert device.sessions_created == ["167PIVGR27072026"]
    assert outcome.picked == 2


def test_a_second_unknown_dialog_is_never_confirmed_blindly():
    """Hộp thoại thứ hai có thể đang hỏi chuyện khác - không bấm bừa."""
    device = FakeInboundDevice([], new_session_qty=2)
    device.extra_screen = True
    runner = make_runner(device, create_missing_session=True)

    with pytest.raises(PickStopped, match="không thấy màn hình quét serial"):
        runner.run_bill("167PIVGR27072026", rows("S1", "S2"))


# --- những chỗ phải dừng -----------------------------------------------------

def test_stops_when_the_code_is_not_in_the_list():
    device = one_checkin(1)

    with pytest.raises(PickStopped, match="Không tìm thấy phiếu check-in"):
        make_runner(device).run_bill("CKSIRVINKHONGCO", rows("S1"))


def test_stops_when_two_cards_match():
    """Hai phiếu cùng khớp thì không dám bấm - mở nhầm phiếu là nhập nhầm hàng."""
    device = FakeInboundDevice([
        Checkin("CKSIRVIN89HN210210 - VIN", INFO, 1),
        Checkin("CKSIRVIN89HN210211 - VIN", "IRVIN89HN210211 - x", 1),
    ])

    with pytest.raises(PickStopped, match="lọc ra 2 phiếu"):
        make_runner(device).run_bill("CKSIRVIN89HN21021", rows("S1"))


def test_unknown_screen_after_receive_stops_and_names_what_it_saw():
    """
    Bước còn thiếu trong luồng phải lộ ra thành thông báo đọc được, không phải
    thành serial gõ nhầm chỗ.
    """
    device = one_checkin(2, extra_screen=True)

    with pytest.raises(PickStopped) as excinfo:
        make_runner(device).run_bill("CKSIRVIN89HN210210", rows("S1", "S2"))

    message = excinfo.value.message
    assert "không thấy màn hình quét serial" in message
    assert "Scan container" in message          # mô tả đủ để bổ sung bước
    assert device.typed == [("list", "CKSIRVIN89HN210210")]   # chưa gõ serial nào


def test_count_mismatch_stops_before_any_serial_is_scanned():
    """
    Thẻ check-in không hiện số lượng, nên chốt chặn duy nhất là tổng của '0/N'.
    Phải chặn trước khi quét, lúc đó chưa động gì vào hàng.
    """
    device = one_checkin(5)

    with pytest.raises(PickStopped, match="app báo cần 5 sản phẩm nhưng Excel có 2"):
        make_runner(device).run_bill("CKSIRVIN89HN210210", rows("S1", "S2"))

    assert device.scanned == 0


def test_turning_the_count_check_off_only_moves_the_failure_later():
    """
    Tắt đối chiếu không làm cho file thiếu serial chạy được - chỉ đổi chỗ vỡ:
    thay vì dừng khi chưa động gì, bot đẩy 2 serial vào phiên thật rồi mới kẹt ở
    2/5. Đây là lý do mặc định để bật.
    """
    device = one_checkin(5)
    runner = make_runner(device, check_expected_count=False)

    with pytest.raises(PickStopped, match="không về được danh sách check-in"):
        runner.run_bill("CKSIRVIN89HN210210", rows("S1", "S2"))

    assert device.scanned == 2
    assert [s.serial for s in runner.last_partial] == ["S1", "S2"]


def test_rejected_serial_stops_the_run_and_reports_what_went_in():
    device = one_checkin(3, reject_serials=("S2",))
    runner = make_runner(device)

    with pytest.raises(PickStopped):
        runner.run_bill("CKSIRVIN89HN210210", rows("S1", "S2", "S3"))

    # S1 đã vào phiên thật - phải báo lại để người dùng biết mà dọn.
    assert [s.serial for s in runner.last_partial] == ["S1"]
