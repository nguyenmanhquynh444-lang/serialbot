"""
inbound_runner.py
Chạy luồng nhập hàng theo mã check-in: mỗi mã check-in là một phiên nhận hàng.

Cùng hình dạng với luồng xuất kho (xem pick_runner.py): một mã gom nhiều serial,
tất cả phải vào đúng một phiên, nên gặp bất thường là dừng cả phiên chạy chứ
không bỏ qua dòng. Khác ở ba chỗ:

- Vào bằng nút Receive (`btnOpenReceive`) chứ không phải Picking.
- Thẻ trên danh sách check-in dùng bộ id riêng: `tvSessionCode` / `tvAddInfo` /
  `btnStart`, và **không** có ô số lượng sản phẩm như thẻ picking. Nên bước đối
  chiếu số lượng phải lùi lại tới màn hình quét, đọc từ `0/N` của `tvCounter`.
- Sau khi bấm Nhận hàng, luồng đi thẳng tới màn hình quét serial. Nếu app chèn
  thêm bước nào khác (quét thùng, chọn sản phẩm...) thì bot **dừng và liệt kê
  những gì đang hiện trên màn hình** - xem `_wait_for_scan_screen`.

Không giữ tham chiếu Qt nào để test được headless.
"""
import logging
import time
from datetime import datetime
from automation_backend import AdbUnavailableError
from verification import classify_session_dialog
from telemetry import measure
from dataclasses import dataclass

from pick_runner import (
    POLL_INTERVAL,
    BillOutcome,
    PickConfig,
    PickRunner,
    PickStopped,
    SerialResult,
    first_with_id,
    nodes_with_id,
    parse_counter,
    bounded_step,
)
from screen_reader import dialog_message, find_dismiss_button, normalize_match_text

logger = logging.getLogger(__name__)

# Lấy từ bản dump máy thật (màn hình "Danh sách check-in", app vn.aipacific.fai.prod).
RID_RECEIVE_MENU = "btnOpenReceive"
RID_INPUT = "textInput"
RID_LIST = "rclView"
RID_SESSION_CODE = "tvSessionCode"     # "CKSIRVIN89HN210210 - VIN"
RID_ADD_INFO = "tvAddInfo"             # "IRVIN89HN210 - ESO26070007-261_3200368076"
RID_START = "btnStart"                 # nút "Nhận hàng" / "Receive" trên thẻ
RID_COUNTER = "tvCounter"              # "0/10" trên màn hình quét

# Hộp thoại hiện khi mã nhập kho chưa có phiên check-in nào:
# "Yêu cầu nhập kho chưa có tạo phiên check-in? Bạn có muốn tạo phiên và nhận hàng"
# Đây là hộp thoại tự vẽ của app, KHÔNG phải AlertDialog của Android - nút thuận
# tên `btnAccept` chứ không phải `button1`.
RID_CONFIRM_ACCEPT = "btnAccept"       # "Xác nhận"
RID_CONFIRM_CANCEL = "btnCancel"       # "Quay lại"
RID_CONFIRM_TITLE = "tvTitle"


@dataclass
class InboundConfig(PickConfig):
    """Dùng lại PickConfig: `tote`/`bin_code` là không có chỗ dùng ở đây."""

    # Bấm "Xác nhận" trên hộp thoại trên = TẠO một phiên check-in mới trong hệ
    # thống. Đó là một giao dịch thật, nên mặc định bot không tự làm: nó dừng và
    # để người dùng quyết định. Bật lên khi biết chắc mọi mã trong file đều cần
    # tạo phiên.
    create_missing_session: bool = False


