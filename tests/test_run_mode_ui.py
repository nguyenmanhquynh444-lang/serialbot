"""
Ô chọn kiểu chạy trên trang Cấu hình.

Hai chế độ dùng hai bộ tham số khác hẳn nhau. Để lẫn thì người dùng tưởng đã
cấu hình xong trong khi ô đó chẳng có tác dụng gì - nguy hiểm nhất là tưởng
"Từ khóa lỗi" đang bảo vệ mình trong lúc chạy xuất kho.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from bot_gui import MODE_INBOUND, MODE_PICK, MODE_SERIAL, BotGUI


@pytest.fixture
def gui(qapp, tmp_path, monkeypatch):
    import bot_gui

    # Ảnh chụp màn hình đổ vào tmp_path; QSettings đã được conftest tách riêng.
    monkeypatch.setattr(bot_gui, "SCREENSHOT_DIR", str(tmp_path))
    window = BotGUI()
    yield window
    window.close()


def set_mode(window, mode):
    window.run_mode_combo.setCurrentIndex(window.run_mode_combo.findData(mode))


def test_serial_mode_is_the_default(gui):
    set_mode(gui, MODE_SERIAL)
    assert gui.run_mode() == MODE_SERIAL


def test_pick_mode_disables_fields_it_never_uses(gui):
    """Khóa chứ không ẩn: người dùng thấy được vì sao không sửa được."""
    set_mode(gui, MODE_PICK)

    for widget in (
        gui.error_keywords_input,
        gui.not_found_keywords_input,
        gui.success_keywords_input,
        gui.recipe_combo,
        gui.enter_delay_input,
        gui.background_check,
        gui.dry_run_check,
    ):
        assert not widget.isEnabled()

    set_mode(gui, MODE_SERIAL)
    for widget in (gui.error_keywords_input, gui.recipe_combo, gui.dry_run_check):
        assert widget.isEnabled()


def test_pick_fields_have_the_defaults_the_user_asked_for(gui):
    set_mode(gui, MODE_PICK)

    assert gui.bill_column_input.text() == "A"     # mã OR
    assert gui.ref_column_input.text() == "B"      # mã vận đơn đi kèm
    assert gui.tote_input.text() == "T001"
    assert gui.bin_input.text() == "PYTES"
    assert gui.check_count_check.isChecked()   # đối chiếu số lượng bật sẵn


def test_mode_and_pick_fields_survive_a_profile_round_trip(gui):
    set_mode(gui, MODE_PICK)
    gui.bill_column_input.setText("C")
    gui.ref_column_input.setText("D")
    gui.tote_input.setText("T009")
    gui.bin_input.setText("PYTKHO2")
    gui.check_count_check.setChecked(False)

    values = gui._collect_profile_values()
    other = BotGUI()
    try:
        other._apply_profile_values(values)

        assert other.run_mode() == MODE_PICK
        assert other.bill_column_input.text() == "C"
        assert other.ref_column_input.text() == "D"
        assert other.tote_input.text() == "T009"
        assert other.bin_input.text() == "PYTKHO2"
        assert not other.check_count_check.isChecked()
        # Nạp profile phải kéo theo cả trạng thái khóa ô.
        assert not other.error_keywords_input.isEnabled()
    finally:
        other.close()


def test_an_empty_bin_survives_a_profile_round_trip(gui):
    """
    Ô bin trống là một lựa chọn có nghĩa ("đi theo vị trí app chỉ"), khác hẳn
    ô chưa từng được lưu - nạp lại mà rơi về PYTES là đổi hành vi sau lưng.
    """
    set_mode(gui, MODE_PICK)
    gui.bin_input.setText("")

    other = BotGUI()
    try:
        other._apply_profile_values(gui._collect_profile_values())
        assert other.bin_input.text() == ""
    finally:
        other.close()


def test_pick_config_is_frozen_while_a_run_is_in_progress(gui, tmp_path, monkeypatch):
    """
    Tote/bin được chốt lúc bấm Start. Để ô sửa được trong lúc chạy là mời người
    dùng đổi mã rồi tưởng bot đã đi theo mã mới.
    """
    import bot_gui as module

    set_mode(gui, MODE_PICK)
    monkeypatch.setattr(module.PickWorker, "start", lambda self: None)
    gui.excel_path = str(tmp_path / "nguon.xlsx")

    gui._launch_pick_run([{"bill": "OR1", "ref": "", "first_row": 2,
                           "rows": [{"row": 2, "value": "S1"}]}])
    try:
        assert not gui.pick_box.isEnabled()
    finally:
        gui.workers = []
        gui._on_pick_finished(module.PickWorker([], "LDPlayer"))

    assert gui.pick_box.isEnabled()
    assert gui.tote_input.isEnabled()      # khóa cả khung không nuốt trạng thái ô


def test_inbound_mode_relabels_the_shared_column_box(gui):
    """Cùng một ô, hai nghĩa - gọi sai tên thì người dùng điền nhầm cột."""
    set_mode(gui, MODE_INBOUND)
    assert gui.bill_column_label.text() == "Cột mã check-in"
    assert "check-in" in gui.pick_box.title()

    set_mode(gui, MODE_PICK)
    assert gui.bill_column_label.text() == "Cột mã OR"


def test_tote_and_bin_only_apply_to_the_pick_flow(gui):
    """Màn hình nhận hàng không hỏi tote/bin - để bật là mời người dùng điền thừa."""
    set_mode(gui, MODE_INBOUND)
    assert not gui.tote_input.isEnabled()
    assert not gui.bin_input.isEnabled()

    set_mode(gui, MODE_PICK)
    assert gui.tote_input.isEnabled()
    assert gui.bin_input.isEnabled()


def test_create_session_option_is_off_by_default_and_pick_only(gui):
    """Tạo phiên check-in là giao dịch thật - không được bật sẵn."""
    assert not gui.create_session_check.isChecked()

    set_mode(gui, MODE_INBOUND)
    assert gui.create_session_check.isEnabled()

    set_mode(gui, MODE_PICK)
    assert not gui.create_session_check.isEnabled()


def test_locking_a_field_does_not_eat_its_original_tooltip(gui):
    """Đè tooltip 'không dùng ở chế độ này' rồi không trả lại là mất lời giải thích."""
    original = gui.recipe_combo.toolTip()
    assert original                                  # ô này vốn có tooltip riêng

    set_mode(gui, MODE_PICK)
    assert gui.recipe_combo.toolTip() != original

    set_mode(gui, MODE_SERIAL)
    assert gui.recipe_combo.toolTip() == original


def test_inbound_mode_survives_a_profile_round_trip(gui):
    set_mode(gui, MODE_INBOUND)
    gui.bill_column_input.setText("A")

    values = gui._collect_profile_values()
    other = BotGUI()
    try:
        other._apply_profile_values(values)
        assert other.run_mode() == MODE_INBOUND
        assert other.bill_column_label.text() == "Cột mã check-in"
        assert not other.tote_input.isEnabled()
    finally:
        other.close()


def make_bill_file(tmp_path, headers, row=None):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    ws.append(row or ["195PIVGR27072026", "E52771260430D01999"])
    path = tmp_path / "bills.xlsx"
    wb.save(path)
    return str(path)


def test_opening_a_bill_file_fills_in_both_columns(gui, tmp_path):
    """Mở file là hai ô cột tự điền - đỡ một bước gõ tay dễ nhầm."""
    gui._load_excel_path(make_bill_file(tmp_path, ["Ma van don", "Serial"]))

    assert gui.bill_column_input.text() == "A"
    assert gui.column_input.text() == "B"


def test_opening_the_three_column_template_splits_or_from_mvd(gui, tmp_path):
    """
    Template xuất kho: OR / MVĐ / Seri. Mã bot gõ vào app là mã OR, còn MVĐ chỉ
    đi kèm - lẫn hai cột này là bot đi tra mã không có trong ô tìm kiếm.
    """
    gui._load_excel_path(make_bill_file(
        tmp_path,
        ["OR", "MVĐ", "Seri"],
        ["ORVINEKGK4T1560", "581PIPTE03082026", "E52771260715N01954"],
    ))

    assert gui.bill_column_input.text() == "A"
    assert gui.ref_column_input.text() == "B"
    assert gui.column_input.text() == "C"


def test_opening_an_old_two_column_file_clears_the_mvd_column(gui, tmp_path):
    """File đời cũ không có cột OR - mã vận đơn lùi về làm mã tìm phiên, và ô
    MVĐ phải trống chứ không trỏ bừa vào cột serial."""
    gui.ref_column_input.setText("B")
    gui._load_excel_path(make_bill_file(tmp_path, ["Ma van don", "Serial"]))

    assert gui.bill_column_input.text() == "A"
    assert gui.ref_column_input.text() == ""


def test_bill_column_is_never_guessed_onto_the_serial_column(gui, tmp_path):
    """Tiêu đề khớp cả hai bộ từ khóa thì giữ nguyên ô cũ, đừng đặt trùng cột."""
    gui.bill_column_input.setText("D")
    gui._load_excel_path(make_bill_file(tmp_path, ["Bill serial", "Ghi chu"]))

    assert gui.column_input.text() == "A"
    assert gui.bill_column_input.text() == "D"     # không bị kéo thành trùng cột A


def test_old_profile_without_the_new_keys_falls_back_to_serial_mode(gui):
    """Profile lưu từ bản trước không có khóa run_mode - không được vỡ."""
    gui._apply_profile_values({"column": "H", "start_row": 2})

    assert gui.run_mode() == MODE_SERIAL
    assert gui.bill_column_input.text() == "A"
    assert gui.error_keywords_input.isEnabled()


# --- thời gian ước tính trên thanh tiến độ ------------------------------------

def test_format_duration_rounds_to_one_unit():
    """Số ước tính mà hiện '11 phút 47 giây' chỉ tạo cảm giác chính xác giả."""
    from bot_gui import _format_duration

    assert _format_duration(0) == "0 giây"
    assert _format_duration(45) == "45 giây"
    assert _format_duration(59) == "59 giây"
    assert _format_duration(90) == "2 phút"
    assert _format_duration(12 * 60) == "12 phút"
    assert _format_duration(65 * 60) == "1h05"
    assert _format_duration(150 * 60) == "2h30"


def test_eta_is_based_on_the_average_pace_of_the_whole_run(gui, monkeypatch):
    """
    Lấy trung bình cả lượt chứ không lấy mã gần nhất: mã không tìm thấy ~3s còn
    mã nhiều serial cả phút, nhìn con số nhảy loạn thì không sắp việc được.
    """
    import bot_gui

    gui._run_start_monotonic = 1000.0
    monkeypatch.setattr(bot_gui.time, "monotonic", lambda: 1000.0 + 60.0)

    # 20/100 mã trong 60s -> còn 80 mã -> 240s -> "4 phút"
    assert "4 phút" in gui._pick_eta_text(20, 100)


def test_eta_is_hidden_before_there_is_anything_to_measure(gui):
    """Chưa xong mã nào thì mọi con số đưa ra đều là bịa."""
    assert gui._pick_eta_text(0, 100) == ""
    assert gui._pick_eta_text(100, 100) == ""       # xong rồi, không còn gì để chờ


# --- đếm ngược trước khi chạy -------------------------------------------------

def test_countdown_hands_the_final_text_back_to_the_progress_bar(gui):
    """
    Đếm xong phải trả lại đúng dòng của chế độ đang chạy. Trước đây luôn lấy số
    ở khung STATS (đếm theo serial), nên chế độ xuất kho hiện '0 / 274' thay vì
    '0 / 274 mã OR' cho tới khi xong mã đầu tiên - hơn hai chục giây sai đơn vị.
    """
    calls = []
    gui._start_countdown(lambda: calls.append("chay"), "Bắt đầu sau {}s...",
                         final_format="0 / 5 mã OR")

    assert "Bắt đầu sau 3s" in gui.progress_bar.format()
    assert calls == []                      # chưa chạy khi chưa đếm xong

    for _ in range(3):
        gui._on_countdown_tick(lambda: calls.append("chay"), "Bắt đầu sau {}s...")

    assert calls == ["chay"]                # chạy đúng một lần, sau khi đếm xong
    assert gui.progress_bar.format() == "0 / 5 mã OR"
    assert gui.pause_btn.isEnabled()        # mở lại nút Tạm dừng
    assert gui.stop_btn.isEnabled()


def test_countdown_without_a_final_format_falls_back_to_the_stats_number(gui):
    """Luồng cũ không truyền gì thì vẫn phải giữ nguyên hành vi trước đây."""
    gui.stat_total_lbl.setText("0 / 42")
    gui._start_countdown(lambda: None, "Starting in {}s...")
    for _ in range(3):
        gui._on_countdown_tick(lambda: None, "Starting in {}s...")

    assert gui.progress_bar.format() == "0 / 42"
