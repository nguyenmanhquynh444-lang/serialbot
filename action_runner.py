"""
action_runner.py
Executes a recipe (list of Step) once per Excel row.

The runner owns no UI and no Qt types so it can be tested headlessly.
"""
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from actions import (
    KEY_CODES,
    ON_FAIL_ERROR,
    ON_FAIL_STOP,
    REASON_APP_ERROR,
    REASON_NOT_FOUND,
    Step,
)
from automation_backend import WindowFocusError
from screen_reader import (
    ScreenReader,
    dialog_message,
    find_dismiss_button,
    normalize_match_text,
)

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{([a-zA-Z_]+)(?::([^}]*))?\}")


class StopRun(Exception):
    """Raised when a step's failure policy asks to abort the whole run."""


@dataclass
class RowContext:
    row: int
    serial: str
    cells: dict = field(default_factory=dict)
    variables: dict = field(default_factory=dict)


@dataclass
class RowResult:
    status: str = "OK"            # OK | ERROR | UNKNOWN
    message: str = ""
    response_text: str = ""
    reason: str = ""              # actions.REASON_* khi status là ERROR
    screenshot_path: str | None = None
    cell_writes: dict = field(default_factory=dict)
    adb_failed: bool = False
    dismiss_failed: bool = False
    focus_failed: bool = False


def resolve_text(template: str, ctx: RowContext) -> str:
    """Expand {serial}, {row}, {cell:B}, {var:name}, {date}, {time}."""
    if not template:
        return ""

    def replace(match: re.Match) -> str:
        kind = match.group(1).lower()
        arg = (match.group(2) or "").strip()

        if kind == "serial":
            return ctx.serial
        if kind == "row":
            return str(ctx.row)
        if kind == "cell":
            return str(ctx.cells.get(arg.upper(), ""))
        if kind == "var":
            return str(ctx.variables.get(arg, ""))
        if kind == "date":
            return datetime.now().strftime("%Y-%m-%d")
        if kind == "time":
            return datetime.now().strftime("%H:%M:%S")
        return match.group(0)

    return _VAR_RE.sub(replace, str(template))


