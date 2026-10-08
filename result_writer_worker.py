"""One QThread owns the workbook for the entire run; callers enqueue records."""
import logging
import queue
import threading
import time
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal
from excel_writer import ResultWriter
from telemetry import CODE_VERSION
import json
import copy
from excel_writer import write_report, write_pick_report

logger = logging.getLogger(__name__)


class ResultWriterWorker(QThread):
    save_status = pyqtSignal(bool, str)
    flushed = pyqtSignal(bool, str)

    def __init__(self, path, data_sheet=None, result_sheet=None, parent=None, run_id=None):
        super().__init__(parent)
        self.path = path
        self.run_id = run_id
        self.data_sheet = data_sheet
        self.sheet_name = result_sheet or f"Ket qua {datetime.now():%Y%m%d_%H%M%S}"
        self._queue = queue.Queue()
        self._busy = threading.Event()
        self._busy.set()
        self._ending = False
        self.saved = False

    @property
    def busy(self):
        return self._busy.is_set()

    def add_record(self, record):
        self.saved = False
        self._queue.put(("record", dict(record)))

    def add_result(self, row, serial, status, response_text, screenshot_path, reason="", verification="unverified"):
        self.add_record(dict(row=row, serial=serial, status=status, response_text=response_text,
                             screenshot_path=screenshot_path, reason=reason, verification=verification))

    def add_cell(self, row, column, value):
        self.saved = False
        self._queue.put(("cell", (row, column, value)))

    def save(self):
        self._busy.set()
        self._queue.put(("save", None))

    def finalize(self):
        if not self._ending:
            self._ending = True
            self._busy.set()
            self._queue.put(("finish", None))

    def run(self):
        writer = None
        last_save = time.monotonic()
        try:
            writer = ResultWriter(self.path, self.data_sheet, save_every=10**9,
                                  result_sheet=self.sheet_name, save_initial=False, auto_save=False)
            self.sheet_name = writer.sheet_name
            self._busy.clear()

            while True:
                try:
                    command, payload = self._queue.get(timeout=0.2)
                except queue.Empty:
                    if writer._pending and time.monotonic() - last_save >= 30:
                        command, payload = "save", None
                    else:
                        continue
                self._busy.set()
                if command == "record":
                    self.saved = False
                    writer.add_result(payload["row"], payload.get("serial", ""), payload["status"],
                                      payload.get("response_text", ""), payload.get("screenshot_path"),
                                      payload.get("reason", ""), payload.get("verification", "unverified"))
                    for column, value in payload.get("cell_writes", {}).items():
                        writer.add_cell(payload["row"], column, value)
                elif command == "cell":
                    self.saved = False
                    writer.add_cell(*payload)
                if command in ("save", "finish") or writer._pending >= 50 or (
                        writer._pending and time.monotonic()-last_save >= 30):
                    started = time.monotonic()
                    try:
                        writer.finalize()
                        self.saved = True
                        message = f"Đã lưu Excel: {self.sheet_name}"
                    except Exception as exc:
                        self.saved = False
                        message = f"Chưa lưu Excel: {exc}"
                        logger.exception("Excel save failed; durable journal retained")
                    logger.info("Excel timing: save=%.0fms saved=%s", (time.monotonic()-started)*1000, self.saved)
                    logger.info("PERF %s", json.dumps({"kind": "excel", "run_id": self.run_id,
                        "version": CODE_VERSION, "mode": "excel", "instance": "", "item": self.sheet_name,
                        "status": "OK" if self.saved else "ERROR",
                        "total_ms": round((time.monotonic()-started)*1000, 3)}))
                    last_save = time.monotonic()
                    self.save_status.emit(self.saved, message)
                    if command == "finish":
                        self.flushed.emit(self.saved, message)
                        return
                self._busy.clear()
        except Exception as exc:
            logger.exception("Workbook worker failed; durable journal retained")
            self.saved = False
            self.save_status.emit(False, f"Chưa lưu Excel: {exc}")
            self.flushed.emit(False, str(exc))
        finally:
            if writer:
                writer.wb.close()
            self._busy.clear()


class ReportWriterWorker(QThread):
    """Own a separate report workbook; capture a stable view of the results."""

    def __init__(self, path, records, summary, bills=None, inbound=False):
        super().__init__()
        self.path = path
        self.records = copy.deepcopy(records)
        self.summary = copy.deepcopy(summary)
        self.bills = copy.deepcopy(bills or [])
        self.inbound = inbound
        self.error = None

    def run(self):
        try:
            if self.bills:
                write_pick_report(self.path, self.bills, self.records, self.summary,
                    bills_sheet="Check-in" if self.inbound else "Ma OR",
                    bill_header="Ma check-in" if self.inbound else "Ma OR",
                    ref_header="Ma van don (MVD)")
            else:
                write_report(self.path, self.records, self.summary)
        except Exception as exc:
            self.error = str(exc)
            logger.exception("Report export failed")
