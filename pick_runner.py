"""
pick_runner.py
Chạy luồng xuất kho: mỗi mã OR trong file Excel là một phiên "Lấy hàng".

Khác hẳn luồng cũ (mỗi dòng Excel một serial độc lập): ở đây một mã OR gồm một
hoặc nhiều serial, và chúng phải vào đúng một phiên - quét lẫn sang phiên khác
là xuất kho nhầm đơn. Nên mọi bước đều xác nhận đang đứng đúng màn hình trước
khi gõ, và gặp bất thường là dừng cả phiên chạy chứ không "bỏ qua dòng này".

Ngoại lệ duy nhất: gõ mã OR mà hết thời gian chờ vẫn không lọc ra thẻ nào
(OrNotFoundError). Lúc đó chưa mở phiên, màn hình vẫn ở "Tìm theo mã OR" nên bỏ
qua an toàn - PickWorker ghi lỗi cho mã đó rồi gõ mã OR tiếp theo.

Chuỗi màn hình của app (bản tiếng Việt, đối chiếu với bản quay màn hình):

    Lấy hàng / "Tìm theo mã OR"  -> gõ mã OR, lọc còn đúng một thẻ
    thẻ phiên (SL OR / SL sản phẩm) -> bấm "Lấy hàng"
    "Quét thiết bị chứa hàng"    -> mã tote, đếm "Số lượng ... cần DK: 0/1"
    "Quét vị trí lấy hàng"       -> mã bin, app gợi ý ở "Vị trí lấy hàng kế tiếp"
    "Quét sản phẩm/serial"       -> từng serial, đếm "SL sản phẩm đã lấy 0/N"
    "Công việc lấy hàng đã kết thúc" [Lịch sử][OK] -> quay lại màn hình tìm mã OR

Lưu ý hai chỗ khác với bản trước, cả hai đều lấy từ bản quay màn hình:
- Đóng phiên xong app trả về **màn hình tìm mã OR**, không về menu chính.
- Thẻ phiên **không in mã OR** lên đâu cả (nó chỉ có mã phiên PL..., "VIN", số
  lượng), nên không thể đối chiếu mã trên thẻ như luồng nhập hàng.

Không giữ tham chiếu Qt nào để test được headless.
"""
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from screen_reader import (
    ScreenReader,
    dialog_message,
    find_dismiss_button,
    list_nodes,
    normalize_match_text,
)

logger = logging.getLogger(__name__)

# resource-id lấy từ bản dump máy thật. Dùng id chứ không dùng chữ: app có nút
# đổi ngôn ngữ, máy này chạy tiếng Anh máy kia tiếng Việt, khớp chữ là hỏng.
RID_PICK_MENU = "btnPick"
RID_INPUT = "textInput"
RID_SUBMIT = "btnSubmit"
RID_PROCEED = "btnProceed"             # nút "Lấy hàng" trên thẻ phiên
RID_NOTE = "holderNote"
RID_PRODUCT_NUMBER = "tvProductNumber"  # "SL sản phẩm" trên thẻ
RID_SESSION_CODE = "tvSessionCode"

# Ba bước quét dùng chung ô nhập, chỉ khác nhau ở mấy thẻ xung quanh.
RID_TOTE_COUNT = "tvRegisterCount"     # chỉ màn hình quét tote mới có
RID_NEXT_BIN = "tvNextBin"             # "Vị trí lấy hàng kế tiếp"
RID_BIN = "tvBin"                      # "Vị trí lấy hàng hiện tại"
RID_COUNTER = "tvCounter"              # "0/10"

# Thẻ chỉ có ở màn hình đã vào phiên - dùng để phân biệt màn hình tìm mã OR
# (cũng có ô nhập) với ba màn hình quét.
IN_SESSION_IDS = (RID_TOTE_COUNT, RID_NEXT_BIN, RID_BIN, RID_COUNTER)

# AlertDialog chuẩn của Android: button1 là nút thuận, button2 là nút nghịch.
# Hộp "Picking assistant" có Set up / Skip -> Skip chính là button2, đúng bất kể
# ngôn ngữ. KHÔNG được khớp theo chữ "Skip": màn hình quét serial cũng có nút
# tên Skip (actionFinish) nhưng nó là "bỏ qua sản phẩm này".
RID_DIALOG_TITLE = "alertTitle"
RID_DIALOG_NEGATIVE = "button2"

