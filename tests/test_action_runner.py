import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from actions import (
    ON_FAIL_CONTINUE,
    ON_FAIL_ERROR,
    ON_FAIL_STOP,
    REASON_APP_ERROR,
    REASON_NOT_FOUND,
    Step,
    make_step,
    validate_steps,
)
from action_runner import ActionRunner, RowContext, StopRun, resolve_text

SCREEN_OK = (
    '<hierarchy><node text="Thành công" resource-id="com.app:id/msg" '
    'bounds="[10,20][110,60]" clickable="true" class="android.widget.TextView"/></hierarchy>'
)
SCREEN_ERR = (
    '<hierarchy><node text="Product not found" resource-id="com.app:id/msg" '
    'bounds="[10,20][110,60]" clickable="true" class="android.widget.TextView"/></hierarchy>'
)
SCREEN_NOT_FOUND = (
    '<hierarchy>'
    '<node text="Không tìm thấy serial trong hệ thống" resource-id="android:id/message" '
    'bounds="[40,300][660,420]" clickable="false" class="android.widget.TextView"/>'
    '<node text="OK" resource-id="android:id/button1" '
    'bounds="[500,460][620,540]" clickable="true" class="android.widget.Button"/>'
    '</hierarchy>'
)


class FakeAdb:
    def __init__(self, xml=SCREEN_OK, fail=False):
        self.instance_name = "LDPlayer"
        self.xml = xml
        self.fail = fail
        self.commands = []

    def run_shell(self, command, timeout=None):
        self.commands.append(command)
        if self.fail:
            return None
        if "uiautomator dump" in command:
            return self.xml
        return ""

    def run_exec_out_binary(self, command, timeout=None):
        return None if self.fail else b"\x89PNG_fake"


class FakeBackend:
    def __init__(self, fail=False):
        self.typed = []
        self.fail = fail

    def type_serial(self, text):
        if self.fail:
            raise RuntimeError("device unreachable")
        self.typed.append(text)

    def send_enter(self, mode):
        pass


def ctx(**kw):
    base = dict(row=7, serial="ABC123", cells={"B": "Sản phẩm X", "C": 42})
    base.update(kw)
    return RowContext(**base)


# --- variable resolution ----------------------------------------------------

def test_resolve_serial_and_row():
    assert resolve_text("SP-{serial}-{row}", ctx()) == "SP-ABC123-7"


def test_resolve_cell_reference():
    assert resolve_text("{cell:B}", ctx()) == "Sản phẩm X"


def test_resolve_cell_is_case_insensitive():
    assert resolve_text("{cell:b}", ctx()) == "Sản phẩm X"


def test_resolve_missing_cell_becomes_empty():
    assert resolve_text("[{cell:Z}]", ctx()) == "[]"


def test_resolve_variable_from_read_step():
    c = ctx()
    c.variables["ketqua"] = "OK-99"
    assert resolve_text("{var:ketqua}", c) == "OK-99"


def test_unknown_placeholder_is_left_alone():
    assert resolve_text("{khong_biet}", ctx()) == "{khong_biet}"


def test_empty_template_returns_empty():
    assert resolve_text("", ctx()) == ""


# --- step execution ---------------------------------------------------------

def make_runner(steps, adb=None, backend=None, **kw):
    return ActionRunner(steps, backend or FakeBackend(), adb or FakeAdb(), **kw)


def test_type_step_expands_variables_before_typing():
    backend = FakeBackend()
    runner = make_runner([Step("type", {"text": "{serial}"})], backend=backend)
    runner.run_row(ctx())
    assert backend.typed == ["ABC123"]


def test_key_step_sends_the_right_keycode():
    adb = FakeAdb()
    make_runner([Step("key", {"key": "enter"})], adb=adb).run_row(ctx())
    assert "input keyevent 66" in adb.commands


def test_unsupported_key_fails_the_step():
    result = make_runner([Step("key", {"key": "f13"})]).run_row(ctx())
    assert result.status == "ERROR"


def test_tap_step_sends_coordinates():
    adb = FakeAdb()
    make_runner([Step("tap", {"x": 100, "y": 250})], adb=adb).run_row(ctx())
    assert "input tap 100 250" in adb.commands


