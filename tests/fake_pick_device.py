"""
Máy ảo giả mô phỏng luồng "Lấy hàng" của app, dựng theo bản quay màn hình thật.

Có nó thì kiểm được những tình huống không thể dựng lại trên kho thật: lọc ra
hai phiên trùng mã, app báo số lượng lệch, app đòi lấy ở vị trí khác, serial bị
từ chối giữa chừng, hộp thoại lạ chen vào. Đây đúng là những chỗ mà chạy sai sẽ
xuất kho nhầm.

Hai chi tiết bám sát app thật, vì chúng chính là thứ luồng cũ làm sai:

- Thẻ phiên **không in mã OR** lên đâu cả. Nó chỉ có mã phiên (PL...), nhãn
  "VIN" và số lượng - nên bot không đối chiếu mã trên thẻ được.
- Đóng phiên xong app trả về **màn hình tìm mã OR**, không về menu chính. Và mã
  vừa lấy biến khỏi danh sách trong khi ô tìm kiếm vẫn giữ nguyên mã cũ.
"""
import re

SCREEN = (0, 0, 720, 1280)


def _node(rid="", text="", bounds=(0, 0, 0, 0), clickable=False, cls="android.widget.TextView"):
    x1, y1, x2, y2 = bounds
    rid_attr = f'vn.app:id/{rid}' if rid else ""
    return (
        f'<node text="{text}" resource-id="{rid_attr}" class="{cls}" '
        f'content-desc="" clickable="{str(clickable).lower()}" '
        f'bounds="[{x1},{y1}][{x2},{y2}]" />'
    )


def _screen(nodes, root=SCREEN):
    x1, y1, x2, y2 = root
    inner = "".join(nodes)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
        f'<node text="" resource-id="" class="android.widget.FrameLayout" '
        f'content-desc="" clickable="false" bounds="[{x1},{y1}][{x2},{y2}]">'
        f"{inner}</node></hierarchy>"
    )


class Session:
    """
    or_code - mã OR gõ vào ô tìm kiếm; app lọc theo nó nhưng KHÔNG in nó ra thẻ
    note    - nhãn hiện trên thẻ ("VIN" ở app thật)
    """

    def __init__(self, or_code, code, product_qty, bins=("PYTES",), note="VIN"):
        self.or_code = or_code
        self.code = code
        self.product_qty = product_qty
        self.bins = bins
        self.note = note
        self.done = False


