"""
pick_worker.py
Thread chạy hai luồng theo phiên: xuất kho theo mã OR (pick_runner.py) và nhập
hàng theo mã check-in (inbound_runner.py).

Khác BotWorker ở hai chỗ quan trọng:

- Chỉ chạy qua ADB. Luồng cũ có thể lui về gõ bàn phím khi ADB hỏng, nhưng ở đây
  giữa chừng một phiên mà gõ nhầm vào cửa sổ Windows thì hỏng đơn hàng thật,
  nên thà không chạy.
- Gặp lỗi là dừng cả phiên chạy, không có "bỏ qua mã này rồi chạy tiếp". Dừng
  xong app còn kẹt trong phiên đang dở, phải có người dọn rồi mới chạy lại được
  - nên worker báo rõ chỗ dừng thay vì âm thầm đi tiếp.
  Ngoại lệ duy nhất: OrNotFoundError (gõ mã OR nhưng không lọc ra thẻ nào). Lúc
  đó chưa mở phiên nên bỏ qua an toàn - worker ghi lỗi cho mã đó rồi gõ mã OR
  kế tiếp thay vì dừng cả lượt chạy.
"""
import logging
import threading
import time
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from actions import REASON_NOT_FOUND
from automation_backend import (
    LDPLAYER_DIR_ENV,
    AdbBackend,
    AdbClient,
    AdbUnavailableError,
    find_ldplayer_tool,
)
from pick_runner import OrNotFoundError, PickConfig, PickRunner, PickStopped

logger = logging.getLogger(__name__)


