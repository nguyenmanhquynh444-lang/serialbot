"""
preview_dialog.py
Preview & validate the serial list loaded from Excel before running:
flags duplicates, lets the user uncheck rows to skip them.
"""
from collections import Counter

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class PreviewDialog(QDialog):
    def __init__(self, serial_items: list, parent=None):
        """serial_items: list of SerialItem(row, value)."""
        super().__init__(parent)
        self.setWindowTitle("Preview & Validate")
        self.resize(560, 560)
        self.serial_items = serial_items

        counts = Counter(item.value for item in serial_items)
        self.duplicate_rows = {item.row for item in serial_items if counts[item.value] > 1}

        layout = QVBoxLayout(self)

        summary = QLabel(
            f"{len(serial_items)} serial(s) loaded - "
            f"{len(self.duplicate_rows)} duplicate value(s) flagged in red."
        )
        layout.addWidget(summary)

        self.table = QTableWidget(len(serial_items), 3)
        self.table.setHorizontalHeaderLabels(["Run", "Excel Row", "Serial"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        for i, item in enumerate(serial_items):
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check_item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(i, 0, check_item)

            row_item = QTableWidgetItem(str(item.row))
            serial_item = QTableWidgetItem(item.value)
            if item.row in self.duplicate_rows:
                row_item.setForeground(Qt.GlobalColor.red)
                serial_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(i, 1, row_item)
            self.table.setItem(i, 2, serial_item)

        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(lambda: self._set_all_checked(False))
        skip_dup_btn = QPushButton("Uncheck Duplicates")
        skip_dup_btn.clicked.connect(self._uncheck_duplicates)
        btn_row.addWidget(select_all_btn)
        btn_row.addWidget(deselect_all_btn)
        btn_row.addWidget(skip_dup_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setCheckState(state)

    def _uncheck_duplicates(self):
        for i, item in enumerate(self.serial_items):
            if item.row in self.duplicate_rows:
                self.table.item(i, 0).setCheckState(Qt.CheckState.Unchecked)

    def selected_items(self) -> list:
        selected = []
        for i, item in enumerate(self.serial_items):
            if self.table.item(i, 0).checkState() == Qt.CheckState.Checked:
                selected.append(item)
        return selected


class BillPreviewDialog(QDialog):
    """
    Xem trước cho chế độ xuất kho: một dòng là một vận đơn, không phải một serial.

    Đây là chỗ duy nhất người dùng nhìn thấy dữ liệu bẩn trước khi bot động vào
    kho thật, nên cảnh báo phải nằm ngay trên đầu chứ không giấu trong log.
    """

    def __init__(
        self,
        groups: list[dict],
        warnings: list[str] | None = None,
        parent=None,
        unit: str = "vận đơn",
        code_header: str = "",
        ref_header: str = "MVĐ",
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Xem trước - chạy theo {unit}")
        self.resize(680, 560)
        self.groups = groups

        layout = QVBoxLayout(self)

        total_serials = sum(len(g["rows"]) for g in groups)
        layout.addWidget(
            QLabel(f"{len(groups)} {unit}, tổng {total_serials} serial.")
        )

        if warnings:
            box = QLabel(
                "⚠ " + f"{len(warnings)} cảnh báo:\n" + "\n".join(f"• {w}" for w in warnings)
            )
            box.setWordWrap(True)
            box.setStyleSheet(
                "background:#4A3E14; color:#F1C40F; padding:8px; border-radius:4px;"
            )
            layout.addWidget(box)

        # Cột mã tham chiếu (MVĐ) chỉ hiện khi file có khai nó - thêm một cột
        # rỗng vào bảng xem trước chỉ làm loãng chỗ người dùng đang soi dữ liệu.
        self.has_ref = any(g.get("ref") for g in groups)
        if not code_header:
            code_header = "Mã check-in" if "check-in" in unit else f"Mã {unit}"

        headers = ["Chạy", code_header]
        if self.has_ref:
            headers.append(ref_header)
        headers += ["Số serial", "Dòng Excel"]

        self.table = QTableWidget(len(groups), len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        for i, group in enumerate(groups):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(i, 0, check)
            values = [group["bill"]]
            if self.has_ref:
                values.append(group.get("ref", ""))
            values += [str(len(group["rows"])), str(group["first_row"])]
            for offset, value in enumerate(values, start=1):
                self.table.setItem(i, offset, QTableWidgetItem(value))

        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        select_all = QPushButton("Chọn tất cả")
        select_all.clicked.connect(lambda: self._set_all_checked(True))
        deselect_all = QPushButton("Bỏ chọn tất cả")
        deselect_all.clicked.connect(lambda: self._set_all_checked(False))
        btn_row.addWidget(select_all)
        btn_row.addWidget(deselect_all)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all_checked(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setCheckState(state)

    def selected_groups(self) -> list[dict]:
        return [
            group for i, group in enumerate(self.groups)
            if self.table.item(i, 0).checkState() == Qt.CheckState.Checked
        ]
