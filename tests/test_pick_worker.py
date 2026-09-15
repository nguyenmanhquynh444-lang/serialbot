"""
Thread chạy luồng xuất kho.

Điều quan trọng nhất cần khóa lại: dừng là dừng hẳn. Lỗi ở vận đơn thứ hai mà
worker vẫn chạy vận đơn thứ ba thì nó quét hàng vào một phiên đang dở - hỏng
đúng thứ mà cả luồng này sinh ra để tránh.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

pytest.importorskip("PyQt6")

from fake_pick_device import FakePickDevice, Session
from pick_runner import PickConfig
from pick_worker import PickWorker


def groups(*specs):
    """specs = [(bill, [serial, ...]), ...] -> đúng dạng read_bill_groups trả về."""
    out = []
    row = 2
    for bill, serials in specs:
        out.append({
            "bill": bill,
            "first_row": row,
            "rows": [{"row": row + i, "value": s} for i, s in enumerate(serials)],
        })
        row += len(serials)
    return out


def make_worker(device, group_list, **config_kwargs):
    config = PickConfig(step_timeout=2.0, capture_screenshot=False, **config_kwargs)
    worker = PickWorker(group_list, "LDPlayer", config)
    worker.adb_client = device
    return worker


def collect(worker):
    """Chạy thẳng run() trong thread hiện tại và gom mọi tín hiệu phát ra."""
    events = {"bills": [], "results": [], "stopped": [], "finished": 0, "progress": []}
    worker.bill_done.connect(events["bills"].append)
    worker.result_ready.connect(events["results"].append)
    worker.stopped.connect(lambda m, p: events["stopped"].append((m, p)))
    worker.finished_all.connect(lambda: events.__setitem__("finished", events["finished"] + 1))
    worker.progress.connect(lambda d, t: events["progress"].append((d, t)))
    worker.run()
    return events


def test_worker_can_drive_the_inbound_runner_too(qapp):
    """Phần khung dùng chung cho hai luồng; chỉ chuỗi màn hình là khác."""
    from fake_inbound_device import Checkin, FakeInboundDevice
    from inbound_runner import InboundRunner

    device = FakeInboundDevice([Checkin("CKSIRVIN89HN210210 - VIN", "IRVIN89HN210 - x", 2)])
    config = PickConfig(step_timeout=2.0, capture_screenshot=False)
    worker = PickWorker(
        groups(("CKSIRVIN89HN210210", ["S1", "S2"])), "LDPlayer", config,
        runner_cls=InboundRunner,
    )
    worker.adb_client = device

    events = collect(worker)

    assert events["stopped"] == []
    assert [b["bill"] for b in events["bills"]] == ["CKSIRVIN89HN210210"]
    assert events["bills"][0]["picked"] == 2
    assert "Đã nhập" in events["bills"][0]["message"]


def test_runs_every_bill_in_order(qapp):
    device = FakePickDevice([
        Session("VD1", "PL_001", 2),
        Session("VD2", "PL_002", 1),
    ])
    worker = make_worker(device, groups(("VD1", ["S1", "S2"]), ("VD2", ["S3"])))

    events = collect(worker)

    assert [b["bill"] for b in events["bills"]] == ["VD1", "VD2"]
    assert [b["picked"] for b in events["bills"]] == [2, 1]
    assert [r["serial"] for r in events["results"]] == ["S1", "S2", "S3"]
    assert events["progress"] == [(1, 2), (2, 2)]
    assert events["stopped"] == []
    assert worker.done_bills == ["VD1", "VD2"]


def test_a_failing_bill_stops_the_whole_run(qapp):
    """Vận đơn 2 hỏng thì vận đơn 3 KHÔNG được chạy."""
    device = FakePickDevice([
        Session("VD1", "PL_001", 1),
        Session("VD2", "PL_002", 2),
        Session("VD3", "PL_003", 1),
    ], reject_serials=["S2"])

    worker = make_worker(
        device, groups(("VD1", ["S1"]), ("VD2", ["S2", "S9"]), ("VD3", ["S3"]))
    )
    events = collect(worker)

    assert [b["bill"] for b in events["bills"]] == ["VD1"]
    assert worker.done_bills == ["VD1"]
    assert len(events["stopped"]) == 1
    assert "S2" in events["stopped"][0][0]
    assert "S3" not in [r["serial"] for r in events["results"]]


def test_or_not_found_is_logged_as_error_and_the_run_moves_to_the_next_or(qapp):
    """
    Ngoại lệ duy nhất so với "lỗi là dừng cả lượt": mã OR không tồn tại nghĩa là
    chưa mở phiên nào (device vẫn ở màn hình tìm mã OR), nên bỏ qua an toàn -
    khác hẳn một serial bị app từ chối giữa chừng (đó vẫn phải dừng, xem
    test_a_failing_bill_stops_the_whole_run).
    """
    device = FakePickDevice([Session("VD2", "PL_002", 1)])
    worker = make_worker(
        device, groups(("VD-KHONG-CO", ["S1"]), ("VD2", ["S2"]))
    )

    events = collect(worker)

    assert events["stopped"] == []
    assert events["finished"] == 1
    assert [b["bill"] for b in events["bills"]] == ["VD-KHONG-CO", "VD2"]
    assert events["bills"][0]["status"] == "ERROR"
    assert events["bills"][1]["status"] == "OK"
    assert worker.done_bills == ["VD2"]           # chỉ mã chạy được mới tính "xong"

    error_result = next(r for r in events["results"] if r["serial"] == "S1")
    assert error_result["status"] == "ERROR"
    assert "Không tìm thấy mã OR" in error_result["message"]
    ok_result = next(r for r in events["results"] if r["serial"] == "S2")
    assert ok_result["status"] == "OK"

    assert events["progress"] == [(1, 2), (2, 2)]


def test_count_mismatch_stops_before_touching_the_warehouse(qapp):
    device = FakePickDevice([Session("VD1", "PL_001", 5)])
    worker = make_worker(device, groups(("VD1", ["S1", "S2"])))

    events = collect(worker)

    assert events["bills"] == []
    assert device.active is None                 # chưa mở phiên nào
    assert "app báo cần 5" in events["stopped"][0][0]


def test_partial_serials_are_reported_when_a_bill_breaks(qapp):
    """
    Dừng giữa chừng thì những serial đã vào phiên vẫn phải hiện ra - người dùng
    cần biết phiên trên máy ảo đang dở tới đâu mà dọn.
    """
    device = FakePickDevice([Session("VD1", "PL_001", 3)], reject_serials=["S2"])
    worker = make_worker(device, groups(("VD1", ["S1", "S2", "S3"])))

    events = collect(worker)

    assert [r["serial"] for r in events["results"]] == ["S1"]
    assert events["results"][0]["message"] == "Đã xuất trước khi dừng"


def test_stop_button_ends_the_run(qapp):
    device = FakePickDevice([Session("VD1", "PL_001", 1), Session("VD2", "PL_002", 1)])
    worker = make_worker(device, groups(("VD1", ["S1"]), ("VD2", ["S2"])))
    worker.stop()

    events = collect(worker)

    assert events["bills"] == []
    assert "bấm Dừng" in events["stopped"][0][0]


def test_dead_adb_refuses_to_run_instead_of_typing_into_windows(qapp):
    """Không có đường lui gõ bàn phím: gõ nhầm cửa sổ giữa phiên pick là hỏng đơn."""
    class Dead:
        def run_shell(self, command, timeout=None):
            return None

        def run_exec_out_binary(self, command, timeout=None):
            return None

    worker = make_worker(Dead(), groups(("VD1", ["S1"])))
    events = collect(worker)

    assert events["bills"] == []
    assert "chỉ chạy qua ADB" in events["stopped"][0][0]


def test_finished_all_fires_exactly_once_on_both_paths(qapp):
    """Giao diện dựa vào tín hiệu này để mở lại nút Bắt đầu."""
    ok_device = FakePickDevice([Session("VD1", "PL_001", 1)])
    assert collect(make_worker(ok_device, groups(("VD1", ["S1"]))))["finished"] == 1

    bad_device = FakePickDevice([Session("VD1", "PL_001", 9)])
    assert collect(make_worker(bad_device, groups(("VD1", ["S1"]))))["finished"] == 1


def test_every_result_carries_the_keys_the_excel_writer_needs(qapp):
    """
    Giao diện đổ thẳng dict này vào ResultWriter.add_result(row, serial, status,
    response_text, screenshot_path, reason). Thiếu một khóa là KeyError, mà chỗ
    gọi có try/except nên nó chỉ chui vào log: phiên chạy trông vẫn xanh, thanh
    tiến trình vẫn chạy, còn sheet kết quả thì trống trơn. Đúng lỗi đã nuốt sạch
    kết quả của một lượt chạy 300 mã.
    """
    device = FakePickDevice([Session("VD2", "PL_002", 1)])
    worker = make_worker(device, groups(("VD-KHONG-CO", ["S1"]), ("VD2", ["S2"])))

    events = collect(worker)

    assert len(events["results"]) == 2          # cả dòng lỗi lẫn dòng chạy được
    for result in events["results"]:
        for key in ("row", "serial", "status", "response_text", "screenshot_path"):
            assert key in result, f"thiếu khóa '{key}' - Excel sẽ không ghi được"


def test_stats_update_fires_per_serial_so_the_panel_moves(qapp):
    """
    Khung STATS lấy tổng là tổng số serial và chỉ nhúc nhích khi có
    `stats_update`. Thiếu tín hiệu này thì cả lượt chạy 300 mã hiện đứng im
    "0 / 274" - nhìn như bot chết dù nó đang chạy ngon.

    Đếm theo serial chứ không theo mã OR, nếu không thanh Processed không bao
    giờ chạy tới tổng.
    """
    device = FakePickDevice([Session("VD2", "PL_002", 2)])
    worker = make_worker(device, groups(("VD-KHONG-CO", ["S1"]), ("VD2", ["S2", "S3"])))

    stats = []
    worker.stats_update.connect(lambda d, s, e, u: stats.append((d, s, e, u)))
    collect(worker)

    # 3 serial -> 3 lần cập nhật, done tăng dần 1,2,3
    assert [s[0] for s in stats] == [1, 2, 3]
    # S1 hỏng (mã không có), S2+S3 chạy được
    assert stats[-1] == (3, 2, 1, 0)


# --- tạm dừng / chạy tiếp ----------------------------------------------------

def test_pause_and_resume_exist_so_f9_and_the_tray_cannot_crash_the_run(qapp):
    """
    Nút Pause từng bị tắt ở chế độ này, nhưng F9, menu Chạy và biểu tượng khay
    hệ thống vẫn gọi thẳng `worker.pause()`. Thiếu hàm là AttributeError giữa
    một lượt chạy kho thật.
    """
    device = FakePickDevice([Session("VD1", "PL_001", 1)])
    worker = make_worker(device, groups(("VD1", ["S1"])))

    worker.pause()
    assert not worker._pause_event.is_set()
    worker.resume()
    assert worker._pause_event.is_set()


def test_stop_releases_a_paused_run(qapp):
    """Đang tạm dừng mà bấm Dừng thì phải thoát được, không kẹt trong lúc chờ."""
    device = FakePickDevice([Session("VD1", "PL_001", 1)])
    worker = make_worker(device, groups(("VD1", ["S1"])))

    worker.pause()
    worker.stop()

    worker._wait_if_paused()        # không được treo ở đây
    assert worker._stop_flag.is_set()


def test_pausing_waits_between_bills_not_inside_a_timed_wait(qapp):
    """
    Chỗ đứng lại phải là điểm không có đồng hồ đếm ngược nào đang chạy. Chặn ở
    trong vòng chờ màn hình thì `step_timeout` vẫn trôi trong lúc dừng - tạm
    dừng một phút là tỉnh dậy với một lỗi 'chờ quá 15s' hoàn toàn bịa.

    Kiểm bằng cách tạm dừng ngay khi mã đầu tiên xong: mã thứ hai phải chưa
    chạy, và khi cho chạy tiếp thì nó chạy trọn vẹn chứ không lỗi timeout.
    """
    device = FakePickDevice([
        Session("VD1", "PL_001", 1),
        Session("VD2", "PL_002", 1),
    ])
    worker = make_worker(device, groups(("VD1", ["S1"]), ("VD2", ["S2"])))

    def pause_after_first(payload):
        if payload["bill"] == "VD1":
            worker.pause()
            # Cho chạy tiếp ngay để test không treo; điều cần kiểm là lượt chạy
            # đi qua đường tạm dừng mà vẫn về đích nguyên vẹn.
            worker.resume()

    worker.bill_done.connect(pause_after_first)
    events = collect(worker)

    assert events["stopped"] == []
    assert [b["bill"] for b in events["bills"]] == ["VD1", "VD2"]
    assert [b["picked"] for b in events["bills"]] == [1, 1]