class PickWorker(QThread):
    """
    Signals:
        progress(int done_bills, int total_bills)
        bill_started(str bill, int serial_count)
        log_entry(int row, str serial, str status, str message)
        result_ready(dict)      # từng serial, để ghi vào Excel
        bill_done(dict)         # tóm tắt một phiên
        step_info(str)          # tiến trình trong một phiên, cho thanh trạng thái
        stats_update(int done, int success, int error, int unknown)
        stopped(str message, str screenshot_path)
        finished_all()
    """

    progress = pyqtSignal(int, int)
    bill_started = pyqtSignal(str, int)
    log_entry = pyqtSignal(int, str, str, str)
    result_ready = pyqtSignal(dict)
    bill_done = pyqtSignal(dict)
    step_info = pyqtSignal(str)
    # Cùng chữ ký với BotWorker.stats_update để dùng lại nguyên phần đếm của
    # giao diện. Thiếu tín hiệu này thì khung STATS đứng im ở 0/N suốt lượt chạy.
    stats_update = pyqtSignal(int, int, int, int)
    stopped = pyqtSignal(str, str)
    finished_all = pyqtSignal()

    def __init__(
        self,
        groups: list[dict],
        instance_name: str,
        config: PickConfig | None = None,
        screenshot_dir: str = "screenshots",
        parent=None,
        runner_cls=PickRunner,
        journal=None,
        run_id=None,
    ):
        super().__init__(parent)
        self.groups = groups
        self.instance_name = instance_name
        self.config = config or PickConfig()
        self.screenshot_dir = screenshot_dir
        # Xuất kho và nhập hàng chỉ khác nhau ở chuỗi màn hình; phần khung -
        # kết nối ADB, dừng cả phiên khi lỗi, báo lại serial đã vào - dùng chung.
        self.runner_cls = runner_cls

        self.adb_client = AdbClient(instance_name)
        self.backend = None
        self.runner: PickRunner | None = None

        self._stop_flag = threading.Event()
        self.adb_client.should_stop = self._stop_flag.is_set
        # set = đang chạy, clear = đang tạm dừng (giống BotWorker).
        self._pause_event = threading.Event()
        self._pause_event.set()
        self.done_bills: list[str] = []
        # Đếm theo serial chứ không theo mã OR: khung STATS lấy tổng là tổng số
        # serial, nên đếm theo mã thì thanh "Processed" không bao giờ chạy tới nơi.
        self._done = 0
        self._success = 0
        self._error = 0
        self.journal = journal
        self.run_id = run_id
        self.completion_state = "failed"
        self.pause_seconds = 0.0

    def stop(self):
        self._stop_flag.set()
        # Đang tạm dừng mà bấm Dừng thì phải thoát được, không kẹt trong lúc chờ.
        self._pause_event.set()

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def _wait_if_paused(self) -> None:
        """
        Đứng lại nếu người dùng bấm Tạm dừng.

        Chỉ được gọi ở **điểm an toàn**: giữa hai mã OR, và giữa hai serial -
        những chỗ không có đồng hồ đếm ngược nào đang chạy. Chặn ở trong vòng
        chờ màn hình thì `step_timeout` vẫn trôi trong lúc dừng, tạm dừng một
        phút là tỉnh dậy với một lỗi 'chờ quá 15s' bịa ra.

        Phiên đang mở dở trên app thì cứ nằm im chờ - khác hẳn Dừng hẳn, không
        có gì phải dọn.
        """
        if self._pause_event.is_set():
            return
        pause_started = time.monotonic()
        self.step_info.emit("Đã tạm dừng - bấm Resume để chạy tiếp.")
        while not self._pause_event.is_set():
            if self._stop_flag.is_set():
                return
            self._pause_event.wait(0.2)
        self.step_info.emit("Chạy tiếp.")
        self.pause_seconds += time.monotonic() - pause_started
        if getattr(self, "runner", None):
            self.runner.pause_seconds = self.pause_seconds
        return True

    # ------------------------------------------------------------------ chạy

    def run(self):
        try:
            self._run()
        except Exception as exc:
            logger.exception("Pick worker failed run_id=%s", self.run_id)
            self._emit_stopped(f"Không hoàn tất phiên: {exc}", "")

    def _run(self):
        if not self._connect():
            return

        self.runner = self.runner_cls(
            self.adb_client,
            self.backend,
            self.config,
            screenshot_dir=self.screenshot_dir,
            on_log=self.step_info.emit,
            should_stop=self._stop_flag.is_set,
            wait_if_paused=self._wait_if_paused,
            journal=self.journal,
            run_id=self.run_id,
        )

        total = len(self.groups)
        started_at = time.monotonic()
        logger.info(
            "Pick run started: %d phiên, %d serial, instance=%s",
            total, sum(len(g["rows"]) for g in self.groups), self.instance_name,
        )

        for index, group in enumerate(self.groups):
            # Giữa hai mã OR là điểm dừng sạch nhất: không có phiên nào đang mở.
            if self._wait_if_paused():
                self.runner._at_search_xml = ""
            if self._stop_flag.is_set():
                self._emit_stopped("Người dùng bấm Dừng.", "")
                return

            bill = group["bill"]
            rows = group["rows"]
            ref = group.get("ref", "")
            self.bill_started.emit(bill, len(rows))
            if self.journal and self.run_id:
                self.journal.begin(self.run_id, "bill", bill=bill, payload={"ref": ref, "rows": rows})

            try:
                outcome = self.runner.run_bill(bill, rows, ref)
            except OrNotFoundError as e:
                # Chưa mở phiên - màn hình vẫn ở "Tìm theo mã OR" nên bỏ qua an
                # toàn: ghi lỗi cho mã này rồi sang mã OR tiếp theo.
                logger.warning("Pick run: khong tim thay ma OR '%s': %s", bill, e.message)
                self._report_not_found(bill, rows, ref, e.message)
                self.progress.emit(index + 1, total)
                continue
            except PickStopped as e:
                self._report_partial(bill, rows, ref)
                self._emit_stopped(e.message, e.screenshot_path or "")
                return
            except AdbUnavailableError as e:
                # Lọt tới đây nghĩa là phiên đã mở: hụt lúc chưa mở thì runner tự
                # chờ và làm lại. Phím gõ hụt có thể vẫn tới app trễ, nên không
                # tự gõ lại - báo rõ để người kiểm tra phiên đang dở.
                logger.warning("Pick run: ADB lost inside the session of '%s': %s", bill, e)
                self._report_partial(bill, rows, ref)
                self._emit_stopped(
                    f"ADB mất phản hồi giữa phiên của mã '{bill}' ({e}).\n\n"
                    "Phiên trên app có thể đang dở: kiểm tra và hoàn tất/đóng phiên "
                    "trên app rồi bấm Start để chạy tiếp.",
                    "",
                )
                return
            except Exception as e:                       # noqa: BLE001
                logger.exception("Pick run crashed on '%s'", bill)
                self._report_partial(bill, rows, ref)
                self._emit_stopped(f"Lỗi không lường trước ở mã '{bill}': {e}", "")
                return

            for serial in outcome.serials:
                self._emit_result(
                    serial.row, serial.serial, bill, ref,
                    serial.status, serial.message or "Đã xuất",
                )
                self.log_entry.emit(serial.row, serial.serial, serial.status, serial.message or "Đã xuất")

            self.done_bills.append(bill)
            bill_result = {
                "bill": bill,
                "ref": outcome.ref or ref,
                "session_code": outcome.session_code,
                "expected": outcome.expected,
                "picked": outcome.picked,
                "status": outcome.status,
                "message": outcome.message,
            }
            if self.journal and self.run_id:
                self.journal.complete_bill(self.run_id, bill_result)
            self.bill_done.emit(bill_result)
            self.progress.emit(index + 1, total)

        self.completion_state = "complete"
        logger.info(
            "Pick run finished: %d/%d phiên trong %.0fs",
            len(self.done_bills), total, time.monotonic() - started_at,
        )
        self.finished_all.emit()

    # -------------------------------------------------------------- tiện ích

    def _connect(self) -> bool:
        backend = AdbBackend(self.adb_client)
        if backend.is_available():
            self.backend = backend
            return True

        logger.error("Pick run: ADB không phản hồi trên '%s'", self.instance_name)

        # Máy mới hay chết ở đây nhất: LDPlayer cài chỗ khác nên không tìm thấy
        # adb.exe. Nói thẳng ra cách sửa thay vì để người dùng đoán.
        if find_ldplayer_tool("adb.exe") is None:
            hint = (
                "Không tìm thấy adb.exe của LDPlayer trên máy này.\n\n"
                f"Nếu LDPlayer cài ở chỗ khác thường, đặt biến môi trường "
                f"{LDPLAYER_DIR_ENV} trỏ tới thư mục chứa adb.exe "
                f"(ví dụ D:\\LDPlayer\\LDPlayer9) rồi mở lại app."
            )
        else:
            hint = (
                "Kiểm tra: LDPlayer đã bật xong chưa, tên máy ảo có đúng không "
                "(bấm Refresh để lấy danh sách)."
            )

        self._emit_stopped(
            f"Không kết nối được ADB tới máy ảo '{self.instance_name}'.\n\n"
            "Luồng xuất kho chỉ chạy qua ADB - không có đường lui gõ bàn phím, "
            "vì gõ nhầm vào cửa sổ khác giữa một phiên pick là hỏng đơn thật.\n\n"
            f"{hint}",
            "",
        )
        return False

    def _emit_result(self, row, serial, bill, ref, status, message, screenshot="", reason=""):
        """
        Một chỗ duy nhất dựng dict kết quả và cập nhật bộ đếm.

        Giao diện đổ thẳng dict này vào ResultWriter, mà writer đòi cả
        `response_text` lẫn `screenshot_path`. Thiếu một khóa là KeyError nuốt
        trọn dòng đó - phiên chạy trông vẫn xanh nhưng file Excel không có gì.
        Gom về một hàm để ba chỗ phát tín hiệu không thể lệch nhau nữa.
        """
        record = {
            "row": row,
            "serial": serial,
            "bill": bill,
            "ref": ref,
            "status": status,
            "verification": "confirmed",
            "message": message,
            "response_text": message,
            "screenshot_path": screenshot,
            "reason": reason,
            "time": datetime.now().strftime("%H:%M:%S"),
        }
        if self.journal and self.run_id:
            self.journal.record_result(self.run_id, record)
        self.result_ready.emit(record)

        self._done += 1
        if status == "OK":
            self._success += 1
        else:
            self._error += 1
        self.stats_update.emit(self._done, self._success, self._error, 0)

    def _report_partial(self, bill: str, rows: list[dict], ref: str = ""):
        """
        Phiên dừng giữa chừng: ghi lại những serial đã vào để người dùng biết
        phiên trên máy ảo đang dở tới đâu mà dọn.
        """
        picked = getattr(self.runner, "last_partial", None)
        if not picked:
            return
        for serial in picked:
            self._emit_result(
                serial.row, serial.serial, bill, ref,
                "OK", "Đã xuất trước khi dừng",
            )

    def _report_not_found(self, bill: str, rows: list[dict], ref: str, message: str):
        """
        Mã OR không tìm thấy: ghi ERROR cho mọi dòng Excel thuộc mã này rồi cho
        biết phiên đó coi như xong (lỗi), để tiến trình và Excel không lệch với
        các mã chạy được.
        """
        for row in rows:
            self._emit_result(
                row["row"], row["value"], bill, ref, "ERROR", message,
                reason=REASON_NOT_FOUND,
            )
            self.log_entry.emit(row["row"], row["value"], "ERROR", message)

        bill_result = {
            "bill": bill,
            "ref": ref,
            "session_code": "",
            "expected": len(rows),
            "picked": 0,
            "status": "ERROR",
            "message": message,
        }
        if self.journal and self.run_id:
            self.journal.complete_bill(self.run_id, bill_result)
        self.bill_done.emit(bill_result)

    def _emit_stopped(self, message: str, screenshot_path: str):
        self.completion_state = "stopped"
        logger.error("Pick run stopped: %s", message)
        self.stopped.emit(message, screenshot_path)
        self.finished_all.emit()
