"""
Đối chiếu các hằng resource-id của luồng nhận hàng với bản dump máy thật.

`tests/data/checkin_list_real_dump.xml` chụp từ LDPlayer ngày 31/07/2026, màn
hình "Danh sách check-in" của app vn.aipacific.fai.prod. Máy ảo giả là do mình
viết ra nên nó luôn "đúng" với chính mình; chỉ file này mới bắt được lúc app cập
nhật và đổi id - lúc đó bot sẽ đứng chờ một phần tử không còn tồn tại.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import inbound_runner as ib
from pick_runner import first_with_id, nodes_with_id
from screen_reader import normalize_match_text

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _read(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def screen():
    return _read("checkin_list_real_dump.xml")


@pytest.fixture(scope="module")
def confirm():
    """Hộp thoại "chưa có phiên check-in", dump 31/07/2026."""
    return _read("checkin_create_session_dialog.xml")


def test_every_id_the_runner_waits_for_exists_on_the_real_screen(screen):
    for rid in (ib.RID_INPUT, ib.RID_LIST, ib.RID_SESSION_CODE,
                ib.RID_ADD_INFO, ib.RID_START):
        assert first_with_id(screen, rid), f"màn hình thật không có '{rid}'"


def test_each_card_carries_one_start_button(screen):
    """Bot đếm nút để biết đã lọc còn đúng một phiếu chưa."""
    assert len(nodes_with_id(screen, ib.RID_START)) == 6
    assert len(nodes_with_id(screen, ib.RID_SESSION_CODE)) == 6


def test_card_fields_hold_the_codes_the_excel_will_contain(screen):
    codes = [n["text"] for n in nodes_with_id(screen, ib.RID_SESSION_CODE)]
    infos = [n["text"] for n in nodes_with_id(screen, ib.RID_ADD_INFO)]

    assert codes[0] == "CKSIRVIN89HN210210 - VIN"
    assert infos[0].startswith("IRVIN89HN210 - ")


@pytest.mark.parametrize("typed", ["CKSIRVIN89HN210210", "IRVIN89HN210"])
def test_both_code_styles_match_a_card(screen, typed):
    """Ô tìm kiếm nhận cả mã check-in lẫn mã nhập kho, nên cả hai phải khớp được."""
    wanted = normalize_match_text(typed)
    labels = nodes_with_id(screen, ib.RID_SESSION_CODE) + nodes_with_id(screen, ib.RID_ADD_INFO)
    matching = [n for n in labels if wanted in normalize_match_text(n.get("text", ""))]

    assert matching, f"'{typed}' không khớp nhãn nào trên màn hình thật"


def test_unfiltered_list_is_refused_rather_than_guessed(screen):
    """
    Màn hình chưa lọc có 6 nút - đúng tình huống bot phải từ chối bấm. Bấm bừa
    thẻ đầu tiên là mở nhầm phiếu của người khác.
    """
    assert len(nodes_with_id(screen, ib.RID_START)) != 1


def test_create_session_dialog_has_the_buttons_the_runner_looks_for(confirm):
    assert first_with_id(confirm, ib.RID_CONFIRM_ACCEPT)
    assert first_with_id(confirm, ib.RID_CONFIRM_CANCEL)
    assert "chưa có tạo phiên check-in" in first_with_id(confirm, ib.RID_CONFIRM_TITLE)["text"]


def test_create_session_dialog_is_not_a_standard_android_alert(confirm):
    """
    Hộp thoại tự vẽ: không có `button1`/`alertTitle` như AlertDialog chuẩn. Đó
    là lý do phải khớp `btnAccept` riêng thay vì dùng lại đường xử lý của luồng
    pick.
    """
    assert not first_with_id(confirm, "button1")
    assert not first_with_id(confirm, "alertTitle")


def test_the_dialog_is_not_mistaken_for_the_checkin_list(confirm):
    """Dump chỉ có cửa sổ hộp thoại - không kèm danh sách phía sau."""
    assert not first_with_id(confirm, ib.RID_START)
    assert not first_with_id(confirm, ib.RID_LIST)


def test_the_card_has_no_quantity_field(screen):
    """
    Vì sao bước đối chiếu số lượng phải lùi tới màn hình quét: thẻ check-in
    không có ô số lượng như thẻ picking (`tvProductNumber`).
    """
    assert not first_with_id(screen, "tvProductNumber")
    assert not first_with_id(screen, "tvCounter")
