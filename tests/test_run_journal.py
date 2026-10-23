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


def test_bill_that_only_typed_the_search_code_is_released(tmp_path):
    journal = RunJournal(str(tmp_path / "ledger.sqlite3"))
    run = journal.create_run("key", "a.xlsx", "pick", {})
    journal.begin(run, "bill", bill="OR1", payload={"rows": []})
    journal.begin(run, "tap", bill="OR1", payload={"resource_id": "btnPick", "harmless": True})
    journal.begin(run, "input", bill="OR1", payload={"text": "OR1"})
    assert journal.release_untouched(run_id=run) == ["OR1"]
    assert journal.pending(run) == []
    journal.close()


def test_bill_that_may_have_changed_the_app_stays_pending(tmp_path):
    journal = RunJournal(str(tmp_path / "ledger.sqlite3"))
    run = journal.create_run("key", "a.xlsx", "pick", {})
    # OR2 đã chạm nút mở phiên; OR3 chạm một nút không đánh dấu (nhật ký cũ);
    # OR4 đã có serial gửi đi. Cả ba đều phải đợi người xem.
    for bill, extra in (("OR2", ("tap", None, {"resource_id": "btnProceed"})),
                        ("OR3", ("tap", None, {"resource_id": "btnPick"})),
                        ("OR4", ("scan", 5, {"serial": "S"}))):
        journal.begin(run, "bill", bill=bill)
        journal.begin(run, "input", bill=bill, payload={"text": bill})
        kind, row, payload = extra
        journal.begin(run, kind, row=row, bill=bill, payload=payload)
    journal.begin(run, "bill", bill="OR5")
    journal.begin(run, "input", bill="OR5", payload={"text": "OR5"})
    assert journal.release_untouched(run_id=run) == ["OR5"]
    assert {op["bill"] for op in journal.pending(run)} == {"OR2", "OR3", "OR4"}
    journal.close()


def test_release_untouched_by_source_ignores_serial_rows(tmp_path):
    journal = RunJournal(str(tmp_path / "ledger.sqlite3"))
    serial_run = journal.create_run("k1", "a.xlsx", "serial", {})
    pick_run = journal.create_run("k2", "a.xlsx", "pick", {})
    other = journal.create_run("k3", "b.xlsx", "pick", {})
    journal.begin(serial_run, "serial", row=2, payload={"serial": "S1"})
    journal.begin(pick_run, "bill", bill="OR1")
    journal.begin(other, "bill", bill="OR9")
    assert journal.release_untouched(source="a.xlsx") == ["OR1"]
    assert len(journal.pending(serial_run)) == 1
    assert len(journal.pending(other)) == 1
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
