import time

import pytest

from tests.fake_pick_device import FakePickDevice, Session, _node, _screen
from tests.fake_inbound_device import Checkin, FakeInboundDevice
from automation_backend import AdbBackend
from pick_runner import PickConfig, PickRunner, PickStopped
from inbound_runner import InboundConfig, InboundRunner
from run_journal import RunJournal


def runner(device, cls=PickRunner, **kwargs):
    config_cls = InboundConfig if cls is InboundRunner else PickConfig
    return cls(device, AdbBackend(device), config_cls(step_timeout=.15, capture_screenshot=False, **kwargs))


@pytest.mark.parametrize("inbound", [False, True])
def test_rejected_final_serial_never_enters_confirmed_partial(inbound):
    if inbound:
        device = FakeInboundDevice([Checkin("CK1", "IR1", 1)], reject_serials={"BAD"})
        work = runner(device, InboundRunner)
        code = "CK1"
    else:
        device = FakePickDevice([Session("OR1", "PL1", 1)], reject_serials={"BAD"})
        work, code = runner(device), "OR1"
    with pytest.raises(PickStopped):
        work.run_bill(code, [{"row": 2, "value": "BAD"}])
    assert work.last_partial == []


@pytest.mark.parametrize("counter", ["2/3", "1/4", "4/3"])
def test_counter_jump_or_changed_total_is_rejected(counter):
    device = FakePickDevice([])
    work = runner(device)
    work._counter_total = 3
    device._xml = lambda: _screen([_node("tvCounter", counter)])
    with pytest.raises(PickStopped):
        work._wait_for_pick("OR1", "S1", 0, False)


def test_stuck_completion_dialog_has_a_deadline():
    device = FakePickDevice([Session("OR1", "PL1", 1)])
    work = runner(device)
    original = device._tap
    device._tap = lambda x, y: None if device.state == "finish" else original(x, y)
    started = time.monotonic()
    with pytest.raises(PickStopped):
        work.run_bill("OR1", [{"row": 2, "value": "S1"}])
    assert time.monotonic() - started < 1


def test_delivered_scan_with_lost_response_is_reconciled_without_resending(tmp_path):
    device = FakePickDevice([Session("OR1", "PL1", 2)])
    original = device.run_shell
    def lost_reply(command, timeout=None):
        scanning = device.state == "serial" and "input text" in command
        output = original(command, timeout)
        return None if scanning else output
    device.run_shell = lost_reply
    work = runner(device)
    journal = RunJournal(str(tmp_path / "journal.sqlite3"))
    work.journal = journal
    work.run_id = journal.create_run("key", "a.xlsx", "pick", {})
    outcome = work.run_bill("OR1", [{"row": 2, "value": "S1"}, {"row": 3, "value": "S2"}])
    assert outcome.picked == 2
    assert [text for state, text in device.typed if state == "serial"] == ["S1", "S2"]
    assert len(journal.results(work.run_id)) == 2
    journal.close()


def _journaled_runner(tmp_path, device):
    work = runner(device)
    work.journal = RunJournal(str(tmp_path / "journal.sqlite3"))
    work.run_id = work.journal.create_run("key", "a.xlsx", "pick", {})
    # PickWorker ghi dòng này trước khi gọi run_bill.
    work.journal.begin(work.run_id, "bill", bill="OR1")
    return work


def _fail_typing_in(device, state):
    original = device.run_shell
    def lost(command, timeout=None):
        return None if device.state == state and "input text" in command else original(command, timeout)
    device.run_shell = lost


def test_adb_lost_while_typing_the_or_code_leaves_nothing_to_reconcile(tmp_path):
    device = FakePickDevice([Session("OR1", "PL1", 1)])
    _fail_typing_in(device, "list")
    work = _journaled_runner(tmp_path, device)
    with pytest.raises(Exception, match="ADB"):
        work.run_bill("OR1", [{"row": 2, "value": "S1"}])
    assert work.journal.pending(work.run_id)          # chưa nhả thì còn nằm chờ
    assert work.journal.release_untouched(run_id=work.run_id) == ["OR1"]
    assert work.journal.pending(work.run_id) == []
    work.journal.close()


def test_adb_lost_after_opening_the_session_still_needs_reconciling(tmp_path):
    device = FakePickDevice([Session("OR1", "PL1", 1)])
    _fail_typing_in(device, "tote")
    work = _journaled_runner(tmp_path, device)
    with pytest.raises(Exception, match="ADB"):
        work.run_bill("OR1", [{"row": 2, "value": "S1"}])
    assert work.journal.release_untouched(run_id=work.run_id) == []
    assert {op["bill"] for op in work.journal.pending(work.run_id)} == {"OR1"}
    work.journal.close()


def test_one_empty_xml_can_recover_within_same_deadline():
    device = FakePickDevice([])
    work = runner(device)
    work.screen._fast_dump_works = True
    original = device.run_shell
    calls = [0]
    def flaky(command, timeout=None):
        if "uiautomator dump" in command:
            calls[0] += 1
            if calls[0] == 1:
                return ""
        return original(command, timeout)
    device.run_shell = flaky
    assert "btnPick" in work._dump()
    assert calls[0] == 2


def test_loading_list_is_not_classified_as_not_found():
    device = FakePickDevice([])
    device.state = "list"
    device._xml = lambda: _screen([_node("textInput", "OR1"), _node("message", "Loading, please wait")])
    work = runner(device)
    with pytest.raises(PickStopped) as caught:
        work.run_bill("OR1", [{"row": 2, "value": "S1"}])
    assert type(caught.value) is PickStopped


def test_stop_in_wait_sends_no_more_input():
    device = FakePickDevice([])
    work = runner(device)
    work._should_stop = lambda: True
    with pytest.raises(PickStopped):
        work._wait_for_pick("OR1", "S1", 0, False)
    assert device.commands == []


def test_multiple_bins_are_processed_before_the_next_serial():
    device = FakePickDevice([Session("OR1", "PL1", 2, bins=("BIN1", "BIN2"))])
    original = device._type
    def move_bin(text):
        was_scan = device.state == "serial"
        original(text)
        if was_scan and device.state != "finish":
            device.bin_index += 1
            device.state = "bin"
    device._type = move_bin
    outcome = runner(device, bin_code="").run_bill("OR1", [{"row": 2, "value": "S1"}, {"row": 3, "value": "S2"}])
    assert outcome.picked == 2
    assert [(state, text) for state, text in device.typed if state == "bin"] == [("bin", "BIN1"), ("bin", "BIN2")]


def test_old_empty_result_is_not_proof_new_query_has_finished():
    device = FakePickDevice([])
    device.state = "list"
    work = runner(device)
    work._search_before_xml = _screen([_node("textInput", "OLD"), _node("message", "No results")])
    device._xml = lambda: _screen([_node("textInput", "NEW"), _node("message", "No results")])
    with pytest.raises(PickStopped) as caught:
        work._search_and_open("NEW", 1)
    assert type(caught.value) is PickStopped
