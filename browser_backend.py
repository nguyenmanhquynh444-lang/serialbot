"""
browser_backend.py
Chạy kịch bản trên trình duyệt thật (Chrome trên Windows) thay vì máy ảo Android.

Bot gắn vào một cửa sổ Chrome đang mở qua CDP (Chrome DevTools Protocol) chứ
không tự mở trình duyệt riêng: hệ thống kho cần đăng nhập, mà phiên đăng nhập
nằm trong profile của Chrome. Gắn vào cũng có nghĩa là người dùng nhìn thấy bot
đang bấm gì - kiểm tra được ngay, không phải đoán.

Điểm cốt lõi so với đường ADB: nút được bấm bằng chính DOM chứ không bằng tọa
độ. Playwright tự cuộn phần tử vào tầm nhìn, tự chờ nó hết bị che, hết disabled,
hết dịch chuyển rồi mới bấm - ba thứ mà `input tap x y` không biết, và là nguồn
gốc của mọi cú bấm trượt.

Lớp `BrowserScreen` cố tình bày ra ĐÚNG bộ hàm của ScreenReader (dump_xml,
wait_for, tap_node, screenshot_png...) và dựng lại cây DOM thành XML kiểu
uiautomator. Nhờ vậy toàn bộ luật đọc màn hình đã có - find_node, dialog_message,
find_dismiss_button, so khớp bỏ dấu tiếng Việt - dùng lại nguyên vẹn cho web,
không phải viết lần thứ hai.
"""
import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from automation_backend import AutomationBackend
from paths import APP_DATA_NAME
from screen_reader import find_node, iter_nodes, xml_attr

logger = logging.getLogger(__name__)

DEFAULT_DEBUG_PORT = 9222
DEFAULT_TIMEOUT_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.25

# Cây DOM to hơn cây view Android rất nhiều. Chặn lại để một trang bảng vài nghìn
# dòng không biến mỗi lần đọc màn hình thành vài megabyte XML.
MAX_NODES = 4000

# Từ Chrome 136, --remote-debugging-port bị chặn nếu dùng chung thư mục profile
# mặc định (chống trang web độc chiếm quyền điều khiển trình duyệt cá nhân). Nên
# bot dùng một profile riêng: đăng nhập một lần, Chrome nhớ lại cho các lần sau.
CHROME_PROFILE_NAME = "chrome-bot-profile"

# Phím của kịch bản (đặt tên theo Android) -> phím của Playwright.
BROWSER_KEYS = {
    "enter": "Enter",
    "tab": "Tab",
    "back": "Alt+ArrowLeft",
    "home": "Home",
    "delete": "Backspace",
    "search": "Enter",
    "escape": "Escape",
    "dpad_down": "ArrowDown",
    "dpad_up": "ArrowUp",
}

_CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


class BrowserUnavailableError(RuntimeError):
    """Không gắn được vào trình duyệt - chạy tiếp là thao tác vào hư không."""


# --------------------------------------------------------------- tìm & mở Chrome

def find_chrome() -> str | None:
    for path in _CHROME_CANDIDATES:
        if os.path.isfile(path):
            return path
    return shutil.which("chrome") or shutil.which("msedge")


def chrome_profile_dir() -> str:
    """
    Profile riêng cho Chrome của bot.

    Luôn nằm trong %LOCALAPPDATA% chứ không theo user_data_dir(): chạy từ mã
    nguồn thì user_data_dir() trỏ vào chính thư mục dự án, mà một profile Chrome
    (vài trăm MB, đổi liên tục) không có việc gì phải nằm trong đó.
    """
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, APP_DATA_NAME, CHROME_PROFILE_NAME)


def debug_url(port: int = DEFAULT_DEBUG_PORT) -> str:
    return f"http://127.0.0.1:{port}"


