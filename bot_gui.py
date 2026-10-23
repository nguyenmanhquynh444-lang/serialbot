"""
bot_gui.py
Main PyQt6 interface for the Serial Paste Bot.
"""
import logging
import os
import time
from datetime import datetime

from PyQt6.QtCore import QSettings, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from action_editor import ActionEditor
from actions import DEFAULT_NOT_FOUND_KEYWORDS, REASON_NOT_FOUND
from app_icons import app_icon, tray_icon
from automation_backend import AdbClient, adb_answers, list_ldplayer_instances
import browser_backend
from bot_worker import (
    DEFAULT_PRODUCT_CODE_DELAY_SECONDS,
    DEFAULT_RESPONSE_TIMEOUT_SECONDS,
    TARGET_ADB,
    TARGET_BROWSER,
    BotWorker,
    SerialItem,
)
from excel_reader import (
    ExcelReadError,
    get_sheet_names,
    guess_bill_column,
    guess_or_column,
    guess_serial_column,
    read_bill_groups,
    read_rows,
    read_serials,
)
from excel_writer import (
    find_formula_cells,
)
from inbound_runner import InboundConfig, InboundRunner
from pick_runner import DEFAULT_BIN_CODE, DEFAULT_TOTE, PickConfig, PickRunner
from pick_worker import PickWorker
from paths import logs_dir, screenshots_dir
from preview_dialog import BillPreviewDialog, PreviewDialog
from recipes import ensure_classic_on_disk, list_recipes, load_recipe
from session_manager import clear_session, load_session, save_session
from run_journal import RunJournal, fingerprint
from result_writer_worker import ResultWriterWorker, ReportWriterWorker
from verification import CONFIRMED, INFERRED, UNVERIFIED
from version import APP_DESCRIPTION, APP_NAME, APP_ORG, APP_VERSION

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = screenshots_dir()
SESSION_SAVE_EVERY = 10

# Ba kiểu chạy khác nhau về đơn vị công việc: một bên là từng serial rời, hai
# bên kia là cả một phiên trong app (phiên lấy hàng khi xuất kho, phiếu check-in
# khi nhập hàng). Hai chế độ phiên dùng chung y hệt kiểu file Excel.
MODE_SERIAL = "serial"
MODE_PICK = "pick"
MODE_INBOUND = "inbound"
SESSION_MODES = (MODE_PICK, MODE_INBOUND)

# Tên đơn vị công việc của từng chế độ phiên, dùng lại trong mọi thông báo để
# chúng gọi đúng thứ người dùng đang chạy.
UNIT_PICK = "mã OR"
UNIT_INBOUND = "phiếu check-in"

STATUS_COLOR = {
    "OK": "#2ecc71",
    "ERROR": "#ff5c72",
    "UNKNOWN": "#f1c40f",
}
STATUS_ICON = {
    "OK": "OK",
    "ERROR": "ERR",
    "UNKNOWN": "?",
}


def _format_duration(seconds: float) -> str:
    """
    Quãng thời gian gọn cho thanh tiến độ: '45 giây', '12 phút', '1h05'.

    Làm tròn tới đơn vị lớn nhất - đây là số ước tính, hiện '11 phút 47 giây'
    chỉ tạo cảm giác chính xác giả.
    """
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} giây"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} phút"
    return f"{minutes // 60}h{minutes % 60:02d}"


def split_serials(serials: list, n: int) -> list:
    """Split a list into n contiguous, near-equal chunks. Drops empty chunks."""
    if n <= 1 or not serials:
        return [serials] if serials else []
    k, m = divmod(len(serials), n)
    chunks = []
    start = 0
    for i in range(n):
        size = k + (1 if i < m else 0)
        if size:
            chunks.append(serials[start:start + size])
        start += size
    return chunks


STYLE_SHEET = """
QMainWindow {
    background-color: #1a1a2e;
}
QWidget {
    background-color: transparent;
    color: #e8e8f0;
    font-family: 'Segoe UI';
    font-size: 13px;
}
QFrame#card {
    background-color: #16213e;
    border-radius: 12px;
    border: 1px solid #26314f;
}
QLabel#sectionTitle {
    color: #00d2ff;
    font-size: 14px;
    font-weight: 600;
    padding-bottom: 4px;
}
QLabel#appTitle {
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
}
QLabel#appSubtitle {
    color: #8a8fa3;
    font-size: 12px;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #0f3460;
    border: 1px solid #26314f;
    border-radius: 6px;
    padding: 6px 10px;
    color: #ffffff;
    selection-background-color: #00d2ff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #00d2ff;
}
QComboBox QAbstractItemView {
    background-color: #0f3460;
    color: #ffffff;
    selection-background-color: #00d2ff;
    selection-color: #0a0a14;
}
QPushButton {
    background-color: #0f3460;
    border-radius: 8px;
    padding: 8px 16px;
    color: #ffffff;
    font-weight: 600;
    border: 1px solid #26314f;
}
QPushButton:hover {
    background-color: #16407a;
    border: 1px solid #00d2ff;
}
QPushButton:disabled {
    background-color: #1c1c30;
    color: #5a5f73;
    border: 1px solid #23233a;
}
QPushButton#browseBtn {
    background-color: #0f3460;
}
QPushButton#startBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00d2ff, stop:1 #7b2ff7);
    color: #0a0a14;
    font-weight: 700;
}
QPushButton#startBtn:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #33dcff, stop:1 #9153fa);
}
QPushButton#pauseBtn {
    background-color: #3a3a55;
}
QPushButton#stopBtn {
    background-color: #7a1f3d;
    border: 1px solid #a53356;
}
QPushButton#stopBtn:hover {
    background-color: #9c2850;
}
QPushButton#exportErrorsBtn {
    background-color: #4f2438;
    border: 1px solid #87405c;
}
QPushButton#exportErrorsBtn:hover {
    background-color: #65304a;
}
QPushButton#retryBtn {
    background-color: #3d3410;
    border: 1px solid #8a731f;
}
QPushButton#retryBtn:hover {
    background-color: #574a17;
}
QProgressBar {
    background-color: #0f3460;
    border-radius: 8px;
    height: 18px;
    text-align: center;
    color: #ffffff;
    border: 1px solid #26314f;
}
QProgressBar::chunk {
    border-radius: 8px;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00d2ff, stop:1 #7b2ff7);
}
QListWidget {
    background-color: #0f3460;
    border-radius: 8px;
    border: 1px solid #26314f;
    padding: 4px;
}
QListWidget::item {
    padding: 6px 4px;
    border-bottom: 1px solid #1c2b4a;
}
QLabel.statValue {
    font-size: 22px;
    font-weight: 700;
}
QLabel.statLabel {
    color: #8a8fa3;
    font-size: 11px;
}
QListWidget#navRail {
    background-color: #12182b;
    border: none;
    border-right: 1px solid #26314f;
    border-radius: 0;
    padding: 8px 0;
    outline: none;
}
QListWidget#navRail::item {
    padding: 12px 18px;
    border: none;
    border-left: 3px solid transparent;
    color: #8a8fa3;
    font-weight: 600;
}
QListWidget#navRail::item:selected {
    background-color: #16213e;
    border-left: 3px solid #00d2ff;
    color: #ffffff;
}
QListWidget#navRail::item:hover {
    color: #ffffff;
}
QMenuBar {
    background-color: #12182b;
    border-bottom: 1px solid #26314f;
}
QMenuBar::item {
    padding: 6px 12px;
    background: transparent;
}
QMenuBar::item:selected {
    background-color: #16407a;
}
QMenu {
    background-color: #16213e;
    border: 1px solid #26314f;
}
QMenu::item {
    padding: 6px 24px;
}
QMenu::item:selected {
    background-color: #16407a;
}
QToolBar {
    background-color: #12182b;
    border-bottom: 1px solid #26314f;
    padding: 4px 8px;
    spacing: 6px;
}
QToolBar QToolButton {
    padding: 6px 14px;
    border-radius: 6px;
    color: #e8e8f0;
    font-weight: 600;
}
QToolBar QToolButton:hover {
    background-color: #16407a;
}
QToolBar QToolButton:disabled {
    color: #5a5f73;
}
QStatusBar {
    background-color: #12182b;
    border-top: 1px solid #26314f;
    color: #8a8fa3;
    min-height: 26px;
    padding: 2px 10px;
}
QStatusBar::item {
    border: none;
}
QScrollArea {
    border: none;
    background-color: #1a1a2e;
}
QStackedWidget {
    background-color: #1a1a2e;
}
QWidget#page {
    background-color: #1a1a2e;
}
QScrollBar:vertical {
    background: #12182b;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2e3a5c;
    border-radius: 6px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #3d4a6b;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
"""


def card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    if title:
        lbl = QLabel(title)
        lbl.setObjectName("sectionTitle")
        layout.addWidget(lbl)
    return frame, layout


class ExcelLoaderWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self, excel_path, sheet_name, column, start_row, end_row,
        with_cells=False, parent=None,
    ):
        super().__init__(parent)
        self.excel_path = excel_path
        self.sheet_name = sheet_name
        self.column = column
        self.start_row = start_row
        self.end_row = end_row
        self.with_cells = with_cells

    def run(self):
        try:
            reader = read_rows if self.with_cells else read_serials
            raw = reader(
                self.excel_path,
                self.sheet_name,
                self.column,
                self.start_row,
                self.end_row or None,
            )
            self.finished.emit(raw)
        except Exception as e:
            self.error.emit(str(e))


class BotGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - LDPlayer Automation")
        self.setWindowIcon(app_icon())
        self.resize(1040, 800)
        self.setStyleSheet(STYLE_SHEET)
        self.setAcceptDrops(True)

        self.settings = QSettings(APP_ORG, "SerialPasteBot")

        self.workers: list[BotWorker] = []
        self.worker_progress_bars: dict[int, QProgressBar] = {}
        self.worker_stats: dict[int, tuple] = {}
        self.worker_finished_count = 0
        self.loader_thread: ExcelLoaderWorker | None = None
        self.excel_path: str | None = None
        self.serials_cache: list[SerialItem] = []
        self.all_records: list[dict] = []
        self.result_writer: ResultWriterWorker | None = None
        self.report_writer = None
        self.journal = None
        self.run_id = None
        self._stop_requested = False
        self._finishing = False
        self._resumed_records = []
        self._resumed_bills = []
        self._result_sheet = None
        self._run_finished_monotonic = None
        self._run_source_path = None
        self._run_sheet = None
        self.session_done_rows: set[int] = set()
        self.is_paused = False
        self.run_started_at: str | None = None
        self._run_start_monotonic: float | None = None
        self._countdown_final_format: str | None = None
        self._current_run_total = 0

        self._quitting = False
        self.active_recipe_steps: list = []

        # Chế độ chạy theo phiên: đơn vị công việc là cả phiên, không phải serial.
        self.pick_groups: list[dict] = []
        self.pick_bill_results: list[dict] = []

        ensure_classic_on_disk()

        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._build_status_bar()
        self._setup_hotkeys()
        self._setup_tray()
        self._restore_last_state()
        self._restore_geometry()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navRail")
        self.nav_list.setFixedWidth(150)
        for label in ("Chạy", "Cấu hình", "Kịch bản"):
            self.nav_list.addItem(QListWidgetItem(label))
        self.nav_list.setCurrentRow(0)
        root.addWidget(self.nav_list)

        self.action_editor = ActionEditor(self._make_adb_client)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_run_page())
        self.pages.addWidget(self._build_setup_page())
        self.pages.addWidget(self.action_editor)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        root.addWidget(self.pages, stretch=1)

    def _on_nav_changed(self, index: int):
        self.pages.setCurrentIndex(index)
        # Recipes saved in the editor should appear in the config dropdown.
        if index == 1:
            self._reload_recipe_choices()

    def _make_adb_client(self) -> AdbClient:
        return AdbClient(self._get_selected_instances()[0])

    def _build_run_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(self._build_control_card())
        layout.addWidget(self._build_stats_card())
        self.instances_frame = self._build_instances_card()
        self.instances_frame.setVisible(False)
        layout.addWidget(self.instances_frame)
        layout.addWidget(self._build_log_card(), stretch=1)
        return page

    def _build_setup_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        inner.setObjectName("page")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        layout.addWidget(self._build_config_card())
        layout.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    def _build_config_card(self):
        frame, layout = card("CONFIG")

        file_row = QHBoxLayout()
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("No Excel file selected...")
        self.file_input.setReadOnly(True)
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("browseBtn")
        browse_btn.clicked.connect(self._on_browse_file)
        file_row.addWidget(self.file_input, stretch=1)
        file_row.addWidget(browse_btn)
        layout.addLayout(file_row)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Profile"))
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self._reload_profile_list()
        profile_row.addWidget(self.profile_combo, stretch=1)
        save_profile_btn = QPushButton("Save")
        save_profile_btn.clicked.connect(self._on_save_profile)
        load_profile_btn = QPushButton("Load")
        load_profile_btn.clicked.connect(self._on_load_profile)
        delete_profile_btn = QPushButton("Delete")
        delete_profile_btn.clicked.connect(self._on_delete_profile)
        profile_row.addWidget(save_profile_btn)
        profile_row.addWidget(load_profile_btn)
        profile_row.addWidget(delete_profile_btn)
        layout.addLayout(profile_row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Chạy trên"))
        self.run_target_combo = QComboBox()
        self.run_target_combo.addItem("LDPlayer (app Android)", TARGET_ADB)
        self.run_target_combo.addItem("Chrome (trang web)", TARGET_BROWSER)
        self.run_target_combo.setToolTip(
            "LDPlayer: bot gõ qua ADB vào app trong máy ảo, như từ trước tới nay.\n\n"
            "Chrome: bot gắn vào một cửa sổ Chrome đang mở và bấm bằng chính DOM -\n"
            "tự cuộn tới nút, tự chờ nút hết bị che và hết disabled rồi mới bấm,\n"
            "nên không còn chuyện bấm trượt như bấm theo tọa độ.\n\n"
            "Chrome phải được mở bằng nút 'Mở Chrome cho bot' bên dưới, và phiên\n"
            "chạy phải chọn một kịch bản có các bước (web)."
        )
        self.run_target_combo.currentIndexChanged.connect(self._on_run_target_changed)
        target_row.addWidget(self.run_target_combo, stretch=1)
        layout.addLayout(target_row)

        self.browser_box = QGroupBox("Trình duyệt")
        browser_grid = QGridLayout(self.browser_box)
        browser_grid.addWidget(QLabel("Cổng gỡ lỗi"), 0, 0)
        self.browser_port_input = QSpinBox()
        self.browser_port_input.setRange(1024, 65535)
        self.browser_port_input.setValue(browser_backend.DEFAULT_DEBUG_PORT)
        self.browser_port_input.setToolTip(
            "Cổng mà Chrome mở ra để bot gắn vào. Chỉ đổi khi cổng 9222 đã bị\n"
            "chương trình khác chiếm."
        )
        browser_grid.addWidget(self.browser_port_input, 0, 1)

        browser_grid.addWidget(QLabel("Tab chứa"), 0, 2)
        self.browser_url_input = QLineEdit("ntl.ops.vnfai.com")
        self.browser_url_input.setPlaceholderText("một đoạn địa chỉ, ví dụ ntl.ops.vnfai.com")
        self.browser_url_input.setToolTip(
            "Chrome thường mở nhiều tab. Bot chọn tab có địa chỉ CHỨA đoạn này.\n"
            "Để trống thì lấy tab đầu tiên - dễ bấm nhầm sang tab khác."
        )
        browser_grid.addWidget(self.browser_url_input, 0, 3)

        open_chrome_btn = QPushButton("Mở Chrome cho bot")
        open_chrome_btn.setToolTip(
            "Mở Chrome bằng một profile riêng của bot, có bật cổng gỡ lỗi.\n\n"
            "Phải là profile riêng: từ Chrome 136, Chrome từ chối bật cổng này\n"
            "trên profile mặc định. Lần đầu hãy đăng nhập hệ thống kho trong cửa\n"
            "sổ vừa mở - Chrome nhớ lại cho các lần sau."
        )
        open_chrome_btn.clicked.connect(self._on_open_chrome)
        browser_grid.addWidget(open_chrome_btn, 1, 0, 1, 2)

        self.browser_status_label = QLabel("")
        self.browser_status_label.setWordWrap(True)
        browser_grid.addWidget(self.browser_status_label, 1, 2, 1, 2)

        self.browser_box.setVisible(False)
        layout.addWidget(self.browser_box)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Kiểu chạy"))
        self.run_mode_combo = QComboBox()
        self.run_mode_combo.addItem("Từng serial (như cũ)", MODE_SERIAL)
        self.run_mode_combo.addItem("Theo mã OR (xuất kho)", MODE_PICK)
        self.run_mode_combo.addItem("Theo mã check-in (nhập hàng)", MODE_INBOUND)
        self.run_mode_combo.setToolTip(
            "Từng serial: mỗi dòng Excel là một serial độc lập.\n\n"
            "Theo mã OR: file OR / MVĐ / Serial. Bot gõ mã OR vào ô 'Tìm theo mã\n"
            "OR' của màn hình Lấy hàng, mỗi mã OR là một phiên lấy hàng. Cột MVĐ\n"
            "chỉ đi kèm để tra ngược, bot không gõ nó vào đâu.\n\n"
            "Theo mã check-in: cùng kiểu file, nhưng vào bằng nút Nhận hàng và\n"
            "mỗi mã là một phiếu nhập.\n\n"
            "Cả hai chế độ phiên đều dừng hẳn cả lượt chạy khi gặp lỗi, vì quét\n"
            "lẫn sang phiên khác nghĩa là làm nhầm đơn."
        )
        self.run_mode_combo.currentIndexChanged.connect(self._on_run_mode_changed)
        mode_row.addWidget(self.run_mode_combo, stretch=1)
        layout.addLayout(mode_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("Sheet name"), 0, 0)
        self.sheet_combo = QComboBox()
        self.sheet_combo.setEditable(True)
        self.sheet_combo.lineEdit().setPlaceholderText("Default: first sheet")
        grid.addWidget(self.sheet_combo, 0, 1)

        grid.addWidget(QLabel("Serial column"), 0, 2)
        self.column_input = QLineEdit("H")
        self.column_input.setMaximumWidth(60)
        grid.addWidget(self.column_input, 0, 3)

        grid.addWidget(QLabel("Start row"), 1, 0)
        self.start_row_input = QSpinBox()
        self.start_row_input.setRange(1, 1000000)
        self.start_row_input.setValue(2)
        grid.addWidget(self.start_row_input, 1, 1)

        grid.addWidget(QLabel("End row (0 = no limit)"), 1, 2)
        self.end_row_input = QSpinBox()
        self.end_row_input.setRange(0, 1000000)
        self.end_row_input.setValue(0)
        grid.addWidget(self.end_row_input, 1, 3)

        grid.addWidget(QLabel("Delay per serial (seconds)"), 2, 0)
        self.delay_input = QDoubleSpinBox()
        self.delay_input.setRange(0.0, 30.0)
        self.delay_input.setSingleStep(0.1)
        self.delay_input.setValue(0.0)
        self.delay_input.setSuffix(" s")
        self.delay_input.setToolTip(
            "Nghỉ thêm sau mỗi serial. Để 0 được: bot đã chờ app phản hồi xong\n"
            "mới gõ dòng tiếp theo, nên không cần delay cứng để 'cho chắc'.\n"
            "Chỉ tăng khi muốn cố tình chạy chậm lại."
        )
        grid.addWidget(self.delay_input, 2, 1)

        grid.addWidget(QLabel("Confirm key (Enter)"), 2, 2)
        self.enter_mode_combo = QComboBox()
        self.enter_mode_combo.addItem("Keyboard Enter", "enter")
        self.enter_mode_combo.addItem("No Enter (paste only)", "none")
        self.enter_mode_combo.addItem("Tab -> Enter", "tab_enter")
        grid.addWidget(self.enter_mode_combo, 2, 3)

        grid.addWidget(QLabel("Wait before Enter (s)"), 3, 0)
        self.enter_delay_input = QDoubleSpinBox()
        self.enter_delay_input.setRange(0.0, 10.0)
        self.enter_delay_input.setSingleStep(0.1)
        self.enter_delay_input.setValue(0.0)
        self.enter_delay_input.setSuffix(" s")
        self.enter_delay_input.setToolTip(
            "Để 0 thì bot gộp 'xóa ô + gõ serial + Enter' vào một lần gọi ADB,\n"
            "nhanh hơn hẳn. Đặt > 0 sẽ tách ra làm hai lần gọi - chỉ cần khi app\n"
            "phải có thời gian nhận đủ chữ trước lúc Enter."
        )
        grid.addWidget(self.enter_delay_input, 3, 1)

        grid.addWidget(QLabel("Chờ app phản hồi tối đa (s)"), 3, 2)
        self.response_timeout_input = QDoubleSpinBox()
        self.response_timeout_input.setRange(0.0, 60.0)
        self.response_timeout_input.setSingleStep(0.5)
        self.response_timeout_input.setValue(DEFAULT_RESPONSE_TIMEOUT_SECONDS)
        self.response_timeout_input.setSuffix(" s")
        self.response_timeout_input.setToolTip(
            "Bot chờ tới khi màn hình đúng là kết quả của serial vừa gửi rồi mới\n"
            "chấm điểm và chạy tiếp - máy nhanh thì đi ngay, máy chậm chờ thêm.\n\n"
            "Đây là mức chờ tối đa khi biết chắc app chưa xử lý xong (màn hình\n"
            "vẫn đang là kết quả của serial trước). Quá mức này dòng đó được ghi\n"
            "UNKNOWN kèm lý do, thay vì chép nhầm kết quả dòng trên.\n\n"
            "Đặt 0 = không chờ (nhanh nhất, nhưng mất lớp bảo vệ này)."
        )
        grid.addWidget(self.response_timeout_input, 3, 3)

        self.adb_input_check = QCheckBox("Use ADB input (recommended)")
        self.adb_input_check.setChecked(True)
        self.adb_input_check.setToolTip(
            "Sends keys directly to the app over ADB - no window focus needed. "
            "Falls back to keyboard simulation automatically if ADB is unavailable."
        )
        grid.addWidget(self.adb_input_check, 4, 0, 1, 4)

        self.background_check = QCheckBox("Background mode - dùng máy làm việc khác được")
        self.background_check.setToolTip(
            "Chỉ dùng ADB, TUYỆT ĐỐI không chuyển sang gõ bàn phím.\n"
            "Bot chạy kể cả khi LDPlayer bị minimize hoặc nằm sau cửa sổ khác.\n"
            "Nếu ADB lỗi, bot dừng và báo lỗi thay vì gõ nhầm vào cửa sổ bạn đang dùng."
        )
        self.background_check.toggled.connect(self._on_background_mode_toggled)
        # Bật sẵn, và bật SAU khi nối tín hiệu để ô "Use ADB input" bị khóa theo
        # ngay từ đầu. Đường lui gõ bàn phím không đem lại gì cho luồng kho -
        # mọi thứ đã chạy qua ADB - nên mặc định tắt nó đi thì một lần ADB chớp
        # tắt không thể biến thành một loạt serial gõ vào cửa sổ đang mở.
        self.background_check.setChecked(True)
        grid.addWidget(self.background_check, 5, 0, 1, 4)

        self.verify_check = QCheckBox("Verify result via ADB")
        self.verify_check.setChecked(True)
        grid.addWidget(self.verify_check, 6, 0, 1, 2)

        self.screenshot_check = QCheckBox("Screenshot on error/unknown")
        self.screenshot_check.setChecked(False)
        grid.addWidget(self.screenshot_check, 6, 2, 1, 2)

        grid.addWidget(QLabel("Error keywords"), 7, 0)
        self.error_keywords_input = QLineEdit(
            "error,product not found,invalid,failed,loi,khong hop le,that bai"
        )
        self.error_keywords_input.setPlaceholderText("Comma separated")
        grid.addWidget(self.error_keywords_input, 7, 1, 1, 3)

        grid.addWidget(QLabel("Từ khóa không tìm thấy"), 8, 0)
        self.not_found_keywords_input = QLineEdit(DEFAULT_NOT_FOUND_KEYWORDS)
        self.not_found_keywords_input.setPlaceholderText("Comma separated")
        self.not_found_keywords_input.setToolTip(
            "Khớp một trong các từ này thì dòng được ghi lỗi với lý do\n"
            "'Không tìm thấy serial', bot tự bấm OK trên màn hình LDPlayer\n"
            "rồi chạy tiếp serial sau.\n\n"
            "Xét TRƯỚC Error keywords, nên câu 'không tìm thấy' không bị\n"
            "từ khóa lỗi chung nuốt mất."
        )
        grid.addWidget(self.not_found_keywords_input, 8, 1, 1, 3)

        grid.addWidget(QLabel("Success keywords"), 9, 0)
        self.success_keywords_input = QLineEdit()
        self.success_keywords_input.setPlaceholderText(
            "Optional, comma separated (e.g. success,thanh cong)"
        )
        grid.addWidget(self.success_keywords_input, 9, 1, 1, 3)

        grid.addWidget(QLabel("Kịch bản thao tác"), 10, 0)
        self.recipe_combo = QComboBox()
        self.recipe_combo.setToolTip(
            "Chọn 'Mặc định' để chạy như cũ (xóa ô -> gõ serial -> Enter -> kiểm tra).\n"
            "Chọn một kịch bản để tự định nghĩa chuỗi thao tác ở tab Kịch bản."
        )
        grid.addWidget(self.recipe_combo, 10, 1, 1, 3)
        self._reload_recipe_choices()

        self.dry_run_check = QCheckBox("Dry run - only first")
        grid.addWidget(self.dry_run_check, 11, 0)
        self.dry_run_count = QSpinBox()
        self.dry_run_count.setRange(1, 1000)
        self.dry_run_count.setValue(5)
        self.dry_run_count.setSuffix(" serial(s)")
        grid.addWidget(self.dry_run_count, 11, 1)

        layout.addLayout(grid)

        self.product_box = QGroupBox("Nhận hàng: dán mã sản phẩm trước mỗi serial")
        product_grid = QGridLayout(self.product_box)
        product_grid.setHorizontalSpacing(14)

        product_grid.addWidget(QLabel("Mã sản phẩm cố định"), 0, 0)
        self.product_code_input = QLineEdit()
        self.product_code_input.setPlaceholderText("để trống = chỉ gõ serial như cũ")
        self.product_code_input.setToolTip(
            "Màn hình nhận hàng chờ xen kẽ: mã sản phẩm -> serial -> mã sản phẩm\n"
            "-> serial... Điền mã vào đây thì bot nhớ đúng một mã cho cả file và\n"
            "tự gõ lại trước từng serial, bạn chỉ cần mở sẵn màn hình quét.\n\n"
            "Để trống là chạy như cũ: mỗi dòng Excel chỉ gõ serial."
        )
        product_grid.addWidget(self.product_code_input, 0, 1, 1, 3)

        product_grid.addWidget(QLabel("Chờ sau mã sản phẩm (s)"), 1, 0)
        self.product_delay_input = QDoubleSpinBox()
        self.product_delay_input.setRange(0.0, 10.0)
        self.product_delay_input.setSingleStep(0.1)
        self.product_delay_input.setValue(DEFAULT_PRODUCT_CODE_DELAY_SECONDS)
        self.product_delay_input.setSuffix(" s")
        self.product_delay_input.setToolTip(
            "Nghỉ bao lâu giữa mã sản phẩm và serial.\n\n"
            "Đây là khoảng chờ cứng duy nhất còn lại, và buộc phải cứng: app đổi\n"
            "ý nghĩa ô nhập theo trạng thái bên trong chứ không đổi màn hình, nên\n"
            "không có dấu hiệu nào rẻ để bot soi. Gõ serial sớm quá thì nó bị đọc\n"
            "thành mã sản phẩm.\n\n"
            "Giảm xuống nếu app phản hồi nhanh; tăng lên nếu thấy serial bị app\n"
            "báo không tìm thấy hàng loạt."
        )
        product_grid.addWidget(self.product_delay_input, 1, 1)

        layout.addWidget(self.product_box)

        self.pick_box = QGroupBox("Xuất kho theo mã OR")
        pick_grid = QGridLayout(self.pick_box)
        pick_grid.setHorizontalSpacing(14)

        self.bill_column_label = QLabel("Cột mã OR")
        pick_grid.addWidget(self.bill_column_label, 0, 0)
        self.bill_column_input = QLineEdit("A")
        self.bill_column_input.setMaximumWidth(60)
        self.bill_column_input.setToolTip(
            "Cột chứa mã bot gõ vào ô tìm kiếm của app: mã OR khi xuất kho, mã\n"
            "check-in khi nhập hàng. Mỗi giá trị khác nhau là một phiên.\n\n"
            "Ô gộp trải nhiều dòng cũng đọc được - bot tự kéo giá trị xuống cho\n"
            "từng serial."
        )
        pick_grid.addWidget(self.bill_column_input, 0, 1)

        self.ref_column_label = QLabel("Cột MVĐ")
        pick_grid.addWidget(self.ref_column_label, 0, 2)
        self.ref_column_input = QLineEdit("B")
        self.ref_column_input.setMaximumWidth(60)
        self.ref_column_input.setPlaceholderText("trống")
        self.ref_column_input.setToolTip(
            "Cột mã vận đơn đi kèm mã OR. Bot KHÔNG gõ mã này vào đâu cả - app\n"
            "chỉ tra theo mã OR. Nó được mang theo để file kết quả và sheet báo\n"
            "cáo tra ngược được về đơn hàng.\n\n"
            "Để trống nếu file không có cột này."
        )
        pick_grid.addWidget(self.ref_column_input, 0, 3)

        pick_grid.addWidget(QLabel("Mã tote"), 1, 0)
        self.tote_input = QLineEdit(DEFAULT_TOTE)
        self.tote_input.setToolTip(
            "Mã thiết bị chứa hàng, gõ ở màn hình 'Quét thiết bị chứa hàng'.\n\n"
            "Cố định cho cả lượt chạy: chỉnh ở đây trước khi bấm Start. App nhớ\n"
            "tote giữa các phiên, nên từ đơn thứ hai trở đi màn hình này thường\n"
            "đã đủ số và bot lướt qua không gõ gì."
        )
        pick_grid.addWidget(self.tote_input, 1, 1)

        pick_grid.addWidget(QLabel("Mã bin"), 1, 2)
        self.bin_input = QLineEdit(DEFAULT_BIN_CODE)
        self.bin_input.setPlaceholderText("để trống = đọc từ màn hình")
        self.bin_input.setToolTip(
            "Vị trí lấy hàng, gõ ở màn hình 'Quét vị trí lấy hàng'. Cố định cho\n"
            "cả lượt chạy như mã tote.\n\n"
            "Điền giá trị là ÉP CỨNG: app chỉ sang vị trí khác thì bot dừng chứ\n"
            "không lấy nhầm kệ. Để trống thì bot đọc vị trí app đang yêu cầu\n"
            "('Vị trí lấy hàng kế tiếp') rồi gõ lại - dùng khi đơn trải nhiều vị trí."
        )
        pick_grid.addWidget(self.bin_input, 1, 3)

        self.check_count_check = QCheckBox("Đối chiếu số lượng app báo với số serial trong Excel")
        self.check_count_check.setChecked(True)
        self.check_count_check.setToolTip(
            "App báo phiên cần bao nhiêu sản phẩm ('SL sản phẩm' trên thẻ). Lệch\n"
            "với số serial trong Excel là dừng ngay TRƯỚC khi mở phiên - lúc đó\n"
            "chưa động gì tới kho.\n"
            "Tắt đi thì sai số sẽ chỉ lộ ra khi đã quét dở dang."
        )
        pick_grid.addWidget(self.check_count_check, 2, 0, 1, 4)

        self.create_session_check = QCheckBox("Tự tạo phiên check-in nếu chưa có")
        self.create_session_check.setToolTip(
            "Mã nhập kho chưa có phiên check-in thì app hỏi 'có tạo phiên và nhận\n"
            "hàng?'. Bấm Xác nhận là TẠO một phiên thật trong hệ thống, nên mặc\n"
            "định bot bấm Quay lại rồi dừng để bạn tự quyết.\n\n"
            "Chỉ bật khi biết chắc mọi mã trong file đều cần tạo phiên mới."
        )
        pick_grid.addWidget(self.create_session_check, 3, 0, 1, 4)

        layout.addWidget(self.pick_box)

        layout.addWidget(QLabel("LDPlayer instances (tick to run in parallel; leave empty to use the name below)"))
        instances_row = QHBoxLayout()
        self.instances_list = QListWidget()
        self.instances_list.setMaximumHeight(90)
        instances_row.addWidget(self.instances_list, stretch=1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._on_refresh_instances)
        instances_row.addWidget(refresh_btn)
        layout.addLayout(instances_row)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Fallback instance name"))
        self.window_title_input = QLineEdit("LDPlayer")
        manual_row.addWidget(self.window_title_input)
        layout.addLayout(manual_row)

        return frame

    def _build_menu(self):
        bar = self.menuBar()

        file_menu = bar.addMenu("&Tệp")
        self.act_open = QAction("Mở file Excel...", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self._on_browse_file)
        file_menu.addAction(self.act_open)

        self.act_save_profile = QAction("Lưu profile", self)
        self.act_save_profile.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save_profile.triggered.connect(self._on_save_profile)
        file_menu.addAction(self.act_save_profile)

        file_menu.addSeparator()
        self.act_export = QAction("Xuất báo cáo...", self)
        self.act_export.triggered.connect(self._on_export_report)
        file_menu.addAction(self.act_export)

        file_menu.addSeparator()
        act_quit = QAction("Thoát", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        run_menu = bar.addMenu("&Chạy")
        run_menu.addAction(self._make_action("Bắt đầu", self._on_start))
        run_menu.addAction(self._make_action("Tạm dừng / Tiếp tục\tF9", self._on_pause_resume))
        run_menu.addAction(self._make_action("Dừng\tF10", self._on_stop))
        run_menu.addSeparator()
        run_menu.addAction(self._make_action("Chạy lại các dòng lỗi", self._on_retry_errors))

        tools_menu = bar.addMenu("&Công cụ")
        tools_menu.addAction(self._make_action("Làm mới danh sách instance", self._on_refresh_instances))
        tools_menu.addAction(self._make_action("Kiểm tra kết nối ADB", self._on_test_adb))
        tools_menu.addAction(self._make_action("Mở thư mục log", self._on_open_logs))

        help_menu = bar.addMenu("&Trợ giúp")
        help_menu.addAction(self._make_action(f"Giới thiệu {APP_NAME}", self._on_about))

    def _make_action(self, text: str, slot) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        return action

    def _build_toolbar(self):
        toolbar = QToolBar("Điều khiển")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        self.tb_start = QAction("Bắt đầu", self)
        self.tb_start.triggered.connect(self._on_start)
        self.tb_pause = QAction("Tạm dừng", self)
        self.tb_pause.setEnabled(False)
        self.tb_pause.triggered.connect(self._on_pause_resume)
        self.tb_stop = QAction("Dừng", self)
        self.tb_stop.setEnabled(False)
        self.tb_stop.triggered.connect(self._on_stop)

        toolbar.addAction(self.tb_start)
        toolbar.addAction(self.tb_pause)
        toolbar.addAction(self.tb_stop)

    def _build_status_bar(self):
        bar = self.statusBar()

        self.status_conn = QLabel("● Chưa kiểm tra")
        self.status_conn.setStyleSheet("color: #8a8fa3;")
        self.status_backend = QLabel("Backend: -")
        self.status_backend.setStyleSheet("color: #8a8fa3;")
        self.status_progress = QLabel("0 / 0")
        self.status_progress.setStyleSheet("color: #8a8fa3;")

        bar.addWidget(self.status_conn)
        bar.addWidget(QLabel("  "))
        bar.addWidget(self.status_backend)
        bar.addPermanentWidget(self.status_progress)

    def _set_connection_status(self, ok: bool | None, detail: str = ""):
        if ok is None:
            self.status_conn.setText("● Chưa kiểm tra")
            self.status_conn.setStyleSheet("color: #8a8fa3;")
        elif ok:
            self.status_conn.setText(f"● ADB sẵn sàng{detail}")
            self.status_conn.setStyleSheet("color: #2ecc71;")
        else:
            self.status_conn.setText(f"● ADB không kết nối{detail}")
            self.status_conn.setStyleSheet("color: #ff5c72;")

    def _on_test_adb(self):
        names = self._get_selected_instances()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            alive = [n for n in names if AdbClient(n, timeout=5).run_shell("echo ok", timeout=5) is not None]
        finally:
            QApplication.restoreOverrideCursor()

        self._set_connection_status(len(alive) == len(names), f" ({len(alive)}/{len(names)})")
        QMessageBox.information(
            self,
            "Kiểm tra ADB",
            "Kết nối được: " + (", ".join(alive) if alive else "(không có)") + "\n"
            "Không kết nối: " + (", ".join(n for n in names if n not in alive) or "(không có)"),
        )

    def _on_open_logs(self):
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(logs_dir()))

    def _on_about(self):
        QMessageBox.about(
            self,
            f"Giới thiệu {APP_NAME}",
            f"<b>{APP_NAME}</b> {APP_VERSION}<br><br>"
            f"{APP_DESCRIPTION}<br><br>"
            "Nhập serial từ Excel vào app trên LDPlayer qua ADB, xác nhận kết quả "
            "và ghi lại báo cáo.",
        )

    def _reload_recipe_choices(self):
        current = self.recipe_combo.currentData()
        self.recipe_combo.clear()
        self.recipe_combo.addItem("Mặc định (không dùng kịch bản)", "")
        for name in list_recipes():
            self.recipe_combo.addItem(name, name)
        if current:
            index = self.recipe_combo.findData(current)
            if index >= 0:
                self.recipe_combo.setCurrentIndex(index)

    def _selected_recipe_steps(self) -> list:
        """Empty list means run the built-in classic path."""
        name = self.recipe_combo.currentData()
        if not name:
            return []
        try:
            return load_recipe(name).steps
        except Exception as e:
            logger.exception("Could not load recipe %s", name)
            QMessageBox.critical(
                self,
                "Không nạp được kịch bản",
                f"Kịch bản '{name}' lỗi:\n{e}\n\nSẽ chạy theo cách mặc định.",
            )
            return []

    def _on_background_mode_toggled(self, enabled: bool):
        """Background mode is ADB-only by definition, so ADB input is forced on
        and locked while it is active."""
        if enabled:
            self.adb_input_check.setChecked(True)
        self.adb_input_check.setEnabled(not enabled)

    def _build_control_card(self):
        frame, layout = card("CONTROLS")

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.clicked.connect(self._on_start)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setObjectName("pauseBtn")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause_resume)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)

        self.retry_errors_btn = QPushButton("Retry Errors")
        self.retry_errors_btn.setObjectName("retryBtn")
        self.retry_errors_btn.setEnabled(False)
        self.retry_errors_btn.clicked.connect(self._on_retry_errors)

        self.export_report_btn = QPushButton("Export Report")
        self.export_report_btn.setObjectName("exportErrorsBtn")
        self.export_report_btn.setEnabled(False)
        self.export_report_btn.clicked.connect(self._on_export_report)
        self.review_progress_btn = QPushButton("Đối chiếu tiến độ")
        self.review_progress_btn.clicked.connect(self._review_unresolved_progress)

        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.pause_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.retry_errors_btn)
        btn_row.addWidget(self.review_progress_btn)
        btn_row.addWidget(self.export_report_btn)
        layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0 / 0")
        layout.addWidget(self.progress_bar)

        hint = QLabel("Hotkeys: F9 = Pause/Resume, F10 = Stop (window must have focus)")
        hint.setStyleSheet("color: #8a8fa3; font-size: 11px;")
        layout.addWidget(hint)

        return frame

    def _build_stats_card(self):
        frame, layout = card("STATS")
        row = QHBoxLayout()

        self.stat_total_lbl = self._stat_block(row, "Processed", "0 / 0", "#e8e8f0")
        self.stat_success_lbl = self._stat_block(row, "Đã xác nhận", "0", "#2ecc71")
        self.stat_error_lbl = self._stat_block(row, "Errors", "0", "#ff5c72")
        self.stat_not_found_lbl = self._stat_block(row, "Không tìm thấy", "0", "#ff9f43")
        self.stat_unknown_lbl = self._stat_block(row, "Unknown", "0", "#f1c40f")
        self.stat_inferred_lbl = self._stat_block(row, "Không phát hiện lỗi", "0", "#4fc3f7")

        layout.addLayout(row)
        return frame

    def _stat_block(self, parent_layout, label_text, value_text, color):
        box = QVBoxLayout()
        value_lbl = QLabel(value_text)
        value_lbl.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        value_lbl.setStyleSheet(f"color: {color};")
        label_lbl = QLabel(label_text)
        label_lbl.setStyleSheet("color: #8a8fa3; font-size: 11px;")
        box.addWidget(value_lbl)
        box.addWidget(label_lbl)
        wrapper = QWidget()
        wrapper.setLayout(box)
        parent_layout.addWidget(wrapper)
        return value_lbl

    def _build_instances_card(self):
        frame, layout = card("PARALLEL INSTANCES")
        self.instances_progress_layout = QVBoxLayout()
        layout.addLayout(self.instances_progress_layout)
        return frame

    def _build_log_card(self):
        frame, layout = card("PROCESS LOG")

        filter_row = QHBoxLayout()
        self.log_search_input = QLineEdit()
        self.log_search_input.setPlaceholderText("Search serial or message...")
        self.log_search_input.textChanged.connect(self._apply_log_filter)
        self.log_filter_combo = QComboBox()
        self.log_filter_combo.addItems(["All", "OK", "ERROR", "UNKNOWN"])
        self.log_filter_combo.currentTextChanged.connect(self._apply_log_filter)
        filter_row.addWidget(self.log_search_input, stretch=1)
        filter_row.addWidget(self.log_filter_combo)
        layout.addLayout(filter_row)

        self.log_list = QListWidget()
        self.log_list.itemDoubleClicked.connect(self._on_log_item_double_clicked)
        layout.addWidget(self.log_list)
        return frame

    # ---------------------------------------------------------------- hotkeys/tray

    def _setup_hotkeys(self):
        QShortcut(QKeySequence("F9"), self, activated=self._on_pause_resume)
        QShortcut(QKeySequence("F10"), self, activated=self._on_stop)

    def _setup_tray(self):
        self.tray_icon = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(tray_icon("idle"), self)
        self.tray_icon.setToolTip(APP_NAME)

        menu = QMenu()
        menu.addAction(self._make_action("Hiện cửa sổ", self._restore_from_tray))
        menu.addSeparator()
        self.tray_pause_action = self._make_action("Tạm dừng / Tiếp tục", self._on_pause_resume)
        menu.addAction(self.tray_pause_action)
        menu.addAction(self._make_action("Dừng", self._on_stop))
        menu.addSeparator()
        menu.addAction(self._make_action("Thoát", self._quit_from_tray))
        self.tray_icon.setContextMenu(menu)

        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_from_tray()

    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self):
        self._quitting = True
        self.close()

    def _set_tray_state(self, state: str, tooltip_extra: str = ""):
        if not self.tray_icon:
            return
        self.tray_icon.setIcon(tray_icon(state))
        label = {
            "idle": "Đang chờ",
            "running": "Đang chạy",
            "paused": "Tạm dừng",
            "error": "Lỗi",
        }.get(state, state)
        tip = f"{APP_NAME} - {label}"
        if tooltip_extra:
            tip += f"\n{tooltip_extra}"
        self.tray_icon.setToolTip(tip)

    def _notify_finished(self, text: str):
        QApplication.beep()
        if self.tray_icon:
            self.tray_icon.showMessage(APP_NAME, text, QSystemTrayIcon.MessageIcon.Information, 5000)

    # ---------------------------------------------------------------- profiles / settings

    PROFILE_FIELDS = (
        "sheet", "column", "start_row", "end_row", "delay", "instance_name",
        "enter_mode", "enter_delay", "adb_input", "background_mode", "verify",
        "screenshot", "error_keywords", "not_found_keywords", "success_keywords",
        "response_timeout", "dry_run", "dry_run_count",
        "run_mode", "bill_column", "ref_column", "tote", "bin_code",
        "check_expected_count", "create_missing_session",
        "product_code", "product_code_delay",
        "run_target", "browser_port", "browser_url",
    )

    def _collect_profile_values(self) -> dict:
        return {
            "sheet": self.sheet_combo.currentText(),
            "column": self.column_input.text(),
            "start_row": self.start_row_input.value(),
            "end_row": self.end_row_input.value(),
            "delay": self.delay_input.value(),
            "instance_name": self.window_title_input.text(),
            "enter_mode": self.enter_mode_combo.currentData(),
            "enter_delay": self.enter_delay_input.value(),
            "adb_input": self.adb_input_check.isChecked(),
            "background_mode": self.background_check.isChecked(),
            "verify": self.verify_check.isChecked(),
            "screenshot": self.screenshot_check.isChecked(),
            "error_keywords": self.error_keywords_input.text(),
            "not_found_keywords": self.not_found_keywords_input.text(),
            "success_keywords": self.success_keywords_input.text(),
            "response_timeout": self.response_timeout_input.value(),
            "dry_run": self.dry_run_check.isChecked(),
            "dry_run_count": self.dry_run_count.value(),
            "run_mode": self.run_mode_combo.currentData(),
            "bill_column": self.bill_column_input.text(),
            "ref_column": self.ref_column_input.text(),
            "tote": self.tote_input.text(),
            "bin_code": self.bin_input.text(),
            "check_expected_count": self.check_count_check.isChecked(),
            "create_missing_session": self.create_session_check.isChecked(),
            "product_code": self.product_code_input.text(),
            "product_code_delay": self.product_delay_input.value(),
            "run_target": self.run_target_combo.currentData(),
            "browser_port": self.browser_port_input.value(),
            "browser_url": self.browser_url_input.text(),
        }

    @staticmethod
    def _to_bool(value, default: bool = False) -> bool:
        """QSettings round-trips booleans as the strings 'true'/'false' on Windows,
        and bool('false') is True - so parse explicitly."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes")

    def _apply_profile_values(self, values: dict):
        self.sheet_combo.setCurrentText(values.get("sheet", ""))
        self.column_input.setText(values.get("column", "H"))
        self.start_row_input.setValue(int(values.get("start_row", 2)))
        self.end_row_input.setValue(int(values.get("end_row", 0)))
        self.delay_input.setValue(float(values.get("delay", 0.2)))
        self.window_title_input.setText(values.get("instance_name", "LDPlayer"))
        idx = self.enter_mode_combo.findData(values.get("enter_mode", "enter"))
        if idx >= 0:
            self.enter_mode_combo.setCurrentIndex(idx)
        self.enter_delay_input.setValue(float(values.get("enter_delay", 0.0)))
        self.adb_input_check.setChecked(self._to_bool(values.get("adb_input"), True))
        self.background_check.setChecked(self._to_bool(values.get("background_mode"), True))
        self.verify_check.setChecked(self._to_bool(values.get("verify"), True))
        self.screenshot_check.setChecked(self._to_bool(values.get("screenshot"), False))
        self.error_keywords_input.setText(values.get("error_keywords", ""))
        # Profile cũ không có khóa này - để trống thì tính năng tắt im lặng, nên
        # rơi về mặc định thay vì "".
        self.not_found_keywords_input.setText(
            values.get("not_found_keywords") or DEFAULT_NOT_FOUND_KEYWORDS
        )
        self.success_keywords_input.setText(values.get("success_keywords", ""))
        self.response_timeout_input.setValue(
            float(values.get("response_timeout") or DEFAULT_RESPONSE_TIMEOUT_SECONDS)
        )
        self.dry_run_check.setChecked(self._to_bool(values.get("dry_run"), False))
        self.dry_run_count.setValue(int(values.get("dry_run_count", 5)))

        mode_idx = self.run_mode_combo.findData(values.get("run_mode") or MODE_SERIAL)
        self.run_mode_combo.setCurrentIndex(mode_idx if mode_idx >= 0 else 0)
        self.bill_column_input.setText(values.get("bill_column") or "A")
        # Profile lưu trước khi có template ba cột không có khóa nào trong hai
        # khóa dưới. Cột MVĐ để trống là an toàn (file cũ chỉ hai cột), còn mã
        # bin rơi về mặc định mới - chứ "" nghĩa là đi theo màn hình, khác hẳn.
        self.ref_column_input.setText(values.get("ref_column") or "")
        self.tote_input.setText(values.get("tote") or DEFAULT_TOTE)
        if "bin_code" in values:
            self.bin_input.setText(values["bin_code"] or "")
        else:
            self.bin_input.setText(DEFAULT_BIN_CODE)
        self.check_count_check.setChecked(
            self._to_bool(values.get("check_expected_count"), True)
        )
        self.create_session_check.setChecked(
            self._to_bool(values.get("create_missing_session"), False)
        )
        self.product_code_input.setText(values.get("product_code", ""))
        self.product_delay_input.setValue(
            float(values.get("product_code_delay") or DEFAULT_PRODUCT_CODE_DELAY_SECONDS)
        )

        # Profile cũ không có ba khóa này - rơi về LDPlayer, đúng như trước
        # khi có chế độ trình duyệt.
        target_idx = self.run_target_combo.findData(values.get("run_target") or TARGET_ADB)
        self.run_target_combo.setCurrentIndex(target_idx if target_idx >= 0 else 0)
        self.browser_port_input.setValue(
            int(values.get("browser_port") or browser_backend.DEFAULT_DEBUG_PORT)
        )
        self.browser_url_input.setText(values.get("browser_url", ""))

        self._on_run_mode_changed()
        self._on_run_target_changed()

    def _reload_profile_list(self):
        self.settings.beginGroup("profiles")
        names = self.settings.childGroups()
        self.settings.endGroup()
        current = self.profile_combo.currentText()
        self.profile_combo.clear()
        self.profile_combo.addItems(names)
        if current:
            self.profile_combo.setCurrentText(current)

    def _on_save_profile(self):
        name = self.profile_combo.currentText().strip() or "Default"
        self.settings.beginGroup(f"profiles/{name}")
        for key, value in self._collect_profile_values().items():
            self.settings.setValue(key, value)
        self.settings.endGroup()
        self.settings.setValue("last_profile", name)
        self.settings.sync()
        self._reload_profile_list()
        self.profile_combo.setCurrentText(name)
        QMessageBox.information(self, "Profile saved", f"Saved profile '{name}'.")

    def _on_load_profile(self):
        name = self.profile_combo.currentText().strip()
        if not name:
            return
        self._load_profile_by_name(name)

    def _load_profile_by_name(self, name: str):
        if not self.pages.widget(1).isEnabled():
            return
        self.settings.beginGroup(f"profiles/{name}")
        keys = self.settings.childKeys()
        if not keys:
            self.settings.endGroup()
            return
        values = {key: self.settings.value(key) for key in keys}
        self.settings.endGroup()
        self._apply_profile_values(values)

    def _on_delete_profile(self):
        name = self.profile_combo.currentText().strip()
        if not name:
            return
        self.settings.remove(f"profiles/{name}")
        self.settings.sync()
        self._reload_profile_list()

    def _restore_geometry(self):
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("window/state")
        if state:
            self.restoreState(state)

    def _save_geometry(self):
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if len(urls) == 1 and urls[0].toLocalFile().lower().endswith(".xlsx"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if path.lower().endswith(".xlsx"):
            self._load_excel_path(path)
            event.acceptProposedAction()

    def _restore_last_state(self):
        last_path = self.settings.value("last_excel_path", "")
        if last_path and os.path.isfile(last_path):
            self.excel_path = last_path
            self.file_input.setText(os.path.basename(last_path))

        last_profile = self.settings.value("last_profile", "")
        if last_profile:
            self.profile_combo.setCurrentText(last_profile)
            self._load_profile_by_name(last_profile)

    def _save_last_state(self):
        if self.excel_path:
            self.settings.setValue("last_excel_path", self.excel_path)
        self.settings.sync()

    # ---------------------------------------------------------------- excel / sheet / column

    def _on_browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Excel file",
            "",
            "Excel Files (*.xlsx)",
        )
        if path:
            self._load_excel_path(path)

    def _load_excel_path(self, path: str):
        if not self.pages.widget(1).isEnabled():
            return
        self.excel_path = path
        self.file_input.setText(os.path.basename(path))

        try:
            sheets = get_sheet_names(path)
            self.sheet_combo.clear()
            self.sheet_combo.addItems(sheets)
            self.sheet_combo.setCurrentIndex(0)
        except ExcelReadError as e:
            QMessageBox.warning(self, "Sheet read warning", str(e))
            return

        sheet = self.sheet_combo.currentText() or None
        guessed_serial = guess_serial_column(path, sheet)
        if guessed_serial:
            self.column_input.setText(guessed_serial)

        # Template xuất kho có ba cột OR / MVĐ / Serial, nên mã tìm phiên lấy từ
        # cột "OR" và cột "MVĐ" thành cột tham chiếu. File hai cột đời cũ không
        # có tiêu đề OR - lúc đó cột mã vận đơn lùi về làm mã tìm phiên như trước.
        #
        # Cột nào cũng chỉ nhận khi khác cột serial: tiêu đề kiểu "Bill serial"
        # khớp cả hai bộ từ khóa, mà đặt trùng nhau thì tới lúc bấm Start mới
        # báo lỗi.
        guessed_or = guess_or_column(path, sheet)
        guessed_bill = guess_bill_column(path, sheet)
        if guessed_or and guessed_or != guessed_serial:
            self.bill_column_input.setText(guessed_or)
            self.ref_column_input.setText(
                guessed_bill if guessed_bill not in (None, guessed_or, guessed_serial) else ""
            )
        elif guessed_bill and guessed_bill != guessed_serial:
            self.bill_column_input.setText(guessed_bill)
            self.ref_column_input.setText("")

    def run_mode(self) -> str:
        return self.run_mode_combo.currentData() or MODE_SERIAL

    def run_target(self) -> str:
        return self.run_target_combo.currentData() or TARGET_ADB

    def _on_run_target_changed(self, *_):
        """
        Đổi đích chạy thì khóa lại những ô chỉ có nghĩa với máy ảo Android.

        Khóa chứ không ẩn, giống _on_run_mode_changed: ẩn đi thì người dùng
        tưởng app thiếu tính năng.
        """
        browser = self.run_target() == TARGET_BROWSER
        self.browser_box.setVisible(browser)
        self._refresh_browser_status()

        # Hai chế độ theo phiên (mã OR, mã check-in) bám sát từng màn hình của
        # app Android - nút Nhận hàng, thẻ phiên, ô quét vị trí - nên không đem
        # sang web được. Ép về 'Từng serial' rồi khóa lại, và khóa TRƯỚC khi nhớ
        # tooltip gốc để không nhớ nhầm câu mà _on_run_mode_changed vừa đè lên.
        if browser and self.run_mode() in SESSION_MODES:
            self.run_mode_combo.setCurrentIndex(
                max(0, self.run_mode_combo.findData(MODE_SERIAL))
            )
        self.run_mode_combo.setEnabled(not browser)

        # Máy ảo, ADB, tên cửa sổ LDPlayer, phím Enter kiểu Android: trên trang
        # web không cái nào có nghĩa. Kịch bản web tự khai bấm gì, chờ gì.
        adb_only = (
            self.instances_list,
            self.window_title_input,
            self.adb_input_check,
            self.background_check,
            self.enter_mode_combo,
            self.enter_delay_input,
            self.product_code_input,
            self.product_delay_input,
        )
        if not hasattr(self, "_tooltips_before_target_lock"):
            # Mấy ô này cũng nằm trong danh sách khóa theo kiểu chạy. Nếu lúc
            # này chúng đang bị khóa thì tooltip hiện tại là câu "Không dùng ở
            # chế độ ...", nhớ lấy nó là mất hẳn phần giải thích gốc - nên hỏi
            # _on_run_mode_changed xem nó đã cất bản gốc chưa.
            saved = getattr(self, "_tooltips_before_lock", {})
            self._tooltips_before_target_lock = {
                w: saved.get(w, w.toolTip()) for w in adb_only
            }
            self._recipe_tooltip_before_target_lock = saved.get(
                self.recipe_combo, self.recipe_combo.toolTip()
            )

        for widget in adb_only:
            widget.setEnabled(not browser)
            widget.setToolTip(
                "Không dùng khi chạy trên trình duyệt."
                if browser
                else self._tooltips_before_target_lock[widget]
            )

        self.recipe_combo.setToolTip(
            "Bắt buộc khi chạy trên trình duyệt: luồng 'như cũ' được viết cho\n"
            "màn hình app Android, không có nghĩa trên một trang web."
            if browser
            else self._recipe_tooltip_before_target_lock
        )
        if not browser:
            # Trả các ô về đúng trạng thái mà kiểu chạy đang chọn quy định.
            self._on_run_mode_changed()

    def _refresh_browser_status(self):
        if self.run_target() != TARGET_BROWSER:
            return
        port = self.browser_port_input.value()
        if browser_backend.debugger_answers(port):
            self.browser_status_label.setText(
                f"Chrome đã sẵn sàng ở cổng {port}."
            )
        else:
            self.browser_status_label.setText(
                f"Chưa có Chrome nào mở cổng {port} - bấm 'Mở Chrome cho bot'."
            )

    def _on_open_chrome(self):
        port = self.browser_port_input.value()
        # Mở thẳng vào trang cần thao tác nếu ô 'Tab chứa' trông như một địa chỉ.
        hint = self.browser_url_input.text().strip()
        url = hint if "." in hint and " " not in hint else ""
        if url and not url.startswith("http"):
            url = "https://" + url

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok = browser_backend.launch_chrome(port=port, url=url)
        finally:
            QApplication.restoreOverrideCursor()

        self._refresh_browser_status()
        if ok:
            QMessageBox.information(
                self,
                "Chrome đã sẵn sàng",
                f"Chrome đang mở cổng {port} bằng profile riêng của bot:\n"
                f"{browser_backend.chrome_profile_dir()}\n\n"
                "Lần đầu dùng, hãy đăng nhập hệ thống kho trong cửa sổ vừa mở rồi "
                "mở đúng màn hình cần chạy. Chrome sẽ nhớ đăng nhập cho các lần sau.",
            )
            return

        QMessageBox.critical(
            self,
            "Không mở được Chrome",
            "Không khởi động được Chrome ở chế độ cho phép bot gắn vào.\n\n"
            "Thử tự chạy lệnh này trong cửa sổ lệnh để xem Chrome báo gì:\n\n"
            + " ".join(f'"{a}"' if " " in a else a
                       for a in browser_backend.chrome_command(port)),
        )

    def _on_run_mode_changed(self, *_):
        """
        Khóa (chứ không ẩn) những ô chế độ đang chọn không dùng tới.

        Ẩn đi thì người dùng tưởng app thiếu tính năng; khóa lại kèm tooltip thì
        thấy ngay là do đang ở chế độ khác.
        """
        mode = self.run_mode()
        is_session = mode in SESSION_MODES
        self.pick_box.setVisible(is_session)
        # Luồng theo phiên tự bấm Receive rồi tự quyết gõ gì vào đâu; mã sản phẩm
        # cố định chỉ có nghĩa khi người dùng mở sẵn màn hình quét.
        self.product_box.setVisible(not is_session)

        inbound = mode == MODE_INBOUND
        self.pick_box.setTitle(
            "Nhập hàng theo mã check-in" if inbound else "Xuất kho theo mã OR"
        )
        self.bill_column_label.setText(
            "Cột mã check-in" if inbound else "Cột mã OR"
        )

        # Luồng chạy theo phiên tự quyết định gõ gì vào đâu theo màn hình app,
        # nên mấy ô này không có chỗ dùng. Tote/bin thì chỉ luồng pick mới hỏi.
        locked = {w: is_session for w in (
            self.enter_mode_combo,
            self.enter_delay_input,
            self.error_keywords_input,
            self.not_found_keywords_input,
            self.success_keywords_input,
            self.recipe_combo,
            self.background_check,
            self.verify_check,
            self.dry_run_check,
            self.dry_run_count,
        )}
        locked[self.tote_input] = inbound
        locked[self.bin_input] = inbound
        # Cột MVĐ là thứ đi kèm mã OR của template xuất kho; phiếu check-in
        # không có khái niệm đó.
        locked[self.ref_column_input] = inbound
        # Hộp thoại "chưa có phiên check-in" chỉ có ở luồng nhập hàng.
        locked[self.create_session_check] = not inbound

        # Nhớ tooltip gốc để trả lại khi đổi chế độ - mấy ô này có phần giải
        # thích riêng, đè lên rồi không khôi phục là mất luôn.
        if not hasattr(self, "_tooltips_before_lock"):
            self._tooltips_before_lock = {w: w.toolTip() for w in locked}

        mode_name = self.run_mode_combo.currentText()
        for widget, is_locked in locked.items():
            widget.setEnabled(not is_locked)
            widget.setToolTip(
                f"Không dùng ở chế độ '{mode_name}'."
                if is_locked
                else self._tooltips_before_lock[widget]
            )

        if is_session:
            self.column_input.setToolTip("Cột chứa số seri.")
            self.instances_list.setToolTip(
                "Chế độ chạy theo phiên chỉ chạy trên MỘT máy ảo: một phiên là một\n"
                "tài khoản đang thao tác kho, chia ra nhiều máy là làm nhầm đơn."
            )

    def _on_refresh_instances(self):
        if not self.pages.widget(1).isEnabled():
            return
        instances = list_ldplayer_instances()
        self.instances_list.clear()
        if not instances:
            QMessageBox.information(
                self,
                "No instances found",
                "Could not read instance list from ldconsole.exe. "
                "You can still type a window/instance name in the fallback field below.",
            )
            return
        for inst in instances:
            label = f"{inst['name']} ({'running' if inst['running'] else 'stopped'})"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, inst["name"])
            self.instances_list.addItem(item)

    def _get_selected_instances(self) -> list[str]:
        names = []
        for i in range(self.instances_list.count()):
            item = self.instances_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                names.append(item.data(Qt.ItemDataRole.UserRole))
        if names:
            return names
        manual = self.window_title_input.text().strip()
        return [manual] if manual else ["LDPlayer"]

    # ---------------------------------------------------------------- run lifecycle

    def _on_start(self):
        if self.report_writer and self.report_writer.isRunning():
            return
        if (getattr(self, "_timer", None) and self._timer.isActive()) or (
                self.loader_thread and self.loader_thread.isRunning()):
            return
        if any(w.isRunning() for w in self.workers) or self._finishing or (
                self.result_writer and self.result_writer.isRunning()):
            return
        if not self.excel_path:
            QMessageBox.warning(self, "Missing file", "Please select an Excel file first.")
            return

        if self.run_mode() in SESSION_MODES:
            self._start_pick_run()
            return

        if not self._product_code_is_usable():
            return

        if self.run_target() == TARGET_BROWSER:
            if not self._preflight_browser_check():
                return
        elif self.background_check.isChecked() and not self._preflight_adb_check():
            return

        self.all_records.clear()
        self.stat_not_found_lbl.setText("0")
        self.export_report_btn.setEnabled(False)
        self.retry_errors_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Reading Excel file...")

        # A recipe may reference other cells on the row ({cell:B}), which needs
        # the wider read; the classic path only needs the serial column.
        self.active_recipe_steps = self._selected_recipe_steps()

        self.loader_thread = ExcelLoaderWorker(
            self.excel_path,
            self.sheet_combo.currentText().strip() or None,
            self.column_input.text().strip() or "H",
            self.start_row_input.value(),
            self.end_row_input.value(),
            with_cells=bool(self.active_recipe_steps),
        )
        self.loader_thread.finished.connect(self._on_excel_loaded)
        self.loader_thread.error.connect(self._on_excel_load_error)
        self.pages.widget(1).setEnabled(False)
        self.pages.widget(2).setEnabled(False)
        self.loader_thread.start()

    def _product_code_is_usable(self) -> bool:
        """
        Chặn hai kiểu cấu hình làm mã sản phẩm bị bỏ qua trong im lặng.

        Cả hai đều chạy trót lọt tới hết file rồi mới lộ ra là app không nhận
        được gì - thà không cho bắt đầu còn hơn quét hỏng cả phiên nhận hàng.
        """
        if not self.product_code_input.text().strip():
            return True

        if self.enter_mode_combo.currentData() == "none":
            QMessageBox.warning(
                self, "Mã sản phẩm cần phím xác nhận",
                "Đang đặt Confirm key = 'No Enter (paste only)', nên mã sản phẩm "
                "chỉ nằm trong ô chứ không được gửi đi - serial gõ tiếp sẽ nối "
                "vào sau nó.\n\nChọn 'Keyboard Enter' rồi chạy lại.",
            )
            return False

        if self.recipe_combo.currentData():
            QMessageBox.warning(
                self, "Kịch bản không dùng mã sản phẩm",
                f"Đang chọn kịch bản '{self.recipe_combo.currentText()}'. Kịch bản "
                "tự định nghĩa chuỗi thao tác nên bot chạy theo nó và BỎ QUA ô "
                "mã sản phẩm.\n\nChọn kịch bản 'Mặc định', hoặc tự thêm bước "
                "'Gõ chữ' cho mã sản phẩm vào chính kịch bản đó.",
            )
            return False

        return True

    # ---------------------------------------------- chế độ chạy theo phiên

    def _session_unit(self) -> str:
        """Tên đơn vị công việc, để mọi thông báo gọi đúng thứ người dùng đang chạy."""
        return UNIT_INBOUND if self.run_mode() == MODE_INBOUND else UNIT_PICK

    def _start_pick_run(self):
        unit = self._session_unit()
        inbound = self.run_mode() == MODE_INBOUND
        try:
            groups, warnings = read_bill_groups(
                self.excel_path,
                self.sheet_combo.currentText().strip() or None,
                self.bill_column_input.text().strip() or "A",
                self.column_input.text().strip() or "B",
                self.start_row_input.value(),
                self.end_row_input.value() or None,
                ref_column="" if inbound else self.ref_column_input.text().strip(),
                code_label=unit,
            )
        except ExcelReadError as e:
            QMessageBox.critical(self, "Lỗi đọc Excel", str(e))
            return

        if not groups:
            QMessageBox.information(
                self, "Không có dữ liệu",
                f"Không đọc được {unit} nào. Kiểm tra lại {self.bill_column_label.text().lower()}, "
                "cột serial và dòng bắt đầu.",
            )
            return

        dialog = BillPreviewDialog(
            groups, warnings, self, unit=unit,
            code_header="Mã check-in" if inbound else "Mã OR",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        groups = dialog.selected_groups()
        if not groups:
            return

        groups = self._prepare_journal(groups, self.run_mode())
        if groups is None:
            return
        if not self._prepare_result_writer():
            self._reset_controls()
            return

        self._save_last_state()
        if not groups:
            self._finish_resume_only()
            return
        self._launch_pick_run(groups)

    def _launch_pick_run(self, groups: list[dict]):
        self.pick_groups = groups
        self.pick_bill_results = list(self._resumed_bills)
        self.all_records = list(self._resumed_records)
        # Bộ đếm cộng dồn theo id(worker); còn sót worker của lượt trước là số
        # liệu STATS bị thổi lên ngay từ dòng đầu tiên.
        self.worker_stats.clear()
        self.stat_not_found_lbl.setText("0")
        self.log_list.clear()

        unit = self._session_unit()
        total_serials = sum(len(g["rows"]) for g in groups)
        self._current_run_total = total_serials + len(self._resumed_records)
        self._run_finished_monotonic = None
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0 / {len(groups)} {unit}")
        self._update_stats(0, 0, 0, 0, total_serials)

        instance = self._get_selected_instances()[0]
        if self.run_mode() == MODE_INBOUND:
            runner_cls = InboundRunner
            config = InboundConfig(
                check_expected_count=self.check_count_check.isChecked(),
                capture_screenshot=True,
                create_missing_session=self.create_session_check.isChecked(),
            )
        else:
            runner_cls = PickRunner
            config = PickConfig(
                tote=self.tote_input.text().strip() or DEFAULT_TOTE,
                # Ô trống ở đây là lựa chọn có ý nghĩa ("đi theo vị trí app chỉ"),
                # nên không rơi về mặc định như ô tote.
                bin_code=self.bin_input.text().strip(),
                check_expected_count=self.check_count_check.isChecked(),
                capture_screenshot=True,
            )

        worker = PickWorker(
            groups, instance, config, screenshot_dir=SCREENSHOT_DIR, runner_cls=runner_cls,
            journal=self.journal, run_id=self.run_id,
        )
        worker.progress.connect(self._on_pick_progress)
        worker.bill_started.connect(self._on_bill_started)
        worker.step_info.connect(self.status_progress.setText)
        worker.log_entry.connect(self._on_log_entry)
        worker.stats_update.connect(
            lambda d, s, e, u, w=worker: self._on_worker_stats(w, d, s, e, u)
        )
        worker.result_ready.connect(self._on_result_ready)
        worker.bill_done.connect(self.pick_bill_results.append)
        worker.stopped.connect(self._on_pick_stopped)
        worker.finished.connect(lambda w=worker: self._on_pick_finished(w))

        self.workers = [worker]
        self.is_paused = False
        # Tạm dừng ở chế độ này có hiệu lực ở điểm an toàn kế tiếp (hết mã OR
        # đang chạy, hoặc hết serial đang quét) chứ không cắt ngang giữa một
        # bước - xem PickWorker._wait_if_paused.
        self.pause_btn.setText("Pause")
        self.tb_pause.setText("Tạm dừng")
        self.run_started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.start_btn.setEnabled(False)
        self.tb_start.setEnabled(False)
        # Cấu hình đã được chốt vào `config` ở trên; khóa cả khung lại để sửa
        # giữa chừng không thành ra "tưởng đã đổi mà bot vẫn chạy mã cũ".
        self.pick_box.setEnabled(False)
        self._set_tray_state("running")
        self._start_countdown(
            self._start_pick_worker,
            "Bắt đầu sau {}s...",
            final_format=f"0 / {len(groups)} {unit}",
        )

    def _start_pick_worker(self):
        # Đồng hồ ước tính chỉ được bắt đầu khi worker chạy thật, nếu không 3
        # giây đếm ngược bị tính vào tốc độ và con số "còn ~" sai ngay từ đầu.
        self._run_start_monotonic = time.monotonic()
        for worker in self.workers:
            worker.start()

    def _on_pick_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        text = f"{done} / {total} {self._session_unit()}"
        eta = self._pick_eta_text(done, total)
        self.progress_bar.setFormat(f"{text}{eta}")

    def _pick_eta_text(self, done: int, total: int) -> str:
        """
        Ước tính thời gian còn lại theo tốc độ thực tế từ đầu lượt chạy.

        Lấy trung bình cả lượt chứ không lấy mã gần nhất: thời gian mỗi mã chênh
        nhau rất nhiều (mã không tìm thấy ~3s, mã nhiều serial cả phút), nhìn
        con số nhảy loạn thì không dựa vào đâu mà sắp việc được.
        """
        remaining = total - done
        if done <= 0 or remaining <= 0 or not self._run_start_monotonic:
            return ""
        elapsed = time.monotonic() - self._run_start_monotonic
        if elapsed <= 0:
            return ""
        return f"  ·  còn ~{_format_duration(elapsed / done * remaining)}"

    def _on_bill_started(self, bill: str, serial_count: int):
        unit = self._session_unit().capitalize()
        item = QListWidgetItem(f"▶ {unit} {bill} ({serial_count} serial)")
        item.setForeground(QColor("#4fc3f7"))
        item.setData(Qt.ItemDataRole.UserRole, "OK")
        self.log_list.addItem(item)
        self.log_list.scrollToBottom()

    def _on_pick_stopped(self, message: str, screenshot_path: str):
        """
        Dừng nghĩa là app còn kẹt trong một phiên dở. Nói thẳng điều đó ra, vì
        chạy lại khi phiên cũ chưa đóng sẽ hỏng tiếp đơn sau.
        """
        unit = self._session_unit()
        worker = self.workers[0] if self.workers else None
        done_bills = list(worker.done_bills) if worker else []
        text = f"{message}\n\n"
        if done_bills:
            text += f"Đã xong {len(done_bills)} {unit}, chỗ dừng đã được ghi nhớ.\n\n"
        text += (
            f"Trên LDPlayer nhiều khả năng còn một phiên "
            f"{'nhận hàng' if self.run_mode() == MODE_INBOUND else 'lấy hàng'} "
            "đang dở. Hãy đóng hoặc hoàn tất phiên đó trước khi chạy lại."
        )
        if screenshot_path:
            text += f"\n\nẢnh màn hình lúc dừng:\n{screenshot_path}"

        self._set_tray_state("error")
        QMessageBox.critical(self, "Phiên chạy đã dừng", text)

    def _on_pick_finished(self, worker):
        self._on_all_finished()
        if not self.result_writer:
            self.pick_box.setEnabled(True)

    def _on_excel_loaded(self, raw):
        if not raw:
            QMessageBox.information(self, "No data", "No serials were found in the selected file.")
            self._reset_controls()
            self.progress_bar.setFormat("0 / 0")
            return

        full_items = [
            SerialItem(row=r["row"], value=r["value"], cells=r.get("cells", {}))
            for r in raw
        ]

        self.session_done_rows = set()
        if not full_items:
            QMessageBox.information(self, "Nothing to do", "All rows in range were already processed.")
            self._reset_controls()
            self.progress_bar.setFormat("0 / 0")
            return

        dialog = PreviewDialog(full_items, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._reset_controls()
            self.progress_bar.setFormat("0 / 0")
            return

        selected_items = dialog.selected_items()
        if not selected_items:
            QMessageBox.information(self, "Nothing selected", "No serials were selected to run.")
            self._reset_controls()
            self.progress_bar.setFormat("0 / 0")
            return

        if self.dry_run_check.isChecked():
            selected_items = selected_items[:self.dry_run_count.value()]

        selected_items = self._prepare_journal(selected_items, MODE_SERIAL)
        if selected_items is None:
            self._reset_controls()
            return
        if not self._prepare_result_writer():
            self._reset_controls()
            return

        self._save_last_state()
        if not selected_items:
            self._finish_resume_only()
            return
        self._launch_run(selected_items)

    def _finish_resume_only(self):
        self.all_records = list(self._resumed_records)
        self.pick_bill_results = list(self._resumed_bills)
        self.workers = []
        self._run_complete = True
        self._finishing = True
        self.start_btn.setEnabled(False)
        self.tb_start.setEnabled(False)
        self.result_writer.finalize()

    def _prepare_journal(self, selected, mode):
        """Match only the exact reviewed selection, never a path-only checkpoint."""
        self._resumed_records = []
        self._resumed_bills = []
        self._stop_requested = False
        if self.journal is None:
            self.journal = RunJournal()
        config = self._collect_profile_values()
        config["instances"] = self._get_selected_instances()
        config["recipe"] = [step.to_dict() for step in getattr(self, "active_recipe_steps", [])]
        # UI preferences do not alter the business workload identity.
        config = {k: v for k, v in config.items() if k not in ("theme",)}
        rows = ([{"row": item.row, "value": item.value, "cells": item.cells} for item in selected]
                if mode == MODE_SERIAL else selected)
        sheet = self.sheet_combo.currentText().strip() or None
        self._run_source_path = self.excel_path
        self._run_sheet = sheet
        key = fingerprint(self.excel_path, sheet, mode, rows, config)
        previous = self.journal.latest(key)
        self._release_untouched_bills()
        other_pending =[op for op in self.journal.pending_for_source(self.excel_path)
                         if not previous or op["run_id"] != previous["id"]]
        if other_pending:
            QMessageBox.warning(self, "Còn thao tác chưa đối chiếu",
                "Dữ liệu hoặc cấu hình đã đổi nhưng file này còn thao tác chưa rõ kết quả từ lượt trước.\n"
                "Bấm 'Đối chiếu tiến độ', kiểm tra trạng thái trên app trước khi chạy dữ liệu mới.")
            return None
        import json
        if previous and (previous["state"] != "complete" or not previous["excel_saved"]):
            pending = self.journal.pending(previous["id"])
            if pending:
                details = "\n".join(f"{op['kind']}: dòng {op['row'] or '-'}, mã {op['bill'] or '-'}" for op in pending[:12])
                answer = QMessageBox.warning(self, "Cần đối chiếu thao tác chưa rõ kết quả",
                    "Có thao tác đã bắt đầu nhưng chưa xác nhận xong.\n" + details +
                    "\n\nKiểm tra và xử lý phiên dở trên app trước. Chọn Yes chỉ khi đã đối chiếu; "
                    "bot sẽ BỎ các dòng/mã đang dở, ghi chưa xác minh và tiếp tục phần chưa chạy. "
                    "Chọn Cancel để giữ nguyên và kiểm tra.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Yes:
                    return None
                pending_bills = {op["bill"] for op in pending if op["bill"]}
                pending_rows = {op["row"] for op in pending if op["row"] is not None}
                known = {r["row"] for r in self.journal.results(previous["id"])}
                for group in (selected if mode != MODE_SERIAL else []):
                    if group["bill"] in pending_bills:
                        for row in group["rows"]:
                            if row["row"] not in known:
                                self.journal.record_result(previous["id"], {
                                    "row": row["row"], "serial": row["value"], "bill": group["bill"],
                                    "status": "UNKNOWN", "verification": UNVERIFIED,
                                    "message": "Đã đối chiếu thủ công; bỏ phiên đang dở", "response_text": "",
                                    "screenshot_path": None, "reason": "", "time": ""})
                        self.journal.complete_bill(previous["id"], {
                            "bill": group["bill"], "ref": group.get("ref", ""), "expected": len(group["rows"]),
                            "picked": sum(r["status"] == "OK" and r.get("verification") == CONFIRMED
                                          for r in self.journal.results(previous["id"]) if r.get("bill") == group["bill"]),
                            "status": "UNKNOWN", "message": "Phiên đã đối chiếu thủ công"})
                for item in (selected if mode == MODE_SERIAL else []):
                    if item.row in pending_rows:
                        self.journal.record_result(previous["id"], {
                            "row": item.row, "serial": item.value, "status": "UNKNOWN", "verification": UNVERIFIED,
                            "message": "Đã đối chiếu thủ công; bỏ thao tác chưa rõ", "response_text": "",
                            "screenshot_path": None, "reason": "", "time": ""})
                for operation in pending:
                    self.journal.resolve(operation["id"], "reviewed")
                answer = QMessageBox.StandardButton.Yes
            else:
                answer = QMessageBox.question(self, "Tiếp tục lượt trước?",
                    "Có tiến độ đã lưu cho đúng dữ liệu và cấu hình này.\n"
                    "Yes: bỏ phần đã xử lý và tiếp tục. No: bắt đầu một lượt mới.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes)
            if answer == QMessageBox.StandardButton.Cancel:
                return None
            if answer == QMessageBox.StandardButton.Yes:
                self.run_id = previous["id"]
                self._resumed_records = self.journal.results(self.run_id)
                self._resumed_bills = self.journal.bills(self.run_id)
                self._result_sheet = json.loads(previous["metadata"])["result_sheet"]
                self.journal.set_state(self.run_id, "running")
                if mode == MODE_SERIAL:
                    done = {r["row"] for r in self._resumed_records}
                    return [item for item in selected if item.row not in done]
                done = {b["bill"] for b in self._resumed_bills}
                return [g for g in selected if g["bill"] not in done]
        legacy = load_session(self.excel_path)
        if legacy and not previous:
            QMessageBox.information(self, "Checkpoint cũ", "Checkpoint cũ chỉ khớp đường dẫn file. "
                                    "Bot không tự bỏ dòng; kiểm tra danh sách xem trước trước khi chạy.")
        import uuid
        self._result_sheet = f"Ket qua {datetime.now():%y%m%d_%H%M%S}_{uuid.uuid4().hex[:4]}"
        self.run_id = self.journal.create_run(key, self.excel_path, mode,
            {"sheet": sheet, "config": config, "selected": rows, "result_sheet": self._result_sheet})
        logger.info("Run metadata: run_id=%s version=%s mode=%s instances=%s config=%s",
                    self.run_id, APP_VERSION, mode, self._get_selected_instances(), config)
        return selected

    def _release_untouched_bills(self):
        """
        Mã dừng giữa chừng khi mới gõ ô tìm kiếm thì app chưa thấy nó: không có
        gì để đối chiếu, và đánh dấu "đã đối chiếu" sẽ làm lượt sau bỏ qua mã đó.
        """
        released = self.journal.release_untouched(source=self.excel_path)
        if released:
            logger.info("Mã chưa mở phiên nào trên app, lượt này chạy lại từ đầu: %s", ", ".join(released))
        return released

    def _review_unresolved_progress(self):
        if any(w.isRunning() for w in self.workers) or self._finishing or not self.excel_path:
            return
        if self.journal is None:
            self.journal = RunJournal()
        released = self._release_untouched_bills()
        pending = self.journal.pending_for_source(self.excel_path)
        if not pending:
            note = (f"\n\n{len(released)} mã dừng trước khi mở phiên trên app nên không cần đối chiếu, "
                    "lần chạy tới bot sẽ chạy lại các mã đó.") if released else ""
            QMessageBox.information(self, "Tiến độ", "Không có thao tác đang chờ đối chiếu cho file này." + note)
            return
        import json
        details = "\n".join(f"Dòng {op['row'] or '-'} / {op['bill'] or '-'}: {op['kind']} {op['payload']}"
                            for op in pending[:15])
        answer = QMessageBox.warning(self, "Đối chiếu trên app",
            details + "\n\nKiểm tra kết quả trên app, hoàn tất hoặc đóng phiên dở. "
            "Chỉ chọn Yes nếu đã đối chiếu toàn bộ thao tác này và chấp nhận chạy lại dữ liệu được chọn ở lượt mới. "
            "Bot sẽ ghi thao tác cũ là chưa xác minh, không tự biến thành thành công.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        for operation in pending:
            if operation["row"] is not None:
                payload = json.loads(operation["payload"])
                records = {r["row"]: r for r in self.journal.results(operation["run_id"])}
                old = records.get(operation["row"], {})
                self.journal.record_result(operation["run_id"], {
                    **old, "row": operation["row"], "serial": old.get("serial", payload.get("serial", "")),
                    "status": "UNKNOWN", "verification": UNVERIFIED,
                    "message": "Đã đối chiếu thủ công; kết quả tự động chưa xác minh"})
            self.journal.resolve(operation["id"], "reviewed")

    def _prepare_result_writer(self) -> bool:
        """
        Dựng chỗ ghi kết quả (một sheet mới trong chính file nguồn).

        Trả False nghĩa là người dùng đã chọn hủy phiên chạy. Ghi hụt thì vẫn
        chạy tiếp - mất kết quả trong Excel còn hơn dừng giữa một phiên kho.
        """
        sheet = self.sheet_combo.currentText().strip() or None

        formulas = find_formula_cells(self.excel_path, sheet)
        if formulas:
            answer = QMessageBox.warning(
                self,
                "File nguồn có ô công thức",
                f"Sheet dữ liệu đang có công thức (ví dụ: {', '.join(formulas)}).\n\n"
                "Bot ghi kết quả vào chính file này, mà thư viện ghi Excel không "
                "giữ được GIÁ TRỊ ĐÃ TÍNH của ô công thức - công thức còn nguyên "
                "nhưng ô sẽ rỗng cho tới khi bạn mở file bằng Excel và lưu lại.\n\n"
                "Nếu cột serial là công thức thì lần chạy sau bot đọc ra rỗng và "
                "bỏ qua hết các dòng.\n\n"
                "Vẫn chạy?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False

        if self.result_writer and self.result_writer.isRunning():
            QMessageBox.information(self, "Đang lưu", "Chờ tác vụ lưu Excel kết thúc trước khi chạy mới.")
            return False
        self.result_writer = ResultWriterWorker(self.excel_path, data_sheet=sheet,
                                               result_sheet=self._result_sheet, run_id=self.run_id)
        self.result_writer.save_status.connect(self._on_excel_save_status)
        self.result_writer.finished.connect(self._on_writer_finished)
        self.result_writer.start()
        for record in self._resumed_records:
            self.result_writer.add_record(record)
        return True

    def _preflight_browser_check(self) -> bool:
        """
        Chặn hai kiểu sai trước khi đọc Excel, vì cả hai đều làm hỏng cả lượt chạy.

        Chrome chưa mở cổng: bot không gắn được vào đâu cả. Chưa chọn kịch bản:
        luồng 'như cũ' gõ vào ô đang focus rồi đọc cây view Android - trên trang
        web nó sẽ chạy mà chẳng làm gì đúng.
        """
        port = self.browser_port_input.value()
        if not browser_backend.debugger_answers(port):
            self._refresh_browser_status()
            QMessageBox.critical(
                self,
                "Chưa có Chrome để gắn vào",
                f"Không thấy Chrome nào mở cổng gỡ lỗi {port}.\n\n"
                "Bấm 'Mở Chrome cho bot', đăng nhập rồi mở đúng màn hình cần chạy, "
                "sau đó bấm Start lại.",
            )
            return False

        if not self._selected_recipe_steps():
            QMessageBox.critical(
                self,
                "Chạy trên trình duyệt cần một kịch bản",
                "Hãy chọn một kịch bản ở ô 'Kịch bản'.\n\n"
                "Luồng 'như cũ' được viết cho màn hình app Android: nó gõ vào ô "
                "đang focus rồi đọc cây view qua ADB, nên trên một trang web sẽ "
                "không làm đúng việc gì cả.\n\n"
                "Vào tab Kịch bản và dựng các bước 'Điền ô (web)', 'Bấm nút (web)', "
                "'Chờ phần tử (web)', 'Đọc chữ (web)'.",
            )
            return False

        return True

    def _preflight_adb_check(self) -> bool:
        """In background mode there is no keyboard fallback, so verify every target
        instance answers over ADB before committing to a run."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # adb_answers hỏi lại một lần: lệnh ADB đầu tiên sau khi LDPlayer vừa
            # mở hay rơi đúng lúc adb server còn đang tự khởi động, kết luận ngay
            # từ lần hụt đó là chặn phiên chạy với lý do sai.
            dead = [
                name for name in self._get_selected_instances()
                if not adb_answers(AdbClient(name, timeout=5))
            ]
        finally:
            QApplication.restoreOverrideCursor()

        if not dead:
            return True

        QMessageBox.critical(
            self,
            "Background mode: ADB không sẵn sàng",
            "Không kết nối được ADB tới: " + ", ".join(f"'{n}'" for n in dead) + "\n\n"
            "Background mode không cho phép gõ bàn phím thay thế, nên bot chưa chạy.\n\n"
            "Kiểm tra: LDPlayer đã khởi động xong chưa? Tên instance có đúng không "
            "(bấm Refresh để lấy danh sách)?",
        )
        return False

    def _on_excel_load_error(self, err_msg):
        self._reset_controls()
        self.progress_bar.setFormat("0 / 0")
        QMessageBox.critical(self, "Excel read error", err_msg)

    def _launch_run(self, serial_items: list[SerialItem]):
        self._stop_requested = False
        self._finishing = False
        self.serials_cache = serial_items
        self.all_records = list(self._resumed_records)
        self._current_run_total = len(serial_items) + len(self._resumed_records)
        self._run_finished_monotonic = None
        self.log_list.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0 / {len(serial_items)}")
        self._update_stats(0, 0, 0, 0, len(serial_items))

        target = self.run_target()
        if target == TARGET_BROWSER:
            # Một cửa sổ Chrome là một phiên đăng nhập; chia serial ra nhiều
            # worker chỉ khiến chúng tranh nhau đúng một tab.
            instance_names = [self.window_title_input.text().strip() or "Chrome"]
            chunks = [serial_items]
        else:
            instance_names = self._get_selected_instances()
            chunks = split_serials(serial_items, len(instance_names))
            instance_names = instance_names[:len(chunks)]

        self.workers = []
        self.worker_progress_bars.clear()
        self.worker_stats.clear()
        self.worker_finished_count = 0

        self._clear_instances_ui()
        self.instances_frame.setVisible(len(chunks) > 1)

        for instance_name, chunk in zip(instance_names, chunks):
            worker = BotWorker(
                serials=chunk,
                instance_name=instance_name,
                delay_seconds=self.delay_input.value(),
                enter_mode=self.enter_mode_combo.currentData() or "enter",
                enter_delay_seconds=self.enter_delay_input.value(),
                prefer_adb_input=self.adb_input_check.isChecked(),
                background_mode=self.background_check.isChecked(),
                verify_result=self.verify_check.isChecked(),
                success_keywords=self.success_keywords_input.text().strip(),
                error_keywords=self.error_keywords_input.text().strip(),
                not_found_keywords=self.not_found_keywords_input.text().strip(),
                response_timeout=self.response_timeout_input.value(),
                product_code=self.product_code_input.text().strip(),
                product_code_delay=self.product_delay_input.value(),
                capture_screenshot=self.screenshot_check.isChecked(),
                screenshot_dir=SCREENSHOT_DIR,
                recipe_steps=getattr(self, "active_recipe_steps", None),
                recipe_name=self.recipe_combo.currentText()
                if self.recipe_combo.currentData() else "",
                journal=self.journal, run_id=self.run_id,
                run_target=target,
                browser_port=self.browser_port_input.value(),
                browser_url=self.browser_url_input.text().strip(),
            )
            worker.progress.connect(lambda done, total, w=worker: self._on_worker_progress(w, done, total))
            worker.log_entry.connect(self._on_log_entry)
            worker.result_ready.connect(self._on_result_ready)
            worker.stats_update.connect(lambda d, s, e, u, w=worker: self._on_worker_stats(w, d, s, e, u))
            worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
            worker.error_occurred.connect(self._on_error)
            worker.backend_info.connect(self._on_backend_info)

            self.workers.append(worker)
            if len(chunks) > 1:
                self._add_instance_progress_row(worker, instance_name, len(chunk))

        self.is_paused = False
        self.pause_btn.setText("Pause")
        self.run_started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._run_start_monotonic = time.monotonic()
        self._start_countdown(self._start_all_workers, "Starting in {}s...")

    def _start_all_workers(self):
        for worker in self.workers:
            worker.start()
        if self.run_target() == TARGET_BROWSER:
            backend = f"Chrome (cổng {self.browser_port_input.value()})"
        else:
            backend = "ADB" if self.adb_input_check.isChecked() else "Bàn phím"
            if self.background_check.isChecked():
                backend += " (nền)"
        self.status_backend.setText(f"Backend: {backend}")
        self._set_connection_status(True)
        self._set_tray_state("running")

    def _clear_instances_ui(self):
        while self.instances_progress_layout.count():
            child = self.instances_progress_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _add_instance_progress_row(self, worker: BotWorker, instance_name: str, total: int):
        row = QHBoxLayout()
        label = QLabel(f"{instance_name} (0/{total})")
        label.setMinimumWidth(160)
        bar = QProgressBar()
        bar.setValue(0)
        bar.setFormat(f"0 / {total}")
        row.addWidget(label)
        row.addWidget(bar, stretch=1)
        wrapper = QWidget()
        wrapper.setLayout(row)
        self.instances_progress_layout.addWidget(wrapper)
        self.worker_progress_bars[id(worker)] = (bar, label, instance_name)

    # ---------------------------------------------------------------- pause / stop / retry

    def _on_pause_resume(self):
        if not self.workers:
            return
        if self.is_paused:
            self.is_paused = False
            self.pause_btn.setText("Pause")
            self.tb_pause.setText("Tạm dừng")
            self._set_tray_state("running")
            self._start_countdown(self._resume_all_workers, "Resuming in {}s...")
        else:
            for worker in self.workers:
                worker.pause()
            self.pause_btn.setText("Resume")
            self.tb_pause.setText("Tiếp tục")
            self.is_paused = True
            self._set_tray_state("paused")

    def _resume_all_workers(self):
        for worker in self.workers:
            worker.resume()

    def _start_countdown(self, callback, msg_template, final_format=None):
        """
        Đếm ngược 3 giây rồi mới chạy `callback`.

        `final_format` là dòng chữ trả lại cho thanh tiến độ khi đếm xong; để
        trống thì lấy số liệu ở khung STATS như cũ.
        """
        self.start_btn.setEnabled(False)
        self.tb_start.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.tb_stop.setEnabled(True)
        self.pages.widget(1).setEnabled(False)
        self.pages.widget(2).setEnabled(False)

        self._countdown_val = 3
        self._countdown_final_format = final_format
        self.progress_bar.setFormat(msg_template.format(self._countdown_val))

        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self._on_countdown_tick(callback, msg_template))
        self._timer.start(1000)

    def _on_countdown_tick(self, callback, msg_template):
        self._countdown_val -= 1
        if self._countdown_val > 0:
            self.progress_bar.setFormat(msg_template.format(self._countdown_val))
        else:
            self._timer.stop()
            self.pause_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.tb_start.setEnabled(False)
            self.tb_pause.setEnabled(True)
            self.tb_stop.setEnabled(True)
            self.progress_bar.setFormat(
                self._countdown_final_format or self.stat_total_lbl.text()
            )
            callback()

    def _on_stop(self):
        if getattr(self, "_timer", None) and self._timer.isActive():
            self._timer.stop()
            self._stop_requested = True
            for worker in self.workers:
                worker.stop()
            if not any(worker.isRunning() for worker in self.workers):
                self._on_all_finished()
                return
        if not any(worker.isRunning() for worker in self.workers):
            self._retry_excel_save()
            return
        self._stop_requested = True
        self.start_btn.setEnabled(False)
        self.tb_start.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.tb_pause.setEnabled(False)
        self.status_progress.setText("Đang dừng...")
        for worker in self.workers:
            worker.stop()

    def _on_retry_errors(self):
        if self.run_mode() != MODE_SERIAL:
            QMessageBox.information(self, "Chạy lại theo phiên", "Chọn lại mã OR/check-in trong lượt mới "
                                    "sau khi đối chiếu trạng thái phiên trên app.")
            return
        error_items = [
            SerialItem(row=r["row"], value=r["serial"])
            for r in self.all_records
            if r["status"] == "ERROR"
        ]
        if not error_items:
            QMessageBox.information(self, "No errors", "There are no error rows to retry.")
            return
        self.retry_errors_btn.setEnabled(False)
        error_items = self._prepare_journal(error_items, MODE_SERIAL)
        if error_items is None or not self._prepare_result_writer():
            return
        if not error_items:
            self._finish_resume_only()
            return
        self._launch_run(error_items)

    # ---------------------------------------------------------------- signal handlers

    def _on_worker_progress(self, worker, done, total):
        entry = self.worker_progress_bars.get(id(worker))
        if entry:
            bar, label, name = entry
            pct = int(done / total * 100) if total else 0
            bar.setValue(pct)
            bar.setFormat(f"{done} / {total}")
            label.setText(f"{name} ({done}/{total})")
        self._update_aggregate_progress()

    def _update_aggregate_progress(self):
        total_done = sum(s[0] for s in self.worker_stats.values()) if self.worker_stats else 0
        newly_done = total_done
        total_done += len(self._resumed_records)
        total = self._current_run_total
        pct = int(total_done / total * 100) if total else 0
        self.progress_bar.setValue(pct)

        eta_text = ""
        if self._run_start_monotonic and newly_done > 0:
            elapsed = time.monotonic() - self._run_start_monotonic - max(
                (getattr(w, "pause_seconds", 0) for w in self.workers), default=0)
            if elapsed > 0:
                rate_per_min = newly_done / elapsed * 60
                remaining = total - total_done
                eta_min = remaining / rate_per_min if rate_per_min > 0 else 0
                eta_text = f" | {rate_per_min:.0f}/min | ETA {eta_min:.0f}m"
        self.progress_bar.setFormat(f"{total_done} / {total}{eta_text}")
        self.status_progress.setText(f"{total_done} / {total}{eta_text}")
        if not self.is_paused:
            self._set_tray_state("running", f"{total_done}/{total}{eta_text}")

    def _on_backend_info(self, message):
        self.log_list.addItem(QListWidgetItem(f"[INFO] {message}"))
        self.log_list.scrollToBottom()

    def _on_log_entry(self, row, serial, status, message):
        icon = STATUS_ICON.get(status, status)
        color = STATUS_COLOR.get(status, "#e8e8f0")
        timestamp = datetime.now().strftime("%H:%M:%S")
        text = f"[{timestamp}] {icon}  Row {row} - {serial}   ({message})"
        item = QListWidgetItem(text)
        item.setForeground(QColor(color))
        item.setData(Qt.ItemDataRole.UserRole, status)
        self.log_list.addItem(item)
        self._apply_log_filter_to_item(item)
        self.log_list.scrollToBottom()

        if status != "OK":
            self.export_report_btn.setEnabled(True)

    def _apply_log_filter_to_item(self, item: QListWidgetItem):
        status = item.data(Qt.ItemDataRole.UserRole)
        search = self.log_search_input.text().strip().lower()
        wanted_status = self.log_filter_combo.currentText()
        visible = True
        if wanted_status != "All" and status != wanted_status:
            visible = False
        if search and search not in item.text().lower():
            visible = False
        item.setHidden(not visible)

    def _apply_log_filter(self):
        for i in range(self.log_list.count()):
            self._apply_log_filter_to_item(self.log_list.item(i))

    def _on_log_item_double_clicked(self, item: QListWidgetItem):
        row_text = item.text()
        for record in self.all_records:
            if f"Row {record['row']} " in row_text and record.get("screenshot_path"):
                from PyQt6.QtGui import QDesktopServices
                from PyQt6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(record["screenshot_path"])))
                return

    def _on_result_ready(self, result: dict):
        result.setdefault("verification", UNVERIFIED)
        existing = next((i for i, record in enumerate(self.all_records) if record["row"] == result["row"]), None)
        if existing is None:
            self.all_records.append(result)
        else:
            self.all_records[existing] = result
        # Workers commit before emitting this signal; the GUI only displays
        # and queues the Excel export, avoiding a second synchronous commit.
        if self.result_writer and self.result_writer.isRunning():
            self.result_writer.add_record(result)
        self.session_done_rows.add(result["row"])
        self.stat_not_found_lbl.setText(str(sum(r.get("reason") == REASON_NOT_FOUND for r in self.all_records)))
        self.stat_inferred_lbl.setText(str(sum(r.get("status") == "OK" and r.get("verification") == INFERRED
                                             for r in self.all_records)))

    def _save_session_snapshot(self):
        # Results and operation intentions are committed by the workers.
        if self.journal and self.run_id:
            self.journal.set_state(self.run_id, "stopped" if self._stop_requested else "running")

    def _on_worker_stats(self, worker, done, success, error, unknown):
        self.worker_stats[id(worker)] = (done, success, error, unknown)
        total_done = sum(s[0] for s in self.worker_stats.values())
        total_success = sum(s[1] for s in self.worker_stats.values())
        total_error = sum(s[2] for s in self.worker_stats.values())
        total_unknown = sum(s[3] for s in self.worker_stats.values())
        total_done += len(self._resumed_records)
        total_success += sum(r["status"] == "OK" and r.get("verification") == CONFIRMED for r in self._resumed_records)
        total_error += sum(r["status"] == "ERROR" for r in self._resumed_records)
        total_unknown += sum(r["status"] == "UNKNOWN" for r in self._resumed_records)
        self._update_stats(total_done, total_success, total_error, total_unknown, self._current_run_total)
        self._update_aggregate_progress()

    def _on_export_report(self):
        if self.report_writer and self.report_writer.isRunning():
            return
        if not self.all_records:
            QMessageBox.information(self, "No data", "There are no records to export yet.")
            return

        default_name = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        default_path = os.path.join(os.path.expanduser("~"), "Desktop", default_name)
        path, _ = QFileDialog.getSaveFileName(self, "Export report", default_path, "Excel Files (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        if os.path.normcase(os.path.abspath(path)) in {
                os.path.normcase(os.path.abspath(p)) for p in (self.excel_path, self._run_source_path) if p}:
            QMessageBox.warning(self, "Xuất báo cáo", "Chọn file báo cáo riêng để giữ nguyên workbook nguồn và kết quả.")
            return
        self.report_writer = ReportWriterWorker(path, self.all_records, self._build_summary(),
                                               self.pick_bill_results, self.run_mode() == MODE_INBOUND)
        self.report_writer.finished.connect(self._on_report_finished)
        self.export_report_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.tb_start.setEnabled(False)
        self.report_writer.start()

    def _on_report_finished(self):
        writer = self.report_writer
        self.export_report_btn.setEnabled(bool(self.all_records))
        if not any(w.isRunning() for w in self.workers) and not (
                self.result_writer and self.result_writer.isRunning()):
            if self._finishing:
                self._finish_controls()
            else:
                self.start_btn.setEnabled(True)
                self.tb_start.setEnabled(True)
        if writer.error:
            QMessageBox.critical(self, "Export failed", f"Could not export report:\n{writer.error}")
        else:
            QMessageBox.information(self, "Export complete", f"Exported {len(writer.records)} record(s) to:\n{writer.path}")

    def _build_summary(self) -> dict:
        done = len(self.all_records)
        success = sum(1 for r in self.all_records if r["status"] == "OK" and r.get("verification") == CONFIRMED)
        error = sum(1 for r in self.all_records if r["status"] == "ERROR")
        unknown = sum(1 for r in self.all_records if r["status"] == "UNKNOWN")

        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elapsed_seconds = 0
        rate_per_min = 0
        if self.run_started_at:
            started = datetime.strptime(self.run_started_at, "%Y-%m-%d %H:%M:%S")
            finished = datetime.strptime(finished_at, "%Y-%m-%d %H:%M:%S")
            elapsed_seconds = max(0, int((finished - started).total_seconds()))
            if self._run_start_monotonic:
                finish_tick = self._run_finished_monotonic or time.monotonic()
                paused = max((getattr(w, "pause_seconds", 0.0) for w in self.workers), default=0.0)
                elapsed_seconds = max(0, round(finish_tick - self._run_start_monotonic - paused, 2))
            if elapsed_seconds > 0:
                rate_per_min = round(done / elapsed_seconds * 60, 1)

        return {
            "total": self._current_run_total,
            "done": done,
            "success": success,
            "confirmed": success,
            "inferred": sum(r["status"] == "OK" and r.get("verification") == INFERRED for r in self.all_records),
            "unverified": sum(r.get("verification", UNVERIFIED) == UNVERIFIED for r in self.all_records),
            "error": error,
            "not_found": sum(
                1 for r in self.all_records if r.get("reason") == REASON_NOT_FOUND
            ),
            "unknown": unknown,
            "started_at": self.run_started_at or "",
            "finished_at": finished_at,
            "elapsed_seconds": elapsed_seconds,
            "rate_per_min": rate_per_min,
        }

    def _update_stats(self, done, success, error, unknown, total):
        self.stat_total_lbl.setText(f"{done} / {total}")
        self.stat_success_lbl.setText(str(success))
        self.stat_error_lbl.setText(str(error))
        self.stat_unknown_lbl.setText(str(unknown))

    def _on_worker_finished(self, worker):
        self.worker_finished_count += 1
        if self.worker_finished_count < len(self.workers):
            return
        self._on_all_finished()

    def _on_all_finished(self):
        self._run_finished_monotonic = time.monotonic()
        self._finishing = True
        self.start_btn.setEnabled(False)
        self.tb_start.setEnabled(False)
        self.status_progress.setText("Đang lưu kết quả...")
        self._run_complete = bool(self.workers) and all(getattr(w, "completion_state", "failed") == "complete"
                                                       for w in self.workers)
        if self.journal and self.run_id and self.journal.pending(self.run_id):
            self._run_complete = False
        if self.journal and self.run_id:
            self.journal.set_state(self.run_id, "complete" if self._run_complete else "stopped")
        if self.result_writer and self.result_writer.isRunning():
            self.result_writer.finalize()
        else:
            self._finish_controls()

    def _on_excel_save_status(self, saved, message):
        if self.sender() is not None and self.sender() is not self.result_writer:
            return
        self.status_progress.setText(message)
        if self.journal and self.run_id:
            # Only final flush marks the run export complete. New results may
            # already be in flight when a periodic-save signal reaches the UI.
            if not saved:
                self.journal.set_state(self.run_id, "complete" if getattr(self, "_run_complete", False) else "running",
                                       excel_saved=False)

    def _on_writer_finished(self):
        if self.sender() is not None and self.sender() is not self.result_writer:
            return
        if self.journal and self.run_id and self._finishing:
            self.journal.set_state(self.run_id, "complete" if getattr(self, "_run_complete", False) else "stopped",
                                   excel_saved=bool(self.result_writer and self.result_writer.saved))
        if self._finishing and not any(w.isRunning() for w in self.workers):
            self._finish_controls()

    def _finish_controls(self):
        if self.report_writer and self.report_writer.isRunning():
            self.status_progress.setText("Đang xuất báo cáo...")
            return
        self._finishing = False
        self._reset_controls()
        self.pick_box.setEnabled(True)
        self.retry_errors_btn.setEnabled(any(r["status"] == "ERROR" for r in self.all_records))
        self.export_report_btn.setEnabled(bool(self.all_records))
        saved = bool(self.result_writer and self.result_writer.saved)
        # Stop doubles as retry-save only after the run ended.
        self.stop_btn.setEnabled(not saved and bool(self.all_records))
        self.tb_stop.setEnabled(not saved and bool(self.all_records))
        self.stop_btn.setText("Stop" if saved else "Lưu lại Excel")
        self._set_tray_state("idle" if saved else "error")
        text = "Đã hoàn tất lượt chạy" if getattr(self, "_run_complete", False) else "Đã dừng; tiến độ được giữ để tiếp tục"
        self._notify_finished(text)

    def _retry_excel_save(self):
        if not self.all_records or (self.result_writer and self.result_writer.isRunning()):
            return
        self._finishing = True
        self.start_btn.setEnabled(False)
        self.tb_start.setEnabled(False)
        self.result_writer = ResultWriterWorker(self._run_source_path or self.excel_path,
            self._run_sheet, self._result_sheet, run_id=self.run_id)
        self.result_writer.save_status.connect(self._on_excel_save_status)
        self.result_writer.finished.connect(self._on_writer_finished)
        self.result_writer.start()
        for record in self.all_records:
            self.result_writer.add_record(record)
        self.result_writer.finalize()

    def _on_error(self, message):
        self._set_tray_state("error")
        self._set_connection_status(False)
        if self.tray_icon and not self.isVisible():
            self.tray_icon.showMessage(
                APP_NAME, message, QSystemTrayIcon.MessageIcon.Warning, 8000
            )
        uncertain = any(getattr(worker, "completion_state", "") == "uncertain" for worker in self.workers)
        if not uncertain:
            for worker in self.workers:
                worker.pause()
        QMessageBox.warning(
            self,
            "Automation error",
            message if uncertain else f"{message}\nBot paused. Please check LDPlayer and press Resume.",
        )
        if uncertain:
            return
        self.pause_btn.setText("Resume")
        self.tb_pause.setText("Tiếp tục")
        self.is_paused = True

    def _reset_controls(self):
        self.pages.widget(1).setEnabled(True)
        self.pages.widget(2).setEnabled(True)
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self.is_paused = False

        self.tb_start.setEnabled(True)
        self.tb_pause.setEnabled(False)
        self.tb_pause.setText("Tạm dừng")
        self.tb_stop.setEnabled(False)

    def closeEvent(self, event):
        if getattr(self, "_timer", None) and self._timer.isActive():
            self._on_stop()
        running = any(w.isRunning() for w in self.workers)

        # While a run is in progress the X button tucks the app into the tray
        # instead of killing it - closing mid-run would strand the emulator.
        if running and not self._quitting and self.tray_icon:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                APP_NAME,
                "Bot vẫn đang chạy trong khay hệ thống.\n"
                "Nhấp đúp biểu tượng để mở lại, hoặc chuột phải để dừng.",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
            return

        if running:
            reply = QMessageBox.question(
                self,
                "Bot is running",
                "The bot is still running. Stop it and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

            for worker in self.workers:
                worker.stop()
            for worker in self.workers:
                worker.wait(5000)
            if any(worker.isRunning() for worker in self.workers):
                self.status_progress.setText("Đang dừng; chờ worker kết thúc trước khi đóng.")
                event.ignore()
                return

        if self.loader_thread and self.loader_thread.isRunning():
            self.loader_thread.wait(3000)

        if self.loader_thread and self.loader_thread.isRunning():
            event.ignore()
            return
        if self.result_writer and self.result_writer.isRunning():
            self.result_writer.finalize()
            event.ignore()
            self.status_progress.setText("Đang lưu Excel; đóng lại sau khi lưu xong.")
            return
        if self.report_writer and self.report_writer.isRunning():
            event.ignore()
            self.status_progress.setText("Đang chờ xuất báo cáo xong...")
            return
        if self.journal:
            self.journal.close()
            self.journal = None

        self._save_last_state()
        self._save_geometry()
        if self.tray_icon:
            self.tray_icon.hide()
        event.accept()
