"""
actions.py
Step catalogue for the customisable automation recipe.

Each step type declares its parameters as a small schema so the editor can build
its form automatically - adding a new step type here makes it appear in the UI
without touching action_editor.py.
"""
from dataclasses import dataclass, field

# Failure policies decide what a failing step does to the row being processed.
ON_FAIL_CONTINUE = "continue"
ON_FAIL_ERROR = "error"
ON_FAIL_STOP = "stop"

ON_FAIL_LABELS = {
    ON_FAIL_CONTINUE: "Bỏ qua, chạy bước tiếp",
    ON_FAIL_ERROR: "Đánh dấu dòng là lỗi",
    ON_FAIL_STOP: "Dừng cả phiên chạy",
}

# Lý do một dòng bị đánh dấu lỗi. Trạng thái vẫn là ERROR như cũ; lý do là thứ
# đi kèm vào Excel/báo cáo để phân biệt "serial này hệ thống không có" với
# "app báo lỗi khác", vì hai loại đó xử lý sau đó hoàn toàn khác nhau.
REASON_NOT_FOUND = "NOT_FOUND"
REASON_APP_ERROR = "APP_ERROR"
REASON_DIALOG = "DIALOG"

REASON_LABELS = {
    REASON_NOT_FOUND: "Không tìm thấy serial",
    REASON_APP_ERROR: "App báo lỗi",
    REASON_DIALOG: "Hộp thoại lạ",
}

# Mặc định cho ô "Từ khóa không tìm thấy". So khớp đã bỏ dấu và không phân biệt
# hoa thường (normalize_match_text), nên chỉ cần liệt kê một biến thể.
DEFAULT_NOT_FOUND_KEYWORDS = (
    "không tìm thấy,không tìm được,not found,không tồn tại,does not exist,"
    "no record,chưa có dữ liệu"
)

# Trạng thái chờ được của bước "Chờ phần tử (web)" - tên lấy đúng của Playwright
# để khỏi phải dịch qua lại một lớp nữa.
WEB_WAIT_STATES = ("visible", "hidden", "attached", "detached")

KEY_CODES = {
    "enter": 66,
    "tab": 61,
    "back": 4,
    "home": 3,
    "delete": 67,
    "search": 84,
    "escape": 111,
    "dpad_down": 20,
    "dpad_up": 19,
}


@dataclass
class ParamSpec:
    name: str
    label: str
    kind: str           # text | int | float | choice | bool
    default: object = ""
    choices: tuple = ()
    hint: str = ""


@dataclass
class StepType:
    name: str
    label: str
    description: str
    params: tuple = ()
    adb_only: bool = False
    browser_only: bool = False