def chrome_command(port: int = DEFAULT_DEBUG_PORT, url: str = "") -> list[str]:
    """Dòng lệnh mở Chrome ở chế độ cho phép bot gắn vào."""
    chrome = find_chrome() or "chrome.exe"
    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={chrome_profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if url:
        args.append(url)
    return args


def debugger_answers(port: int = DEFAULT_DEBUG_PORT, timeout: float = 1.0) -> bool:
    """Cổng gỡ lỗi có ai trả lời không - hỏi trước khi dựng cả Playwright."""
    try:
        with urllib.request.urlopen(f"{debug_url(port)}/json/version", timeout=timeout) as r:
            json.load(r)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def launch_chrome(port: int = DEFAULT_DEBUG_PORT, url: str = "", wait: float = 20.0) -> bool:
    """
    Mở Chrome ở chế độ gỡ lỗi rồi chờ tới khi nó trả lời.

    Chrome đã chạy sẵn ở đúng profile này thì lệnh mở chỉ bảo nó mở thêm tab -
    tiến trình vừa gọi thoát ngay, còn cổng vẫn là của cửa sổ cũ. Nên điều kiện
    dừng là "cổng trả lời", không phải "tiến trình còn sống".
    """
    if debugger_answers(port):
        return True

    try:
        subprocess.Popen(
            chrome_command(port, url),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as e:
        logger.error("Không mở được Chrome: %s", e)
        return False

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if debugger_answers(port):
            return True
        time.sleep(0.3)
    return False


# ------------------------------------------------------------------ đọc cây DOM

# Trả về cây LỒNG NHAU chứ không phải danh sách phẳng: dialog_message() đi ngược
# từ nút đóng lên tổ tiên để khoanh vùng hộp thoại, mất quan hệ cha-con là mất
# luôn khả năng đọc đúng câu mà hệ thống báo lỗi.
_DUMP_JS = r"""
(maxNodes) => {
  const CLICKABLE = 'a,button,input,select,textarea,label,option,summary,' +
    '[role=button],[role=link],[role=tab],[role=menuitem],[role=option],' +
    '[role=checkbox],[role=switch],[onclick]';
  const SKIP = new Set(['script', 'style', 'noscript', 'template', 'svg', 'head']);
  let counter = 0;

  const ownText = (el) => {
    let s = '';
    for (const n of el.childNodes) if (n.nodeType === 3) s += n.nodeValue;
    return s.replace(/\s+/g, ' ').trim();
  };

  const label = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      if (t === 'checkbox' || t === 'radio') return el.checked ? 'checked' : '';
      return (el.value || '').trim();
    }
    if (tag === 'textarea') return (el.value || '').trim();
    if (tag === 'select') {
      const o = el.selectedOptions && el.selectedOptions[0];
      return o ? o.textContent.replace(/\s+/g, ' ').trim() : '';
    }
    return ownText(el);
  };

  const desc = (el) => (
    el.getAttribute('aria-label') || el.getAttribute('title') ||
    el.getAttribute('placeholder') || el.getAttribute('alt') || ''
  ).replace(/\s+/g, ' ').trim();

  const ident = (el) => (
    el.id || el.getAttribute('name') || el.getAttribute('data-testid') || ''
  );

  const shownOn = (el, rect) => {
    if (rect.width <= 0 || rect.height <= 0) return false;
    const st = window.getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return false;
    return parseFloat(st.opacity || '1') > 0.01;
  };

  const walk = (el) => {
    if (counter >= maxNodes) return null;
    if (SKIP.has(el.tagName.toLowerCase())) return null;

    const rect = el.getBoundingClientRect();
    const shown = shownOn(el, rect);

    const kids = [];
    for (const child of el.children) {
      const node = walk(child);
      if (node) kids.push(node);
    }

    const text = shown ? label(el) : '';
    const d = shown ? desc(el) : '';
    const id = ident(el);
    const keep = shown && (text || d || id || el.matches(CLICKABLE));

    if (!keep && kids.length === 0) return null;
    if (!keep && kids.length === 1) return kids[0];

    const ref = 'r' + (counter++);
    el.setAttribute('data-bot-ref', ref);
    return {
      ref: ref,
      text: text,
      desc: d,
      id: id,
      cls: 'html.' + el.tagName.toLowerCase(),
      bounds: [Math.round(rect.left), Math.round(rect.top),
               Math.round(rect.right), Math.round(rect.bottom)],
      // Bấm vào chữ nằm trong nút vẫn là bấm nút - sự kiện nổi bọt lên. Nên
      // "bấm được" xét cả tổ tiên, khỏi phải dò cho ra đúng thẻ <button>.
      clickable: !!el.closest(CLICKABLE),
      children: kids,
    };
  };

  const root = walk(document.body) || {
    ref: 'r0', text: '', desc: '', id: 'body', cls: 'html.body',
    bounds: [0, 0, 0, 0], clickable: false, children: [],
  };
  // Gốc luôn to bằng khung nhìn: dialog_message() lấy node lớn nhất làm "màn
  // hình" rồi so diện tích để biết khối nào là hộp thoại.
  root.bounds = [0, 0, Math.round(window.innerWidth), Math.round(window.innerHeight)];
  return root;
}
"""


def _escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def tree_to_xml(root: dict | None, prefix: str = "") -> str:
    """Cây DOM (dict lồng nhau) -> XML kiểu uiautomator để dùng lại screen_reader."""
    parts: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>', "<hierarchy>"]
    if root:
        _node_to_xml(root, prefix, parts)
    parts.append("</hierarchy>")
    return "".join(parts)


def _node_to_xml(node: dict, prefix: str, out: list[str]) -> None:
    bounds = node.get("bounds") or (0, 0, 0, 0)
    x1, y1, x2, y2 = (int(v) for v in bounds)
    out.append(
        '<node text="{text}" resource-id="{rid}" content-desc="{desc}" '
        'class="{cls}" bounds="[{x1},{y1}][{x2},{y2}]" clickable="{click}" '
        'ref="{ref}">'.format(
            text=_escape(node.get("text", "")),
            rid=_escape(node.get("id", "")),
            desc=_escape(node.get("desc", "")),
            cls=_escape(node.get("cls", "")),
            x1=x1, y1=y1, x2=x2, y2=y2,
            click="true" if node.get("clickable") else "false",
            ref=_escape(prefix + str(node.get("ref", ""))),
        )
    )
    for child in node.get("children") or ():
        _node_to_xml(child, prefix, out)
    out.append("</node>")


def ref_index(screen_xml: str) -> dict[tuple[str, str, str], str]:
    """
    bounds/text/id -> ref, để nhận lại phần tử từ một dict do screen_reader trả về.

    find_node() và find_dismiss_button() là hàm dùng chung với đường ADB nên chỉ
    trả về các khóa mà Android có; `ref` không nằm trong đó. Tra ngược bằng bảng
    này thì hai hàm cũ vẫn bấm được bằng DOM chứ không phải tụt về tọa độ.
    """
    index: dict[tuple[str, str, str], str] = {}
    for node in iter_nodes(screen_xml):
        ref = xml_attr(node, "ref")
        if not ref:
            continue
        bounds = xml_attr(node, "bounds")
        text = xml_attr(node, "text")
        rid = xml_attr(node, "resource-id")
        for key in ((bounds, text, rid), (bounds, "", ""), ("", text, rid)):
            index.setdefault(key, ref)
    return index


# ------------------------------------------------------------------ phiên làm việc

class BrowserSession:
    """Giữ kết nối Playwright tới Chrome đang chạy và chọn ra tab để thao tác."""

    def __init__(self, port: int = DEFAULT_DEBUG_PORT, url_filter: str = ""):
        self.port = port
        self.url_filter = (url_filter or "").strip().lower()
        self._playwright = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover - phụ thuộc cài ngoài
            raise BrowserUnavailableError(
                "Chưa cài thư viện playwright. Chạy: pip install playwright"
            ) from e

        if not debugger_answers(self.port):
            raise BrowserUnavailableError(
                f"Không thấy Chrome nào mở cổng gỡ lỗi {self.port}.\n\n"
                "Mở Chrome bằng lệnh:\n  " + " ".join(chrome_command(self.port))
            )

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(debug_url(self.port))
        except Exception as e:
            self.stop()
            raise BrowserUnavailableError(f"Gắn vào Chrome thất bại: {e}") from e
        self._page = self._pick_page()

    def _pick_page(self):
        pages = [p for ctx in self._browser.contexts for p in ctx.pages if not p.is_closed()]
        if not pages:
            context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else self._browser.new_context()
            )
            return context.new_page()

        if self.url_filter:
            for page in pages:
                if self.url_filter in (page.url or "").lower():
                    return page
            logger.warning("Không tab nào khớp '%s', dùng tab đầu tiên", self.url_filter)
        return pages[0]

    @property
    def page(self):
        if self._page is None:
            raise BrowserUnavailableError("Chưa gắn vào trình duyệt (thiếu start()).")
        # Người dùng đóng tab giữa chừng thì chọn lại, đừng để cả phiên chạy đổ.
        if self._page.is_closed():
            self._page = self._pick_page()
        return self._page

    def stop(self) -> None:
        # Chỉ NGẮT kết nối, không đóng Chrome của người dùng: connect_over_cdp
        # gắn vào tiến trình có sẵn, đóng nó là đóng luôn cửa sổ họ đang mở.
        for closable in (self._browser, self._playwright):
            if closable is None:
                continue
            try:
                closable.close() if closable is self._browser else closable.stop()
            except Exception:
                pass
        self._browser = None
        self._playwright = None
        self._page = None


# --------------------------------------------------------------- đọc & bấm màn hình

class BrowserScreen:
    """
    Bản ScreenReader cho trang web: cùng bộ hàm, khác đường đi.

    Mọi cú bấm đều cố đi qua DOM trước (`data-bot-ref` gắn lúc đọc màn hình).
    Chỉ khi không tra được ref mới hạ xuống bấm theo tọa độ - đường cuối cùng,
    và cũng là đường duy nhất mà bản ADB có.
    """

    def __init__(self, session: BrowserSession, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.session = session
        self.timeout = timeout
        self._refs: dict[tuple[str, str, str], str] = {}

    # ------------------------------------------------------------- đọc màn hình

    @property
    def page(self):
        return self.session.page

    def dump_xml(self) -> str:
        try:
            tree = self.page.evaluate(_DUMP_JS, MAX_NODES)
        except Exception as e:
            logger.warning("Không đọc được DOM: %s", e)
            return ""
        xml = tree_to_xml(tree)
        self._refs = ref_index(xml)
        return xml

    def wait_for(
        self,
        text: str = "",
        resource_id: str = "",
        content_desc: str = "",
        timeout: float = 5.0,
        poll_interval: float = POLL_INTERVAL_SECONDS,
    ) -> dict | None:
        deadline = time.monotonic() + timeout
        while True:
            xml = self.dump_xml()
            if xml:
                found = find_node(xml, text, resource_id, content_desc)
                if found:
                    found["ref"] = self._ref_for(found)
                    return found
            if time.monotonic() >= deadline:
                return None
            time.sleep(poll_interval)

    def screenshot_png(self) -> bytes | None:
        try:
            return self.page.screenshot()
        except Exception as e:
            logger.warning("Không chụp được màn hình: %s", e)
            return None

    def focused_window(self) -> str | None:
        return self.page.url

    def is_dialog_focused(self) -> bool | None:
        # Trang web không có khái niệm cửa sổ đang focus; đường duy nhất đúng là
        # đọc nội dung. Trả None để phía gọi biết mà đọc màn hình thay vì tin.
        return None

    def disable_compressed(self) -> bool:
        # Chỉ có ý nghĩa với uiautomator; giữ hàm để hai lớp thay nhau được.
        return False

    # ------------------------------------------------------------------- thao tác

    def tap(self, x: int, y: int) -> bool:
        try:
            self.page.mouse.click(x, y)
            return True
        except Exception as e:
            logger.warning("Bấm tọa độ (%s,%s) thất bại: %s", x, y, e)
            return False

    def tap_node(self, node: dict) -> bool:
        ref = node.get("ref") or self._ref_for(node)
        if ref and self.click_ref(ref):
            return True

        # Không tra được ref (bản dump đã cũ, node do hàm dùng chung tạo ra):
        # hạ xuống bấm theo tọa độ như bản ADB.
        from screen_reader import center_of

        point = center_of(node.get("bounds", ""))
        return self.tap(*point) if point else False

    def click_ref(self, ref: str, timeout: float | None = None) -> bool:
        """Bấm một phần tử đã đánh dấu lúc đọc màn hình."""
        return self._click(
            self.page.locator(f'[data-bot-ref="{ref}"]'), f"ref={ref}", timeout
        )

    def _click(self, locator, label: str, timeout: float | None = None) -> bool:
        """
        Bấm, hạ dần qua ba nấc.

        1. Bấm thật. Playwright tự cuộn phần tử vào tầm nhìn rồi chờ tới khi nó
           hiện, hết dịch chuyển, hết disabled và không bị thứ gì che mới bấm.
           Gần như mọi lần đều dừng ở đây, và đây mới là nấc bấm ĐÚNG.

        2. Gọi el.click() ngay trong DOM. Dành cho nút nằm dưới một lớp phủ -
           chuột không chạm tới được, nhưng chính phần tử đó vẫn nhận sự kiện.

        3. Bấm ép theo tọa độ. Nấc cuối, và là nấc mong manh nhất: sự kiện đi
           tới phần tử nằm TRÊN CÙNG tại điểm đó, nên có thể không phải cái mình
           định bấm - hàm vẫn trả về True vì lệnh đã gửi đi trót lọt.

        Vì nấc 3 nói dối được, kịch bản đừng bao giờ coi "bấm xong" là "đã xong":
        đặt một bước "Chờ phần tử (web)" ngay sau để xác nhận màn hình đã đổi -
        đúng như luồng ADB kiểm tra lại hộp thoại sau khi bấm OK.
        """
        wait_ms = int((timeout if timeout is not None else self.timeout) * 1000)

        try:
            locator.click(timeout=wait_ms)
            return True
        except Exception as e:
            logger.info("Bấm thường '%s' không được (%s), gọi click() trong DOM", label, e)

        try:
            locator.evaluate("el => el.click()")
            return True
        except Exception as e:
            logger.info("click() trong DOM không được (%s), bấm ép theo tọa độ", e)

        try:
            locator.click(timeout=wait_ms, force=True)
            logger.warning(
                "Đã bấm ép '%s' theo tọa độ - hãy thêm bước chờ để xác nhận màn "
                "hình thật sự đổi", label
            )
            return True
        except Exception as e:
            logger.warning("Không bấm được '%s': %s", label, e)
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> bool:
        """Trang web không vuốt - đổi thành cuộn đúng quãng đường đó."""
        try:
            self.page.mouse.move(x1, y1)
            self.page.mouse.wheel(x1 - x2, y1 - y2)
            return True
        except Exception as e:
            logger.warning("Cuộn thất bại: %s", e)
            return False

    # ------------------------------------------------------ thao tác riêng của web

    def open_url(self, url: str, timeout: float | None = None) -> bool:
        wait_ms = int((timeout if timeout is not None else self.timeout) * 1000)
        try:
            self.page.goto(url, timeout=wait_ms)
            return True
        except Exception as e:
            logger.warning("Mở '%s' thất bại: %s", url, e)
            return False

    def locate(self, selector: str = "", text: str = ""):
        """
        Locator theo CSS, theo chữ hiển thị, hoặc cả hai (CSS lọc trước, chữ sau).

        Chỉ lấy phần tử ĐANG hiện: trang web hay giữ lại bản ẩn của hộp thoại
        trong DOM, khớp trúng bản ẩn là chờ tới hết giờ mà chẳng bấm được gì.
        """
        page = self.page
        if selector and text:
            return page.locator(selector).filter(has_text=text).locator("visible=true")
        if selector:
            return page.locator(selector).locator("visible=true")
        if text:
            return page.get_by_text(text, exact=False).locator("visible=true")
        raise ValueError("cần selector hoặc text")

    def click(self, selector: str = "", text: str = "", timeout: float | None = None) -> bool:
        return self._click(
            self.locate(selector, text).first, selector or text, timeout
        )

    def fill(self, selector: str, value: str, timeout: float | None = None) -> bool:
        wait_ms = int((timeout if timeout is not None else self.timeout) * 1000)
        try:
            locator = self.locate(selector).first
            locator.fill(value, timeout=wait_ms)
            return True
        except Exception as e:
            logger.warning("Không điền được vào '%s': %s", selector, e)
            return False

    def wait_selector(
        self, selector: str, state: str = "visible", timeout: float | None = None
    ) -> bool:
        wait_ms = int((timeout if timeout is not None else self.timeout) * 1000)
        try:
            self.page.wait_for_selector(selector, state=state, timeout=wait_ms)
            return True
        except Exception:
            return False

    def read_selector(
        self, selector: str = "", text: str = "", timeout: float | None = None
    ) -> str | None:
        wait_ms = int((timeout if timeout is not None else self.timeout) * 1000)
        try:
            locator = self.locate(selector, text).first
            locator.wait_for(state="visible", timeout=wait_ms)
            value = locator.inner_text()
            return value.strip()
        except Exception as e:
            logger.warning("Không đọc được '%s%s': %s", selector, text, e)
            return None

    def select_option(self, selector: str, value: str, timeout: float | None = None) -> bool:
        wait_ms = int((timeout if timeout is not None else self.timeout) * 1000)
        locator = self.locate(selector).first
        for kwargs in ({"value": value}, {"label": value}):
            try:
                locator.select_option(timeout=wait_ms, **kwargs)
                return True
            except Exception:
                continue
        logger.warning("Không chọn được '%s' trong '%s'", value, selector)
        return False

    # -------------------------------------------------------------------- nội bộ

    def _ref_for(self, node: dict) -> str:
        bounds = node.get("bounds", "")
        text = node.get("text", "")
        rid = node.get("resource_id", "")
        for key in ((bounds, text, rid), (bounds, "", ""), ("", text, rid)):
            ref = self._refs.get(key)
            if ref:
                return ref
        return ""


# ------------------------------------------------------------------------ backend

class BrowserBackend(AutomationBackend):
    """Gõ phím vào trang web đang mở, dùng chung giao diện với AdbBackend."""

    def __init__(self, session: BrowserSession, screen: BrowserScreen | None = None):
        self.session = session
        self.screen = screen or BrowserScreen(session)

    def is_available(self) -> bool:
        return debugger_answers(self.session.port)

    @property
    def _page(self):
        return self.session.page

    def type_serial(self, serial: str) -> None:
        self.clear_field()
        self._page.keyboard.type(serial)

    def clear_field(self) -> None:
        """
        Xóa ô đang focus.

        Ctrl+A trong trang web bôi đen cả trang nếu focus không nằm trong ô nhập
        nào - và Backspace sau đó không xóa gì, nhưng cũng chẳng hỏng gì. Ô nhập
        thật thì đây là cách xóa nhanh nhất, không phụ thuộc độ dài chuỗi cũ.
        """
        self._page.keyboard.press("Control+A")
        self._page.keyboard.press("Backspace")

    def send_key(self, key: str) -> None:
        mapped = BROWSER_KEYS.get(str(key).lower())
        if mapped is None:
            raise ValueError(f"phím không hỗ trợ trên trình duyệt: {key}")
        self._page.keyboard.press(mapped)

    def send_enter(self, mode: str) -> None:
        if mode == "none":
            return
        if mode == "tab_enter":
            self._page.keyboard.press("Tab")
        self._page.keyboard.press("Enter")

    def close(self) -> None:
        self.session.stop()
