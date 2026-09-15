"""
ui_inspector.py
Two helpers that make recipe steps writable without guesswork:

- UiInspectorDialog lists everything on the LDPlayer screen so a step can be
  built from a real resource-id instead of a guessed one.
- ScreenPickerDialog shows a live screenshot and turns a click into device
  coordinates for a tap step.

Both read the device over ADB, so LDPlayer does not need window focus.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from screen_reader import ScreenReader, list_nodes, parse_bounds


class UiInspectorDialog(QDialog):
    """Pick an on-screen element and get back a ready-made step parameter set."""

    def __init__(self, adb_client, parent=None):
        super().__init__(parent)
        self.setWindowTitle("UI Inspector - chọn phần tử trên màn hình")
        self.resize(860, 560)
        self.screen = ScreenReader(adb_client)
        self.rows: list[dict] = []
        self.selected: dict | None = None

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.refresh_btn = QPushButton("Đọc lại màn hình")
        self.refresh_btn.clicked.connect(self.refresh)
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Lọc theo text hoặc resource id...")
        self.filter_input.textChanged.connect(self._apply_filter)
        self.clickable_only = QCheckBox("Chỉ phần tử bấm được")
        self.clickable_only.toggled.connect(self._apply_filter)
        top.addWidget(self.refresh_btn)
        top.addWidget(self.filter_input, stretch=1)
        top.addWidget(self.clickable_only)
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Text", "Resource id", "Mô tả", "Loại", "Vùng"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.accept)
        layout.addWidget(self.table)

        self.hint = QLabel("Nhấn 'Đọc lại màn hình' để nạp danh sách phần tử.")
        self.hint.setStyleSheet("color: #8a8fa3;")
        layout.addWidget(self.hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def refresh(self):
        xml = self.screen.dump_xml()
        if not xml:
            QMessageBox.warning(
                self,
                "Không đọc được màn hình",
                "Không lấy được nội dung màn hình qua ADB.\n"
                "Kiểm tra LDPlayer đã bật và đúng tên instance chưa.",
            )
            return
        self.rows = list_nodes(xml)
        self._apply_filter()
        self.hint.setText(f"Tìm thấy {len(self.rows)} phần tử. Nhấp đúp một dòng để chọn.")

    def _apply_filter(self):
        needle = self.filter_input.text().strip().lower()
        shown = [
            r for r in self.rows
            if (not self.clickable_only.isChecked() or r["clickable"])
            and (
                not needle
                or needle in r["text"].lower()
                or needle in r["resource_id"].lower()
                or needle in r["content_desc"].lower()
            )
        ]

        self.table.setRowCount(len(shown))
        for i, r in enumerate(shown):
            for col, key in enumerate(("text", "resource_id", "content_desc", "class", "bounds")):
                self.table.setItem(i, col, QTableWidgetItem(str(r[key])))
            self.table.item(i, 0).setData(Qt.ItemDataRole.UserRole, r)

    def accept(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Chưa chọn", "Hãy chọn một dòng trong bảng.")
            return
        self.selected = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        super().accept()

    def step_params(self) -> dict:
        """Prefer resource-id: it survives text and language changes."""
        if not self.selected:
            return {}
        resource_id = self.selected.get("resource_id", "")
        if resource_id:
            return {"resource_id": resource_id.rsplit("/", 1)[-1], "text": ""}
        return {"resource_id": "", "text": self.selected.get("text", "")}

    def tap_coordinates(self) -> tuple[int, int] | None:
        if not self.selected:
            return None
        parsed = parse_bounds(self.selected.get("bounds", ""))
        if not parsed:
            return None
        x1, y1, x2, y2 = parsed
        return (x1 + x2) // 2, (y1 + y2) // 2


class ScreenPickerDialog(QDialog):
    """Click a screenshot to pick device coordinates for a tap step."""

    def __init__(self, adb_client, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Chọn tọa độ - nhấp vào ảnh màn hình")
        self.screen = ScreenReader(adb_client)
        self.device_size: tuple[int, int] | None = None
        self.picked: tuple[int, int] | None = None

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        refresh_btn = QPushButton("Chụp lại")
        refresh_btn.clicked.connect(self.refresh)
        self.coord_label = QLabel("Chưa chọn điểm nào")
        top.addWidget(refresh_btn)
        top.addWidget(self.coord_label, stretch=1)
        layout.addLayout(top)

        self.image_label = ClickableImage()
        self.image_label.clicked.connect(self._on_image_clicked)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(360, 480)
        layout.addWidget(self.image_label, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.refresh()

    def refresh(self):
        data = self.screen.screenshot_png()
        if not data:
            QMessageBox.warning(
                self,
                "Không chụp được màn hình",
                "Không lấy được ảnh màn hình qua ADB. Kiểm tra LDPlayer đã bật chưa.",
            )
            return

        pixmap = QPixmap()
        if not pixmap.loadFromData(data, "PNG"):
            QMessageBox.warning(self, "Ảnh lỗi", "Không đọc được dữ liệu ảnh trả về.")
            return

        self.device_size = (pixmap.width(), pixmap.height())
        scaled = pixmap.scaled(
            420, 700,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.resize(max(self.width(), scaled.width() + 60), scaled.height() + 140)

    def _on_image_clicked(self, x: int, y: int):
        pixmap = self.image_label.pixmap()
        if pixmap is None or not self.device_size:
            return

        # The label centres the pixmap, so strip the letterbox before scaling up.
        offset_x = (self.image_label.width() - pixmap.width()) // 2
        offset_y = (self.image_label.height() - pixmap.height()) // 2
        px, py = x - offset_x, y - offset_y
        if not (0 <= px < pixmap.width() and 0 <= py < pixmap.height()):
            return

        dev_w, dev_h = self.device_size
        self.picked = (
            int(px * dev_w / pixmap.width()),
            int(py * dev_h / pixmap.height()),
        )
        self.coord_label.setText(
            f"Tọa độ thiết bị: x={self.picked[0]}, y={self.picked[1]}  "
            f"(màn hình {dev_w}x{dev_h})"
        )


class ClickableImage(QLabel):
    clicked = pyqtSignal(int, int)

    def mousePressEvent(self, event):
        position = event.position()
        self.clicked.emit(int(position.x()), int(position.y()))
