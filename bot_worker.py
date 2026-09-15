"""
bot_worker.py
Worker running inside QThread for automation:
type serial into the target app (via ADB or keyboard simulation),
optionally verify the app's response, then move to the next serial.
"""
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field

from PyQt6.QtCore import QThread, pyqtSignal

from automation_backend import (
    AdbBackend,
    AdbClient,
    AdbUnavailableError,
    PyAutoGuiBackend,
    WindowFocusError,
)
from action_runner import ActionRunner, RowContext, StopRun
from actions import REASON_APP_ERROR, REASON_DIALOG, REASON_NOT_FOUND
import browser_backend
import device_profile
from excel_reader import clean_serial
from screen_reader import (
    ScreenReader,
    current_focus_window,
    dialog_marker,
    dialog_message,
    extract_xml,
    find_dismiss_button,
    list_nodes,
    normalize_match_text,
    parse_bounds,
    xml_attr,
)

logger = logging.getLogger(__name__)

ERROR_DIALOG_TOKENS = ("dialog", "alert", "popup")
MAX_CONSECUTIVE_ADB_FAILURES = 5

# Bot gõ vào đâu: máy ảo Android qua ADB, hay trang web trong Chrome.
TARGET_ADB = "adb"
TARGET_BROWSER = "browser"

# Không đóng được hộp thoại thì mọi serial sau đó đều gõ vào màn hình đang kẹt
# và bị đánh dấu sai hàng loạt, nên dừng sớm để người dùng xử lý.
MAX_CONSECUTIVE_DISMISS_FAILURES = 3

# Trạng thái màn hình so với serial vừa gửi.
RESPONSE_NONE = "none"
RESPONSE_FRESH = "fresh"
RESPONSE_STALE = "stale"

DEFAULT_RESPONSE_TIMEOUT_SECONDS = 3.0
RESPONSE_POLL_INTERVAL_SECONDS = 0.12

# Khi màn hình chưa hé lộ gì cả thì chỉ chờ ngần này rồi đi tiếp: nhiều app xử
# lý xong là im lặng, chờ đủ response_timeout cho mọi dòng sẽ giết tốc độ. Còn
# khi biết chắc app chưa xong (màn hình vẫn là kết quả dòng trước) thì mới chờ
# hết response_timeout.
QUIET_TIMEOUT_SECONDS = 0.6

# Chờ hộp thoại đóng hẳn rồi mới sang serial sau.
DISMISS_VERIFY_TIMEOUT_SECONDS = 2.0

# Dò "cửa sổ focus đã đổi chưa" - đường nhanh để biết hộp thoại đã đóng. Ngắn
# thôi: hết ngần này mà chưa đổi thì đằng nào cũng phải đối chiếu nội dung.
DISMISS_FOCUS_PROBE_SECONDS = 0.6

# Số dòng đầu dùng để dò xem app có tự dọn ô nhập sau mỗi lần quét không.
#
# Đo trên máy thật: lệnh xóa ô là 22 keyevent, tốn ~605ms mỗi serial - gần bằng
# cả phần gõ chữ (581ms). App tự dọn ô thì đó là 605ms vứt đi mỗi dòng. Nhưng
# đoán sai thì serial sau nối vào serial trước, gửi đi một mã không có thật mà
# file kết quả nhìn vẫn bình thường - nên phải nhìn tận mắt vài lần rồi mới bỏ.
CLEAR_PROBE_ROWS = 3

# Chờ hộp thoại lỗi hiện ra trước khi dám kết luận dòng này chạy trót lọt.
#
# Đây là con số đánh đổi quan trọng nhất của đường nhanh, và là khoản chờ chết
# mà MỌI dòng chạy trót lọt đều phải gánh. 600 mẫu "Dialog xuat hien sau" đo
# trên máy thật: 50% hiện trong 260ms, 95% trong 400ms, 99% trong 530ms - nhưng
# đuôi kéo tới 1220ms. Chờ cho đủ cái đuôi đó là cộng hơn một giây vào từng
# dòng để phòng một phần trăm; nên chỉ chờ tới mức bắt được gần hết, phần đuôi
# để lưới ở đầu dòng sau đỡ - lưới đó giờ đọc được hộp thoại, gán về đúng dòng
# đã gõ ra nó rồi đóng lại (xem _handle_late_dialog), chứ không còn dừng cả
# phiên chạy như trước.
#
# Chỉ được siết khi việc soi cửa sổ và việc gõ đi CHUNG một lệnh. Tách làm hai
# lượt gọi ADB thì giữa chúng còn kẽ hở ~130ms, hộp thoại lọt đúng vào đó là
# serial gõ ra rơi vào hộp thoại mà cả hai dòng vẫn được ghi thành công - máy ảo
# nào không chạy được lệnh gộp thì giữ mức chờ rộng như cũ.
# 554 mẫu trên máy thật: 50% hộp thoại hiện trong 197ms, 75% trong 310ms, 90%
# trong 424ms, 95% trong 495ms. Chờ 500ms bắt được gần hết, nhưng đó là 500ms
# CHẾT mà mọi dòng đều gánh, trong khi tỷ lệ dòng thật sự có hộp thoại chỉ ~10%
# (5421 dòng log, 554 lần thấy hộp thoại). Chờ 350ms: mỗi dòng bớt 150ms, đổi
# lại ~2% số dòng rơi vào lưới bắt hộp thoại muộn ở đầu dòng sau (~1.5s một
# lần) - tính ra vẫn lãi hơn 100ms mỗi dòng, và lưới đó chấm đúng dòng đã gõ ra
# hộp thoại chứ không bỏ sót.
DIALOG_GRACE_SECONDS = 0.35
DIALOG_GRACE_UNGUARDED_SECONDS = 0.8
# Bản thân lệnh hỏi cửa sổ đã tốn ~130ms nên nó tự giãn nhịp rồi; ngủ thêm nhiều
# chỉ làm chậm việc nhận ra hộp thoại.
DIALOG_POLL_INTERVAL_SECONDS = 0.03

# Số dòng đầu được gõ kèm mốc thời gian từng chặng (xóa ô / gõ chữ / Enter).
# Mấy lệnh `date` trên máy ảo tốn vài ms, đổi lại lần sau muốn biết thời gian
# nằm ở chặng nào là mở log ra xem chứ không phải đoán.
INPUT_PROFILE_ROWS = 3

# Nhịp nghỉ giữa "quét mã sản phẩm" và "quét serial" trên màn hình nhận hàng.
#
# Đây là khoảng chờ cứng duy nhất trong một dòng, và nó buộc phải cứng: app đổi
# ý nghĩa của ô nhập theo trạng thái bên trong (đang chờ mã sản phẩm hay đang
# chờ serial) chứ không đổi cửa sổ, nên không có dấu hiệu nào rẻ để soi - chỉ
# dump cả cây view (~1200ms) mới thấy tên sản phẩm hiện ra, đắt hơn chính khoản
# chờ này. Gõ serial trong lúc app còn đang chờ mã sản phẩm thì serial bị đọc
# thành mã sản phẩm: nhẹ là app báo không tìm thấy, nặng là quét vào nhầm chỗ.
DEFAULT_PRODUCT_CODE_DELAY_SECONDS = 0.5


def _package_of_focus(focus: str) -> str:
    """
    Tên package lấy từ chuỗi cửa sổ đang focus.

    `mCurrentFocus` có dạng "<hash> u0 vn.abc.app/vn.abc.app.MainActivity": phần
    hash đổi mỗi lần mở lại app nên không dùng làm mốc nhớ được, còn package thì
    không đổi - đó mới là thứ nhận dạng "đang nói chuyện với app nào".
    """
    match = re.search(r"([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)/", focus or "")
    return match.group(1) if match else ""


