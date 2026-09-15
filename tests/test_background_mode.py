import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

import automation_backend
from automation_backend import (
    AdbBackend,
    AdbUnavailableError,
    PyAutoGuiBackend,
    adb_answers,
    looks_like_adb_failure,
)
from bot_worker import BotWorker, SerialItem


# --- ldconsole exits 0 even when the device is gone, so output must be read ---

def test_detects_device_not_found_reported_on_stdout():
    assert looks_like_adb_failure("adb.exe: device 'emulator-5554' not found\n\n") is True


def test_detects_no_devices_message():
    assert looks_like_adb_failure("error: no devices/emulators found") is True


def test_normal_command_output_is_not_a_failure():
    assert looks_like_adb_failure("ok\n") is False


def test_empty_output_is_not_a_failure():
    """`input text` succeeds with no output at all."""
    assert looks_like_adb_failure("") is False


def test_screen_dump_containing_not_found_is_not_an_adb_failure():
    """'Product not found' is a real app error keyword - it must not be mistaken
    for adb being unreachable, or genuine app errors would be reported as UNKNOWN."""
    dump = '<hierarchy><node text="Product not found" resource-id="msg"/></hierarchy>'
    assert looks_like_adb_failure(dump) is False


class FakeAdbClient:
    """Stands in for AdbClient; run_shell returns None to simulate a dead device."""

    def __init__(self, responses=None, instance_name="LDPlayer"):
        self.instance_name = instance_name
        self.responses = responses if responses is not None else {}
        self.calls = []

    def run_shell(self, command, timeout=None):
        self.calls.append(command)
        return self.responses.get("default", "")


class DeadAdbClient(FakeAdbClient):
    def run_shell(self, command, timeout=None):
        self.calls.append(command)
        return None


def make_worker(**overrides):
    kwargs = dict(
        serials=[SerialItem(row=2, value="ABC123")],
        instance_name="LDPlayer",
        delay_seconds=0.0,
        verify_result=False,
        error_keywords="",
    )
    kwargs.update(overrides)
    return BotWorker(**kwargs)


# --- lần hỏi ADB đầu tiên hay rơi vào lúc adb server đang khởi động ---------

class ColdStartAdbClient(FakeAdbClient):
    """Hụt lần đầu rồi trả lời bình thường - đúng kiểu adb server nguội."""

    def run_shell(self, command, timeout=None):
        self.calls.append(command)
        return None if len(self.calls) == 1 else "ok\n"


def test_probe_retries_once_after_a_cold_start_miss(monkeypatch):
    monkeypatch.setattr(automation_backend, "ADB_PROBE_RETRY_SECONDS", 0.0)
    client = ColdStartAdbClient()

    assert adb_answers(client) is True
    assert len(client.calls) == 2


def test_probe_gives_up_when_the_device_is_really_gone(monkeypatch):
    monkeypatch.setattr(automation_backend, "ADB_PROBE_RETRY_SECONDS", 0.0)
    client = DeadAdbClient()

    assert adb_answers(client) is False


def test_backend_is_available_survives_a_cold_start(monkeypatch):
    """Không có lớp thử lại này thì background mode chặn phiên chạy với lý do sai."""
    monkeypatch.setattr(automation_backend, "ADB_PROBE_RETRY_SECONDS", 0.0)

    assert AdbBackend(ColdStartAdbClient()).is_available() is True


def test_run_time_failures_do_not_go_through_the_probe():
    """
    Lớp thử lại chỉ dành cho lần dò đầu phiên. Lệnh trong lúc chạy mà cũng thử
    lại thì mỗi dòng chậm gấp đôi khi máy ảo chết thật, và bộ đếm hỏng-liên-tiếp
    không bao giờ chạm ngưỡng dừng.
    """
    client = DeadAdbClient()
    with pytest.raises(AdbUnavailableError):
        AdbBackend(client).type_serial("ABC123")

    # Có gọi lại một lần, nhưng là đường lui gộp-phím -> tách-phím, không phải
    # dò lại thiết bị: mọi lệnh đều là lệnh gõ thật, không có "echo ok" nào.
    assert all("input text" in call for call in client.calls)


# --- AdbBackend must not swallow delivery failures -------------------------

def test_adb_backend_raises_when_device_unreachable():
    backend = AdbBackend(DeadAdbClient())
    with pytest.raises(AdbUnavailableError):
        backend.type_serial("ABC123")


def test_adb_backend_raises_on_failed_enter():
    backend = AdbBackend(DeadAdbClient())
    with pytest.raises(AdbUnavailableError):
        backend.send_enter("enter")


def test_adb_backend_succeeds_on_empty_stdout():
    """`input text` returns no output on success - empty string must not read as failure."""
    backend = AdbBackend(FakeAdbClient())
    backend.type_serial("ABC123")
    backend.send_enter("enter")


def test_adb_backend_send_enter_none_mode_sends_nothing():
    client = FakeAdbClient()
    AdbBackend(client).send_enter("none")
    assert client.calls == []


# --- Background mode must never fall back to the keyboard ------------------

def test_background_mode_refuses_to_fall_back(qapp):
    worker = make_worker(background_mode=True)
    worker.adb_client = DeadAdbClient()

    errors = []
    worker.error_occurred.connect(errors.append)

    assert worker._select_backend() is False
    assert worker.backend is None
    assert errors and "Background mode" in errors[0]


def test_non_background_mode_does_fall_back(qapp):
    worker = make_worker(background_mode=False, prefer_adb_input=True)
    worker.adb_client = DeadAdbClient()

    assert worker._select_backend() is True
    assert isinstance(worker.backend, PyAutoGuiBackend)


def test_background_mode_forces_adb_input_on(qapp):
    worker = make_worker(background_mode=True, prefer_adb_input=False)
    assert worker.prefer_adb_input is True


def test_background_mode_uses_adb_when_available(qapp):
    worker = make_worker(background_mode=True)
    worker.adb_client = FakeAdbClient()

    assert worker._select_backend() is True
    assert isinstance(worker.backend, AdbBackend)


# --- A dead device must not be reported as a successful paste --------------

def test_dead_device_reports_unknown_not_ok(qapp):
    worker = make_worker(background_mode=True, verify_result=False)
    worker.adb_client = DeadAdbClient()
    worker.backend = AdbBackend(worker.adb_client)

    result = worker._process_serial(2, "ABC123")

    assert result["status"] == "UNKNOWN"
    assert result["adb_failed"] is True


def test_run_aborts_immediately_when_background_adb_dead(qapp):
    worker = make_worker(background_mode=True)
    worker.adb_client = DeadAdbClient()

    results = []
    finished = []
    worker.result_ready.connect(results.append)
    worker.finished_all.connect(lambda: finished.append(True))

    worker.run()  # run() directly, not start(), to stay synchronous

    assert results == []      # no serial was attempted
    assert finished == [True]  # but the GUI still gets told the run ended
