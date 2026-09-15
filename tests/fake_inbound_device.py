"""
Máy ảo giả mô phỏng luồng nhận hàng, dựng theo bản dump máy thật ngày 31/07
(màn hình "Danh sách check-in", app vn.aipacific.fai.prod, 1080x1920).

Phần sau khi bấm "Nhận hàng" chưa dò được trên máy thật, nên máy giả dựng đúng
giả thiết bot đang chạy: bấm xong là vào thẳng màn hình quét serial. Cờ
`extra_screen` dựng lại tình huống ngược lại - app chèn thêm một bước - để kiểm
rằng bot dừng và mô tả màn hình lạ thay vì gõ serial vào nhầm ô.
"""
import re

SCREEN = (0, 0, 1080, 1920)


def _node(rid="", text="", bounds=(0, 0, 0, 0), clickable=False, cls="android.widget.TextView"):
    x1, y1, x2, y2 = bounds
    rid_attr = f"vn.aipacific.fai.prod:id/{rid}" if rid else ""
    return (
        f'<node text="{text}" resource-id="{rid_attr}" class="{cls}" '
        f'content-desc="" clickable="{str(clickable).lower()}" '
        f'bounds="[{x1},{y1}][{x2},{y2}]" />'
    )


def _screen(nodes, root=SCREEN):
    x1, y1, x2, y2 = root
    return (
        '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
        f'<node text="" resource-id="" class="android.widget.FrameLayout" '
        f'content-desc="" clickable="false" bounds="[{x1},{y1}][{x2},{y2}]">'
        f'{"".join(nodes)}</node></hierarchy>'
    )


class Checkin:
    def __init__(self, code, add_info, product_qty):
        self.code = code                # "CKSIRVIN89HN210210 - VIN"
        self.add_info = add_info        # "IRVIN89HN210 - ESO26070007-261_3200368076"
        self.product_qty = product_qty