class ActionRunner:
    """
    Runs a recipe against one device.

    backend  - supplies type/key so the pyautogui fallback still works
    adb_client - needed for the screen-aware steps (tap, wait_for, check...)
    screen   - lớp đọc màn hình. Để trống thì đọc qua uiautomator như cũ; chạy
               trên trình duyệt thì backend đưa sẵn BrowserScreen vào đây, và
               mọi bước phía dưới không cần biết mình đang ở Android hay web.
    """

    def __init__(
        self,
        steps: list[Step],
        backend,
        adb_client,
        screenshot_dir: str = "screenshots",
        capture_screenshot_on_error: bool = False,
        screen=None,
    ):
        self.steps = steps
        self.backend = backend
        self.adb = adb_client
        self.screen = screen or getattr(backend, "screen", None) or ScreenReader(adb_client)
        self.screenshot_dir = screenshot_dir
        self.capture_screenshot_on_error = capture_screenshot_on_error
        # Bước ngay trước có phải "xóa ô" chạy trót lọt không - xem _step_type.
        self._field_is_empty = False

    def run_row(self, ctx: RowContext) -> RowResult:
        result = RowResult()
        previous_type = ""

        for index, step in enumerate(self.steps, start=1):
            if not step.enabled:
                continue
            # Chỉ tin "ô đang trống" khi bước xóa ô nằm NGAY TRƯỚC và đã chạy
            # trót lọt: xen một bước Enter vào giữa là app có thể đã tự điền lại
            # ô, lúc đó bỏ lệnh xóa là nối serial này vào phần app để lại.
            self._field_is_empty = previous_type == "clear_field"
            try:
                ok, detail = self._run_step(step, ctx, result)
            except StopRun:
                raise
            except Exception as e:
                logger.exception("Row %s step %d (%s) crashed", ctx.row, index, step.type)
                ok, detail = False, str(e)

            if ok:
                previous_type = step.type
                continue

            previous_type = ""
            label = step.spec().label if step.type in _known_types() else step.type
            message = f"Bước {index} ({label}) thất bại: {detail}"

            if step.on_fail == ON_FAIL_STOP:
                result.status = "ERROR"
                result.message = message
                raise StopRun(message)
            if step.on_fail == ON_FAIL_ERROR:
                result.status = "ERROR"
                result.message = message
                result.response_text = result.response_text or detail
                break
            logger.info("Row %s: %s (bỏ qua theo cấu hình)", ctx.row, message)

        if result.status == "OK" and not result.message:
            result.message = "Hoàn tất kịch bản"

        if self.capture_screenshot_on_error and result.status in ("ERROR", "UNKNOWN"):
            result.screenshot_path = self._save_screenshot(ctx)

        return result

    # ---------------------------------------------------------------- steps

    def _run_step(self, step: Step, ctx: RowContext, result: RowResult) -> tuple[bool, str]:
        handler = getattr(self, f"_step_{step.type}", None)
        if handler is None:
            return False, f"loại bước không hỗ trợ: {step.type}"
        return handler(step, ctx, result)

    def _step_clear_field(self, step, ctx, result):
        """
        Xóa ô nhập - qua backend, để đi chung đường tối ưu với luồng chạy thường.

        Bản cũ tự dựng lệnh ở đây: ba lệnh `input` rời nhau cho đúng dãy phím mà
        backend gửi gọn trong một lệnh. Mỗi lệnh `input` là một lần máy ảo dựng
        tiến trình Java (~300ms), nên riêng bước này của kịch bản đắt gấp ba lần
        cần thiết - mà nó chạy trên MỌI dòng.
        """
        clear = getattr(self.backend, "clear_field", None)
        if clear is None:
            # Backend lạ (test giả, bản cũ): giữ nguyên đường cũ chứ không hỏng.
            del_keys = " ".join(["67"] * 20)
            out = self.adb.run_shell(
                f"input keyevent 123; input keyevent 28; input keyevent {del_keys}"
            )
            if out is None:
                result.adb_failed = True
                return False, "không gửi được lệnh tới thiết bị"
            return True, ""

        try:
            clear()
        except WindowFocusError as e:
            result.focus_failed = True
            return False, str(e)
        except Exception as e:
            result.adb_failed = True
            return False, str(e)
        return True, ""

    def _step_type(self, step, ctx, result):
        """
        Gõ chuỗi vào ô đang focus.

        `type_serial` luôn xóa ô trước khi gõ - đúng cho kịch bản chỉ có bước gõ,
        nhưng kịch bản mặc định có hẳn một bước "xóa ô" đứng ngay trước, nên ô đã
        trống rồi mà vẫn xóa thêm lần nữa: thừa ~600ms mỗi dòng cho một dãy 22
        phím không xóa gì cả. Xóa xong ngay trước đó thì gõ thẳng.
        """
        text = resolve_text(step.param("text"), ctx)
        if not text:
            return False, "nội dung rỗng sau khi thay biến"
        type_only = getattr(self.backend, "type_and_submit", None)
        try:
            if self._field_is_empty and type_only is not None:
                type_only(text, "none", clear_first=False)
            else:
                self.backend.type_serial(text)
        except WindowFocusError as e:
            # Không phải thiết bị hỏng: cửa sổ máy ảo không ở trước nên bước gõ
            # tự chặn lại. Đếm chung với lỗi ADB thì vòng chạy báo sai nguyên nhân.
            result.focus_failed = True
            return False, str(e)
        except Exception as e:
            result.adb_failed = True
            return False, str(e)
        return True, ""

    def _step_key(self, step, ctx, result):
        key = str(step.param("key")).lower()
        code = KEY_CODES.get(key)
        if code is None:
            return False, f"phím không hỗ trợ: {key}"

        # Backend nào tự gửi được phím thì để nó gửi - trên trình duyệt thì
        # `input keyevent` của Android không có nghĩa gì cả.
        send_key = getattr(self.backend, "send_key", None)
        if send_key is not None:
            try:
                send_key(key)
            except WindowFocusError as e:
                result.focus_failed = True
                return False, str(e)
            except Exception as e:
                result.adb_failed = True
                return False, str(e)
            return True, ""

        if self.adb.run_shell(f"input keyevent {code}") is None:
            result.adb_failed = True
            return False, "không gửi được phím tới thiết bị"
        return True, ""

    def _step_tap(self, step, ctx, result):
        if not self.screen.tap(int(step.param("x")), int(step.param("y"))):
            result.adb_failed = True
            return False, "không gửi được lệnh chạm"
        return True, ""

    def _step_tap_element(self, step, ctx, result):
        node = self.screen.wait_for(
            text=resolve_text(step.param("text"), ctx),
            resource_id=str(step.param("resource_id") or ""),
            timeout=float(step.param("timeout")),
        )
        if not node:
            return False, "không tìm thấy phần tử"
        if not self.screen.tap_node(node):
            result.adb_failed = True
            return False, "tìm thấy phần tử nhưng không chạm được"
        return True, ""

    def _step_swipe(self, step, ctx, result):
        ok = self.screen.swipe(
            int(step.param("x1")), int(step.param("y1")),
            int(step.param("x2")), int(step.param("y2")),
            int(step.param("duration_ms")),
        )
        if not ok:
            result.adb_failed = True
            return False, "không gửi được lệnh vuốt"
        return True, ""

    def _step_wait(self, step, ctx, result):
        time.sleep(max(0.0, float(step.param("seconds"))))
        return True, ""

    def _step_wait_for(self, step, ctx, result):
        node = self.screen.wait_for(
            text=resolve_text(step.param("text"), ctx),
            resource_id=str(step.param("resource_id") or ""),
            timeout=float(step.param("timeout")),
        )
        if not node:
            return False, "hết thời gian chờ mà phần tử không xuất hiện"
        return True, ""

    def _step_read(self, step, ctx, result):
        node = self.screen.wait_for(
            text=resolve_text(step.param("text"), ctx),
            resource_id=str(step.param("resource_id") or ""),
            timeout=float(step.param("timeout")),
        )
        if not node:
            return False, "không tìm thấy phần tử để đọc"
        value = node.get("text") or node.get("content_desc") or ""
        ctx.variables[str(step.param("var_name"))] = value
        result.response_text = value
        return True, ""

    def _step_check(self, step, ctx, result):
        xml = self.screen.dump_xml()
        if not xml:
            result.adb_failed = True
            result.status = "UNKNOWN"
            return False, "không đọc được màn hình để kiểm tra"

        content = normalize_match_text(xml)
        error_kws = _split_keywords(resolve_text(step.param("error_keywords"), ctx))
        success_kws = _split_keywords(resolve_text(step.param("success_keywords"), ctx))
        not_found_kws = _split_keywords(resolve_text(step.param("not_found_keywords"), ctx))
        dismiss = _as_bool(step.param("dismiss_dialog"), True)

        # "Không tìm thấy" xét trước từ khóa lỗi chung, vì từ khóa lỗi thường
        # khớp luôn cả câu đó và sẽ nuốt mất lý do cụ thể.
        for kw in not_found_kws:
            if kw in content:
                self._record_error(result, xml, REASON_NOT_FOUND, kw, dismiss)
                result.message = f"Không tìm thấy serial: '{result.response_text}'"
                return True, ""

        for kw in error_kws:
            if kw in content:
                self._record_error(result, xml, REASON_APP_ERROR, kw, dismiss)
                result.message = f"Màn hình báo lỗi: '{result.response_text}'"
                return True, ""

        if success_kws:
            for kw in success_kws:
                if kw in content:
                    result.status = "OK"
                    result.response_text = kw
                    result.message = f"Khớp từ khóa thành công: '{kw}'"
                    return True, ""
            result.status = "UNKNOWN"
            result.message = "Không khớp từ khóa thành công lẫn lỗi"
            return True, ""

        result.status = "OK"
        return True, ""

    def _step_write_cell(self, step, ctx, result):
        column = str(step.param("column")).strip().upper()
        if not column:
            return False, "thiếu tên cột"
        result.cell_writes[column] = resolve_text(step.param("value"), ctx)
        return True, ""

    # -------------------------------------------------------------- bước cho web

    def _web(self, result: RowResult):
        """
        Lớp đọc màn hình, nếu nó là trình duyệt.

        Bước web nằm trong kịch bản chạy bằng ADB là cấu hình sai chứ không phải
        thiết bị hỏng - nên báo rõ ràng ngay tại bước, đừng đếm vào lỗi ADB rồi
        làm cả phiên chạy tự dừng vì tưởng máy ảo chết.
        """
        if getattr(self.screen, "click", None) is None:
            return None
        return self.screen

    _WEB_ONLY = "bước này chỉ chạy khi bot đang nối với trình duyệt"

    def _step_web_open(self, step, ctx, result):
        screen = self._web(result)
        if screen is None:
            return False, self._WEB_ONLY
        url = resolve_text(step.param("url"), ctx)
        if not url:
            return False, "địa chỉ rỗng sau khi thay biến"
        if not screen.open_url(url, timeout=float(step.param("timeout"))):
            return False, f"không mở được '{url}'"
        return True, ""

    def _step_web_click(self, step, ctx, result):
        screen = self._web(result)
        if screen is None:
            return False, self._WEB_ONLY
        selector = resolve_text(step.param("selector"), ctx)
        text = resolve_text(step.param("text"), ctx)
        if not (selector or text):
            return False, "cần selector hoặc chữ trên nút"
        if not screen.click(selector, text, timeout=float(step.param("timeout"))):
            return False, f"không bấm được '{selector or text}'"
        return True, ""

    def _step_web_fill(self, step, ctx, result):
        screen = self._web(result)
        if screen is None:
            return False, self._WEB_ONLY
        selector = resolve_text(step.param("selector"), ctx)
        value = resolve_text(step.param("value"), ctx)
        if not selector:
            return False, "thiếu selector"
        if not screen.fill(selector, value, timeout=float(step.param("timeout"))):
            return False, f"không điền được vào '{selector}'"
        return True, ""

    def _step_web_select(self, step, ctx, result):
        screen = self._web(result)
        if screen is None:
            return False, self._WEB_ONLY
        selector = resolve_text(step.param("selector"), ctx)
        value = resolve_text(step.param("value"), ctx)
        if not selector:
            return False, "thiếu selector"
        if not screen.select_option(selector, value, timeout=float(step.param("timeout"))):
            return False, f"không chọn được '{value}'"
        return True, ""

    def _step_web_wait(self, step, ctx, result):
        screen = self._web(result)
        if screen is None:
            return False, self._WEB_ONLY
        selector = resolve_text(step.param("selector"), ctx)
        if not selector:
            return False, "thiếu selector"
        state = str(step.param("state") or "visible")
        if not screen.wait_selector(selector, state, timeout=float(step.param("timeout"))):
            return False, f"hết thời gian chờ mà '{selector}' chưa ở trạng thái {state}"
        return True, ""

    def _step_web_read(self, step, ctx, result):
        screen = self._web(result)
        if screen is None:
            return False, self._WEB_ONLY
        selector = resolve_text(step.param("selector"), ctx)
        text = resolve_text(step.param("text"), ctx)
        if not (selector or text):
            return False, "cần selector hoặc chữ để tìm"
        value = screen.read_selector(selector, text, timeout=float(step.param("timeout")))
        if value is None:
            return False, f"không đọc được '{selector or text}'"
        ctx.variables[str(step.param("var_name"))] = value
        result.response_text = value
        return True, ""

    def _step_screenshot(self, step, ctx, result):
        path = self._save_screenshot(ctx)
        if not path:
            result.adb_failed = True
            return False, "không chụp được màn hình"
        result.screenshot_path = path
        return True, ""

    # ---------------------------------------------------------------- helpers

    def _record_error(self, result: RowResult, xml: str, reason: str, keyword: str, dismiss: bool):
        """
        Ghi lỗi kèm đúng câu app báo, rồi đóng hộp thoại.

        Đọc nội dung trước khi bấm - bấm xong là màn hình đổi, không còn gì để
        ghi vào Excel. Và phải đóng, nếu không dòng kế tiếp sẽ gõ vào màn hình
        vẫn đang bị hộp thoại chặn.
        """
        result.status = "ERROR"
        result.reason = reason
        result.response_text = dialog_message(xml) or keyword
        if dismiss:
            result.dismiss_failed = not self._dismiss_dialog(xml)

    def _dismiss_dialog(self, xml: str) -> bool:
        node = find_dismiss_button(xml)
        if node and self.screen.tap_node(node):
            return True

        # Không thấy nút đóng: gõ Enter, hộp thoại nào cũng nhận. Qua backend
        # trước để đường trình duyệt dùng phím thật của trình duyệt.
        send_key = getattr(self.backend, "send_key", None)
        if send_key is not None:
            try:
                send_key("enter")
                return True
            except Exception:
                return False
        return self.adb.run_shell(f"input keyevent {KEY_CODES['enter']}") is not None

    def _save_screenshot(self, ctx: RowContext) -> str | None:
        data = self.screen.screenshot_png()
        if not data:
            return None
        os.makedirs(self.screenshot_dir, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", ctx.serial)[:40]
        path = os.path.join(self.screenshot_dir, f"{ctx.row}_{safe}.png")
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            return None
        return path


def _split_keywords(text: str) -> list[str]:
    return [normalize_match_text(k) for k in str(text).split(",") if k.strip()]


def _as_bool(value, default: bool = True) -> bool:
    """Tham số bool của bước quay về từ JSON có thể là chuỗi 'true'/'false'."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def _known_types():
    from actions import STEP_TYPES

    return STEP_TYPES
