import threading

from run_journal import RunJournal, fingerprint


def test_crash_preserves_intention_and_results_before_excel(tmp_path):
    path = str(tmp_path / "ledger.sqlite3")
    journal = RunJournal(path)
    run = journal.create_run("key", "source.xlsx", "pick", {})
    pending = journal.begin(run, "scan", row=3, bill="OR1", payload={"serial": "S2"})
    confirmed = journal.begin(run, "scan", row=2, bill="OR1")
    journal.record_result(run, {"row": 2, "status": "OK", "verification": "confirmed"}, confirmed)
    journal.close()
    recovered = RunJournal(path)
    assert [op["id"] for op in recovered.pending(run)] == [pending]
    assert recovered.results(run)[0]["verification"] == "confirmed"
    assert recovered.latest("key")["excel_saved"] == 0
    recovered.close()


def test_complete_bill_and_clear_intentions_commit_together(tmp_path):
    journal = RunJournal(str(tmp_path / "ledger.sqlite3"))
    run = journal.create_run("key", "a.xlsx", "pick", {})
    journal.begin(run, "tap", bill="OR1")
    journal.complete_bill(run, {"bill": "OR1", "picked": 2, "status": "OK"})
    assert journal.pending(run) == []
    assert journal.bills(run)[0]["picked"] == 2
    journal.close()


def test_fingerprint_matches_selected_data_not_workbook_bytes(tmp_path):
    args = (str(tmp_path / "a.xlsx"), "Data", "serial", [{"row": 2, "value": "S1"}], {"enter": "enter"})
    first = fingerprint(*args)
    (tmp_path / "a.xlsx").write_bytes(b"new result sheet")
    assert fingerprint(*args) == first
    for index, replacement in [(1, "Other"), (2, "inbound"), (3, [{"row": 2, "value": "S2"}]),
                               (4, {"enter": "none"})]:
        changed = list(args)
        changed[index] = replacement
        assert fingerprint(*changed) != first


def test_multiple_instances_do_not_lose_results(tmp_path):
    journal = RunJournal(str(tmp_path / "ledger.sqlite3"))
    run = journal.create_run("key", "a.xlsx", "serial", {})
    threads = [threading.Thread(target=lambda start=i: [journal.record_result(run, {"row": start*10+j,
                "status": "OK"}) for j in range(10)]) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(journal.results(run)) == 40
    journal.close()