class FakeInboundDevice:
    """
    Trạng thái: menu -> list -> (extra) -> scan -> finish -> list

    reject_serials - serial app sẽ báo lỗi thay vì nhận
    extra_screen   - app chèn một màn hình lạ sau khi bấm Nhận hàng
    back_to_menu   - đóng phiếu xong app về menu chính thay vì về danh sách
    new_session_qty- mã gõ vào chưa có phiên: app hỏi "có tạo phiên không?", xác
                     nhận thì mở phiên mới với đúng số lượng này
    enter_opens    - gõ mã + Enter là vào thẳng phiên, không dừng ở thẻ nào
    """

    def __init__(self, checkins, reject_serials=(), extra_screen=False,
                 back_to_menu=False, new_session_qty=None, enter_opens=False):
        self.checkins = list(checkins)
        self.reject_serials = set(reject_serials)
        self.extra_screen = extra_screen
        self.back_to_menu = back_to_menu
        self.new_session_qty = new_session_qty
        self.enter_opens = enter_opens

        self.state = "menu"
        self.filter_text = ""
        self.active: Checkin | None = None
        self.scanned = 0
        self.error = ""
        self.typed: list[str] = []
        self.sessions_created: list[str] = []

    # ------------------------------------------------------------- màn hình

    def dump(self) -> str:
        if self.error:
            return _screen([
                _node("alertTitle", "Thông báo", (200, 700, 880, 780)),
                _node("message", self.error, (200, 800, 880, 900)),
                _node("button1", "OK", (700, 950, 880, 1030), True, "android.widget.Button"),
            ])

        if self.state == "menu":
            return _screen([
                _node("btnOpenReceive", "", (30, 400, 350, 600), True, "android.widget.LinearLayout"),
                _node("", "Nhận hàng", (60, 520, 320, 580)),
                _node("btnPick", "", (380, 400, 700, 600), True, "android.widget.LinearLayout"),
            ])

        if self.state == "list":
            nodes = [
                _node("icRefresh", "", (960, 111, 1050, 201), True, "android.widget.ImageView"),
                _node("textInputLO", "", (30, 240, 1050, 399)),
                _node("textInput", self.filter_text or "Tìm theo mã check-in hoặc mã nhập kho",
                      (30, 256, 1050, 399), True, "android.widget.EditText"),
                _node("rclView", "", (0, 423, 1080, 1920), False, "androidx.recyclerview.widget.RecyclerView"),
            ]
            top = 453
            for c in self._visible():
                nodes += [
                    _node("tvCustomer", "VINFAST", (204, top + 24, 376, top + 81)),
                    _node("tvTime", "14:28:54", (24, top + 97, 204, top + 146)),
                    _node("tvSessionCode", c.code, (204, top + 87, 698, top + 155), True),
                    _node("tvAddInfo", c.add_info, (204, top + 161, 698, top + 218)),
                    _node("btnStart", "Nhận hàng", (710, top + 49, 1044, top + 193),
                          True, "android.widget.Button"),
                ]
                top += 272
            return _screen(nodes)

        if self.state == "confirm":
            # Hộp thoại tự vẽ của app: uiautomator chỉ dump cửa sổ này, không
            # kèm màn hình phía sau - đúng như bản dump máy thật.
            return _screen([
                _node("tvTitle",
                      "Yêu cầu nhập kho chưa có tạo phiên check-in? "
                      "Bạn có muốn tạo phiên và nhận hàng",
                      (84, 866, 996, 957)),
                _node("btnCancel", "Quay lại", (228, 981, 528, 1125), True,
                      "android.widget.Button"),
                _node("btnAccept", "Xác nhận", (552, 981, 852, 1125), True,
                      "android.widget.Button"),
            ], root=(48, 830, 1032, 1161))

        if self.state == "extra":
            # Màn hình lạ: có ô nhập nhưng không có số đếm.
            return _screen([
                _node("tvHint", "Scan container", (296, 264, 423, 305)),
                _node("textInput", "", (192, 315, 462, 388), True, "android.widget.EditText"),
                _node("btnSubmit", "", (468, 323, 528, 383), True, "android.widget.Button"),
            ])

        if self.state == "scan":
            return _screen([
                _node("tvSessionCode", self.active.code, (15, 147, 705, 180)),
                _node("tvCounter", f"{self.scanned}/{self.active.product_qty}", (628, 159, 690, 200)),
                _node("tvHint", "Scan serial", (37, 255, 683, 296)),
                _node("textInput", "", (192, 306, 462, 379), True, "android.widget.EditText"),
                _node("btnSubmit", "", (468, 314, 528, 374), True, "android.widget.Button"),
            ])

        if self.state == "finish":
            return _screen([
                _node("alertTitle", "Thông báo", (200, 700, 880, 780)),
                _node("message", "Receiving session is finishing", (200, 800, 880, 900)),
                _node("button1", "OK", (700, 950, 880, 1030), True, "android.widget.Button"),
            ])

        raise AssertionError(f"trạng thái lạ: {self.state}")

    def _visible(self):
        if not self.filter_text:
            return self.checkins
        want = self.filter_text.lower()
        return [
            c for c in self.checkins
            if want in c.code.lower() or want in c.add_info.lower()
        ]

    # -------------------------------------------------------------- thao tác

    # --------------------------------------------------------------- lệnh adb

    def run_shell(self, command, timeout=None):
        if "uiautomator dump" in command:
            return self.dump()
        if command.startswith("input tap"):
            x, y = (int(v) for v in command.split()[2:4])
            self.tap(x, y)
            return ""
        if "input text" in command:
            match = re.search(r"input text '([^']*)'", command)
            if match:
                self.type_text(match.group(1))
            return ""
        return ""

    def run_exec_out_binary(self, command, timeout=None):
        return b"\x89PNG fake"

    def type_text(self, text: str):
        self.typed.append((self.state, text))
        if self.state == "list":
            self.filter_text = text
            if self.new_session_qty is not None and not self._visible():
                self.state = "confirm"
            elif self.enter_opens and len(self._visible()) == 1:
                self.active = self._visible()[0]
                self.scanned = 0
                self.state = "scan"
        elif self.state == "scan":
            self._scan(text)
        elif self.state == "extra":
            raise AssertionError(
                "bot gõ serial vào màn hình lạ - đúng cái phải chặn được"
            )

    def _scan(self, serial: str):
        if serial in self.reject_serials:
            self.error = f"Serial {serial} không thuộc phiếu này"
            return
        self.scanned += 1
        if self.scanned >= self.active.product_qty:
            self.state = "finish"

    def tap(self, x: int, y: int):
        if self.error:
            self.error = ""
            return
        if self.state == "menu" and self._hit(x, y, "btnOpenReceive"):
            self.state = "list"
            self.filter_text = ""
        elif self.state == "list" and self._hit(x, y, "btnStart"):
            self.active = self._visible()[0]
            self.scanned = 0
            self.state = "extra" if self.extra_screen else "scan"
        elif self.state == "confirm" and self._hit(x, y, "btnAccept"):
            self.sessions_created.append(self.filter_text)
            self.active = Checkin(f"CKS{self.filter_text} - VIN", self.filter_text,
                                  self.new_session_qty)
            self.scanned = 0
            self.state = "extra" if self.extra_screen else "scan"
        elif self.state == "confirm" and self._hit(x, y, "btnCancel"):
            self.state = "list"
            self.filter_text = ""
        elif self.state == "finish" and self._hit(x, y, "button1"):
            self.state = "menu" if self.back_to_menu else "list"
            self.filter_text = ""
            self.active = None

    def _hit(self, x: int, y: int, rid: str) -> bool:
        """Chạm đúng phần tử này không - hỏi theo id chứ không hỏi 'ở toạ độ này
        có gì', vì các khung bao ngoài (rclView...) trùm lên gần hết màn hình."""
        for node in re.findall(r"<node[^>]*>", self.dump()):
            if f"id/{rid}" not in node:
                continue
            b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
            x1, y1, x2, y2 = (int(v) for v in b.groups())
            if x1 <= x <= x2 and y1 <= y <= y2:
                return True
        return False