class FakePickDevice:
    """
    Trạng thái: menu -> list -> assistant -> tote -> bin -> serial -> finish -> list

    reject_serials  - những serial app sẽ báo lỗi thay vì nhận
    skip_assistant  - app không hiện hộp trợ lý (để kiểm cả hai nhánh)
    stuck_dialog    - hộp thoại lạ hiện lúc mở phiên
    totes_needed    - số thiết bị chứa hàng phải đăng ký cho mỗi lượt làm việc.
                      App nhớ tote giữa các phiên, nên đăng ký đủ một lần là từ
                      phiên sau màn hình quét tote tự lướt qua.
    """

    def __init__(
        self,
        sessions,
        reject_serials=(),
        skip_assistant=False,
        stuck_dialog="",
        totes_needed=1,
    ):
        self.sessions = list(sessions)
        self.reject_serials = set(reject_serials)
        self.skip_assistant = skip_assistant
        self.stuck_dialog = stuck_dialog
        self.totes_needed = totes_needed

        self.state = "menu"
        self.filter_text = ""
        self.active: Session | None = None
        self.picked = 0
        self.bin_index = 0
        self.totes_registered = 0
        self.commands = []
        self.typed = []
        self.error_message = ""

    # --------------------------------------------------------------- màn hình

    def _visible_sessions(self):
        open_sessions = [s for s in self.sessions if not s.done]
        if not self.filter_text:
            return open_sessions
        return [s for s in open_sessions if self.filter_text.lower() in s.or_code.lower()]

    def _xml(self) -> str:
        if self.state == "menu":
            return _screen([_node("btnPick", "Lấy hàng", (0, 0, 200, 100), True,
                                  "android.widget.LinearLayout")])

        if self.state == "list":
            nodes = [_node("textInput", self.filter_text, (0, 120, 720, 200), True,
                           "android.widget.EditText")]
            for i, s in enumerate(self._visible_sessions()):
                top = 240 + i * 220
                nodes += [
                    _node("tvSessionCode", s.code, (20, top, 600, top + 30)),
                    _node("tvProductNumber", str(s.product_qty), (620, top, 700, top + 30)),
                    _node("holderNote", s.note, (20, top + 60, 300, top + 90), True),
                    _node("btnProceed", "Lấy hàng", (20, top + 100, 700, top + 150), True,
                          "android.widget.Button"),
                ]
            return _screen(nodes)

        if self.state == "assistant":
            return _screen([
                _node("alertTitle", "Picking assistant", (90, 560, 630, 600)),
                _node("message", "Choose language in list", (54, 620, 666, 680)),
                _node("button2", "Skip", (456, 698, 552, 770), True, "android.widget.Button"),
                _node("button1", "Set up", (552, 698, 648, 770), True, "android.widget.Button"),
            ], root=(54, 540, 666, 776))

        if self.state == "error_dialog":
            return _screen([
                _node("tvMessage", self.error_message, (60, 560, 660, 640)),
                _node("btnClose", "OK", (60, 700, 660, 770), True, "android.widget.Button"),
            ], root=(54, 540, 666, 776))

        if self.state == "tote":
            # Tote đã đăng ký đủ từ phiên trước thì app chỉ lướt qua màn hình này.
            if self.totes_registered >= self.totes_needed:
                self.state = "bin"
                return self._xml()
            return _screen([
                _node("tvSessionCode", self.active.code, (15, 147, 705, 180)),
                _node("tvProductNumber", str(self.active.product_qty), (135, 180, 159, 209)),
                _node("tvHint", "Quét thiết bị chứa hàng", (296, 264, 423, 305)),
                _node("textInput", "", (192, 315, 462, 388), True, "android.widget.EditText"),
                _node("btnSubmit", "", (468, 323, 528, 383), True, "android.widget.Button"),
                _node("tvRegisterCount", f"{self.totes_registered}/{self.totes_needed}",
                      (346, 431, 378, 460)),
            ])

        if self.state == "bin":
            return _screen([
                _node("tvCounter", f"{self.picked}/{self.active.product_qty}", (628, 159, 690, 200)),
                _node("tvHint", "Quét vị trí lấy hàng", (37, 255, 683, 296)),
                _node("textInput", "", (192, 306, 462, 379), True, "android.widget.EditText"),
                _node("btnSubmit", "", (468, 314, 528, 374), True, "android.widget.Button"),
                _node("tvBinHint", "Vị trí lấy hàng kế tiếp", (30, 434, 107, 463)),
                _node("tvNextBin", self.active.bins[self.bin_index], (287, 499, 433, 580)),
            ])

        if self.state == "serial":
            return _screen([
                _node("tvCounter", f"{self.picked}/{self.active.product_qty}", (628, 159, 690, 200)),
                _node("tvHint", "Quét sản phẩm/serial", (37, 255, 683, 296)),
                _node("textInput", "", (192, 306, 462, 379), True, "android.widget.EditText"),
                _node("btnSubmit", "", (468, 314, 528, 374), True, "android.widget.Button"),
                _node("tvBinHint", "Vị trí lấy hàng hiện tại", (30, 434, 253, 463)),
                _node("tvBin", self.active.bins[self.bin_index], (639, 434, 690, 463)),
                _node("actionFinish", "Bỏ qua", (650, 48, 720, 107), True),
            ])

        if self.state == "finish":
            return _screen([
                _node("message", "Công việc lấy hàng đã kết thúc", (60, 560, 660, 640)),
                _node("button2", "Lịch sử", (370, 700, 480, 770), True, "android.widget.Button"),
                _node("button1", "OK", (500, 700, 640, 770), True, "android.widget.Button"),
            ], root=(54, 540, 666, 776))

        raise AssertionError(f"trang thai la: {self.state}")

    # --------------------------------------------------------------- lệnh adb

    def run_shell(self, command, timeout=None):
        """
        Chạy từng chặng ngăn bởi `;` theo đúng thứ tự, như shell thật.

        Bot gộp "gõ xong rồi đọc màn hình" vào một lệnh duy nhất để bớt một lượt
        gọi ADB. Nếu ở đây cứ thấy chữ `uiautomator dump` là trả màn hình luôn
        thì phần gõ bị nuốt mất - fake sẽ dựng nên một app không bao giờ nhận
        chữ, và test đứng chờ vô nghĩa.
        """
        self.commands.append(command)

        output = ""
        for part in command.split(";"):
            part = part.strip()
            if not part:
                continue
            if "uiautomator dump" in part:
                output = self._xml()          # đọc sau khi các chặng trên đã chạy
            elif part.startswith("input tap"):
                x, y = (int(v) for v in part.split()[2:4])
                self._tap(x, y)
            elif "input text" in part:
                match = re.search(r"input text '([^']*)'", part)
                if match:
                    self._type(match.group(1))
            # `input keyevent` và `sleep` không đổi trạng thái gì của app giả.
        return output

    def run_exec_out_binary(self, command, timeout=None):
        return b"\x89PNG fake"

    # --------------------------------------------------------------- hành vi

    def _hit(self, x, y, rid) -> bool:
        for node in re.findall(r"<node[^>]*>", self._xml()):
            if f"id/{rid}" not in node:
                continue
            b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            x1, y1, x2, y2 = (int(v) for v in b.groups())
            if x1 <= x <= x2 and y1 <= y <= y2:
                return True
        return False

    def _tap(self, x, y):
        if self.state == "menu" and self._hit(x, y, "btnPick"):
            self.state = "list"
            self.filter_text = ""
        elif self.state == "list" and self._hit(x, y, "btnProceed"):
            visible = self._visible_sessions()
            self.active = visible[0]
            self.picked = 0
            self.bin_index = 0
            if self.stuck_dialog:
                self.error_message = self.stuck_dialog
                self.state = "error_dialog"
            else:
                self.state = "tote" if self.skip_assistant else "assistant"
        elif self.state == "assistant" and self._hit(x, y, "button2"):
            self.state = "tote"
        elif self.state == "finish" and self._hit(x, y, "button1"):
            # App trả về màn hình tìm mã OR chứ không về menu chính, và giữ
            # nguyên mã cũ trong ô tìm kiếm.
            self.active.done = True
            self.state = "list"
            self.active = None

    def _type(self, text):
        self.typed.append((self.state, text))

        if self.state == "list":
            self.filter_text = text
        elif self.state == "tote":
            self.totes_registered += 1
            if self.totes_registered >= self.totes_needed:
                self.state = "bin"
        elif self.state == "bin":
            self.state = "serial"
        elif self.state == "serial":
            if text in self.reject_serials:
                self.error_message = f"Không tìm được sản phẩm {text}"
                self.state = "error_dialog"
                return
            self.picked += 1
            if self.picked >= self.active.product_qty:
                self.state = "finish"
