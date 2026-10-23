"""Durable run/result ledger. Excel is an export, never the recovery authority."""
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime

from paths import user_data_dir


def journal_path():
    return os.path.join(user_data_dir(), "run_journal.sqlite3")


def fingerprint(source, sheet, mode, selected, config):
    payload = {"source": os.path.normcase(os.path.abspath(source)), "sheet": sheet or "",
               "mode": mode, "selected": selected, "config": config}
    wire = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def _changes_nothing_on_app(op):
    """
    Thao tác chưa làm đổi gì trên app: mở đầu một mã, gõ vào ô nhập, hoặc chạm
    điều hướng (runner đánh dấu `harmless`). Quét serial (có dòng) và mọi lần
    chạm còn lại - nhất là nút mở phiên - thì không.

    Gõ vào ô nhập vẫn tính là vô hại vì mọi lần gõ trong phiên đều đi sau một
    lần chạm mở phiên, mà lần chạm đó đã đủ để cả mã bị coi là đã đụng vào app.
    """
    if op["row"] is not None:
        return False
    if op["kind"] in ("bill", "input"):
        return True
    if op["kind"] == "tap":
        try:
            return bool(json.loads(op["payload"]).get("harmless"))
        except (TypeError, ValueError, AttributeError):
            return False
    return False


class RunJournal:
    def __init__(self, path=None):
        self.path = path or journal_path()
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, source TEXT NOT NULL,
                mode TEXT NOT NULL, metadata TEXT NOT NULL, state TEXT NOT NULL,
                excel_saved INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS runs_fingerprint ON runs(fingerprint);
            CREATE TABLE IF NOT EXISTS operations (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL,
                row_no INTEGER, bill TEXT, payload TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS results (
                run_id TEXT NOT NULL, row_no INTEGER NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(run_id, row_no));
            CREATE TABLE IF NOT EXISTS bills (
                run_id TEXT NOT NULL, code TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(run_id, code));
        """)
        self._db.commit()

    def create_run(self, key, source, mode, metadata):
        run_id = uuid.uuid4().hex
        with self._lock, self._db:
            self._db.execute("INSERT INTO runs VALUES(?,?,?,?,?,'running',0,?)",
                             (run_id, key, os.path.normcase(os.path.abspath(source)), mode, json.dumps(metadata, default=str),
                              datetime.now().isoformat()))
        return run_id

    def latest(self, key):
        with self._lock:
            row = self._db.execute(
                "SELECT id,state,excel_saved,metadata FROM runs WHERE fingerprint=? "
                "ORDER BY created DESC LIMIT 1", (key,)).fetchone()
        return dict(zip(("id", "state", "excel_saved", "metadata"), row)) if row else None

    def get_run(self, run_id):
        with self._lock:
            row = self._db.execute("SELECT id,state,excel_saved,metadata FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(zip(("id", "state", "excel_saved", "metadata"), row)) if row else None

    def begin(self, run_id, kind, row=None, bill="", payload=None):
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO operations(run_id,kind,row_no,bill,payload,created) VALUES(?,?,?,?,?,?)",
                (run_id, kind, row, bill, json.dumps(payload or {}, ensure_ascii=False, default=str),
                 datetime.now().isoformat()))
            return cursor.lastrowid

    def resolve(self, operation, state="confirmed"):
        if operation is None:
            return
        with self._lock, self._db:
            self._db.execute("UPDATE operations SET state=? WHERE id=?", (state, operation))

    def pending(self, run_id):
        with self._lock:
            rows = self._db.execute(
                "SELECT id,kind,row_no,bill,payload FROM operations "
                "WHERE run_id=? AND state='pending' ORDER BY id", (run_id,)).fetchall()
        return [dict(zip(("id", "kind", "row", "bill", "payload"), row)) for row in rows]

    def pending_for_source(self, source):
        with self._lock:
            rows = self._db.execute(
                "SELECT o.id,o.kind,o.row_no,o.bill,o.payload,o.run_id FROM operations o "
                "JOIN runs r ON r.id=o.run_id WHERE r.source=? AND o.state='pending' ORDER BY o.id",
                (os.path.normcase(os.path.abspath(source)),)).fetchall()
        return [dict(zip(("id", "kind", "row", "bill", "payload", "run_id"), row)) for row in rows]

    def release_untouched(self, run_id=None, source=None):
        """
        Nhả khỏi danh sách chờ đối chiếu những mã chưa chạm tới phiên nào trên app.

        Dừng giữa chừng lúc mới gõ mã tìm kiếm (ADB hụt) để lại đúng hai thao
        tác 'bill' + 'input' ở trạng thái chờ. Chưa mở hay quét gì nên không có
        gì để đối chiếu; bắt người dùng "đối chiếu" thì mã đó bị ghi chưa xác
        minh và bỏ qua luôn dù app chưa hề thấy nó. Nhả ra thì lượt sau làm lại
        mã đó từ đầu.

        Chỉ cần một thao tác có thể đã đổi trạng thái app (chạm nút mở phiên,
        quét serial) là cả mã vẫn nằm lại chờ người xem. Trả về các mã đã nhả.
        """
        pending = self.pending(run_id) if run_id else self.pending_for_source(source)
        by_bill = {}
        for op in pending:
            by_bill.setdefault((op.get("run_id", run_id), op["bill"]), []).append(op)
        released, ids = [], []
        for (_, bill), ops in by_bill.items():
            if bill and all(_changes_nothing_on_app(op) for op in ops):
                released.append(bill)
                ids.extend(op["id"] for op in ops)
        if ids:
            with self._lock, self._db:
                self._db.executemany("UPDATE operations SET state='aborted' WHERE id=?", [(i,) for i in ids])
        return released

    def record_result(self, run_id, result, operation=None):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO results VALUES(?,?,?)",
                             (run_id, result["row"], json.dumps(result, ensure_ascii=False, default=str)))
            self._db.execute("UPDATE runs SET excel_saved=0 WHERE id=?", (run_id,))
            if operation is not None:
                self._db.execute("UPDATE operations SET state=? WHERE id=?",
                                 (result.get("verification", "unverified"), operation))

    def results(self, run_id):
        with self._lock:
            rows = self._db.execute("SELECT payload FROM results WHERE run_id=? ORDER BY row_no",
                                    (run_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def complete_bill(self, run_id, outcome):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO bills VALUES(?,?,?)",
                             (run_id, outcome["bill"], json.dumps(outcome, ensure_ascii=False)))
            self._db.execute("UPDATE operations SET state='confirmed' WHERE run_id=? AND bill=?",
                             (run_id, outcome["bill"]))

    def bills(self, run_id):
        with self._lock:
            rows = self._db.execute("SELECT payload FROM bills WHERE run_id=?", (run_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def set_state(self, run_id, state, excel_saved=None):
        with self._lock, self._db:
            self._db.execute("UPDATE runs SET state=? WHERE id=?", (state, run_id))
            if excel_saved is not None:
                self._db.execute("UPDATE runs SET excel_saved=? WHERE id=?", (int(excel_saved), run_id))

    def close(self):
        with self._lock:
            self._db.close()
