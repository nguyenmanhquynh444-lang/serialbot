"""
screen_reader.py
Reads and queries the Android screen through uiautomator dumps.

Kept separate from bot_worker so the action engine and the classic run path
share one implementation of the XML parsing and text matching rules.
"""
import re
import time
import unicodedata
import xml.etree.ElementTree as ET

ERROR_DIALOG_TOKENS = ("dialog", "alert", "popup")
_NODE_RE = re.compile(r"<node\b[^>]*>")
_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# Nhãn nút đóng hộp thoại, đã chuẩn hóa (bỏ dấu, thường hóa). Thứ tự là thứ tự
# ưu tiên: OK trước, Hủy sau cùng - hộp thoại báo lỗi thường chỉ có một nút,
# nhưng nếu là hộp xác nhận thì Hủy mới là lựa chọn không làm gì thêm.
DISMISS_LABELS = (
    "ok", "dong y", "xac nhan", "da hieu", "yes", "close", "dong", "cancel", "huy",
)

# resource-id thường gặp của phần nội dung hộp thoại (AlertDialog của Android là
# android:id/message, android:id/alertTitle).
_DIALOG_TEXT_IDS = (
    "message", "msg", "alerttitle", "dialog_message", "tv_message", "tv_msg",
    "txt_message", "content",
)

# Tiêu đề chung chung thì bỏ đi khi hộp thoại còn dòng khác: ghi "Lỗi" vào Excel
# không cho biết thêm điều gì so với cột Trạng thái.
_GENERIC_TITLES = (
    "loi", "error", "thong bao", "canh bao", "warning", "alert", "chu y", "thong tin",
)

# Hộp thoại chiếm gần hết màn hình thì coi như không phải hộp thoại - đó là cả
# trang. Ngưỡng rộng tay vì dialog toàn màn hình vẫn chừa lề.
_DIALOG_MAX_SCREEN_RATIO = 0.9


def normalize_match_text(text: str) -> str:
    """Fold Vietnamese diacritics and case so keyword matching is accent-blind."""
    text = text.replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.lower()).strip()


def extract_xml(text: str) -> str:
    start = text.find("<?xml")
    if start < 0:
        start = text.find("<hierarchy")
    return text[start:] if start >= 0 else ""


def current_focus_window(window_dump: str) -> str:
    compact = re.sub(r"\s+", " ", window_dump)
    match = re.search(r"mCurrentFocus=Window\{([^}]*)\}", compact)
    return match.group(1) if match else ""


def xml_attr(node: str, attr: str) -> str:
    """
    Đọc một thuộc tính bằng regex, nhanh hơn dựng cả cây cho mỗi lần hỏi.

    Phải tự giải mã thực thể XML: câu app báo lỗi có dấu " hay & thì trong bản
    dump nó nằm ở dạng &quot; / &amp;, mà bước "Kiểm tra kết quả" so khớp từ khóa
    trên chuỗi thô - không giải mã là không bao giờ khớp, và câu ghi vào Excel
    cũng lẫn nguyên mấy ký tự đó. Đường đọc bằng cây (dialog_lines) vốn đã giải
    mã sẵn, nên đây còn là để hai đường cho ra cùng một chuỗi.
    """
    match = re.search(rf'{re.escape(attr)}="([^"]*)"', node)
    return _unescape(match.group(1)) if match else ""


def _unescape(text: str) -> str:
    if "&" not in text:
        return text
    for entity, char in (
        ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&"),
    ):
        text = text.replace(entity, char)
    return text