class InboundRunner(PickRunner):
    """
    Chạy từng mã check-in. Bên gọi lo việc lặp danh sách và ghi Excel.

    Kế thừa PickRunner để dùng lại nguyên phần hạ tầng đã chạy thật: chờ theo
    dấu hiệu màn hình, chụp ảnh lúc dừng, gõ-rồi-chờ-số-đếm-tăng, đóng phiên.
    """

    @measure("bill")
    def run_bill(self, bill: str, rows: list[dict], ref: str = "") -> BillOutcome:
        outcome = BillOutcome(bill=bill, ref=ref, expected=len(rows))
        self.last_partial = []
        self._bill = bill
        self.session_mode = "inbound"
        self._counter_total = None
        self._completion_seen = False
        started_at = time.monotonic()
        dumps_before, seconds_before = self.screen.dump_count, self.screen.dump_seconds
        # `_wait_for_pick` dùng chung với luồng pick nên vẫn đặt biến này; luồng
        # nhập hàng có `_finish_session` riêng, không tiêu thụ nó.
        self._pending_finish_xml = ""
        self._log(f"[{bill}] mở danh sách check-in")

        self._open_checkin_list()
        outcome.session_code = self._search_and_open(bill)
        outcome.serials = self._scan_serials(bill, rows)
        outcome.picked = sum(1 for s in outcome.serials if s.status == "OK")
        self._finish_session(bill)

        outcome.message = f"Đã nhập {outcome.picked}/{outcome.expected} serial."
        self._log(f"[{bill}] xong - {outcome.message}")
        self._log_dump_cost(bill, started_at, dumps_before, seconds_before)
        return outcome

    # ------------------------------------------------------------ các bước

    @bounded_step
    def _open_checkin_list(self) -> None:
        """
        Vào danh sách check-in.

        Nhận cả hai điểm xuất phát: menu chính, hoặc đang đứng sẵn ở danh sách
        (app quay về đâu sau khi đóng phiếu thì chưa dò được, nên đỡ cả hai thay
        vì cược vào một). Ô tìm kiếm được xóa trước mỗi lần gõ nên mã cũ còn sót
        lại cũng không sao.
        """
        if self._at_search_xml:
            self._at_search_xml = ""
            return
        deadline = time.monotonic() + self.config.step_timeout
        while True:
            xml = self._dump(deadline)

            if first_with_id(xml, RID_LIST) and first_with_id(xml, RID_INPUT):
                return

            if first_with_id(xml, RID_RECEIVE_MENU):
                self._tap_id(xml, RID_RECEIVE_MENU)
                self._wait_for_id(RID_INPUT)
                return

            if time.monotonic() >= deadline:
                raise self._stop(
                    f"Không về được danh sách check-in (không thấy "
                    f"'{RID_RECEIVE_MENU}' lẫn '{RID_LIST}').\n\n"
                    f"Màn hình đang hiện: {self._describe(xml)}"
                )
            self._poll()

    @bounded_step
    def _search_and_open(self, bill: str) -> str:
        """
        Gõ mã rồi chờ danh sách lọc còn đúng một thẻ khớp.

        Khớp cả `tvSessionCode` lẫn `tvAddInfo` vì ô tìm kiếm nhận cả mã check-in
        (`CKSIRVIN89HN210210`) lẫn mã nhập kho (`IRVIN89HN210`) - người dùng điền
        cái nào vào Excel cũng chạy được.
        """
        self._log(f"[{bill}] tìm phiếu check-in")
        # Gõ xong Enter là app tra luôn (đã xác nhận trên máy thật) - ô tìm kiếm
        # có nút CHECKIN nhưng không cần bấm tới.
        self._type(bill)

        deadline = time.monotonic() + self.config.step_timeout
        wanted = normalize_match_text(bill)
        while True:
            xml = self._dump(deadline)

            # Mã chưa có phiên: app hỏi có tạo phiên mới không.
            if first_with_id(xml, RID_CONFIRM_ACCEPT) and first_with_id(xml, RID_CONFIRM_CANCEL):
                return self._handle_missing_session(bill, xml)

            # Enter có thể đưa thẳng vào phiên, không qua thẻ nào - lúc đó không
            # còn gì để bấm, đi tiếp luôn.
            if first_with_id(xml, RID_COUNTER):
                code = (first_with_id(xml, RID_SESSION_CODE) or {}).get("text", "")
                if not code or wanted not in normalize_match_text(code):
                    raise self._stop(f"[{bill}] đã vào màn hình quét nhưng mã phiên chưa khớp; cần đối chiếu.")
                self._scan_xml = xml
                self._log(f"[{bill}] vào thẳng phiên {code or '(không đọc được mã)'}")
                return code

            buttons = nodes_with_id(xml, RID_START)
            labels = nodes_with_id(xml, RID_SESSION_CODE) + nodes_with_id(xml, RID_ADD_INFO)
            matching = [n for n in labels if wanted in normalize_match_text(n.get("text", ""))]
            if len(buttons) == 1 and matching and not self._search_loading(xml):
                break

            if time.monotonic() >= deadline:
                if not buttons:
                    raise self._stop(
                        f"Không tìm thấy phiếu check-in '{bill}' trong danh sách, "
                        f"cũng không thấy hộp thoại tạo phiên.\n\n"
                        f"Màn hình đang hiện: {self._describe(xml)}"
                    )
                if len(buttons) == 1:
                    # Lọc còn đúng một thẻ nhưng không nhãn nào chứa mã vừa gõ:
                    # có thể mã nằm ở ô khác. Thà dừng và nói rõ thẻ đó là gì.
                    raise self._stop(
                        f"Mã '{bill}' lọc ra đúng một phiếu nhưng không nhãn nào "
                        f"trên thẻ chứa mã đó - không dám bấm.\n\n"
                        f"Thẻ đang hiện: {self._describe(xml)}"
                    )
                raise self._stop(
                    f"Mã '{bill}' lọc ra {len(buttons)} phiếu khớp "
                    f"({len(matching)} nhãn đúng mã) - không dám bấm vì có thể "
                    f"mở nhầm phiếu."
                )
            self._poll()

        node = first_with_id(xml, RID_SESSION_CODE)
        session_code = (node or {}).get("text", "")
        self._log(f"[{bill}] vào phiếu {session_code}")
        self._tap_id(xml, RID_START)
        return session_code

    def _handle_missing_session(self, bill: str, xml: str) -> str:
        """
        Xử lý hộp thoại "chưa có phiên check-in, có tạo không?".

        Bấm Xác nhận là tạo một phiên mới trong hệ thống - giao dịch thật, không
        phải chỉ mở màn hình. Nên đây là chỗ duy nhất trong cả luồng mà bot hỏi ý
        trước bằng một tùy chọn riêng, thay vì tự quyết.
        """
        title = (first_with_id(xml, RID_CONFIRM_TITLE) or {}).get("text", "").strip()
        normalized = normalize_match_text(title)
        if not all(token in normalized for token in ("check-in", "tao phien", "nhan hang")):
            raise self._stop(f"[{bill}] hộp thoại tạo phiên chưa biết nội dung: {title}")

        if not self.config.create_missing_session:
            self._tap_id(xml, RID_CONFIRM_CANCEL)
            raise self._stop(
                f"Mã '{bill}' chưa có phiên check-in nào - app hỏi có tạo phiên "
                f"mới không.\n\nĐã bấm 'Quay lại' và dừng, vì tạo phiên là một "
                f"giao dịch thật. Bật 'Tự tạo phiên check-in nếu chưa có' trong "
                f"Cấu hình nếu muốn bot tự xác nhận.\n\nApp hỏi: {title}"
            )

        self._log(f"[{bill}] chưa có phiên - tạo mới ({title})")
        self._tap_id(xml, RID_CONFIRM_ACCEPT)
        return f"(tạo mới) {bill}"

    def _scan_serials(self, bill: str, rows: list[dict]) -> list[SerialResult]:
        xml, self._scan_xml = self._scan_xml, ""
        if not xml:
            xml = self._wait_for_scan_screen(bill)

        counter = parse_counter((first_with_id(xml, RID_COUNTER) or {}).get("text", ""))
        if not counter:
            raise self._stop("Không đọc được bộ đếm trước khi quét serial.")
        picked = counter[0]
        self._counter_total = counter[1]
        self._scan_xml = xml
        if picked:
            raise self._stop("Phiên đã có serial; cần đối chiếu trước khi chạy lại.")

        # Thẻ check-in không hiện số lượng sản phẩm như thẻ picking, nên chỗ duy
        # nhất đối chiếu được là tổng của '0/N' - vẫn kịp, vì lúc này chưa quét
        # serial nào.
        if self.config.check_expected_count and counter and counter[1] != len(rows):
            raise self._stop(
                f"Phiếu '{bill}': app báo cần {counter[1]} sản phẩm nhưng Excel "
                f"có {len(rows)} serial. Dừng trước khi quét - sửa file rồi chạy lại."
            )

        results = []
        for index, row in enumerate(rows, start=1):
            if self._should_stop():
                raise PickStopped("Người dùng bấm Dừng.")

            serial = row["value"]
            self._log(f"[{bill}] {index}/{len(rows)} quét {serial}")
            if self._wait_if_paused():
                self._scan_xml = self._wait_for_scan_screen(bill)
            xml, self._scan_xml = self._scan_xml, ""
            operation = self._begin_operation("scan", row["row"], {"serial": serial, "previous": picked})
            self._scan_deadline = time.monotonic() + self.config.step_timeout
            try:
                self._type(serial, xml, self._scan_deadline)
            except AdbUnavailableError:
                self._log(f"[{bill}] ADB mất phản hồi; đối chiếu serial, không gửi lại")
            picked = self._wait_for_pick(bill, serial, picked, last=index == len(rows))
            result = SerialResult(row=row["row"], serial=serial, status="OK")
            results.append(result)
            self.last_partial.append(result)
            self._record_scan(result, operation)
        return results

    @bounded_step
    def _wait_for_scan_screen(self, bill: str) -> str:
        """
        Chờ màn hình quét serial hiện ra sau khi bấm Nhận hàng.

        Luồng nhận hàng chưa được dò hết: nếu app chèn thêm bước ở giữa (quét
        thùng, chọn sản phẩm, hộp thoại trợ lý...) thì đoán bừa là gửi serial vào
        nhầm ô của một phiên nhận hàng thật. Nên hết giờ là dừng và **liệt kê
        những gì đang hiện** - đủ để bổ sung bước còn thiếu mà không phải dò lại
        từ đầu.
        """
        deadline = time.monotonic() + self.config.step_timeout
        while True:
            xml = self._dump(deadline)

            if first_with_id(xml, RID_COUNTER):
                return xml

            if first_with_id(xml, RID_CONFIRM_ACCEPT):
                # Hộp thoại xác nhận thứ hai - chưa gặp trên máy thật, nên không
                # tự bấm: nó có thể đang hỏi một chuyện hoàn toàn khác.
                title = (first_with_id(xml, RID_CONFIRM_TITLE) or {}).get("text", "").strip()
                raise self._stop(
                    f"[{bill}] app hỏi thêm một lần nữa sau khi tạo phiên: "
                    f"{title or dialog_message(xml)}\n\nBot không tự bấm hộp thoại "
                    f"chưa biết nội dung."
                )

            if find_dismiss_button(xml) is not None:
                raise self._stop(f"[{bill}] app báo lỗi khi mở phiếu: {dialog_message(xml)}")

            if time.monotonic() >= deadline:
                raise self._stop(
                    f"[{bill}] bấm Nhận hàng xong nhưng không thấy màn hình quét "
                    f"serial (không có '{RID_COUNTER}').\n\n"
                    f"Màn hình đang hiện: {self._describe(xml)}"
                )
            self._poll()

    @bounded_step
    def _finish_session(self, bill: str) -> None:
        deadline = time.monotonic() + self.config.step_timeout
        xml = self._pending_finish_xml
        self._pending_finish_xml = ""
        while True:
            if self._should_stop():
                raise PickStopped("Người dùng bấm Dừng.")
            if time.monotonic() >= deadline:
                raise self._stop(f"[{bill}] quét đủ serial nhưng không về được danh sách check-in.")
            if not xml:
                xml = self._dump(deadline)
            back_home = first_with_id(xml, RID_RECEIVE_MENU)
            back_list = first_with_id(xml, RID_LIST) and first_with_id(xml, RID_INPUT)
            if back_home or back_list:
                if not self._completion_seen:
                    raise self._stop(f"[{bill}] chưa có bằng chứng hoàn tất phiếu nhập.")
                self._at_search_xml = xml if back_list else ""
                return
            button = find_dismiss_button(xml)
            if button:
                kind = classify_session_dialog(xml, "inbound")
                if kind != "complete":
                    raise self._stop(f"[{bill}] hộp thoại {kind}: {dialog_message(xml)}")
                self._completion_seen = True
                self._log(f"[{bill}] kết thúc phiếu: {dialog_message(xml)}")
                self._tap_id(xml, button["resource_id"])
            xml = ""
            self._poll()