STEP_TYPES: dict[str, StepType] = {
    "clear_field": StepType(
        "clear_field", "Xóa ô nhập",
        "Xóa sạch nội dung ô đang được focus",
    ),
    "type": StepType(
        "type", "Gõ chữ",
        "Gõ nội dung vào ô đang focus, hỗ trợ biến",
        params=(
            ParamSpec("text", "Nội dung", "text", "{serial}",
                      hint="Dùng {serial}, {cell:B}, {row}, {var:ten}"),
        ),
    ),
    "key": StepType(
        "key", "Gửi phím",
        "Gửi một phím bấm tới thiết bị",
        params=(
            ParamSpec("key", "Phím", "choice", "enter", tuple(KEY_CODES)),
        ),
    ),
    "tap": StepType(
        "tap", "Chạm tọa độ",
        "Chạm vào một điểm trên màn hình",
        params=(
            ParamSpec("x", "X", "int", 0),
            ParamSpec("y", "Y", "int", 0),
        ),
        adb_only=True,
    ),
    "tap_element": StepType(
        "tap_element", "Chạm phần tử",
        "Tìm phần tử theo text hoặc id rồi chạm - bền hơn tọa độ",
        params=(
            ParamSpec("text", "Text chứa", "text", ""),
            ParamSpec("resource_id", "Resource id", "text", ""),
            ParamSpec("timeout", "Chờ tối đa (s)", "float", 5.0),
        ),
        adb_only=True,
    ),
    "swipe": StepType(
        "swipe", "Vuốt",
        "Vuốt từ điểm này sang điểm khác",
        params=(
            ParamSpec("x1", "X bắt đầu", "int", 0),
            ParamSpec("y1", "Y bắt đầu", "int", 0),
            ParamSpec("x2", "X kết thúc", "int", 0),
            ParamSpec("y2", "Y kết thúc", "int", 0),
            ParamSpec("duration_ms", "Thời gian (ms)", "int", 300),
        ),
        adb_only=True,
    ),
    "wait": StepType(
        "wait", "Chờ cố định",
        "Dừng một khoảng thời gian",
        params=(
            ParamSpec("seconds", "Số giây", "float", 0.5),
        ),
    ),
    "wait_for": StepType(
        "wait_for", "Chờ phần tử",
        "Chờ tới khi phần tử xuất hiện - thay cho delay cứng",
        params=(
            ParamSpec("text", "Text chứa", "text", ""),
            ParamSpec("resource_id", "Resource id", "text", ""),
            ParamSpec("timeout", "Chờ tối đa (s)", "float", 10.0),
        ),
        adb_only=True,
    ),
    "read": StepType(
        "read", "Đọc chữ vào biến",
        "Đọc text của phần tử và lưu vào biến để dùng sau",
        params=(
            ParamSpec("resource_id", "Resource id", "text", ""),
            ParamSpec("text", "Text chứa", "text", ""),
            ParamSpec("var_name", "Tên biến", "text", "ketqua"),
            ParamSpec("timeout", "Chờ tối đa (s)", "float", 5.0),
        ),
        adb_only=True,
    ),
    "check": StepType(
        "check", "Kiểm tra kết quả",
        "Quyết định dòng này là OK hay lỗi dựa trên nội dung màn hình",
        params=(
            ParamSpec("success_keywords", "Từ khóa thành công", "text", "",
                      hint="Ngăn cách bằng dấu phẩy, để trống = bỏ qua"),
            ParamSpec("error_keywords", "Từ khóa lỗi", "text", ""),
            ParamSpec("not_found_keywords", "Từ khóa không tìm thấy", "text",
                      DEFAULT_NOT_FOUND_KEYWORDS,
                      hint="Khớp thì ghi lý do 'Không tìm thấy serial' vào Excel"),
            ParamSpec("dismiss_dialog", "Tự bấm OK khi lỗi", "bool", True,
                      hint="Đóng hộp thoại báo lỗi để serial sau không gõ vào màn hình đang kẹt"),
        ),
        adb_only=True,
    ),
    "write_cell": StepType(
        "write_cell", "Ghi ra cột Excel",
        "Ghi một giá trị vào cột Excel của dòng hiện tại",
        params=(
            ParamSpec("column", "Cột", "text", "J"),
            ParamSpec("value", "Giá trị", "text", "{var:ketqua}"),
        ),
    ),
    "screenshot": StepType(
        "screenshot", "Chụp màn hình",
        "Lưu ảnh màn hình hiện tại làm bằng chứng",
        adb_only=True,
    ),

    # --------------------------------------------------------- bước cho trình duyệt
    #
    # Các bước chung ở trên (gõ chữ, gửi phím, chờ phần tử, kiểm tra kết quả...)
    # chạy được cả trên web: BrowserScreen dựng cây DOM thành đúng dạng XML mà
    # chúng đang đọc, và "Resource id" lúc đó là id/name của thẻ HTML.
    #
    # Nhóm dưới đây là thứ chỉ web mới có: chọn phần tử bằng CSS selector. Bền
    # hơn khớp theo chữ vì không đổi khi hệ thống đổi nhãn hay đổi ngôn ngữ.
    "web_open": StepType(
        "web_open", "Mở trang web",
        "Chuyển tab hiện tại sang một địa chỉ",
        params=(
            ParamSpec("url", "Địa chỉ", "text", "",
                      hint="Dùng được biến: .../serial/{serial}"),
            ParamSpec("timeout", "Chờ tối đa (s)", "float", 15.0),
        ),
        browser_only=True,
    ),
    "web_click": StepType(
        "web_click", "Bấm nút (web)",
        "Bấm bằng DOM: tự cuộn tới, tự chờ nút hết bị che và hết mờ rồi mới bấm",
        params=(
            ParamSpec("selector", "CSS selector", "text", "",
                      hint="Ví dụ: button.btn-primary, #btn-luu"),
            ParamSpec("text", "Chữ trên nút", "text", "",
                      hint="Để trống nếu đã có selector; điền cả hai = lọc theo cả hai"),
            ParamSpec("timeout", "Chờ tối đa (s)", "float", 15.0),
        ),
        browser_only=True,
    ),
    "web_fill": StepType(
        "web_fill", "Điền ô (web)",
        "Xóa rồi điền thẳng vào ô chỉ định, không cần ô đang được focus",
        params=(
            ParamSpec("selector", "CSS selector", "text", ""),
            ParamSpec("value", "Giá trị", "text", "{serial}"),
            ParamSpec("timeout", "Chờ tối đa (s)", "float", 15.0),
        ),
        browser_only=True,
    ),
    "web_select": StepType(
        "web_select", "Chọn trong danh sách (web)",
        "Chọn một mục của thẻ <select>, khớp theo value hoặc theo chữ hiển thị",
        params=(
            ParamSpec("selector", "CSS selector", "text", ""),
            ParamSpec("value", "Giá trị / nhãn", "text", ""),
            ParamSpec("timeout", "Chờ tối đa (s)", "float", 15.0),
        ),
        browser_only=True,
    ),
    "web_wait": StepType(
        "web_wait", "Chờ phần tử (web)",
        "Chờ phần tử hiện ra hoặc biến mất - thay cho delay cứng",
        params=(
            ParamSpec("selector", "CSS selector", "text", ""),
            ParamSpec("state", "Trạng thái", "choice", "visible", WEB_WAIT_STATES),
            ParamSpec("timeout", "Chờ tối đa (s)", "float", 15.0),
        ),
        browser_only=True,
    ),
    "web_read": StepType(
        "web_read", "Đọc chữ (web)",
        "Đọc chữ của phần tử vào biến để ghi ra Excel",
        params=(
            ParamSpec("selector", "CSS selector", "text", ""),
            ParamSpec("text", "Chữ chứa", "text", ""),
            ParamSpec("var_name", "Tên biến", "text", "ketqua"),
            ParamSpec("timeout", "Chờ tối đa (s)", "float", 15.0),
        ),
        browser_only=True,
    ),
}