@dataclass
class SerialItem:
    row: int
    value: str
    cells: dict = field(default_factory=dict)


class BotWorker(QThread):
    """
    Signals:
        progress(int current, int total)
        log_entry(int row, str serial, str status, str message)
        stats_update(int done, int success, int error, int unknown)
        result_ready(dict)  # row, serial, status, message, response_text, screenshot_path, time
        finished_all()
        error_occurred(str message)
        backend_info(str message)
    """

    progress = pyqtSignal(int, int)
    log_entry = pyqtSignal(int, str, str, str)
    stats_update = pyqtSignal(int, int, int, int)
    result_ready = pyqtSignal(dict)
    finished_all = pyqtSignal()
    error_occurred = pyqtSignal(str)
    backend_info = pyqtSignal(str)

    def __init__(
        self,
        serials: list[SerialItem],
        instance_name: str,
        delay_seconds: float,
        enter_mode: str = "enter",
        enter_delay_seconds: float = 0.0,
        prefer_adb_input: bool = True,
        background_mode: bool = False,
        verify_result: bool = True,
        success_keywords: str = "",
        error_keywords: str = "",
        not_found_keywords: str = "",
        capture_screenshot: bool = False,
        screenshot_dir: str = "screenshots",
        recipe_steps: list | None = None,
        recipe_name: str = "",
        response_timeout: float = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
        product_code: str = "",
        product_code_delay: float = DEFAULT_PRODUCT_CODE_DELAY_SECONDS,
        run_target: str = TARGET_ADB,
        browser_port: int = browser_backend.DEFAULT_DEBUG_PORT,
        browser_url: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.serials = serials
        self.instance_name = instance_name
        self.delay_seconds = delay_seconds
        self.enter_mode = enter_mode
        self.enter_delay_seconds = enter_delay_seconds
        self.prefer_adb_input = prefer_adb_input or background_mode
        self.background_mode = background_mode
        self.verify_result = verify_result
        self.success_keywords = self._parse_keywords(success_keywords)
        self.error_keywords = self._parse_keywords(error_keywords)
        self.not_found_keywords = self._parse_keywords(not_found_keywords)
        self.capture_screenshot = capture_screenshot
        self.screenshot_dir = screenshot_dir
        self.recipe_steps = recipe_steps or []
        # Chỉ để ghi log: kịch bản nào đang chạy quyết định tốc độ của cả phiên
        # (kịch bản gõ từng bước rời nhau, không có mấy lối tắt của luồng chạy
        # thường), mà log cũ chỉ ghi "recipe=yes" nên đọc lại không biết là cái
        # nào.
        self.recipe_name = recipe_name
        self.response_timeout = max(0.0, response_timeout)
        # Màn hình nhận hàng dùng CHUNG một ô cho hai thứ, xen kẽ nhau: quét mã
        # sản phẩm rồi quét serial, rồi lại mã sản phẩm. Cả file dùng đúng một mã
        # nên nhớ ở đây, khỏi đọc lại từ Excel. Để trống = gõ serial như cũ.
        self.product_code = clean_serial(product_code)
        self.product_code_delay = max(0.0, product_code_delay)

        self.run_target = run_target
        self.browser_port = browser_port
        self.browser_url = browser_url
        self.browser_session: browser_backend.BrowserSession | None = None

        self.adb_client = AdbClient(instance_name)
        self.backend = None
        self.runner: ActionRunner | None = None

        self._screen: ScreenReader | None = None
        # Serial của dòng ngay trước, để nhận ra màn hình còn đang là kết quả cũ.
        self._previous_serial = ""
        # App có in lại mã vừa quét không - biết rồi thì dùng chính nó làm mốc
        # xác nhận app đã xử lý đúng serial này.
        self._echo_seen = False
        # App có phản hồi gì nhìn thấy được không (hộp thoại / từ khóa).
        self._verdict_seen = False
        # dumpsys có nhìn thấy hộp thoại của app này không. None = chưa biết.
        # Biết rồi thì bước xác nhận "đã đóng chưa" hỏi dumpsys (~130ms) thay vì
        # dump cả cây view (~1200ms).
        self._dialog_seen_by_dumpsys: bool | None = None
        # Khóa "máy ảo + app + phiên bản app" để nhớ câu trả lời trên sang phiên
        # chạy sau (xem device_profile). None = chưa dựng, "" = đã thử mà không
        # dựng được, thôi đừng hỏi lại nữa.
        self._device_key: str | None = None
        # Cửa sổ đang focus lúc màn hình sạch, nhớ lại từ dòng chạy trót lọt gần
        # nhất. Rỗng = chưa biết, phải hỏi ADB. Bản `_raw` là nguyên dòng
        # mCurrentFocus để máy ảo tự so sánh được ngay trong lệnh gõ.
        self._clean_focus = ""
        self._clean_focus_raw = ""
        self._last_focus_line = ""
        # Bản dump của chính dòng đang chạy, để dò Enter mà không phải đọc lại.
        self._last_screen_xml = ""
        # Dòng vừa gõ xong và kết luận sửa lại cho nó, khi hộp thoại của nó hiện
        # muộn tới mức dòng sau mới nhìn thấy.
        self._previous_row: int | None = None
        self._pending_correction: tuple[int, dict] | None = None
        self._text_submit_probed = False
        self._input_profile_rows_left = INPUT_PROFILE_ROWS
        # App có tự dọn ô nhập sau mỗi lần quét không. None = chưa biết, còn đang
        # dò; lúc chưa biết thì vẫn gửi lệnh xóa cho chắc.
        self._field_self_clears: bool | None = None
        self._clear_probes_left = CLEAR_PROBE_ROWS

        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_flag = threading.Event()

    @property
    def screen(self):
        """Dựng lại nếu adb_client bị thay (test hay đổi client sau khởi tạo)."""
        # Chạy trên trình duyệt thì backend mang sẵn lớp đọc màn hình của nó.
        from_backend = getattr(self.backend, "screen", None)
        if from_backend is not None:
            return from_backend
        if self._screen is None or self._screen.adb is not self.adb_client:
            self._screen = ScreenReader(self.adb_client)
        return self._screen

    def _parse_keywords(self, text: str) -> list[str]:
        return [
            self._normalize_match_text(kw.strip())
            for kw in text.split(",")
            if kw.strip()
        ]

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def stop(self):
        self._stop_flag.set()
        self._pause_event.set()

    def _select_backend(self) -> bool:
        """Returns False if no usable backend could be selected and the run must abort."""
        if self.run_target == TARGET_BROWSER:
            return self._select_browser_backend()

        if self.prefer_adb_input:
            adb_backend = AdbBackend(self.adb_client)
            if adb_backend.is_available():
                # Dò một lần cho cả phiên: lệnh dò không gõ gì vào app.
                adb_backend.probe_guard()
                self.backend = adb_backend
                return True

            if self.background_mode:
                # Falling back here would start typing into whatever window the
                # user is working in. Refuse to run instead.
                logger.error("Background mode: ADB unavailable on '%s', aborting run", self.instance_name)
                self.error_occurred.emit(
                    f"Background mode: không kết nối được ADB tới instance "
                    f"'{self.instance_name}'.\n\n"
                    "Bot đã DỪNG thay vì chuyển sang gõ bàn phím, để không gõ nhầm "
                    "vào cửa sổ bạn đang làm việc.\n\n"
                    "Kiểm tra: LDPlayer đã bật chưa, đúng tên instance chưa?"
                )
                return False

            self.backend_info.emit(
                "ADB không phản hồi, chuyển sang gõ bàn phím (yêu cầu cửa sổ "
                "LDPlayer luôn ở foreground - KHÔNG dùng máy làm việc khác)."
            )
            logger.warning("ADB unavailable, falling back to PyAutoGuiBackend")

        self.backend = PyAutoGuiBackend(self.instance_name)
        return True

    def _select_browser_backend(self) -> bool:
        """
        Gắn vào Chrome đang mở.

        Không có đường lui nào cả: gắn hụt mà vẫn chạy tiếp thì phím sẽ rơi vào
        cửa sổ bất kỳ đang ở trước - đúng thứ mà background_mode của luồng ADB
        cấm tiệt. Nên hụt là dừng.
        """
        if not self.recipe_steps:
            self.error_occurred.emit(
                "Chạy trên trình duyệt thì phải chọn một kịch bản.\n\n"
                "Luồng 'như cũ' được viết cho màn hình app Android (gõ vào ô đang\n"
                "focus rồi đọc cây view), không có nghĩa gì trên một trang web.\n\n"
                "Vào tab Kịch bản, tạo kịch bản với các bước 'Điền ô (web)',\n"
                "'Bấm nút (web)', 'Chờ phần tử (web)' rồi chạy lại."
            )
            return False

        session = browser_backend.BrowserSession(
            port=self.browser_port, url_filter=self.browser_url
        )
        try:
            session.start()
        except browser_backend.BrowserUnavailableError as e:
            logger.error("Không gắn được vào trình duyệt: %s", e)
            self.error_occurred.emit(f"Không gắn được vào trình duyệt.\n\n{e}")
            return False

        self.browser_session = session
        self.backend = browser_backend.BrowserBackend(session)
        self.backend_info.emit(
            f"Đang điều khiển tab: {session.page.url}"
        )
        return True

    def run(self):
        try:
            self._run()
        finally:
            # Ngắt kết nối dù phiên chạy kết thúc kiểu gì: bỏ mặc thì tiến trình
            # driver của Playwright sống dai hơn cả app.
            if self.browser_session is not None:
                self.browser_session.stop()
                self.browser_session = None

    def _run(self):
        if not self._select_backend():
            self.finished_all.emit()
            return

        if self.recipe_steps:
            self.runner = ActionRunner(
                self.recipe_steps,
                self.backend,
                self.adb_client,
                screenshot_dir=self.screenshot_dir,
                capture_screenshot_on_error=self.capture_screenshot,
            )

        total = len(self.serials)
        counters = {"done": 0, "success": 0, "error": 0, "unknown": 0}
        consecutive_adb_failures = 0
        consecutive_dismiss_failures = 0
        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        logger.info(
            "Run started: %d serials, backend=%s, recipe=%s",
            total, type(self.backend).__name__,
            (self.recipe_name or "yes") if self.runner else "no",
        )

        # Kết quả của dòng vừa chạy được giữ lại một nhịp trước khi công bố. Hộp
        # thoại trả lời cho nó có thể hiện muộn tới mức phải sang dòng sau mới
        # nhìn thấy; giữ lại một nhịp thì lúc đó còn sửa được, thay vì công bố
        # một dòng OK sai rồi thôi.
        pending: tuple | None = None

        for item in self.serials:
            if self._stop_flag.is_set():
                break

            if not self._pause_event.is_set() and pending is not None:
                # Sắp đứng chờ người dùng bấm Resume: công bố nốt dòng đang giữ
                # để bảng kết quả không thiếu dòng suốt lúc dừng.
                self._publish(pending[0], pending[1], counters, total)
                pending = None

            self._pause_event.wait()
            if self._stop_flag.is_set():
                break

            if self.runner:
                try:
                    result = self._process_with_recipe(item)
                except StopRun as e:
                    self.error_occurred.emit(
                        f"Kịch bản yêu cầu dừng phiên chạy:\n{e}"
                    )
                    break
            else:
                result = self._process_serial(item.row, item.value)

            pending = self._apply_correction(pending)
            if pending is not None:
                self._publish(pending[0], pending[1], counters, total)
            pending = (item, result)

            if result.get("adb_failed"):
                consecutive_adb_failures += 1
            else:
                consecutive_adb_failures = 0

            if result.get("dismiss_failed"):
                consecutive_dismiss_failures += 1
            else:
                consecutive_dismiss_failures = 0

            if result.get("focus_failed") or (
                result["status"] != "OK" and "Could not find window" in result["message"]
            ):
                self.error_occurred.emit(result["message"])
                self._pause_event.clear()

            if consecutive_adb_failures >= MAX_CONSECUTIVE_ADB_FAILURES:
                logger.error(
                    "Aborting: %d consecutive ADB failures on '%s'",
                    consecutive_adb_failures, self.instance_name,
                )
                self.error_occurred.emit(
                    f"{consecutive_adb_failures} serial liên tiếp thất bại vì ADB "
                    f"không phản hồi (instance '{self.instance_name}').\n\n"
                    "Bot đã tạm dừng để bạn kiểm tra LDPlayer, thay vì chạy tiếp "
                    "và đánh dấu sai hàng loạt dòng còn lại."
                )
                self._pause_event.clear()
                consecutive_adb_failures = 0

            if consecutive_dismiss_failures >= MAX_CONSECUTIVE_DISMISS_FAILURES:
                logger.error(
                    "Aborting: %d consecutive dialogs could not be dismissed on '%s'",
                    consecutive_dismiss_failures, self.instance_name,
                )
                self.error_occurred.emit(
                    f"{consecutive_dismiss_failures} lần liên tiếp không đóng được "
                    f"hộp thoại trên instance '{self.instance_name}'.\n\n"
                    "Màn hình nhiều khả năng đang kẹt ở một hộp thoại mà bot không "
                    "tìm ra nút đóng, nên serial sau sẽ gõ vào chỗ không nhận.\n\n"
                    "Bot đã tạm dừng: hãy đóng hộp thoại đó, hoặc dùng UI Inspector "
                    "xem nút đó tên gì rồi thêm vào kịch bản."
                )
                self._pause_event.clear()
                consecutive_dismiss_failures = 0

            self._interruptible_sleep(self.delay_seconds)

        pending = self._apply_correction(pending)
        if pending is not None:
            self._publish(pending[0], pending[1], counters, total)

        logger.info(
            "Run finished: done=%d success=%d error=%d unknown=%d (started %s)",
            counters["done"], counters["success"], counters["error"],
            counters["unknown"], started_at,
        )
        self.finished_all.emit()

    def _apply_correction(self, pending: tuple | None) -> tuple | None:
        """
        Dán kết luận muộn (hộp thoại của dòng trước) vào đúng dòng đã gõ ra nó.

        Chỉ sửa dòng đang được chấm OK: dòng đã có kết luận riêng thì kết luận đó
        đọc từ chính màn hình của nó, đáng tin hơn.
        """
        correction, self._pending_correction = self._pending_correction, None
        if correction is None or pending is None:
            return pending

        row, verdict = correction
        item, result = pending
        if item.row != row or result["status"] != "OK":
            return pending

        return item, {
            **result,
            "status": verdict["status"],
            "message": self._build_message(
                verdict["status"], verdict.get("reason", ""),
                verdict.get("response_text", ""), verdict,
            ),
            "response_text": verdict.get("response_text", ""),
            "reason": verdict.get("reason", ""),
        }

    def _publish(self, item, result: dict, counters: dict, total: int) -> None:
        counters["done"] += 1
        if result["status"] == "OK":
            counters["success"] += 1
        elif result["status"] == "ERROR":
            counters["error"] += 1
        else:
            counters["unknown"] += 1

        clean_val = clean_serial(item.value)
        self.log_entry.emit(item.row, clean_val, result["status"], result["message"])
        self.result_ready.emit({
            "row": item.row,
            "serial": clean_val,
            "status": result["status"],
            "message": result["message"],
            "response_text": result.get("response_text", ""),
            "reason": result.get("reason", ""),
            "screenshot_path": result.get("screenshot_path"),
            "cell_writes": result.get("cell_writes", {}),
            "time": time.strftime("%H:%M:%S"),
        })
        self.stats_update.emit(
            counters["done"], counters["success"], counters["error"], counters["unknown"]
        )
        self.progress.emit(counters["done"], total)

    def _interruptible_sleep(self, seconds: float):
        step = 0.1
        elapsed = 0.0
        while elapsed < seconds:
            if self._stop_flag.is_set():
                return
            time.sleep(step)
            elapsed += step

    def _process_with_recipe(self, item) -> dict:
        clean_val = clean_serial(item.value)
        if not clean_val:
            return {"status": "ERROR", "message": "Empty serial skipped"}

        outcome = self.runner.run_row(
            RowContext(row=item.row, serial=clean_val, cells=getattr(item, "cells", {}) or {})
        )
        return {
            "status": outcome.status,
            "message": outcome.message,
            "response_text": outcome.response_text,
            "reason": outcome.reason,
            "screenshot_path": outcome.screenshot_path,
            "cell_writes": outcome.cell_writes,
            "adb_failed": outcome.adb_failed,
            "dismiss_failed": outcome.dismiss_failed,
            "focus_failed": outcome.focus_failed,
        }

    def _process_serial(self, row: int, serial: str) -> dict:
        clean_val = clean_serial(serial)
        if not clean_val:
            return {"status": "ERROR", "message": "Empty serial skipped"}

        # Mốc thời gian từng chặng: một serial chỉ có hai khoản đáng kể là gõ và
        # đọc kết quả, mà đọc lại chia tiếp thành mấy lần dump. Ghi ra log thì
        # lần sau muốn biết chậm ở đâu là mở log ra xem, khỏi đo từ ngoài vào
        # (đo từ ngoài còn giành mất uiautomator của chính bot).
        started_at = time.monotonic()
        dumps_before = self.screen.dump_count
        dump_seconds_before = self.screen.dump_seconds
        self._last_screen_xml = ""

        clear_first = self._should_clear_field()

        try:
            if self.product_code:
                blocked = self._send_product_code(row, clear_first)
                if blocked is not None:
                    return blocked

            base_focus, typed = self._send_serial(row, clean_val, clear_first)
            if not typed:
                # Màn hình đã đổi khác TRƯỚC lúc gõ, nên serial này chưa đi đâu
                # cả. Gần như luôn là hộp thoại trả lời cho serial trước, hiện
                # muộn hơn khoảng chờ của dòng đó.
                blocked = self._handle_late_dialog(row)
                if blocked is not None:
                    return blocked
                base_focus, typed = self._send_serial(row, clean_val, clear_first, guard=False)
        except AdbUnavailableError as e:
            logger.error("Row %d ('%s') ADB delivery failed: %s", row, clean_val, e)
            return {
                "status": "UNKNOWN",
                "message": f"Không gửi được tới thiết bị: {e}",
                "adb_failed": True,
            }
        except WindowFocusError as e:
            # Đường gõ bàn phím tự chặn lại vì cửa sổ máy ảo không ở trước. Dòng
            # này chưa gõ (hoặc gõ dở), và mọi dòng sau cũng sẽ hụt như vậy -
            # vòng chạy tạm dừng để người dùng đưa LDPlayer lên rồi bấm Resume.
            logger.error("Row %d ('%s') focus check failed: %s", row, clean_val, e)
            return {
                "status": "UNKNOWN",
                "message": f"Chưa gõ được: {e}",
                "focus_failed": True,
            }
        except Exception as e:
            logger.error("Row %d ('%s') input failed: %s", row, clean_val, e)
            return {"status": "ERROR", "message": f"Paste/enter error: {e}"}

        input_seconds = time.monotonic() - started_at

        if self._device_key is None:
            # Chỉ chạy đúng một lần, ở dòng đầu tiên gõ được: tới đây mới biết
            # cửa sổ nào đang ở trước, tức là mới biết đang nói chuyện với app nào.
            self._sync_device_profile(base_focus)

        if self.verify_result:
            # Đường nhanh chỉ mở sau khi đã tận mắt thấy một hộp thoại làm đổi
            # cửa sổ focus (xác nhận lúc đóng hộp thoại đầu tiên). Chưa thấy thì
            # chưa dám tin, vì hộp thoại tự vẽ kiểu Flutter/WebView không đổi
            # focus - dùng đường nhanh với app như thế là mọi dòng đều "thành
            # công".
            fast_path = bool(base_focus) and bool(self._dialog_seen_by_dumpsys)
            verdict = self._verdict_by_focus(base_focus) if fast_path else None
            if verdict is None:
                # Đọc màn hình xong thì màn hình có thể đã khác (vừa đóng hộp
                # thoại), nên quên mốc focus cũ đi, dòng sau hỏi lại từ đầu.
                self._clean_focus = ""
                self._clean_focus_raw = ""
                verdict = self._read_result(clean_val)
            else:
                self._clean_focus = base_focus
                self._clean_focus_raw = self._last_focus_line
            verdict = self._confirm_text_submit(clean_val, verdict)
        else:
            verdict = {"status": "OK", "response_text": "Typed successfully"}

        total_seconds = time.monotonic() - started_at
        logger.info(
            "Row %d timing: total=%.0fms input=%.0fms verify=%.0fms "
            "(%d dump=%.0fms, khac=%.0fms) -> %s",
            row,
            total_seconds * 1000,
            input_seconds * 1000,
            (total_seconds - input_seconds) * 1000,
            self.screen.dump_count - dumps_before,
            (self.screen.dump_seconds - dump_seconds_before) * 1000,
            (total_seconds - input_seconds
             - (self.screen.dump_seconds - dump_seconds_before)) * 1000,
            verdict.get("status"),
        )

        self._previous_serial = clean_val
        self._previous_row = row

        status = verdict["status"]
        response_text = verdict.get("response_text", "")
        reason = verdict.get("reason", "")

        screenshot_path = None
        if self.capture_screenshot and status in ("ERROR", "UNKNOWN"):
            screenshot_path = self._capture_screenshot(row, clean_val)

        return {
            "status": status,
            "message": self._build_message(status, reason, response_text, verdict),
            "response_text": response_text,
            "reason": reason,
            "screenshot_path": screenshot_path,
            "adb_failed": verdict.get("adb_failed", False),
            "dismiss_failed": verdict.get("dismiss_failed", False),
        }

    # ---------------------------------------------------- gõ mã sản phẩm cố định

    def _send_product_code(self, row: int, clear_first: bool) -> dict | None:
        """
        Gõ mã sản phẩm vào cùng ô nhập, ngay trước serial của dòng này.

        Màn hình nhận hàng chờ xen kẽ: mã sản phẩm -> serial -> mã sản phẩm ->
        serial... Mã giữ nguyên cho cả file nhưng vẫn phải gõ lại trước từng
        serial, vì quét xong một serial là app quay về chờ mã sản phẩm.

        Trả về None nghĩa là mã đã vào, gõ serial tiếp được; trả về dict nghĩa là
        dòng này hỏng ngay từ mã sản phẩm - serial CHƯA được gõ.
        """
        code = self.product_code
        base_focus, typed = self._send_serial(row, code, clear_first)
        if not typed:
            # Màn hình đổi khác TRƯỚC lúc gõ, nên hộp thoại này là của dòng
            # trước chứ không phải trả lời cho mã sản phẩm (chưa gõ mà).
            blocked = self._handle_late_dialog(row)
            if blocked is not None:
                return blocked
            base_focus, _ = self._send_serial(row, code, clear_first, guard=False)

        if self._product_code_accepted(base_focus):
            return None
        return self._product_code_rejected(row, code)

    def _product_code_accepted(self, base_focus: str) -> bool:
        """
        Nghỉ cho app kịp nhận mã sản phẩm, và nhân lúc chờ thì soi luôn cửa sổ.

        Khoản chờ này đằng nào cũng phải có (xem DEFAULT_PRODUCT_CODE_DELAY_
        SECONDS), nên việc soi không tốn thêm giây nào: mã sai làm app bật hộp
        thoại thì biết ngay ở đây. Không soi thì serial gõ tiếp vào hộp thoại,
        Enter đóng luôn nó, và dòng đó được ghi OK trong khi chẳng có gì vào kho
        - đúng kiểu sai không lộ ra ở file kết quả.

        Chỉ soi được khi đã tận mắt thấy hộp thoại của app này làm đổi cửa sổ
        focus; chưa thấy thì soi cũng không kết luận được gì, cứ chờ đủ nhịp.
        """
        if not (base_focus and self._dialog_seen_by_dumpsys):
            self._interruptible_sleep(self.product_code_delay)
            return True

        # Soi ít nhất một lần kể cả khi nhịp nghỉ đặt bằng 0: bản thân lệnh hỏi
        # cửa sổ đã tốn ~130ms nên nó vừa là lớp bảo vệ vừa là nhịp nghỉ tối
        # thiểu, giống cách _verdict_by_focus chờ hộp thoại sau serial.
        deadline = time.monotonic() + self.product_code_delay
        while True:
            if self._stop_flag.is_set():
                return True
            focus = self.screen.focused_window()
            if focus and focus != base_focus:
                return False
            if time.monotonic() >= deadline:
                return True
            time.sleep(DIALOG_POLL_INTERVAL_SECONDS)

    def _product_code_rejected(self, row: int, code: str) -> dict:
        """App bật hộp thoại ngay sau mã sản phẩm - serial dòng này chưa gõ."""
        self._clean_focus = ""
        self._clean_focus_raw = ""

        xml = self.screen.dump_xml()
        verdict = self._classify_dialog(xml) if xml else {
            "response_text": "Hộp thoại lỗi (không đọc được nội dung)",
            "reason": REASON_DIALOG,
        }
        dismissed = self._dismiss_error_dialog(xml)
        response_text = verdict.get("response_text", "")
        logger.warning("Row %d: app từ chối mã sản phẩm '%s' (%s)", row, code, response_text)

        return {
            "status": "ERROR",
            "message": (
                f"App báo lỗi ngay ở mã sản phẩm '{code}' ({response_text}) "
                f"- serial CHƯA được gõ."
            ),
            "response_text": response_text,
            "reason": verdict.get("reason", REASON_DIALOG),
            "dismiss_failed": not dismissed,
        }

    # --------------------------------------------------------------- gõ serial

    def _send_serial(
        self, row: int, serial: str, clear_first: bool, guard: bool = True
    ) -> tuple[str, bool]:
        """
        Gõ serial. Trả về (cửa sổ đang focus ngay trước lúc gõ, đã gõ hay chưa).

        Máy ảo chạy được thì việc soi cửa sổ và việc gõ đi chung MỘT lệnh: bớt
        một lượt đi-về ADB (~130ms mỗi dòng), mà quan trọng hơn là khép gần kín
        kẽ hở giữa lúc soi và lúc gõ. Hộp thoại lọt đúng vào kẽ đó thì serial gõ
        ra rơi vào hộp thoại, Enter đóng luôn hộp thoại, và cả dòng này lẫn dòng
        trước đều được ghi là thành công - kiểu sai không thể phát hiện qua file
        kết quả.
        """
        # Chỉ chốt cửa sổ khi đã biết màn hình sạch trông thế nào, và khi hộp
        # thoại của app này thật sự làm đổi cửa sổ focus.
        expected = ""
        if guard and self.verify_result and self._dialog_seen_by_dumpsys:
            expected = self._clean_focus_raw

        if self.enter_delay_seconds > 0 or not getattr(self.backend, "guards_focus", False):
            return self._send_serial_two_calls(row, serial, clear_first, guard)

        outcome = self.backend.type_and_submit_guarded(
            serial, self.enter_mode, clear_first, expected,
            profile=self._input_profile_rows_left > 0,
        )
        if outcome.stages:
            self._input_profile_rows_left -= 1
            logger.info("Row %d input stages: %s", row, outcome.stage_report())
        self._last_focus_line = outcome.focus_line
        return current_focus_window(outcome.focus_line), outcome.typed

    def _send_serial_two_calls(
        self, row: int, serial: str, clear_first: bool, guard: bool
    ) -> tuple[str, bool]:
        """Đường cũ cho máy ảo không chạy được lệnh gộp: soi rồi mới gõ."""
        self._last_focus_line = ""
        base_focus = ""
        if self.verify_result and self._dialog_seen_by_dumpsys:
            base_focus = self.screen.focused_window() or ""
            if guard and self._clean_focus and base_focus and base_focus != self._clean_focus:
                return base_focus, False

        if self.enter_delay_seconds > 0:
            self.backend.type_serial(serial)
            time.sleep(self.enter_delay_seconds)
            self.backend.send_enter(self.enter_mode)
        else:
            self.backend.type_and_submit(serial, self.enter_mode, clear_first)
        return base_focus, True

    def _handle_late_dialog(self, row: int) -> dict | None:
        """
        Màn hình đã đổi khác trước khi kịp gõ serial của dòng này.

        Gần như luôn là hộp thoại trả lời cho serial TRƯỚC, hiện muộn hơn khoảng
        chờ của dòng đó. Bản trước bỏ qua dòng này rồi dừng cả phiên chạy sau ba
        lần như vậy; giờ đọc lấy nội dung, gán về đúng dòng đã gõ ra nó, đóng
        lại rồi để dòng này gõ lại - phiên chạy đi tiếp mà không ai phải vào dọn
        tay, và dòng kia được chấm đúng thay vì OK oan.

        Trả về None nghĩa là dọn xong, cứ gõ tiếp; trả về dict nghĩa là dòng này
        chưa gõ được.
        """
        self._clean_focus = ""
        self._clean_focus_raw = ""

        xml = self.screen.dump_xml()
        if not xml or find_dismiss_button(xml) is None:
            # Không phải hộp thoại: người dùng chuyển màn hình, hoặc app tự đi
            # chỗ khác. Gõ vào đó là gõ vào chỗ không nhận.
            logger.warning("Row %d: màn hình đổi khác nhưng không thấy hộp thoại nào.", row)
            return {
                "status": "UNKNOWN",
                "message": (
                    "Màn hình không còn ở chỗ nhập serial (app đổi màn hình) "
                    "- serial này CHƯA được gõ."
                ),
                "dismiss_failed": True,
            }

        verdict = self._classify_dialog(xml)
        dismissed = self._dismiss_error_dialog(xml)
        if self._previous_row is not None:
            self._pending_correction = (self._previous_row, verdict)
            logger.info(
                "Row %d: hộp thoại tới muộn, gán kết luận về dòng %d (%s).",
                row, self._previous_row, verdict.get("response_text", ""),
            )
        if not dismissed:
            return {
                "status": "UNKNOWN",
                "message": (
                    "Hộp thoại của serial trước chưa đóng được "
                    "- serial này CHƯA được gõ."
                ),
                "dismiss_failed": True,
            }
        return None

    def _classify_dialog(self, xml: str) -> dict:
        """Kết luận cho hộp thoại đang hiện, KHÔNG đóng nó (bên gọi tự đóng)."""
        haystack = self._normalize_match_text(xml)
        reason = REASON_DIALOG
        for kw in self.error_keywords:
            if kw and kw in haystack:
                reason = REASON_APP_ERROR
                break
        # "Không tìm thấy" xét sau cùng để nó ghi đè lý do chung, giống _read_result.
        for kw in self.not_found_keywords:
            if kw and kw in haystack:
                reason = REASON_NOT_FOUND
                break
        return {
            "status": "ERROR",
            "response_text": dialog_message(xml) or "Hộp thoại lỗi",
            "reason": reason,
        }

    def _confirm_text_submit(self, serial: str, verdict: dict) -> dict:
        """
        Nhìn tận mắt một lần rằng Enter gộp trong `input text` thật sự tới nơi.

        Máy ảo dịch '\\n' thành KEYCODE_ENTER qua bảng ký tự bàn phím ảo, nhưng
        đó là thứ không được tin theo lý thuyết: dịch hụt thì serial nằm nguyên
        trong ô, app chưa quét gì mà bot vẫn ghi OK - đúng kiểu sai không thể
        phát hiện qua file kết quả. Nên dòng đầu tiên đi lối này phải soi lại màn
        hình, khớp mới cho dùng tiếp.

        Chỉ dò được khi app đã biết là tự dọn ô sau mỗi lần quét (xem
        `_should_clear_field`): lúc đó "ô còn nguyên serial" mới đồng nghĩa với
        "app chưa quét", nên bấm Enter bù là an toàn, không sợ quét thành hai lần.
        """
        backend = self.backend
        if self._text_submit_probed or not getattr(backend, "submits_with_text", False):
            return verdict

        if verdict.get("status") == "ERROR":
            # Hộp thoại của chính dòng này = Enter đã tới nơi, khỏi soi ô nhập.
            self._accept_text_submit()
            return verdict

        xml = self._last_screen_xml or self.screen.dump_xml()
        if not xml:
            return verdict                  # chưa kết luận được, để dòng sau dò
        if not self._field_still_holds(xml, serial):
            self._accept_text_submit()
            return verdict

        logger.warning(
            "Máy ảo không dịch ký tự xuống dòng thành Enter - quay về gửi Enter riêng."
        )
        backend.disable_text_submit()
        self._text_submit_probed = True
        try:
            backend.send_enter(self.enter_mode)
        except AdbUnavailableError as e:
            return {
                "status": "UNKNOWN",
                "response_text": f"Không gửi được Enter: {e}",
                "adb_failed": True,
            }
        return self._read_result(serial)

    def _accept_text_submit(self) -> None:
        self._text_submit_probed = True
        self.backend.confirm_text_submit()
        logger.info(
            "Enter gộp trong `input text` chạy được - bớt một lần dựng tiến "
            "trình Java cho mỗi serial."
        )

    def _field_still_holds(self, xml: str, serial: str) -> bool:
        wanted = self._normalize_match_text(serial)
        if not wanted:
            return False
        return any(
            wanted in self._normalize_match_text(node.get("text") or "")
            for node in list_nodes(xml, only_interesting=False)
            if node.get("class") == "EditText"
        )

    def _build_message(self, status: str, reason: str, response_text: str, verdict: dict) -> str:
        if reason == REASON_NOT_FOUND:
            detail = response_text or "app báo không tìm thấy"
            if verdict.get("dismiss_failed"):
                return f"Không tìm thấy serial - CHƯA đóng được hộp thoại ({detail})"
            return f"Không tìm thấy serial - đã bấm OK, chạy tiếp ({detail})"

        return {
            "OK": "Typed successfully" if response_text == "Typed successfully" else f"Matched: {response_text}",
            "ERROR": f"App error: '{response_text}'" if response_text else "App error",
            "UNKNOWN": response_text or "Could not verify result",
        }[status]

    def _should_clear_field(self) -> bool:
        """
        Có cần gửi lệnh xóa ô trước khi gõ serial này không.

        Lệnh xóa là 22 keyevent, đo được ~605ms mỗi dòng - gần bằng cả phần gõ
        chữ. App tự dọn ô sau mỗi lần quét thì đó là 605ms vứt đi. Nhưng bỏ nhầm
        thì serial sau nối vào serial trước và gửi đi một mã không có thật, nên
        phải nhìn tận mắt vài dòng rồi mới dám bỏ.

        Nhìn được là nhờ lệnh xóa nằm ở ĐẦU lệnh gõ của dòng sau: ô nhập ngay
        trước lúc gõ phản ánh đúng thứ app để lại sau dòng trước, chưa bị lệnh
        xóa của bot chạm vào.
        """
        if self._field_self_clears is not None:
            return not self._field_self_clears
        if not self.verify_result or self._clear_probes_left <= 0:
            return True
        # Dòng đầu tiên chưa nói lên điều gì: ô trống là chuyện đương nhiên khi
        # chưa quét gì. Chỉ tính từ dòng thứ hai trở đi.
        if not self._previous_serial:
            return True

        xml = self.screen.dump_xml()
        if not xml:
            return True

        fields = [n for n in list_nodes(xml, only_interesting=False)
                  if n.get("class") == "EditText"]
        if not fields:
            return True                 # không thấy ô nhập -> chưa kết luận được

        if any((n.get("text") or "").strip() for n in fields):
            logger.info("App không tự dọn ô nhập - giữ lệnh xóa.")
            self._field_self_clears = False
            self._clear_probes_left = 0
            return True

        self._clear_probes_left -= 1
        if self._clear_probes_left <= 0:
            self._field_self_clears = True
            logger.info(
                "App tự dọn ô nhập sau mỗi lần quét - bỏ lệnh xóa, "
                "tiết kiệm ~605ms mỗi serial."
            )
            # Biết app tự dọn ô rồi thì "ô còn nguyên serial" mới đọc được thành
            # "Enter chưa tới nơi" - tới đây mới dò được lối gộp Enter vào lệnh
            # gõ, xem _confirm_text_submit.
            if hasattr(self.backend, "enable_text_submit"):
                self.backend.enable_text_submit()
        return True

    def _verdict_by_focus(self, base_focus: str) -> dict | None:
        """
        Phân loại dòng này bằng cửa sổ đang focus, không đọc cả màn hình.

        `dumpsys window` tốn ~130ms còn `uiautomator dump` ~1200ms, mà đa số dòng
        chạy trót lọt thì chẳng có gì để đọc - hỏi cửa sổ là đủ biết app có bật
        hộp thoại lỗi hay không.

        Trả về verdict "OK" nếu hết thời gian chờ mà không có gì hiện ra; trả về
        None nghĩa là "đừng đoán, đi đọc màn hình cho chắc" - dùng cho cả khi có
        hộp thoại (còn phải đọc lý do) lẫn khi ADB không trả lời.
        """
        started = time.monotonic()
        deadline = started + self._dialog_grace()

        while True:
            focus = self.screen.focused_window()
            if focus is None:
                return None
            if focus and focus != base_focus:
                # Ghi lại độ trễ thật để sau còn siết DIALOG_GRACE_SECONDS cho
                # vừa máy, thay vì cứ để rộng tay mãi.
                logger.info(
                    "Dialog xuat hien sau %.0fms", (time.monotonic() - started) * 1000
                )
                return None
            if self._stop_flag.is_set():
                return None
            if time.monotonic() >= deadline:
                return {"status": "OK", "response_text": "Typed successfully"}
            time.sleep(DIALOG_POLL_INTERVAL_SECONDS)

    def _dialog_grace(self) -> float:
        """Chờ ngắn chỉ an toàn khi lệnh gõ tự chốt được cửa sổ (xem hằng số)."""
        if getattr(self.backend, "guards_focus", False):
            return DIALOG_GRACE_SECONDS
        return DIALOG_GRACE_UNGUARDED_SECONDS

    def _read_result(self, serial: str = "") -> dict:
        """
        Phân loại kết quả sau khi gõ serial.

        Đọc màn hình TRƯỚC rồi mới bấm OK: bản trước bấm Enter ngay khi thấy có
        hộp thoại, nên mọi lỗi đều bị ghi vào Excel là 'dialog' và không tài nào
        biết được dòng nào hỏng vì serial không có trong hệ thống.
        """
        content, state = self._wait_for_response(serial)
        self._last_screen_xml = content

        if not content:
            # Chỉ lúc này mới hỏi tới dumpsys - đường chạy thường không cần, bỏ
            # được một lượt gọi ADB cho mỗi serial.
            dialog_focused = self._check_error_dialog_fast()
            if dialog_focused is None:
                return {
                    "status": "UNKNOWN",
                    "response_text": "Could not verify (adb communication failed)",
                    "adb_failed": True,
                }
            if dialog_focused:
                # Có hộp thoại nhưng không đọc nổi nội dung: vẫn phải đóng, nếu
                # không serial kế tiếp sẽ gõ vào màn hình đang bị chặn.
                dismissed = self._dismiss_error_dialog("")
                return {
                    "status": "ERROR",
                    "response_text": "Hộp thoại lỗi (không đọc được nội dung)",
                    "reason": REASON_DIALOG,
                    "dismiss_failed": not dismissed,
                }
            return {"status": "OK", "response_text": "Typed successfully"}

        if state == RESPONSE_STALE:
            # Màn hình vẫn đang là kết quả của serial trước. Chấm dòng này theo
            # nội dung đó thì chép nhầm kết quả của dòng trên xuống dòng dưới -
            # đúng kiểu sai nguy hiểm nhất vì file kết quả trông vẫn bình thường.
            return {
                "status": "UNKNOWN",
                "response_text": (
                    f"App chưa phản hồi kịp: màn hình vẫn là kết quả của serial "
                    f"'{self._previous_serial}'"
                ),
            }

        normalized_content = self._normalize_match_text(content)

        # Xét "không tìm thấy" trước từ khóa lỗi chung: từ khóa lỗi thường bao
        # luôn cả câu này ("not found" khớp cả "product not found"), xét sau thì
        # lý do cụ thể không bao giờ tới lượt.
        for kw in self.not_found_keywords:
            if kw and kw in normalized_content:
                return self._error_verdict(content, REASON_NOT_FOUND, kw)

        for kw in self.error_keywords:
            if kw and kw in normalized_content:
                return self._error_verdict(content, REASON_APP_ERROR, kw)

        for kw in self.success_keywords:
            if kw and kw in normalized_content:
                return {"status": "OK", "response_text": kw}

        # Không khớp từ khóa nào nhưng màn hình có nút đóng: chỉ lúc đó mới tốn
        # thêm một lượt dumpsys để hỏi xem đây có thật là hộp thoại không. Màn
        # hình sạch thì không mất gì.
        if find_dismiss_button(content) is not None and self._check_error_dialog_fast():
            return self._error_verdict(content, REASON_DIALOG, "")

        if self.success_keywords:
            return {"status": "UNKNOWN", "response_text": "No success/error keyword matched"}

        return {"status": "OK", "response_text": "Typed successfully"}

    # ------------------------------------------------------------ chờ phản hồi

    def _wait_for_response(self, serial: str) -> tuple[str, str]:
        """
        Đợi tới khi màn hình thực sự là kết quả của serial vừa gửi.

        Thay cho việc ngủ một khoảng cố định rồi hy vọng app kịp: máy nhanh thì
        đi tiếp ngay, máy chậm thì chờ thêm. Trả về (xml, trạng thái).
        """
        deadline = time.monotonic() + self.response_timeout

        # Chỉ đáng chờ thêm khi app đã từng cho thấy nó có trả lời (hộp thoại,
        # từ khóa, hay in lại mã). App nào xử lý xong là im lặng thì chờ chỉ tổ
        # cộng thêm ngần này giây vào từng dòng mà chẳng biết thêm gì.
        quiet_window = (
            min(QUIET_TIMEOUT_SECONDS, self.response_timeout)
            if (self._verdict_seen or self._echo_seen)
            else 0.0
        )
        quiet_deadline = time.monotonic() + quiet_window
        last_xml = ""

        while True:
            xml = self.screen.dump_xml()
            if xml:
                last_xml = xml
                state = self._response_state(xml, serial)
                if state == RESPONSE_FRESH:
                    return xml, state
            else:
                state = RESPONSE_NONE

            now = time.monotonic()
            if state == RESPONSE_STALE:
                # Biết chắc app chưa xong: đáng chờ hết thời gian cho phép.
                if now >= deadline:
                    return last_xml, RESPONSE_STALE
            elif now >= quiet_deadline:
                # Không thấy dấu hiệu nào của phản hồi. Nhiều app xử lý xong là
                # im lặng, chờ tiếp chỉ tổ chậm cả phiên chạy.
                return last_xml, RESPONSE_NONE

            if self._stop_flag.is_set():
                return last_xml, RESPONSE_NONE
            time.sleep(RESPONSE_POLL_INTERVAL_SECONDS)

    def _response_state(self, xml: str, serial: str) -> str:
        """
        FRESH  - màn hình đang nói về serial vừa gửi
        STALE  - vẫn là màn hình trả lời serial trước đó
        NONE   - chưa thấy gì để kết luận
        """
        if not serial:
            return RESPONSE_FRESH

        haystack = self._normalize_match_text(xml)
        if self._normalize_match_text(serial) in haystack:
            # App in lại mã vừa quét -> vừa xác nhận app đã xử lý đúng serial
            # này, vừa chứng minh ký tự gửi đi không bị sai lệch.
            self._echo_seen = True
            return RESPONSE_FRESH

        previous = self._previous_serial
        if previous and self._normalize_match_text(previous) in haystack:
            return RESPONSE_STALE

        if self._echo_seen:
            # App vốn có in lại mã, lần này chưa thấy nghĩa là chưa xử lý xong.
            return RESPONSE_NONE

        return RESPONSE_FRESH if self._screen_has_verdict(xml) else RESPONSE_NONE

    def _screen_has_verdict(self, xml: str) -> bool:
        haystack = self._normalize_match_text(xml)
        keywords = self.not_found_keywords + self.error_keywords + self.success_keywords
        found = any(kw and kw in haystack for kw in keywords) or (
            find_dismiss_button(xml) is not None
        )
        if found:
            self._verdict_seen = True
        return found

    def _error_verdict(self, content: str, reason: str, matched_keyword: str) -> dict:
        message = dialog_message(content)
        dismissed = self._dismiss_error_dialog(content)
        return {
            "status": "ERROR",
            "response_text": message or matched_keyword or "Hộp thoại lỗi",
            "reason": reason,
            "dismiss_failed": not dismissed,
        }

    def _normalize_match_text(self, text: str) -> str:
        return normalize_match_text(text)

    def _check_error_dialog_fast(self) -> bool | None:
        """True/False = có/không hộp thoại đang focus, None = ADB không trả lời."""
        output = self.adb_client.run_shell("dumpsys window windows")
        if output is None:
            return None

        focus = self._current_focus_window(output).lower()
        if not focus:
            return False

        return any(token in focus for token in ERROR_DIALOG_TOKENS)

    def _current_focus_window(self, window_dump: str) -> str:
        return current_focus_window(window_dump)

    # ------------------------------------------- nhớ qua từng phiên chạy

    def _sync_device_profile(self, focus: str) -> None:
        """
        Nạp lại những gì phiên chạy trước đã dò ra trên chính máy ảo + app này.

        Cụ thể là câu "hộp thoại của app này có phải cửa sổ riêng không" - câu
        duy nhất mà bot không tự hỏi được, phải chờ có hộp thoại lỗi thật mới
        trả lời được. Phiên chạy sạch không lỗi thì không bao giờ trả lời được,
        nên đường nhanh nằm im cả phiên và mỗi dòng gánh thêm ~750ms oan (xem
        device_profile).
        """
        self._device_key = ""
        package = _package_of_focus(focus)
        if not package:
            return

        version = self._app_version_code(package)
        key = device_profile.device_key(self.instance_name, package, version)
        if not key:
            # Không đọc được phiên bản app thì không dám tin bản nhớ: app cập
            # nhật là cách nó vẽ hộp thoại có thể đã khác.
            logger.info("Không đọc được versionCode của %s - dò lại từ đầu.", package)
            return

        self._device_key = key
        remembered = device_profile.load(key).get("dialog_seen_by_dumpsys")
        if self._dialog_seen_by_dumpsys is None and isinstance(remembered, bool):
            self._dialog_seen_by_dumpsys = remembered
            logger.info(
                "Nhớ từ phiên trước (%s): hộp thoại của app %s cửa sổ riêng - "
                "%s ngay từ dòng đầu.",
                key,
                "LÀ" if remembered else "KHÔNG phải",
                "dùng đường nhanh" if remembered else "đọc cả màn hình",
            )

    def _app_version_code(self, package: str) -> str:
        """versionCode của app đang chạy. Rỗng = không đọc được."""
        for command in (
            f"dumpsys package {package} | grep -m1 versionCode",
            f"dumpsys package {package}",
        ):
            output = self.adb_client.run_shell(command)
            match = re.search(r"versionCode=(\S+)", output or "")
            if match:
                return match.group(1)
        return ""

    def _remember_dialog_window(self, seen: bool) -> None:
        """Ghi nhớ câu trả lời cho cả phiên này lẫn những phiên sau."""
        self._dialog_seen_by_dumpsys = seen
        if self._device_key:
            device_profile.save(self._device_key, {"dialog_seen_by_dumpsys": seen})

    def _dismiss_error_dialog(self, screen_xml: str) -> bool:
        """
        Bấm nút đóng hộp thoại rồi kiểm tra lại xem nó đã biến mất chưa.

        Gửi lệnh thành công không có nghĩa là hộp thoại đã đóng - chạm trượt hay
        bấm nhầm nút vẫn trả về OK. Mà đóng hụt thì serial kế tiếp gõ vào màn
        hình đang kẹt và bị chấm sai, nên phải xác nhận bằng mắt thật.
        """
        # Ghi lại cửa sổ đang focus TRƯỚC khi bấm. Hộp thoại là một cửa sổ riêng,
        # nên chuỗi này đổi ngay khi nó đóng - kể cả với app mà dumpsys không hề
        # đặt tên cửa sổ là 'dialog'. So chuỗi tốn ~130ms, trong khi dump cả cây
        # view để đối chiếu nội dung tốn ~1200ms.
        focus_with_dialog = ""
        if self._dialog_seen_by_dumpsys is not False:
            focus_with_dialog = self.screen.focused_window() or ""

        if not self._tap_ok_button(screen_xml):
            # Không thấy nút nào: thử Enter, nút mặc định của AlertDialog thường là OK.
            if self.adb_client.run_shell("input keyevent 66") is None:
                return False

        if focus_with_dialog and self._focus_moved_off(focus_with_dialog):
            self._remember_dialog_window(True)
            return True

        if self._dialog_seen_by_dumpsys is None:
            # Focus không đổi ở lần đầu tiên: hộp thoại của app này không phải
            # cửa sổ riêng (tự vẽ kiểu Flutter/WebView), thôi đừng hỏi nữa.
            self._remember_dialog_window(False)

        return not self._dialog_still_open(screen_xml)

    def _focus_moved_off(self, focus_with_dialog: str) -> bool:
        """
        Cửa sổ đang focus đã rời khỏi hộp thoại chưa.

        Chỉ dò trong một khoảng ngắn: quá thời gian đó thì hoặc hộp thoại đang
        kẹt thật, hoặc nó vốn không phải cửa sổ riêng - cả hai trường hợp đều
        phải nhờ tới bước đối chiếu nội dung mới kết luận được.
        """
        deadline = time.monotonic() + DISMISS_FOCUS_PROBE_SECONDS
        while True:
            focus = self.screen.focused_window()
            if focus is None:
                return False        # ADB im: không kết luận bừa là đã đóng
            if focus and focus != focus_with_dialog:
                return True
            if time.monotonic() >= deadline or self._stop_flag.is_set():
                return False
            time.sleep(RESPONSE_POLL_INTERVAL_SECONDS)

    def _dialog_still_open(self, previous_xml: str) -> bool:
        """
        Kiểm tra bằng chính nội dung màn hình chứ không bằng tên cửa sổ đang
        focus: hộp thoại tự vẽ (Flutter/WebView) nằm trong cửa sổ của app nên
        dumpsys không hề gọi nó là 'dialog', và bot sẽ tưởng đã đóng xong.
        """
        marker = self._normalize_match_text(dialog_marker(previous_xml)) if previous_xml else ""
        deadline = time.monotonic() + DISMISS_VERIFY_TIMEOUT_SECONDS

        while True:
            after = self.screen.dump_xml()
            if not after:
                return self._check_error_dialog_fast() is not False

            if marker:
                if marker not in self._normalize_match_text(after):
                    return False
            elif find_dismiss_button(after) is None:
                return False

            if time.monotonic() >= deadline or self._stop_flag.is_set():
                return True
            time.sleep(RESPONSE_POLL_INTERVAL_SECONDS)

    def _tap_ok_button(self, screen_xml: str) -> bool:
        node = find_dismiss_button(screen_xml) if screen_xml else None
        if not node:
            return False

        bounds = parse_bounds(node.get("bounds", ""))
        if not bounds:
            return False

        x1, y1, x2, y2 = bounds
        output = self.adb_client.run_shell(
            f"input tap {(x1 + x2) // 2} {(y1 + y2) // 2}"
        )
        return output is not None

    def _xml_attr(self, node: str, attr: str) -> str:
        return xml_attr(node, attr)

    def _read_screen_xml(self) -> str:
        return self.screen.dump_xml()

    def _extract_xml(self, text: str) -> str:
        return extract_xml(text)

    def _capture_screenshot(self, row: int, serial: str) -> str | None:
        data = self.adb_client.run_exec_out_binary("screencap -p")
        if not data:
            return None

        os.makedirs(self.screenshot_dir, exist_ok=True)
        safe_serial = re.sub(r"[^A-Za-z0-9_-]", "_", serial)[:40]
        path = os.path.join(self.screenshot_dir, f"{row}_{safe_serial}.png")
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            return None
        return path