DEFAULT_STEP_TIMEOUT = 15.0
DEFAULT_SEARCH_TIMEOUT = 2.0
# Một lần `uiautomator dump` mất ~1.46s trên máy thật, nên bản thân vòng lặp đã
# tự giãn nhịp rồi - khoảng nghỉ thêm chỉ là thời gian chết cộng vào mỗi vòng.
# 0.25s cũ làm mỗi mã OR mất thêm ~3s. Giữ lại một nhịp rất ngắn để không quay
# ADB liên tục khi máy ảo đang chuyển cảnh.
POLL_INTERVAL = 0.05
# Hai mã mặc định của kho đang dùng. Giao diện nạp thẳng hai giá trị này vào ô
# Cấu hình, nên kho khác chỉ cần sửa ở đây là đổi được mặc định cho cả app.
DEFAULT_TOTE = "T001"
DEFAULT_BIN_CODE = "PYTES"
_COUNTER_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


class PickStopped(Exception):
    """Dừng cả phiên chạy. Luồng này không có khái niệm 'bỏ qua rồi chạy tiếp'."""

    def __init__(self, message: str, screenshot_path: str | None = None):
        super().__init__(message)
        self.message = message
        self.screenshot_path = screenshot_path


class OrNotFoundError(PickStopped):
    """
    Ngoại lệ duy nhất được phép "bỏ qua rồi chạy tiếp": gõ mã OR nhưng hết
    step_timeout mà danh sách Lấy hàng không lọc ra thẻ nào.

    An toàn để bỏ qua vì thời điểm này bot chưa mở phiên - màn hình vẫn đang là
    "Tìm theo mã OR", chưa động gì tới kho. Bên gọi (PickWorker) bắt riêng lỗi
    này để ghi lỗi cho mã đó rồi gõ mã OR kế tiếp, thay vì dừng cả lượt chạy như
    mọi PickStopped khác.
    """


@dataclass
class PickConfig:
    # Hai mã này cố định cho cả lượt chạy, chỉnh ở khung Cấu hình trước khi bấm
    # Start. Đổi giữa chừng thì phải dừng rồi chạy lại - phiên đang dở trên máy
    # ảo mới là thứ quyết định tote/bin nào đang hợp lệ.
    tote: str = DEFAULT_TOTE
    # Bin (vị trí lấy hàng). Điền giá trị là ép cứng: app chỉ sang vị trí khác
    # thì bot dừng chứ không lấy nhầm kệ. Để trống nghĩa là đọc vị trí app đang
    # yêu cầu (tvNextBin) rồi gõ lại - dùng khi đơn trải nhiều vị trí.
    bin_code: str = DEFAULT_BIN_CODE
    step_timeout: float = DEFAULT_STEP_TIMEOUT
    # Riêng bước gõ mã OR: mã không có thật là chuyện thường trong file, mà chờ
    # hết `step_timeout` cho mỗi mã như vậy thì 300 mã mất cả tiếng đồng hồ chỉ
    # để đứng nhìn. Chờ chừng này rồi ghi lỗi và sang mã sau.
    search_timeout: float = DEFAULT_SEARCH_TIMEOUT
    # Bỏ qua bước đối chiếu số lượng app báo với số serial trong Excel. Mặc định
    # là bật vì lệch số nghĩa là file sai, mà phát hiện trước khi mở phiên thì
    # chưa động gì tới kho.
    check_expected_count: bool = True
    capture_screenshot: bool = True


@dataclass
class SerialResult:
    row: int
    serial: str
    status: str = "OK"
    message: str = ""


@dataclass
class BillOutcome:
    bill: str
    status: str = "OK"                 # OK | ERROR
    message: str = ""
    session_code: str = ""
    # Mã vận đơn (MVĐ) đi kèm mã OR. Bot không gõ nó vào đâu cả, chỉ mang theo
    # để file kết quả và báo cáo tra ngược được về đơn hàng.
    ref: str = ""
    expected: int = 0
    picked: int = 0
    serials: list = field(default_factory=list)