@dataclass
class Step:
    type: str
    params: dict = field(default_factory=dict)
    on_fail: str = ON_FAIL_ERROR
    enabled: bool = True

    def spec(self) -> StepType:
        return STEP_TYPES[self.type]

    def param(self, name: str, fallback=None):
        spec = STEP_TYPES.get(self.type)
        if spec:
            for p in spec.params:
                if p.name == name:
                    return self.params.get(name, p.default)
        return self.params.get(name, fallback)

    def summary(self) -> str:
        spec = STEP_TYPES.get(self.type)
        if not spec:
            return f"(bước không rõ: {self.type})"
        if not spec.params:
            return spec.label
        bits = []
        for p in spec.params:
            value = self.params.get(p.name, p.default)
            if value not in ("", None):
                bits.append(f"{p.label}={value}")
        return f"{spec.label}: " + ", ".join(bits) if bits else spec.label

    def to_dict(self) -> dict:
        data = {"type": self.type, "params": dict(self.params), "on_fail": self.on_fail}
        if not self.enabled:
            data["enabled"] = False
        return data

    @staticmethod
    def from_dict(data: dict) -> "Step":
        return Step(
            type=data["type"],
            params=dict(data.get("params", {})),
            on_fail=data.get("on_fail", ON_FAIL_ERROR),
            enabled=data.get("enabled", True),
        )


def make_step(step_type: str) -> Step:
    """Create a step pre-filled with its declared defaults."""
    spec = STEP_TYPES[step_type]
    return Step(
        type=step_type,
        params={p.name: p.default for p in spec.params},
    )


def validate_steps(steps: list[Step]) -> list[str]:
    """Return a list of human-readable problems; empty means the recipe is runnable."""
    problems = []
    if not steps:
        return ["Kịch bản chưa có bước nào."]

    for index, step in enumerate(steps, start=1):
        if step.type not in STEP_TYPES:
            problems.append(f"Bước {index}: loại '{step.type}' không tồn tại.")
            continue
        if not step.enabled:
            continue

        if step.type in ("tap_element", "wait_for"):
            if not (step.param("text") or step.param("resource_id")):
                problems.append(
                    f"Bước {index} ({step.spec().label}): cần nhập Text hoặc Resource id."
                )
        if step.type in ("web_click", "web_read"):
            if not (step.param("selector") or step.param("text")):
                problems.append(
                    f"Bước {index} ({step.spec().label}): cần nhập CSS selector hoặc chữ."
                )
        if step.type in ("web_fill", "web_select", "web_wait"):
            if not str(step.param("selector")).strip():
                problems.append(
                    f"Bước {index} ({step.spec().label}): cần nhập CSS selector."
                )
        if step.type == "web_open" and not str(step.param("url")).strip():
            problems.append(f"Bước {index}: thiếu địa chỉ trang.")
        if step.type == "web_wait" and step.param("state") not in WEB_WAIT_STATES:
            problems.append(
                f"Bước {index}: trạng thái '{step.param('state')}' không hợp lệ."
            )
        if step.type in ("read", "web_read") and not step.param("var_name"):
            problems.append(f"Bước {index}: thiếu tên biến.")
        if step.type == "write_cell" and not str(step.param("column")).strip():
            problems.append(f"Bước {index}: thiếu cột Excel.")
        if step.type == "key" and step.param("key") not in KEY_CODES:
            problems.append(f"Bước {index}: phím '{step.param('key')}' không hỗ trợ.")

    return problems
