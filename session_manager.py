"""
session_manager.py
Checkpoints run progress to disk so a crashed or closed session can be
resumed instead of re-running everything from row 1.
"""
import json
import os
from datetime import datetime

SESSION_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SerialBot")
SESSION_PATH = os.path.join(SESSION_DIR, "session.json")


def save_session(
    excel_path: str,
    done_rows: list[int],
    done: int,
    success: int,
    error: int,
    unknown: int,
    done_bills: list[str] | None = None,
    mode: str = "serial",
):
    """
    mode="pick" kèm done_bills: chế độ xuất kho tính theo vận đơn, không theo
    dòng. Dừng giữa chừng là còn một phiên đang mở trên máy ảo, nên lần sau phải
    biết chính xác đã xong tới vận đơn nào để không mở lại đơn đã xuất.
    """
    os.makedirs(SESSION_DIR, exist_ok=True)
    data = {
        "excel_path": excel_path,
        "done_rows": sorted(set(done_rows)),
        "done": done,
        "success": success,
        "error": error,
        "unknown": unknown,
        "mode": mode,
        "done_bills": list(done_bills or []),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    tmp_path = SESSION_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, SESSION_PATH)


def load_session(excel_path: str) -> dict | None:
    """Return the saved session dict if it matches this excel_path, else None."""
    if not os.path.isfile(SESSION_PATH):
        return None
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    if os.path.normcase(os.path.abspath(data.get("excel_path", ""))) != os.path.normcase(
        os.path.abspath(excel_path)
    ):
        return None
    return data


def clear_session():
    try:
        os.remove(SESSION_PATH)
    except OSError:
        pass