def test_check_step_flags_error_keyword():
    runner = make_runner(
        [Step("check", {
            "error_keywords": "product not found",
            "success_keywords": "",
            "not_found_keywords": "",
        })],
        adb=FakeAdb(xml=SCREEN_ERR),
    )
    result = runner.run_row(ctx())
    assert result.status == "ERROR"
    # Ghi lại đúng câu app hiện, không phải từ khóa đã chuẩn hóa.
    assert result.response_text == "Product not found"
    assert result.reason == REASON_APP_ERROR


def test_check_step_taps_ok_and_records_not_found_reason():
    adb = FakeAdb(xml=SCREEN_NOT_FOUND)
    runner = make_runner(
        [Step("check", {
            "error_keywords": "loi",
            "not_found_keywords": "không tìm thấy",
            "success_keywords": "",
        })],
        adb=adb,
    )
    result = runner.run_row(ctx())

    assert result.status == "ERROR"
    assert result.reason == REASON_NOT_FOUND
    assert result.response_text == "Không tìm thấy serial trong hệ thống"
    assert not result.dismiss_failed
    assert "input tap 560 500" in adb.commands


def test_not_found_wins_over_a_generic_error_keyword_that_also_matches():
    runner = make_runner(
        [Step("check", {
            "error_keywords": "không tìm thấy,loi",
            "not_found_keywords": "không tìm thấy",
            "success_keywords": "",
        })],
        adb=FakeAdb(xml=SCREEN_NOT_FOUND),
    )
    assert runner.run_row(ctx()).reason == REASON_NOT_FOUND


def test_check_step_can_leave_the_dialog_open():
    adb = FakeAdb(xml=SCREEN_NOT_FOUND)
    runner = make_runner(
        [Step("check", {
            "not_found_keywords": "không tìm thấy",
            "error_keywords": "",
            "success_keywords": "",
            "dismiss_dialog": False,
        })],
        adb=adb,
    )
    runner.run_row(ctx())
    assert not any(c.startswith("input tap") for c in adb.commands)


def test_check_step_matches_success_keyword_ignoring_accents():
    runner = make_runner(
        [Step("check", {"success_keywords": "thanh cong", "error_keywords": ""})],
        adb=FakeAdb(xml=SCREEN_OK),
    )
    assert runner.run_row(ctx()).status == "OK"


def test_check_returns_unknown_when_no_keyword_matches():
    runner = make_runner(
        [Step("check", {"success_keywords": "khong-co-o-day", "error_keywords": ""})],
        adb=FakeAdb(xml=SCREEN_OK),
    )
    assert runner.run_row(ctx()).status == "UNKNOWN"


def test_read_step_stores_variable_for_later_steps():
    backend = FakeBackend()
    steps = [
        Step("read", {"resource_id": "msg", "var_name": "kq", "timeout": 1}),
        Step("type", {"text": "ket qua: {var:kq}"}),
    ]
    make_runner(steps, backend=backend).run_row(ctx())
    assert backend.typed == ["ket qua: Thành công"]


def test_write_cell_step_collects_output():
    steps = [Step("write_cell", {"column": "j", "value": "{serial}-ok"})]
    result = make_runner(steps).run_row(ctx())
    assert result.cell_writes == {"J": "ABC123-ok"}


def test_wait_for_times_out_and_marks_error():
    steps = [Step("wait_for", {"text": "không bao giờ có", "timeout": 0.01})]
    result = make_runner(steps, adb=FakeAdb(xml=SCREEN_OK)).run_row(ctx())
    assert result.status == "ERROR"


# --- failure policies -------------------------------------------------------

def test_on_fail_continue_keeps_going():
    backend = FakeBackend()
    steps = [
        Step("key", {"key": "bad"}, on_fail=ON_FAIL_CONTINUE),
        Step("type", {"text": "{serial}"}),
    ]
    result = make_runner(steps, backend=backend).run_row(ctx())
    assert backend.typed == ["ABC123"]
    assert result.status == "OK"


def test_on_fail_error_stops_the_row_only():
    backend = FakeBackend()
    steps = [
        Step("key", {"key": "bad"}, on_fail=ON_FAIL_ERROR),
        Step("type", {"text": "{serial}"}),
    ]
    result = make_runner(steps, backend=backend).run_row(ctx())
    assert backend.typed == []
    assert result.status == "ERROR"


def test_on_fail_stop_raises_to_abort_the_run():
    steps = [Step("key", {"key": "bad"}, on_fail=ON_FAIL_STOP)]
    with pytest.raises(StopRun):
        make_runner(steps).run_row(ctx())


