"""
action_editor.py
Editor for automation recipes: a step list on the left, the selected step's
parameters on the right.

The parameter form is generated from the schema in actions.STEP_TYPES, so new
step types show up here without any change to this file.
"""
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from actions import (
    ON_FAIL_LABELS,
    STEP_TYPES,
    Step,
    make_step,
    validate_steps,
)
from recipes import Recipe, delete_recipe, list_recipes, load_recipe, save_recipe
from ui_inspector import ScreenPickerDialog, UiInspectorDialog

logger = logging.getLogger(__name__)


class ActionEditor(QWidget):
    """Embedded as a page in the main window's nav rail."""

    def __init__(self, adb_client_factory, test_row_provider=None, parent=None):
        """
        adb_client_factory - callable returning an AdbClient for the chosen instance
        test_row_provider  - callable returning a RowContext for 'run one row', or None
        """
        super().__init__(parent)
        self.adb_client_factory = adb_client_factory
        self.test_row_provider = test_row_provider
        self.recipe = Recipe(name="Kịch bản mới", steps=[])
        self.field_widgets: dict = {}
        self._loading = False

        self._build_ui()
        self._reload_recipe_list()

    # ---------------------------------------------------------------- ui

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        root.addLayout(self._build_recipe_bar())

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_step_list_panel(), stretch=3)
        body.addWidget(self._build_param_panel(), stretch=4)
        root.addLayout(body, stretch=1)

        self.problem_label = QLabel("")
        self.problem_label.setWordWrap(True)
        self.problem_label.setStyleSheet("color: #f1c40f;")
        root.addWidget(self.problem_label)

    def _build_recipe_bar(self):
        row = QHBoxLayout()
        row.addWidget(QLabel("Kịch bản"))

        self.recipe_combo = QComboBox()
        self.recipe_combo.setMinimumWidth(220)
        row.addWidget(self.recipe_combo, stretch=1)

        load_btn = QPushButton("Nạp")
        load_btn.clicked.connect(self._on_load)
        save_btn = QPushButton("Lưu")
        save_btn.clicked.connect(self._on_save)
        save_as_btn = QPushButton("Lưu thành...")
        save_as_btn.clicked.connect(self._on_save_as)
        del_btn = QPushButton("Xóa")
        del_btn.clicked.connect(self._on_delete)
        for b in (load_btn, save_btn, save_as_btn, del_btn):
            row.addWidget(b)
        return row

    def _build_step_list_panel(self):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)

        title = QLabel("CÁC BƯỚC")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.step_list = QListWidget()
        self.step_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.step_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.step_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.step_list.currentRowChanged.connect(self._on_step_selected)
        layout.addWidget(self.step_list, stretch=1)

        add_row = QHBoxLayout()
        self.add_type_combo = QComboBox()
        for name, spec in STEP_TYPES.items():
            self.add_type_combo.addItem(spec.label, name)
        add_btn = QPushButton("Thêm")
        add_btn.clicked.connect(self._on_add_step)
        add_row.addWidget(self.add_type_combo, stretch=1)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        tool_row = QHBoxLayout()
        for text, slot in (
            ("Lên", self._on_move_up),
            ("Xuống", self._on_move_down),
            ("Nhân đôi", self._on_duplicate),
            ("Xóa bước", self._on_delete_step),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            tool_row.addWidget(btn)
        layout.addLayout(tool_row)

        return frame

    def _build_param_panel(self):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)

        title = QLabel("THAM SỐ BƯỚC")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.step_desc = QLabel("Chọn một bước ở danh sách bên trái.")
        self.step_desc.setWordWrap(True)
        self.step_desc.setStyleSheet("color: #8a8fa3;")
        layout.addWidget(self.step_desc)

        self.form_host = QWidget()
        self.form_layout = QFormLayout(self.form_host)
        self.form_layout.setContentsMargins(0, 8, 0, 8)
        layout.addWidget(self.form_host)

        self.enabled_check = QCheckBox("Bật bước này")
        self.enabled_check.setChecked(True)
        self.enabled_check.toggled.connect(self._on_enabled_toggled)
        layout.addWidget(self.enabled_check)

        fail_row = QHBoxLayout()
        fail_row.addWidget(QLabel("Khi bước lỗi"))
        self.on_fail_combo = QComboBox()
        for key, label in ON_FAIL_LABELS.items():
            self.on_fail_combo.addItem(label, key)
        self.on_fail_combo.currentIndexChanged.connect(self._on_fail_changed)
        fail_row.addWidget(self.on_fail_combo, stretch=1)
        layout.addLayout(fail_row)

        helper_box = QGroupBox("Trợ lý")
        helper_layout = QHBoxLayout(helper_box)
        inspect_btn = QPushButton("UI Inspector")
        inspect_btn.setToolTip("Đọc màn hình LDPlayer và chọn phần tử để điền tham số")
        inspect_btn.clicked.connect(self._on_inspect)
        pick_btn = QPushButton("Chọn tọa độ")
        pick_btn.setToolTip("Chụp màn hình và nhấp để lấy tọa độ")
        pick_btn.clicked.connect(self._on_pick_coords)
        helper_layout.addWidget(inspect_btn)
        helper_layout.addWidget(pick_btn)
        layout.addWidget(helper_box)

        layout.addStretch(1)

        hint = QLabel(
            "Biến dùng được: {serial}, {row}, {cell:B}, {var:ten}, {date}, {time}"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8a8fa3; font-size: 11px;")
        layout.addWidget(hint)

        return frame

    # ---------------------------------------------------------------- state

    def current_step(self) -> Step | None:
        index = self.step_list.currentRow()
        if 0 <= index < len(self.recipe.steps):
            return self.recipe.steps[index]
        return None

    def steps(self) -> list[Step]:
        return self.recipe.steps

    def _refresh_step_list(self, keep_index: int | None = None):
        index = self.step_list.currentRow() if keep_index is None else keep_index
        self._loading = True
        self.step_list.clear()
        for i, step in enumerate(self.recipe.steps, start=1):
            item = QListWidgetItem(f"{i}. {step.summary()}")
            if not step.enabled:
                item.setForeground(Qt.GlobalColor.gray)
            self.step_list.addItem(item)
        self._loading = False

        if self.recipe.steps:
            self.step_list.setCurrentRow(min(max(index, 0), len(self.recipe.steps) - 1))
        else:
            self._clear_form()
        self._revalidate()

    def _revalidate(self):
        problems = validate_steps(self.recipe.steps)
        self.problem_label.setText(" · ".join(problems) if problems else "")

    def _clear_form(self):
        while self.form_layout.count():
            child = self.form_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.step_desc.setText("Chọn một bước ở danh sách bên trái.")

    def _on_step_selected(self, index: int):
        if self._loading:
            return
        step = self.current_step()
        self._clear_form()
        if not step:
            return

        spec = STEP_TYPES.get(step.type)
        if not spec:
            self.step_desc.setText(f"Bước không rõ: {step.type}")
            return

        note = ""
        if spec.adb_only:
            note = "\n(Chỉ chạy được qua ADB - máy ảo Android)"
        elif spec.browser_only:
            note = "\n(Chỉ chạy được khi bot nối với trình duyệt)"
        self.step_desc.setText(f"{spec.label} — {spec.description}{note}")
        self.enabled_check.setChecked(step.enabled)
        fail_index = self.on_fail_combo.findData(step.on_fail)
        if fail_index >= 0:
            self.on_fail_combo.setCurrentIndex(fail_index)

        self.field_widgets = {}
        for param in spec.params:
            widget = self._make_widget(param, step.params.get(param.name, param.default))
            if param.hint:
                widget.setToolTip(param.hint)
            self.form_layout.addRow(param.label, widget)
            self.field_widgets[param.name] = widget

    def _make_widget(self, param, value):
        if param.kind == "int":
            w = QSpinBox()
            w.setRange(-100000, 100000)
            w.setValue(int(value or 0))
            w.valueChanged.connect(lambda v, n=param.name: self._set_param(n, v))
            return w
        if param.kind == "float":
            w = QDoubleSpinBox()
            w.setRange(0.0, 3600.0)
            w.setSingleStep(0.1)
            w.setDecimals(2)
            w.setValue(float(value or 0))
            w.valueChanged.connect(lambda v, n=param.name: self._set_param(n, v))
            return w
        if param.kind == "bool":
            w = QCheckBox()
            w.setChecked(_as_bool(value))
            w.toggled.connect(lambda v, n=param.name: self._set_param(n, v))
            return w
        if param.kind == "choice":
            w = QComboBox()
            w.addItems(list(param.choices))
            if value in param.choices:
                w.setCurrentText(str(value))
            w.currentTextChanged.connect(lambda v, n=param.name: self._set_param(n, v))
            return w
        w = QLineEdit(str(value or ""))
        w.textChanged.connect(lambda v, n=param.name: self._set_param(n, v))
        return w

    def _set_param(self, name: str, value):
        step = self.current_step()
        if step is None:
            return
        step.params[name] = value
        index = self.step_list.currentRow()
        if 0 <= index < self.step_list.count():
            self.step_list.item(index).setText(f"{index + 1}. {step.summary()}")
        self._revalidate()

    def _on_enabled_toggled(self, checked: bool):
        step = self.current_step()
        if step is None:
            return
        step.enabled = checked
        self._refresh_step_list()

    def _on_fail_changed(self):
        step = self.current_step()
        if step is None:
            return
        step.on_fail = self.on_fail_combo.currentData()

    # ---------------------------------------------------------------- step ops

    def _on_add_step(self):
        step_type = self.add_type_combo.currentData()
        self.recipe.steps.append(make_step(step_type))
        self._refresh_step_list(keep_index=len(self.recipe.steps) - 1)

    def _on_delete_step(self):
        index = self.step_list.currentRow()
        if 0 <= index < len(self.recipe.steps):
            self.recipe.steps.pop(index)
            self._refresh_step_list(keep_index=index - 1)

    def _on_duplicate(self):
        index = self.step_list.currentRow()
        step = self.current_step()
        if step:
            self.recipe.steps.insert(index + 1, Step.from_dict(step.to_dict()))
            self._refresh_step_list(keep_index=index + 1)

    def _on_move_up(self):
        index = self.step_list.currentRow()
        if index > 0:
            steps = self.recipe.steps
            steps[index - 1], steps[index] = steps[index], steps[index - 1]
            self._refresh_step_list(keep_index=index - 1)

    def _on_move_down(self):
        index = self.step_list.currentRow()
        if 0 <= index < len(self.recipe.steps) - 1:
            steps = self.recipe.steps
            steps[index + 1], steps[index] = steps[index], steps[index + 1]
            self._refresh_step_list(keep_index=index + 1)

    # ---------------------------------------------------------------- helpers

    def _on_inspect(self):
        step = self.current_step()
        if step is None:
            QMessageBox.information(self, "Chưa chọn bước", "Hãy chọn một bước trước.")
            return

        dialog = UiInspectorDialog(self.adb_client_factory(), self)
        dialog.refresh()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        params = dialog.step_params()
        applied = [name for name in ("resource_id", "text") if name in self.field_widgets]
        if not applied:
            QMessageBox.information(
                self,
                "Bước này không dùng phần tử",
                "Bước đang chọn không có tham số Text/Resource id để điền.",
            )
            return

        for name in applied:
            widget = self.field_widgets.get(name)
            if isinstance(widget, QLineEdit):
                widget.setText(str(params.get(name, "")))

    def _on_pick_coords(self):
        step = self.current_step()
        if step is None:
            QMessageBox.information(self, "Chưa chọn bước", "Hãy chọn một bước trước.")
            return
        if "x" not in self.field_widgets:
            QMessageBox.information(
                self,
                "Bước này không dùng tọa độ",
                "Chỉ bước 'Chạm tọa độ' và 'Vuốt' mới cần tọa độ.",
            )
            return

        dialog = ScreenPickerDialog(self.adb_client_factory(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.picked:
            return

        x, y = dialog.picked
        self.field_widgets["x"].setValue(x)
        self.field_widgets["y"].setValue(y)

    # ---------------------------------------------------------------- recipes

    def _reload_recipe_list(self):
        current = self.recipe_combo.currentText()
        self.recipe_combo.clear()
        self.recipe_combo.addItems(list_recipes())
        if current:
            self.recipe_combo.setCurrentText(current)

    def _on_load(self):
        name = self.recipe_combo.currentText().strip()
        if not name:
            return
        try:
            self.recipe = load_recipe(name)
        except Exception as e:
            QMessageBox.critical(self, "Không nạp được kịch bản", str(e))
            return
        self._refresh_step_list(keep_index=0)

    def _on_save(self):
        name = self.recipe_combo.currentText().strip()
        if not name:
            self._on_save_as()
            return
        self._save_as_name(name)

    def _on_save_as(self):
        name, ok = QInputDialog.getText(self, "Lưu kịch bản", "Tên file kịch bản:")
        if ok and name.strip():
            self._save_as_name(name.strip())

    def _save_as_name(self, name: str):
        self.recipe.name = name
        try:
            path = save_recipe(self.recipe, name)
        except Exception as e:
            QMessageBox.critical(self, "Không lưu được", str(e))
            return
        self._reload_recipe_list()
        self.recipe_combo.setCurrentText(name)
        QMessageBox.information(self, "Đã lưu", f"Kịch bản đã lưu:\n{path}")

    def _on_delete(self):
        name = self.recipe_combo.currentText().strip()
        if not name:
            return
        if QMessageBox.question(
            self, "Xóa kịch bản", f"Xóa kịch bản '{name}'?"
        ) != QMessageBox.StandardButton.Yes:
            return
        delete_recipe(name)
        self._reload_recipe_list()


def _as_bool(value, default: bool = True) -> bool:
    """Kịch bản lưu ra JSON nên giá trị bool có thể quay lại dưới dạng chuỗi."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "co", "có")
