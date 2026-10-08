import pytest
from automation_backend import AdbBackend
from bot_worker import BotWorker, SerialItem
from tests.test_fast_input import FakeDevice, FOCUS_MAIN, FOCUS_DIALOG, DIALOG_SCREEN, make_worker


def test_fast_path_is_inferred_instead_of_confirmed(qapp):
    worker = make_worker(FakeDevice())
    worker._dialog_seen_by_dumpsys = True
    result = worker._process_serial(2, "A1")
    assert result["status"] == "OK"
    assert result["verification"] == "inferred"


def test_final_row_late_dialog_is_read_before_publishing(qapp, monkeypatch):
    device = FakeDevice()
    worker = make_worker(device, response_timeout=.08)
    worker._dialog_seen_by_dumpsys = True
    result = worker._process_serial(2, "A1")
    device.focus, device.xml = FOCUS_DIALOG, DIALOG_SCREEN
    pending = worker._finalize_pending((SerialItem(2, "A1"), result))
    assert pending[1]["status"] == "ERROR"
    assert pending[1]["verification"] == "confirmed"


def test_dialog_after_pause_corrects_an_already_published_row(qapp):
    worker = make_worker(FakeDevice())
    events = []
    worker.result_ready.connect(events.append)
    counters = {"done": 0, "success": 0, "error": 0, "unknown": 0}
    worker._publish(SerialItem(2, "A1"), {"status": "OK", "verification": "inferred", "message": "inferred"}, counters, 2)
    worker._pending_correction = (2, {"status": "ERROR", "response_text": "late error", "reason": "APP_ERROR"})
    assert worker._apply_correction(None) is None
    assert events[-1]["row"] == 2
    assert events[-1]["status"] == "ERROR"
    assert counters["done"] == 1
    assert counters["error"] == 1
