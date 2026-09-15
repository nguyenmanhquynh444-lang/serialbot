"""
Màn hình xem trước theo vận đơn.

Đây là chốt chặn cuối trước khi bot động vào kho thật, nên hai thứ phải đúng:
bỏ tick là không chạy, và cảnh báo dữ liệu bẩn phải hiện ra chứ không nuốt mất.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from preview_dialog import BillPreviewDialog

GROUPS = [
    {"bill": "VD1", "first_row": 2, "rows": [{"row": 2, "value": "S1"}, {"row": 3, "value": "S2"}]},
    {"bill": "VD2", "first_row": 4, "rows": [{"row": 4, "value": "S3"}]},
]


def test_every_bill_starts_checked(qapp):
    dialog = BillPreviewDialog(GROUPS)
    assert [g["bill"] for g in dialog.selected_groups()] == ["VD1", "VD2"]


def test_unchecking_a_bill_drops_it_from_the_run(qapp):
    dialog = BillPreviewDialog(GROUPS)
    dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)

    selected = dialog.selected_groups()

    assert [g["bill"] for g in selected] == ["VD2"]
    assert selected[0]["rows"] == [{"row": 4, "value": "S3"}]


def test_table_shows_serial_count_and_starting_row(qapp):
    dialog = BillPreviewDialog(GROUPS)

    assert dialog.table.item(0, 1).text() == "VD1"
    assert dialog.table.item(0, 2).text() == "2"
    assert dialog.table.item(0, 3).text() == "2"
    assert dialog.table.item(1, 3).text() == "4"


def test_warnings_are_shown_not_swallowed(qapp):
    warnings = ["Dòng 5: serial 'S1' trùng với dòng 2."]
    dialog = BillPreviewDialog(GROUPS, warnings)

    texts = " ".join(label.text() for label in dialog.findChildren(QLabel))

    assert "trùng với dòng 2" in texts
    assert "1 cảnh báo" in texts


def test_deselect_all_then_nothing_runs(qapp):
    dialog = BillPreviewDialog(GROUPS)
    dialog._set_all_checked(False)
    assert dialog.selected_groups() == []