def parse_bounds(bounds: str) -> tuple[int, int, int, int] | None:
    match = _BOUNDS_RE.fullmatch(bounds.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def center_of(bounds: str) -> tuple[int, int] | None:
    parsed = parse_bounds(bounds)
    if not parsed:
        return None
    x1, y1, x2, y2 = parsed
    return (x1 + x2) // 2, (y1 + y2) // 2


def iter_nodes(screen_xml: str):
    for node in _NODE_RE.findall(screen_xml):
        yield node


def find_node(
    screen_xml: str,
    text: str = "",
    resource_id: str = "",
    content_desc: str = "",
) -> dict | None:
    """
    Find the first node matching the given criteria. `text` and `content_desc`
    match on a normalized substring; `resource_id` matches on a suffix so the
    caller can pass either "com.app:id/name" or just "name".
    """
    want_text = normalize_match_text(text) if text else ""
    want_desc = normalize_match_text(content_desc) if content_desc else ""
    want_id = resource_id.strip()

    for node in iter_nodes(screen_xml):
        node_text = xml_attr(node, "text")
        node_desc = xml_attr(node, "content-desc")
        node_id = xml_attr(node, "resource-id")

        if want_text and want_text not in normalize_match_text(node_text):
            continue
        if want_desc and want_desc not in normalize_match_text(node_desc):
            continue
        if want_id and not (node_id == want_id or node_id.endswith("/" + want_id)):
            continue
        if not (want_text or want_desc or want_id):
            continue

        return {
            "text": node_text,
            "content_desc": node_desc,
            "resource_id": node_id,
            "bounds": xml_attr(node, "bounds"),
            "clickable": xml_attr(node, "clickable") == "true",
            "class": xml_attr(node, "class"),
        }
    return None


def node_label(node: str) -> str:
    return (xml_attr(node, "text") or xml_attr(node, "content-desc")).strip()


def dialog_lines(screen_xml: str) -> list[str]:
    """
    Các dòng chữ của riêng khối hộp thoại, theo đúng thứ tự hiển thị.

    Hộp thoại thật không phải một câu: nó có tiêu đề, câu lỗi, rồi bảng chi tiết
    (mã vừa quét, mã phiên, tài khoản, thời gian). Lấy nguyên khối mới giữ được
    bằng chứng, còn lấy "node dài nhất" thì hay vớ trúng dòng thời gian.

    Khối hộp thoại được xác định bằng cây: đi ngược từ nút đóng lên tổ tiên cao
    nhất mà vẫn nhỏ hơn màn hình - đó là cái thẻ dialog. Cách này không phụ
    thuộc resource-id nên chạy được cả với dialog tự vẽ (Flutter, WebView).
    """
    root = _parse_tree(screen_xml)
    if root is not None:
        container = _dialog_container(root)
        if container is not None:
            lines = _texts_in(container)
            if lines:
                return lines

    # Không dựng được cây (dump lỗi), không có nút đóng, hoặc khoanh trúng khối
    # rỗng: quay về đọc phẳng.
    by_id: list[str] = []
    others: list[str] = []
    for node in iter_nodes(screen_xml):
        text = node_label(node)
        if not text:
            continue
        resource_id = xml_attr(node, "resource-id").rsplit("/", 1)[-1].lower()
        if resource_id in _DIALOG_TEXT_IDS:
            by_id.append(text)
        elif normalize_match_text(text) not in DISMISS_LABELS:
            others.append(text)

    if by_id:
        return list(dict.fromkeys(by_id))
    return [max(others, key=len)] if others else []


def dialog_message(screen_xml: str, max_len: int = 300) -> str:
    """
    Nội dung hộp thoại gộp thành một dòng để ghi vào Excel.

    Phải đọc TRƯỚC khi bấm OK, vì bấm xong là mất - mà đây chính là thứ cần ghi
    lại để sau còn biết serial hỏng vì lý do gì.
    """
    lines = dialog_lines(screen_xml)

    # Bỏ tiêu đề chung chung, nhưng chỉ khi còn dòng khác để nói thay nó.
    meaningful = [ln for ln in lines if normalize_match_text(ln) not in _GENERIC_TITLES]
    parts = meaningful or lines

    joined = " | ".join(dict.fromkeys(parts))
    return re.sub(r"\s+", " ", joined).strip()[:max_len]


def dialog_marker(screen_xml: str) -> str:
    """
    Dòng đặc trưng nhất của hộp thoại, dùng để sau khi bấm OK còn kiểm tra lại
    xem nó đã biến mất thật chưa. Bỏ tiêu đề chung ("Lỗi") và các nhãn quá ngắn
    vì chúng xuất hiện đầy trên màn hình khác.
    """
    for line in dialog_lines(screen_xml):
        normalized = normalize_match_text(line)
        if len(normalized) >= 8 and normalized not in _GENERIC_TITLES:
            return line
    return ""


def _parse_tree(screen_xml: str):
    if not screen_xml.strip():
        return None
    try:
        return ET.fromstring(screen_xml)
    except ET.ParseError:
        return None


def _node_bounds_area(node) -> int:
    parsed = parse_bounds(node.get("bounds", "") or "")
    if not parsed:
        return 0
    x1, y1, x2, y2 = parsed
    return max(0, x2 - x1) * max(0, y2 - y1)


def _dialog_container(root):
    parents = {child: parent for parent in root.iter() for child in parent}

    button = None
    for node in root.iter("node"):
        if normalize_match_text(_element_label(node)) in DISMISS_LABELS:
            button = node
            break
    if button is None:
        return None

    screen_area = max((_node_bounds_area(n) for n in root.iter("node")), default=0)
    if not screen_area:
        return None

    # Bắt đầu từ cha của nút đóng: bản thân cái nút không bao giờ là khối hộp
    # thoại, mà nhận nhầm nó thì `_texts_in` lọc mất chữ "OK" rồi trả về rỗng.
    ancestors = []
    node = parents.get(button)
    while node is not None and node.tag == "node":
        ancestors.append(node)
        node = parents.get(node)

    container = None
    for node in ancestors:
        if 0 < _node_bounds_area(node) < screen_area * _DIALOG_MAX_SCREEN_RATIO:
            container = node

    if container is None and ancestors:
        # uiautomator nhiều khi chỉ dump riêng cửa sổ hộp thoại chứ không dump cả
        # màn hình. Lúc đó tổ tiên nào cũng to đúng bằng "màn hình" nên không cái
        # nào lọt ngưỡng - mà cả bản dump chính là hộp thoại, nên lấy nút ngoài
        # cùng. Không có nhánh này thì mọi dòng chi tiết (mã vừa quét, mã phiên,
        # tài khoản, thời gian) đều rơi mất, chỉ còn đúng một câu.
        container = ancestors[-1]
    return container


def _element_label(node) -> str:
    return (node.get("text") or node.get("content-desc") or "").strip()


def _texts_in(container) -> list[str]:
    lines = []
    for node in container.iter("node"):
        text = _element_label(node)
        if not text or normalize_match_text(text) in DISMISS_LABELS:
            continue
        if text not in lines:
            lines.append(text)
    return lines


def find_dismiss_button(screen_xml: str, labels: tuple = DISMISS_LABELS) -> dict | None:
    """Nút đóng hộp thoại, ưu tiên nút bấm được và nhãn đứng trước trong `labels`."""
    candidates = []
    for node in iter_nodes(screen_xml):
        label = normalize_match_text(node_label(node))
        if label not in labels:
            continue
        if not parse_bounds(xml_attr(node, "bounds")):
            continue
        candidates.append({
            "text": node_label(node),
            "bounds": xml_attr(node, "bounds"),
            "clickable": xml_attr(node, "clickable") == "true",
            "resource_id": xml_attr(node, "resource-id"),
            "_rank": labels.index(label),
        })

    if not candidates:
        return None
    best = min(candidates, key=lambda c: (not c["clickable"], c["_rank"]))
    best.pop("_rank")
    return best


def list_nodes(screen_xml: str, only_interesting: bool = True) -> list[dict]:
    """Flatten a dump into rows for the UI inspector."""
    rows = []
    for node in iter_nodes(screen_xml):
        entry = {
            "text": xml_attr(node, "text"),
            "content_desc": xml_attr(node, "content-desc"),
            "resource_id": xml_attr(node, "resource-id"),
            "bounds": xml_attr(node, "bounds"),
            "clickable": xml_attr(node, "clickable") == "true",
            "class": xml_attr(node, "class").rsplit(".", 1)[-1],
        }
        if only_interesting and not (
            entry["text"] or entry["content_desc"] or entry["resource_id"]
        ):
            continue
        rows.append(entry)
    return rows


class ScreenReader:
    """Dumps and queries the screen of one device."""

    # Đổ thẳng ra stdout: bỏ được lượt ghi file lên /sdcard rồi `cat` đọc lại,
    # tức là bớt hẳn một lần chạy tiến trình trên máy ảo cho mỗi lần đọc màn
    # hình - mà mỗi serial đọc màn hình ít nhất một lần.
    FAST_DUMP_COMMAND = "uiautomator dump {flags}/dev/tty"
    FILE_DUMP_COMMAND = (
        "uiautomator dump {flags}/sdcard/window_dump.xml >/dev/null "
        "&& cat /sdcard/window_dump.xml"
    )
    # `--compressed` bảo uiautomator bỏ những node không mang thông tin cho
    # accessibility (layout rỗng, ViewGroup bọc ngoài). Cây nhỏ đi thì cả lượt
    # duyệt trên máy ảo lẫn lượt truyền qua ADB đều nhanh hơn - mà đây là khoản
    # đắt nhất của mỗi bước (đo trên máy thật: ~1.46s một lần dump).
    #
    # Đánh đổi: node nào bị coi là "không quan trọng" thì biến mất. Mọi thứ
    # luồng này đọc đều là TextView/EditText/Button có chữ nên vẫn còn, nhưng
    # không đoán mò - hễ chờ mãi không thấy id cần tìm thì `disable_compressed`
    # tắt hẳn chế độ này rồi đọc lại bằng bản đầy đủ trước khi kết luận.
    COMPRESSED_FLAG = "--compressed "

    def __init__(self, adb_client, compressed: bool = False):
        self.adb = adb_client
        self._fast_dump_works: bool | None = None
        self.compressed = compressed
        # Đọc màn hình là khoản đắt nhất của mỗi serial, nên đếm luôn để lát nữa
        # nhìn log là biết thời gian đi đâu, khỏi phải đoán.
        self.dump_count = 0
        self.dump_seconds = 0.0

    def disable_compressed(self) -> bool:
        """
        Tắt chế độ dump rút gọn. Trả True nếu vừa tắt thật - bên gọi dựa vào đó
        để biết có đáng đọc lại màn hình một lần nữa trước khi báo lỗi không.
        """
        if not self.compressed:
            return False
        self.compressed = False
        return True

    def dump_xml(self) -> str:
        started = time.monotonic()
        try:
            return self._dump_xml()
        finally:
            self.dump_count += 1
            self.dump_seconds += time.monotonic() - started

    def _dump_command(self, template: str) -> str:
        return template.format(flags=self.COMPRESSED_FLAG if self.compressed else "")

    def dump_command(self) -> str:
        """
        Lệnh dump đang dùng, để bên khác ghép chung vào một lần gọi ADB với lệnh
        gõ (xem `AdbBackend.type_and_dump`).
        """
        return self._dump_command(self.FAST_DUMP_COMMAND)

    def absorb_dump(self, output: str, seconds: float) -> str:
        """
        Ghi nhận một lần đọc màn hình do bên khác thực hiện, để bộ đếm vẫn phản
        ánh đúng tổng số lần đọc màn hình của một mã OR.
        """
        self.dump_count += 1
        self.dump_seconds += seconds
        return extract_xml(output) if output else ""

    def _dump_xml(self) -> str:
        if self._fast_dump_works is not False:
            output = self.adb.run_shell(self._dump_command(self.FAST_DUMP_COMMAND))
            xml = extract_xml(output) if output else ""
            if xml:
                self._fast_dump_works = True
                return xml
            if self._fast_dump_works:
                # Đã từng chạy được thì lần rỗng này là trục trặc nhất thời
                # (màn hình đang chuyển cảnh), không phải máy không hỗ trợ.
                return ""
            self._fast_dump_works = False

        output = self.adb.run_shell(self._dump_command(self.FILE_DUMP_COMMAND))
        return extract_xml(output) if output else ""

    def focused_window(self) -> str | None:
        """None means adb could not be reached, '' means nothing was focused."""
        output = self.adb.run_shell("dumpsys window windows")
        if output is None:
            return None
        return current_focus_window(output)

    def is_dialog_focused(self) -> bool | None:
        focus = self.focused_window()
        if focus is None:
            return None
        return any(token in focus.lower() for token in ERROR_DIALOG_TOKENS)

    def wait_for(
        self,
        text: str = "",
        resource_id: str = "",
        content_desc: str = "",
        timeout: float = 5.0,
        poll_interval: float = 0.25,
    ) -> dict | None:
        """Poll until a matching node appears. Returns the node, or None on timeout."""
        deadline = time.monotonic() + timeout
        while True:
            xml = self.dump_xml()
            if xml:
                found = find_node(xml, text, resource_id, content_desc)
                if found:
                    return found
            if time.monotonic() >= deadline:
                return None
            time.sleep(poll_interval)

    def tap(self, x: int, y: int) -> bool:
        return self.adb.run_shell(f"input tap {x} {y}") is not None

    def tap_node(self, node: dict) -> bool:
        point = center_of(node.get("bounds", ""))
        if not point:
            return False
        return self.tap(*point)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> bool:
        return self.adb.run_shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}") is not None

    def screenshot_png(self) -> bytes | None:
        return self.adb.run_exec_out_binary("screencap -p")