def test_disabled_step_is_skipped():
    backend = FakeBackend()
    steps = [Step("type", {"text": "{serial}"}, enabled=False)]
    make_runner(steps, backend=backend).run_row(ctx())
    assert backend.typed == []


def test_dead_device_marks_adb_failed():
    steps = [Step("clear_field", {})]
    result = make_runner(steps, adb=FakeAdb(fail=True)).run_row(ctx())
    assert result.adb_failed is True


def test_clearing_the_field_costs_one_input_call_instead_of_three():
    """
    Bước "xóa ô" chạy trên MỌI dòng của kịch bản, mà mỗi lệnh `input` là một lần
    máy ảo dựng tiến trình Java (~300ms). Đúng dãy phím ấy phải đi trong một
    lệnh duy nhất - và phải vẫn là ĐÚNG dãy phím đó, không tiện tay cắt bớt.
    """
    from automation_backend import AdbBackend

    adb = FakeAdb()
    result = make_runner(
        [Step("clear_field", {})], adb=adb, backend=AdbBackend(adb)
    ).run_row(ctx())

    assert result.status == "OK"
    assert adb.commands == ["input keyevent 123 28 " + " ".join(["67"] * 20)]


def test_the_default_recipe_does_not_clear_the_same_field_twice():
    """
    Kịch bản mặc định là [xóa ô, gõ, Enter, ...] mà `type_serial` cũng tự xóa ô:
    dòng nào cũng gửi thừa một dãy 22 phím không xóa gì cả (~600ms). Xóa xong
    ngay trước đó thì lệnh gõ chỉ còn đúng phần gõ.
    """
    from automation_backend import AdbBackend

    adb = FakeAdb()
    steps = [Step("clear_field", {}), Step("type", {"text": "{serial}"})]
    make_runner(steps, adb=adb, backend=AdbBackend(adb)).run_row(ctx())

    assert adb.commands == [
        "input keyevent 123 28 " + " ".join(["67"] * 20),
        "input text 'ABC123'",
    ]


def test_an_enter_between_clearing_and_typing_brings_the_clear_back():
    """
    Enter là lúc app xử lý và có thể tự điền lại ô. Bỏ lệnh xóa sau đó là nối
    serial này vào phần app để lại - gửi đi một mã không có thật.
    """
    from automation_backend import AdbBackend

    adb = FakeAdb()
    steps = [
        Step("clear_field", {}),
        Step("key", {"key": "enter"}),
        Step("type", {"text": "{serial}"}),
    ]
    make_runner(steps, adb=adb, backend=AdbBackend(adb)).run_row(ctx())

    assert "input keyevent 123 28" in adb.commands[-1]
    assert adb.commands[-1].endswith("input text 'ABC123'")


def test_a_failed_clear_is_not_taken_as_an_empty_field():
    """Bước xóa hụt (bỏ qua theo cấu hình) thì bước gõ phải tự xóa lấy."""
    from automation_backend import AdbBackend

    adb = FakeAdb()
    backend = AdbBackend(adb)
    backend.clear_field = lambda: (_ for _ in ()).throw(RuntimeError("máy ảo im"))
    steps = [
        Step("clear_field", {}, on_fail=ON_FAIL_CONTINUE),
        Step("type", {"text": "{serial}"}),
    ]
    make_runner(steps, adb=adb, backend=backend).run_row(ctx())

    assert adb.commands[-1].startswith("input keyevent 123 28")


def test_a_backend_without_clear_field_still_clears_the_old_way():
    """FakeBackend của test (và mọi backend cũ) không có clear_field - đừng đổ."""
    adb = FakeAdb()
    result = make_runner([Step("clear_field", {})], adb=adb).run_row(ctx())

    assert result.status == "OK"
    assert adb.commands == [
        "input keyevent 123; input keyevent 28; input keyevent " + " ".join(["67"] * 20)
    ]


# --- validation -------------------------------------------------------------

def test_validate_rejects_empty_recipe():
    assert validate_steps([])


def test_validate_requires_a_matcher_for_wait_for():
    problems = validate_steps([Step("wait_for", {"text": "", "resource_id": ""})])
    assert problems and "Text hoặc Resource id" in problems[0]


def test_validate_accepts_a_complete_recipe():
    steps = [make_step("clear_field"), make_step("type"), make_step("key")]
    assert validate_steps(steps) == []


def test_make_step_fills_declared_defaults():
    assert make_step("type").params["text"] == "{serial}"
