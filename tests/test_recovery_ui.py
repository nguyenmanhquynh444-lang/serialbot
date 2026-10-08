import threading
import time

import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QMessageBox
from openpyxl import Workbook

import bot_gui
import excel_writer
from bot_gui import BotGUI, MODE_SERIAL
from bot_worker import SerialItem


@pytest.fixture
def gui(tmp_path, monkeypatch):
    window = BotGUI()
    path = tmp_path / "source.xlsx"
    wb = Workbook()
    wb.active.append(["Serial"])
    wb.active.append(["S1"])
    wb.active.append(["S2"])
    wb.save(path)
    window.excel_path = str(path)
    monkeypatch.setattr(window, "_notify_finished", lambda *args: None)
    yield window
    if window.result_writer and window.result_writer.isRunning():
        window.result_writer.finalize()
        window.result_writer.wait(5000)
    window.workers = []
    window.close()


def selected():
    return [SerialItem(2, "S1"), SerialItem(3, "S2")]


def result():
    return {"row": 2, "serial": "S1", "status": "OK", "verification": "confirmed",
            "message": "accepted", "response_text": "accepted", "screenshot_path": None}


def test_resume_uses_selected_sheet_mode_data_and_config(gui, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    assert len(gui._prepare_journal(selected(), MODE_SERIAL)) == 2
    run = gui.run_id
    gui.journal.record_result(run, result())
    gui.journal.set_state(run, "stopped")
    remaining = gui._prepare_journal(selected(), MODE_SERIAL)
    assert [item.row for item in remaining] == [3]
    assert gui.run_id == run
    gui.sheet_combo.setCurrentText("Other")
    assert len(gui._prepare_journal(selected(), MODE_SERIAL)) == 2
    assert gui.run_id != run


def test_ambiguous_intention_is_never_replayed_automatically(gui, monkeypatch):
    gui._prepare_journal(selected(), MODE_SERIAL)
    run = gui.run_id
    gui.journal.begin(run, "serial", row=2, payload={"serial": "S1"})
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    assert gui._prepare_journal(selected(), MODE_SERIAL) is None
    assert len(gui.journal.pending(run)) == 1
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    remaining = gui._prepare_journal(selected(), MODE_SERIAL)
    assert [item.row for item in remaining] == [3]
    assert gui.journal.pending(run) == []
    assert gui.journal.results(run)[0]["status"] == "UNKNOWN"


def test_result_updates_replace_the_same_row_after_a_late_reply(gui):
    gui._on_result_ready(result())
    gui._on_result_ready({**result(), "status": "ERROR", "message": "late dialog"})
    assert len(gui.all_records) == 1
    assert gui.all_records[0]["status"] == "ERROR"


class SlowStop(QThread):
    completion_state = "stopped"
    pause_seconds = 0
    def __init__(self):
        super().__init__()
        self.requested = threading.Event()
    def run(self):
        self.requested.wait(2)
        time.sleep(.05)
    def stop(self):
        self.requested.set()


def test_stop_does_not_reenable_start_before_thread_exit(gui):
    worker = SlowStop()
    gui.workers = [worker]
    worker.start()
    try:
        gui._on_stop()
        assert not gui.start_btn.isEnabled()
        assert worker.isRunning()
        assert worker.wait(2000)
        gui._on_all_finished()
        assert gui.start_btn.isEnabled()
    finally:
        worker.stop()
        worker.wait(2000)


def test_start_waits_for_final_excel_flush(gui, monkeypatch, qapp):
    gui._prepare_journal(selected(), MODE_SERIAL)
    gui.journal.record_result(gui.run_id, result())
    gui.all_records = [result()]
    entered, release = threading.Event(), threading.Event()
    original = excel_writer.atomic_save
    def blocked(workbook, path):
        entered.set()
        assert release.wait(3)
        original(workbook, path)
    monkeypatch.setattr(excel_writer, "atomic_save", blocked)
    assert gui._prepare_result_writer()
    gui.result_writer.add_record(result())
    worker = SlowStop()
    worker.completion_state = "complete"
    gui.workers = [worker]
    try:
        gui._on_all_finished()
        assert entered.wait(2)
        assert not gui.start_btn.isEnabled()
        release.set()
        assert gui.result_writer.wait(5000)
        qapp.processEvents()
        assert gui.start_btn.isEnabled()
        assert gui.journal.get_run(gui.run_id)["excel_saved"] == 1
    finally:
        release.set()


def test_inferred_ok_does_not_count_as_confirmed_success(gui):
    gui._on_result_ready({**result(), "verification": "inferred"})
    summary = gui._build_summary()
    assert summary["success"] == 0
    assert summary["inferred"] == 1


def test_changed_selection_cannot_hide_unresolved_operation(gui, monkeypatch):
    gui._prepare_journal(selected(), MODE_SERIAL)
    old_run = gui.run_id
    gui.journal.begin(old_run, "serial", row=2, payload={"serial": "S1"})
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    changed = [SerialItem(2, "OTHER")]
    assert gui._prepare_journal(changed, MODE_SERIAL) is None
    assert len(gui.journal.pending(old_run)) == 1
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Yes)
    gui._review_unresolved_progress()
    assert gui.journal.pending(old_run) == []
    assert gui.journal.results(old_run)[0]["verification"] == "unverified"
    assert gui._prepare_journal(changed, MODE_SERIAL) == changed


def test_stop_during_countdown_never_starts_worker(gui, qapp):
    called = []
    gui._start_countdown(lambda: called.append(True), "Starting {}")
    assert not gui.pages.widget(1).isEnabled()
    gui._on_stop()
    qapp.processEvents()
    assert not gui._timer.isActive()
    assert called == []
    assert gui.pages.widget(1).isEnabled()