def parse_counter(text: str) -> tuple[int, int] | None:
    """'0/10' -> (0, 10). Trả None nếu không đọc được."""
    match = _COUNTER_RE.search(text or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def nodes_with_id(screen_xml: str, resource_id: str) -> list[dict]:
    """Mọi phần tử mang resource-id này (khớp phần đuôi sau dấu '/')."""
    wanted = resource_id.strip()
    found = []
    for node in list_nodes(screen_xml, only_interesting=False):
        rid = node.get("resource_id", "")
        if rid == wanted or rid.endswith("/" + wanted):
            found.append(node)
    return found


def first_with_id(screen_xml: str, resource_id: str) -> dict | None:
    nodes = nodes_with_id(screen_xml, resource_id)
    return nodes[0] if nodes else None


class PickRunner:
    """
    Chạy từng vận đơn. Bên gọi lo việc lặp danh sách và ghi Excel.

    on_log(text) - để giao diện hiện tiến trình từng bước, vì một vận đơn mất
    khá lâu và người dùng cần thấy nó đang ở đâu.
    """

    def __init__(
        self,
        adb_client,
        backend,
        config: PickConfig | None = None,
        screenshot_dir: str = "screenshots",
        on_log=None,
        should_stop=None,
        wait_if_paused=None,
    ):
        self.adb = adb_client
        # Đã thử `--compressed`: đo trên máy thật 1.46s -> 1.44s, tức là không
        # nhanh hơn gì. Chi phí một lần dump nằm ở việc khởi động tiến trình
        # `uiautomator` trên máy ảo chứ không ở kích thước cây node, nên rút gọn
        # cây chẳng giải quyết được gì - chỉ còn lại rủi ro lược mất node cần
        # đọc. Giữ cơ chế trong ScreenReader cho máy khác, ở đây tắt.
        self.backend = backend
        self.screen = ScreenReader(adb_client)
        self.config = config or PickConfig()
        self.screenshot_dir = screenshot_dir
        self._on_log = on_log
        self._should_stop = should_stop or (lambda: False)
        # Chỉ gọi ở chỗ không có đồng hồ đếm ngược nào đang chạy - xem
        # PickWorker._wait_if_paused.
        self._wait_if_paused = wait_if_paused or (lambda: None)
        # Những serial đã vào phiên tính tới lúc này. Dừng giữa chừng thì đây là
        # thứ cho biết phiên trên máy ảo đang dở tới đâu mà dọn.
        self.last_partial: list[SerialResult] = []
        # Bản dump chuyền tay từ `_wait_for_pick` sang `_finish_session`.
        self._pending_finish_xml = ""
        # Màn hình tìm mã OR mà `_finish_session` vừa xác nhận, để mã kế tiếp
        # khỏi dump lại hỏi đúng câu đó. Chỉ dùng đúng một lần.
        self._at_search_xml = ""

    # ------------------------------------------------------------- tiện ích

    def _log(self, text: str):
        logger.info(text)
        if self._on_log:
            self._on_log(text)

    def _dump(self) -> str:
        xml = self.screen.dump_xml()
        if not xml:
            raise PickStopped(
                "Không đọc được màn hình máy ảo qua ADB. Kiểm tra LDPlayer còn chạy không."
            )
        return xml

    def _stop(self, message: str) -> "PickStopped":
        return PickStopped(message, self._screenshot())

    def _not_found(self, message: str) -> "OrNotFoundError":
        return OrNotFoundError(message, self._screenshot())

    def _screenshot(self) -> str | None:
        if not self.config.capture_screenshot:
            return None
        data = self.screen.screenshot_png()
        if not data:
            return None
        try:
            os.makedirs(self.screenshot_dir, exist_ok=True)
            path = os.path.join(
                self.screenshot_dir,
                f"pick_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png",
            )
            with open(path, "wb") as f:
                f.write(data)
            return path
        except OSError:
            return None

    def _wait_for_id(self, resource_id: str, timeout: float | None = None) -> str:
        return self._wait_for_any_id((resource_id,), timeout)

    def _wait_for_any_id(self, resource_ids, timeout: float | None = None) -> str:
        """
        Chờ tới khi màn hình có một trong các phần tử này, trả về bản dump lúc
        thấy.

        Chờ theo dấu hiệu chứ không ngủ cố định: máy ảo lúc nhanh lúc chậm, mà
        gõ sớm một nhịp là chữ rơi vào ô của bước trước.

        Nhận nhiều id vì có bước app lướt qua một màn hình: tote còn hiệu lực từ
        phiên trước thì màn hình quét tote chỉ hiện thoáng rồi tự sang quét vị
        trí - chờ đúng một id là thua cuộc đua đó.
        """
        deadline = time.monotonic() + (timeout or self.config.step_timeout)
        last = ""
        while True:
            if self._should_stop():
                raise PickStopped("Người dùng bấm Dừng.")
            xml = self.screen.dump_xml()
            if xml:
                last = xml
                if any(first_with_id(xml, rid) for rid in resource_ids):
                    return xml
            if time.monotonic() >= deadline:
                # Hết giờ mà đang đọc bản dump rút gọn: có thể id cần tìm nằm
                # trong đúng phần `--compressed` lược đi. Tắt hẳn chế độ đó rồi
                # đọc lại một lần bằng bản đầy đủ - sai vì đọc thiếu thì tệ hơn
                # nhiều so với mất thêm một lần dump.
                if self.screen.disable_compressed():
                    logger.info("Chờ hết giờ với dump rút gọn - đọc lại bản đầy đủ")
                    xml = self.screen.dump_xml()
                    if xml:
                        last = xml
                        if any(first_with_id(xml, rid) for rid in resource_ids):
                            return xml
                detail = dialog_message(last) if last else ""
                extra = f" Màn hình đang hiện: {detail}" if detail else ""
                raise self._stop(
                    f"Chờ quá {timeout or self.config.step_timeout:.0f}s mà màn hình "
                    f"không xuất hiện {' hoặc '.join(repr(r) for r in resource_ids)}."
                    f"{extra}"
                )
            time.sleep(POLL_INTERVAL)

    def _tap_id(self, xml: str, resource_id: str) -> None:
        node = first_with_id(xml, resource_id)
        if not node:
            raise self._stop(f"Không tìm thấy nút '{resource_id}' trên màn hình.")
        if not self.screen.tap_node(node):
            raise self._stop(f"Gửi lệnh chạm '{resource_id}' thất bại.")

    def _type(self, text: str) -> None:
        """
        Gõ vào ô đang focus rồi Enter - dùng chung cho cả bốn ô nhập.

        Luôn xóa ô trước (mặc định của `type_and_submit`): ô "Tìm theo mã OR"
        giữ nguyên mã của đơn trước sau khi đóng phiên, nối thêm vào là ra một
        mã không có thật.
        """
        self.backend.type_and_submit(text, "enter")

    def _type_and_wait(self, text: str, resource_ids: tuple) -> str:
        """
        Gõ rồi chờ màn hình kế tiếp.

        Đã thử ghép "gõ + ngủ một nhịp + dump" vào một lệnh ADB để bỏ lần dump
        bắt được màn hình cũ. Đo trên máy thật: **chậm đi** (bin -> serial
        3.80s -> 5.75s). App chuyển cảnh mất khoảng bằng đúng một lần dump, nên
        không có nhịp ngủ nào vừa: ngắn thì dump vẫn trượt và phải đọc lại (trả
        cả nhịp ngủ lẫn lần dump phí), dài thì chính nhịp ngủ là thời gian chết.
        Vòng poll tự dò lấy vẫn hơn.
        """
        self._type(text)
        return self._wait_for_any_id(resource_ids)

    def _is_search_screen(self, xml: str) -> bool:
        """
        Đang ở màn hình "Tìm theo mã OR" chứ không phải một trong ba màn hình
        quét (cả bốn đều có ô nhập, nên chỉ nhìn ô nhập là không phân biệt được).
        """
        if not first_with_id(xml, RID_INPUT):
            return False
        return not any(first_with_id(xml, rid) for rid in IN_SESSION_IDS)

    # ------------------------------------------------------------ các bước

    def run_bill(self, bill: str, rows: list[dict], ref: str = "") -> BillOutcome:
        outcome = BillOutcome(bill=bill, ref=ref, expected=len(rows))
        self.last_partial = []
        self._pending_finish_xml = ""
        # Không xóa `_at_search_xml` ở đây: nó chính là kết luận mã trước vừa để
        # lại. `_open_picking_list` tự tiêu thụ và xóa.
        started_at = time.monotonic()
        dumps_before = self.screen.dump_count
        seconds_before = self.screen.dump_seconds
        self._log(f"[{bill}] mở màn hình tìm mã OR")

        self._open_picking_list()
        session_code = self._search_and_open(bill, len(rows))
        outcome.session_code = session_code

        # Mỗi bước trả màn hình cho bước sau: gõ và đọc màn hình đi chung một
        # lần gọi ADB, nên bước sau không phải dò lại từ đầu.
        xml = self._scan_tote(self._pass_assistant_dialog())
        outcome.serials = self._scan_serials(bill, rows, self._scan_bin(xml))
        outcome.picked = sum(1 for s in outcome.serials if s.status == "OK")
        self._finish_session(bill)

        outcome.message = f"Đã xuất {outcome.picked}/{outcome.expected} serial."
        self._log(f"[{bill}] xong - {outcome.message}")
        self._log_dump_cost(bill, started_at, dumps_before, seconds_before)
        return outcome

    def _log_dump_cost(self, bill, started_at, dumps_before, seconds_before) -> None:
        """
        Ghi lại đọc màn hình tốn bao nhiêu trong tổng thời gian của một mã OR.

        Đây gần như là toàn bộ chi phí của luồng này (đo trên máy thật: ~1.46s
        một lần dump, ~18 lần một mã OR), nên muốn biết chỉnh gì có tác dụng thì
        phải nhìn thấy con số chứ không đoán.
        """
        total = time.monotonic() - started_at
        dumps = self.screen.dump_count - dumps_before
        dump_time = self.screen.dump_seconds - seconds_before
        share = (dump_time / total * 100) if total else 0
        logger.info(
            "[%s] %.1fs tong - %d lan doc man hinh mat %.1fs (%.0f%%)",
            bill, total, dumps, dump_time, share,
        )

    def _open_picking_list(self) -> None:
        """
        Vào màn hình tìm mã OR.

        Nhận cả hai điểm xuất phát: menu chính (bấm nút Lấy hàng), hoặc đang
        đứng sẵn ở màn hình tìm - đóng xong một phiên app trả về đúng chỗ đó chứ
        không về menu chính, nên từ đơn thứ hai trở đi luôn là nhánh này.

        `_finish_session` của mã trước vừa xác nhận đúng màn hình này xong (cách
        đây vài mili giây, chưa ai gõ gì thêm), nên dùng lại kết luận đó thay vì
        đọc màn hình lần nữa - 1.46s mỗi mã, với 300 mã là hơn 7 phút. Chỉ dùng
        một lần: mã nào dừng giữa chừng thì biến này rỗng và bước này đọc lại
        như thường.
        """
        if self._at_search_xml:
            self._at_search_xml = ""
            return

        deadline = time.monotonic() + self.config.step_timeout
        while True:
            xml = self._dump()

            if self._is_search_screen(xml):
                return

            if first_with_id(xml, RID_PICK_MENU):
                self._tap_id(xml, RID_PICK_MENU)
                self._wait_for_search_screen()
                return

            if time.monotonic() >= deadline:
                raise self._stop(
                    f"Không về được màn hình tìm mã OR (không thấy "
                    f"'{RID_PICK_MENU}' lẫn ô tìm kiếm).\n\n"
                    f"Màn hình đang hiện: {self._describe(xml)}"
                )
            time.sleep(POLL_INTERVAL)

    def _wait_for_search_screen(self) -> str:
        deadline = time.monotonic() + self.config.step_timeout
        while True:
            xml = self._dump()
            if self._is_search_screen(xml):
                return xml
            if time.monotonic() >= deadline:
                raise self._stop(
                    f"Bấm Lấy hàng xong nhưng không thấy màn hình tìm mã OR.\n\n"
                    f"Màn hình đang hiện: {self._describe(xml)}"
                )
            time.sleep(POLL_INTERVAL)

    def _search_and_open(self, bill: str, serial_count: int) -> str:
        """
        Gõ mã OR rồi chờ danh sách lọc còn đúng một thẻ.

        Thẻ phiên **không in mã OR** lên đâu cả, nên không đối chiếu được mã trên
        thẻ như luồng nhập hàng. Hai lớp thay thế:

        - Đúng **một** thẻ. Ra 0 hay 2+ là dừng, không đoán.
        - Ô tìm kiếm phải đang giữ đúng mã bot vừa gõ. Đây là chỗ bắt được lỗi
          ADB gõ thiếu/thừa ký tự - lỗi đó lọc ra một thẻ trông rất bình thường
          nhưng là của đơn khác. Ô nào không trả về text thì bỏ qua lớp này chứ
          không chặn, vì không đọc được không có nghĩa là sai.

        Mã không có trong danh sách thì kết luận sau `search_timeout` (2s) chứ
        không chờ hết `step_timeout` - nhưng chỉ khi ô tìm kiếm đã giữ đúng mã
        vừa gõ. Ô đã nhận đủ chữ mà danh sách vẫn trống nghĩa là mã không có
        thật; còn ô chưa kịp cập nhật thì trống là do app đang chậm, kết luận
        lúc đó sẽ bỏ sót một đơn có thật.

        Ô giữ nguyên mã của lần trước thì gõ lại **một** lần: chạm vào ô cho nó
        nhận lại focus rồi gõ. Quan sát trên máy thật - sau vài mã không tìm
        thấy liên tiếp, `input text` không vào được ô nữa (ô còn nguyên mã cũ)
        và cả lượt chạy dừng ở đó. Chạm vào ô nhập là thao tác vô hại (không
        phải nút hành động), còn lớp đối chiếu "ô phải khớp mã" vẫn giữ nguyên
        nên gõ lại vẫn không thể mở nhầm đơn.
        """
        self._log(f"[{bill}] tìm mã OR")
        self._type(bill)

        # Danh sách lọc bất đồng bộ; chờ tới khi đúng một thẻ khớp mã vừa gõ.
        deadline = time.monotonic() + self.config.step_timeout
        empty_since = None
        stale_since = None
        retried = False
        wanted = normalize_match_text(bill)
        while True:
            xml = self._dump()
            cards = nodes_with_id(xml, RID_PROCEED)
            typed = self._search_field_text(xml)
            notes = nodes_with_id(xml, RID_NOTE)
            matching = [n for n in notes if wanted in normalize_match_text(n.get("text", ""))]

            if len(cards) == 1 and (not typed or typed == wanted) and len(matching) <= 1:
                break

            if not cards and typed == wanted:
                now = time.monotonic()
                if empty_since is None:
                    empty_since = now
                elif now - empty_since >= self.config.search_timeout:
                    raise self._not_found(
                        f"Không tìm thấy mã OR '{bill}' trong danh sách Lấy hàng "
                        f"(ô tìm kiếm đã nhận đủ mã nhưng không lọc ra thẻ nào "
                        f"sau {self.config.search_timeout:.0f}s)."
                    )
            else:
                empty_since = None

            # Ô đang giữ một mã khác hẳn: chữ bot gửi không vào được ô. Đợi cho
            # chắc (app có thể đang vẽ dở) rồi chạm vào ô và gõ lại một lần.
            if typed and typed != wanted and not retried:
                now = time.monotonic()
                if stale_since is None:
                    stale_since = now
                elif now - stale_since >= self.config.search_timeout:
                    self._log(
                        f"[{bill}] ô tìm kiếm còn '{typed}' - chạm vào ô rồi gõ lại"
                    )
                    self._tap_id(xml, RID_INPUT)
                    self._type(bill)
                    retried = True
                    stale_since = None
                    empty_since = None
                    deadline = time.monotonic() + self.config.step_timeout
                    time.sleep(POLL_INTERVAL)
                    continue
            elif typed == wanted:
                stale_since = None

            if time.monotonic() >= deadline:
                if typed and typed != wanted:
                    raise self._stop(
                        f"Ô tìm kiếm đang là '{typed}' chứ không phải mã OR "
                        f"'{bill}' bot vừa gửi - lệnh gõ qua ADB bị hụt hoặc thừa "
                        f"ký tự (đã chạm vào ô và gõ lại một lần vẫn không được). "
                        f"Dừng, vì thẻ lọc ra là của mã khác."
                    )
                if not cards:
                    raise self._not_found(
                        f"Không tìm thấy mã OR '{bill}' trong danh sách Lấy hàng."
                    )
                if len(cards) == 1:
                    raise self._stop(
                        f"Mã OR '{bill}' lọc ra đúng một thẻ nhưng có {len(matching)} "
                        f"nhãn cùng chứa mã đó - không dám bấm.\n\n"
                        f"Thẻ đang hiện: {self._describe(xml)}"
                    )
                raise self._stop(
                    f"Mã OR '{bill}' lọc ra {len(cards)} phiên khớp - không dám "
                    f"bấm vì có thể mở nhầm đơn."
                )
            time.sleep(POLL_INTERVAL)

        session_node = first_with_id(xml, RID_SESSION_CODE)
        session_code = (session_node or {}).get("text", "")

        if self.config.check_expected_count:
            expected = self._expected_count(xml)
            if expected is not None and expected != serial_count:
                raise self._stop(
                    f"Mã OR '{bill}': app báo cần {expected} sản phẩm nhưng "
                    f"Excel có {serial_count} serial. Dừng trước khi mở phiên - "
                    f"sửa file rồi chạy lại."
                )

        self._log(f"[{bill}] vào phiên {session_code}")
        self._tap_id(xml, RID_PROCEED)
        return session_code

    @staticmethod
    def _search_field_text(xml: str) -> str:
        node = first_with_id(xml, RID_INPUT)
        return normalize_match_text((node or {}).get("text", ""))

    def _expected_count(self, xml: str) -> int | None:
        node = first_with_id(xml, RID_PRODUCT_NUMBER)
        if not node:
            return None
        try:
            return int((node.get("text") or "").strip())
        except ValueError:
            return None

    def _pass_assistant_dialog(self) -> str:
        """
        Ngay sau khi vào phiên, app hiện hộp 'Picking assistant' (chọn ngôn ngữ).
        Nó hiện mỗi lần pick nên buộc phải đóng, nhưng chỉ đóng đúng hộp này -
        hộp thoại lạ nghĩa là có chuyện, phải dừng cho người xem.

        Trả về bản dump đã thấy màn hình quét, để `_scan_tote` dùng lại thay vì
        dump thêm một lần nữa hỏi đúng câu hỏi vừa trả lời xong.
        """
        deadline = time.monotonic() + self.config.step_timeout
        while True:
            xml = self._dump()

            if first_with_id(xml, RID_TOTE_COUNT) or first_with_id(xml, RID_NEXT_BIN):
                return xml                  # đã vào thẳng màn hình quét

            has_title = first_with_id(xml, RID_DIALOG_TITLE)
            negative = first_with_id(xml, RID_DIALOG_NEGATIVE)
            if has_title and negative:
                message = dialog_message(xml)
                self._log(f"đóng hộp thoại trợ lý: {message}")
                self.screen.tap_node(negative)
                return self._wait_for_any_id((RID_TOTE_COUNT, RID_NEXT_BIN))

            if find_dismiss_button(xml) is not None:
                # Hộp thoại có nút OK/Đóng ở đây là báo lỗi, không phải trợ lý.
                raise self._stop(f"App báo lỗi khi mở phiên: {dialog_message(xml)}")

            if time.monotonic() >= deadline:
                raise self._stop(
                    f"Vào phiên xong nhưng không thấy màn hình quét.\n\n"
                    f"Màn hình đang hiện: {self._describe(xml)}"
                )
            time.sleep(POLL_INTERVAL)

    def _scan_tote(self, xml: str = "") -> str:
        """
        Quét thiết bị chứa hàng (tote).

        App nhớ tote giữa các phiên: mở đơn thứ hai mà số đếm "cần DK" đã đủ thì
        màn hình này chỉ lướt qua rồi tự sang bước quét vị trí. Gõ thêm lúc đó là
        đăng ký chồng một thiết bị nữa, nên thấy đủ là không gõ.

        `xml` là bản dump `_pass_assistant_dialog` vừa đọc xong - nó đã xác nhận
        đúng màn hình này rồi, dump lại chỉ để hỏi y hệt câu đó là mất không một
        lần đọc màn hình (~1.4s) mỗi mã OR.

        Trả về màn hình quét vị trí, để `_scan_bin` khỏi phải đọc lại lần nữa.
        """
        if not xml:
            xml = self._wait_for_any_id((RID_TOTE_COUNT, RID_NEXT_BIN))

        if not first_with_id(xml, RID_TOTE_COUNT):
            self._log("app đã qua bước quét tote - tote còn hiệu lực từ phiên trước")
            return xml

        counter = parse_counter((first_with_id(xml, RID_TOTE_COUNT) or {}).get("text", ""))
        if counter and counter[1] and counter[0] >= counter[1]:
            self._log(
                f"tote đã đăng ký sẵn ({counter[0]}/{counter[1]}) - bỏ qua bước quét"
            )
            return xml

        tote = self.config.tote.strip()
        if not tote:
            raise self._stop(
                "App đang đòi quét thiết bị chứa hàng nhưng ô 'Mã tote' trong "
                "Cấu hình đang để trống."
            )
        self._log(f"quét tote {tote}")
        return self._type_and_wait(tote, (RID_NEXT_BIN,))

    def _scan_bin(self, xml: str = "") -> str:
        """
        Quét vị trí lấy hàng (bin).

        App tự chỉ vị trí kế tiếp ở `tvNextBin`. Ô 'Mã bin' trong Cấu hình là ép
        cứng: lệch với vị trí app chỉ thì dừng chứ không gõ, vì gõ đại là đi lấy
        nhầm kệ. Để trống ô đó thì bot đi theo app, đúng cả với đơn trải nhiều
        vị trí.

        `xml` là màn hình quét vị trí `_scan_tote` vừa đọc được ngay trong lần
        gọi ADB gõ tote; trả về màn hình quét serial cho `_scan_serials`.
        """
        if not xml:
            xml = self._wait_for_id(RID_NEXT_BIN)
        asked = (first_with_id(xml, RID_NEXT_BIN) or {}).get("text", "").strip()
        bin_code = self.config.bin_code.strip()

        if not bin_code:
            bin_code = asked
            if not bin_code:
                raise self._stop("Không đọc được vị trí lấy hàng app đang yêu cầu.")
        elif asked and normalize_match_text(asked) != normalize_match_text(bin_code):
            raise self._stop(
                f"App yêu cầu lấy ở vị trí '{asked}' nhưng ô 'Mã bin' trong Cấu "
                f"hình đang ép '{bin_code}'. Dừng để khỏi lấy nhầm kệ.\n\n"
                f"Sửa ô 'Mã bin' cho khớp, hoặc để trống ô đó để bot đi theo vị "
                f"trí app chỉ."
            )

        self._log(f"quét vị trí lấy hàng {bin_code}")
        return self._type_and_wait(bin_code, (RID_BIN,))

    def _scan_serials(self, bill: str, rows: list[dict], xml: str = "") -> list[SerialResult]:
        if not xml:
            xml = self._wait_for_id(RID_BIN)
        counter = parse_counter((first_with_id(xml, RID_COUNTER) or {}).get("text", ""))
        picked = counter[0] if counter else 0

        results = []
        for index, row in enumerate(rows, start=1):
            # Trước khi gõ serial kế tiếp: chưa bấm gì, chưa chờ gì, nên đứng
            # lại ở đây là an toàn. Phiên vẫn mở nhưng chỉ nằm im.
            self._wait_if_paused()
            if self._should_stop():
                raise PickStopped("Người dùng bấm Dừng.")

            serial = row["value"]
            self._log(f"[{bill}] {index}/{len(rows)} quét {serial}")
            self._type(serial)
            picked = self._wait_for_pick(bill, serial, picked, last=index == len(rows))
            result = SerialResult(row=row["row"], serial=serial, status="OK")
            results.append(result)
            self.last_partial.append(result)
        return results

    def _wait_for_pick(self, bill: str, serial: str, previous: int, last: bool) -> int:
        """
        Chờ số đếm tăng đúng một đơn vị.

        Đây là bằng chứng app đã nhận serial, chắc chắn hơn hẳn kiểu 'gõ xong là
        coi như xong'. Ở serial cuối cùng app đóng phiên và hiện hộp thoại, lúc
        đó không còn số đếm để đọc nữa - nên coi hộp thoại cũng là dấu hiệu xong.

        """
        deadline = time.monotonic() + self.config.step_timeout
        while True:
            xml = self._dump()

            counter_node = first_with_id(xml, RID_COUNTER)
            if counter_node:
                counter = parse_counter(counter_node.get("text", ""))
                if counter and counter[0] > previous:
                    return counter[0]

            if find_dismiss_button(xml) is not None:
                message = dialog_message(xml)
                if last:
                    # Hộp thoại kết thúc phiên. Giữ lại bản dump: `_finish_session`
                    # chạy ngay sau đây và việc đầu tiên nó làm là đi tìm đúng hộp
                    # thoại này - đọc lại màn hình lần nữa là thừa.
                    self._pending_finish_xml = xml
                    return previous + 1
                raise self._stop(
                    f"[{bill}] serial '{serial}': app báo lỗi - {message}"
                )

            if time.monotonic() >= deadline:
                raise self._stop(
                    f"[{bill}] serial '{serial}': quét xong mà số đếm không tăng "
                    f"sau {self.config.step_timeout:.0f}s."
                )
            time.sleep(POLL_INTERVAL)

    def _finish_session(self, bill: str) -> None:
        """
        Bấm OK trên hộp "Công việc lấy hàng đã kết thúc" rồi chờ về chỗ chạy
        được đơn sau.

        Nhận cả màn hình tìm mã OR (app trả về đây) lẫn menu chính (gặp khi
        người dùng tự bấm Back). Có thể phải bấm hơn một lần: sau serial cuối app
        còn chèn hộp "Vị trí cần đặt sản phẩm vừa lấy" trước hộp kết thúc.
        """
        deadline = time.monotonic() + self.config.step_timeout
        # Bản dump `_wait_for_pick` vừa đọc (đã thấy hộp thoại kết thúc) dùng
        # được cho vòng đầu; từ vòng hai trở đi phải đọc lại vì mình vừa bấm.
        xml = self._pending_finish_xml
        self._pending_finish_xml = ""
        while True:
            if not xml:
                xml = self._dump()

            if first_with_id(xml, RID_PICK_MENU) or self._is_search_screen(xml):
                # Chuyền kết luận này sang mã kế tiếp để nó khỏi đọc lại.
                self._at_search_xml = xml if self._is_search_screen(xml) else ""
                return

            button = find_dismiss_button(xml)
            if button:
                self._log(f"[{bill}] kết thúc phiên: {dialog_message(xml)}")
                self.screen.tap_node(button)
                # Vừa bấm thì bản dump đang cầm hết giá trị - phải đọc lại.
                xml = ""
                time.sleep(POLL_INTERVAL)
                continue

            if time.monotonic() >= deadline:
                raise self._stop(
                    f"[{bill}] quét đủ serial nhưng không về được màn hình tìm "
                    f"mã OR.\n\nMàn hình đang hiện: {self._describe(xml)}"
                )
            xml = ""
            time.sleep(POLL_INTERVAL)

    @staticmethod
    def _describe(xml: str, limit: int = 12) -> str:
        """Tóm tắt màn hình lạ thành một dòng đọc được, để dán lại khi báo lỗi."""
        seen = []
        for node in list_nodes(xml, only_interesting=False):
            rid = (node.get("resource_id") or "").split("/")[-1]
            text = (node.get("text") or "").strip()
            if not rid and not text:
                continue
            label = f"{rid}='{text}'" if rid and text else (rid or f"'{text}'")
            if label not in seen:
                seen.append(label)
            if len(seen) >= limit:
                seen.append("...")
                break
        return ", ".join(seen) or "(không đọc được phần tử nào)"
