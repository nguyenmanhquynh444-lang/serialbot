"""
Đường chạy trên trình duyệt.

Hai tầng test:
  - phần logic thuần (dựng XML, tra ref, kiểm tra kịch bản) chạy ở đâu cũng được;
  - phần đầu-cuối mở Chrome thật ở chế độ ẩn, nạp trang giả lập trong
    tests/data/fake_warehouse.html rồi bấm bằng đúng đường mà bot dùng.

Trang giả lập là bắt buộc: hệ thống kho thật không phải chỗ để chạy test.
"""
import os
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import browser_backend as bb
from action_runner import ActionRunner, RowContext
from actions import Step, validate_steps
from screen_reader import dialog_message, find_dismiss_button, find_node

FAKE_PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fake_warehouse.html")


# --------------------------------------------------------------------- logic thuần

def _tree(**over):
    node = {
        "ref": "r0", "text": "", "desc": "", "id": "", "cls": "html.div",
        "bounds": [0, 0, 100, 100], "clickable": False, "children": [],
    }
    node.update(over)
    return node


def test_dom_tree_becomes_xml_the_old_reader_understands():
    root = _tree(ref="r3", id="body", cls="html.body", bounds=[0, 0, 1280, 800], children=[
        _tree(ref="r2", id="dlg", bounds=[300, 200, 900, 500], children=[
            _tree(ref="r0", text="Không tìm thấy serial trong hệ thống",
                  cls="html.p", bounds=[320, 240, 880, 300]),
            _tree(ref="r1", text="Đồng ý", id="btn-ok", cls="html.button",
                  bounds=[700, 420, 860, 470], clickable=True),
        ]),
    ])
    xml = bb.tree_to_xml(root)

    assert "Không tìm thấy serial" in dialog_message(xml)
    assert find_dismiss_button(xml)["resource_id"] == "btn-ok"
    assert find_node(xml, resource_id="btn-ok")["clickable"] is True


def test_special_characters_survive_the_round_trip():
    """Chữ trong trang web có & < > " - thoát sai là hỏng cả cây XML."""
    xml = bb.tree_to_xml(_tree(text='Lô "A&B" <gấp>', id="x"))
    assert find_node(xml, resource_id="x")["text"] == 'Lô "A&B" <gấp>'


def test_ref_survives_a_lookup_that_came_back_without_it():
    """
    find_dismiss_button() là hàm dùng chung với đường ADB nên không trả về ref.
    Tra ngược được thì nút vẫn được bấm bằng DOM chứ không tụt về tọa độ.
    """
    xml = bb.tree_to_xml(_tree(ref="r7", text="OK", id="btn", bounds=[10, 20, 90, 60]))
    screen = bb.BrowserScreen.__new__(bb.BrowserScreen)
    screen._refs = bb.ref_index(xml)

    assert screen._ref_for(find_dismiss_button(xml)) == "r7"


def test_chrome_is_started_with_its_own_profile():
    """
    Từ Chrome 136, cổng gỡ lỗi bị chặn nếu dùng chung profile mặc định - thiếu
    --user-data-dir là bot không bao giờ gắn vào được.
    """
    command = bb.chrome_command(port=9333, url="https://vi.du")
    assert "--remote-debugging-port=9333" in command
    assert any(a.startswith("--user-data-dir=") for a in command)
    assert command[-1] == "https://vi.du"


def test_the_bot_profile_never_lands_inside_the_project():
    assert "Desktop" not in bb.chrome_profile_dir()


# ------------------------------------------------------- kịch bản có bước cho web

class FakeWebScreen:
    """Đủ giống BrowserScreen để ActionRunner nhận ra đây là trình duyệt."""

    def __init__(self, read_value="Thành công"):
        self.clicks = []
        self.fills = []
        self.opened = []
        self.read_value = read_value

    def click(self, selector="", text="", timeout=None):
        self.clicks.append((selector, text))
        return True

    def fill(self, selector, value, timeout=None):
        self.fills.append((selector, value))
        return True

    def open_url(self, url, timeout=None):
        self.opened.append(url)
        return True

    def wait_selector(self, selector, state="visible", timeout=None):
        return True

    def read_selector(self, selector="", text="", timeout=None):
        return self.read_value

    def select_option(self, selector, value, timeout=None):
        return True


class FakeBrowserBackend:
    def __init__(self, screen):
        self.screen = screen
        self.typed = []
        self.keys = []

    def type_serial(self, text):
        self.typed.append(text)

    def clear_field(self):
        pass

    def send_key(self, key):
        self.keys.append(key)


def _runner(steps, screen=None):
    screen = screen or FakeWebScreen()
    return ActionRunner(steps, FakeBrowserBackend(screen), adb_client=None), screen


def test_web_steps_expand_variables_like_every_other_step():
    steps = [
        Step("web_open", {"url": "https://kho/tra-cuu/{serial}", "timeout": 5}),
        Step("web_fill", {"selector": "#serial", "value": "{serial}", "timeout": 5}),
        Step("web_click", {"selector": "#btn-tim", "text": "", "timeout": 5}),
    ]
    runner, screen = _runner(steps)
    result = runner.run_row(RowContext(row=2, serial="SN-001"))

    assert result.status == "OK"
    assert screen.opened == ["https://kho/tra-cuu/SN-001"]
    assert screen.fills == [("#serial", "SN-001")]
    assert screen.clicks == [("#btn-tim", "")]


def test_web_read_lands_in_a_variable_and_can_be_written_to_excel():
    steps = [
        Step("web_read", {"selector": "#ket-qua", "var_name": "ketqua", "timeout": 5}),
        Step("write_cell", {"column": "J", "value": "{var:ketqua}"}),
    ]
    runner, _ = _runner(steps, FakeWebScreen(read_value="Đã ghi nhận SN-001"))
    result = runner.run_row(RowContext(row=2, serial="SN-001"))

    assert result.cell_writes == {"J": "Đã ghi nhận SN-001"}
    assert result.response_text == "Đã ghi nhận SN-001"


def test_a_web_step_in_an_adb_recipe_says_so_instead_of_blaming_the_device():
    """Cấu hình sai thì phải nói là cấu hình sai - đếm vào lỗi ADB là cả phiên
    chạy tự dừng vì tưởng máy ảo chết."""
    class FakeAdb:
        instance_name = "LDPlayer"

        def run_shell(self, command, timeout=None):
            return ""

    runner = ActionRunner(
        [Step("web_click", {"selector": "#x", "timeout": 5})],
        backend=object(),
        adb_client=FakeAdb(),
    )
    result = runner.run_row(RowContext(row=2, serial="SN-001"))

    assert result.status == "ERROR"
    assert "trình duyệt" in result.message
    assert result.adb_failed is False


def test_key_step_goes_through_the_backend_when_it_has_one():
    runner, _ = _runner([Step("key", {"key": "enter"})])
    result = runner.run_row(RowContext(row=2, serial="SN-001"))

    assert result.status == "OK"
    assert runner.backend.keys == ["enter"]


def test_validation_catches_a_web_step_with_nothing_to_aim_at():
    problems = validate_steps([
        Step("web_click", {"selector": "", "text": ""}),
        Step("web_fill", {"selector": "", "value": "x"}),
        Step("web_open", {"url": ""}),
    ])
    assert len(problems) == 3
    assert all("Bước" in p for p in problems)


def test_a_fully_specified_web_recipe_validates():
    assert validate_steps([
        Step("web_open", {"url": "https://kho"}),
        Step("web_fill", {"selector": "#serial", "value": "{serial}"}),
        Step("web_click", {"selector": "#btn-tim"}),
        Step("web_wait", {"selector": "#ket-qua", "state": "visible"}),
        Step("web_read", {"selector": "#ket-qua", "var_name": "ketqua"}),
    ]) == []


# ------------------------------------------------------ worker chọn đích chạy

def _browser_worker(qapp, monkeypatch, recipe_steps=None, chrome_up=True):
    import bot_worker

    monkeypatch.setattr(
        bot_worker.browser_backend, "debugger_answers", lambda *a, **k: chrome_up
    )
    if not chrome_up:
        def refuse(self):
            raise bb.BrowserUnavailableError("Không thấy Chrome nào mở cổng 9222")
        monkeypatch.setattr(bot_worker.browser_backend.BrowserSession, "start", refuse)

    worker = bot_worker.BotWorker(
        serials=[],
        instance_name="Chrome",
        delay_seconds=0.0,
        run_target=bot_worker.TARGET_BROWSER,
        recipe_steps=recipe_steps,
    )
    errors = []
    worker.error_occurred.connect(errors.append)
    return worker, errors


def test_browser_mode_without_a_recipe_stops_and_says_why(qapp, monkeypatch):
    """Luồng 'như cũ' đọc cây view Android; chạy nó trên web là chạy vào hư không."""
    worker, errors = _browser_worker(qapp, monkeypatch)

    assert worker._select_backend() is False
    assert errors and "kịch bản" in errors[0].lower()


def test_browser_mode_stops_instead_of_falling_back_to_the_keyboard(qapp, monkeypatch):
    """
    Không có đường lui nào: gắn hụt mà gõ tiếp thì phím rơi vào cửa sổ bất kỳ
    đang ở trước - đúng thứ mà background_mode của luồng ADB cấm tiệt.
    """
    worker, errors = _browser_worker(
        qapp, monkeypatch, recipe_steps=[Step("web_click", {"selector": "#x"})],
        chrome_up=False,
    )

    assert worker._select_backend() is False
    assert worker.backend is None
    assert errors and "trình duyệt" in errors[0].lower()


# --------------------------------------------------------------- chạy thật trên Chrome

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def chrome_page(tmp_path_factory):
    """Chrome thật, chạy ẩn, profile tạm - không đụng gì tới Chrome của người dùng."""
    pytest.importorskip("playwright.sync_api")
    chrome = bb.find_chrome()
    if not chrome:
        pytest.skip("Máy này không có Chrome/Edge")

    port = _free_port()
    profile = tmp_path_factory.mktemp("chrome-profile")
    process = subprocess.Popen([
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--headless=new",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ])

    deadline = time.monotonic() + 30
    while not bb.debugger_answers(port) and time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.skip("Chrome thoát ngay khi vừa mở")
        time.sleep(0.2)
    if not bb.debugger_answers(port):
        process.kill()
        pytest.skip("Chrome không mở được cổng gỡ lỗi")

    session = bb.BrowserSession(port=port)
    session.start()
    try:
        yield session
    finally:
        session.stop()
        process.kill()


@pytest.fixture
def screen(chrome_page):
    reader = bb.BrowserScreen(chrome_page, timeout=5.0)
    reader.open_url(f"file:///{FAKE_PAGE.replace(os.sep, '/')}")
    return reader


def test_the_dump_sees_what_the_page_shows(screen):
    xml = screen.dump_xml()

    assert find_node(xml, resource_id="serial") is not None
    assert find_node(xml, text="Tìm") is not None
    # Hộp thoại đang ẩn (display:none) - không được lọt vào bản dump, nếu không
    # bước kiểm tra kết quả sẽ khớp từ khóa lỗi ngay từ dòng đầu tiên.
    assert find_node(xml, text="Không tìm thấy serial") is None


def test_clicking_the_label_inside_a_button_still_presses_the_button(screen):
    """Node có chữ là <span>, không phải <button> - trên web thì bấm span vẫn ăn."""
    screen.fill("#serial", "OK-123")
    node = screen.wait_for(text="Tìm", timeout=5)

    assert node is not None
    assert screen.tap_node(node) is True
    assert screen.wait_selector("#ket-qua:not(:empty)", timeout=5) is True
    assert "OK-123" in screen.read_selector("#ket-qua")


def test_a_button_far_below_the_fold_is_scrolled_to_and_pressed(screen):
    """Bấm theo tọa độ sẽ trượt: nút nằm ngoài khung nhìn."""
    assert screen.click("#btn-luu") is True
    assert screen.read_selector("#trang-thai-luu") == "Đã lưu phiên"


def test_a_button_that_only_enables_later_is_waited_for(screen):
    """Nút bật lên muộn 400ms - bấm ngay là bấm vào nút còn disabled."""
    screen.fill("#serial", "OK-999")
    screen.click("#btn-tim")

    assert screen.click("#btn-xuat", timeout=5) is True
    assert screen.read_selector("#ket-qua") == "Đã xuất file"


def test_a_dialog_button_under_an_overlay_still_gets_pressed(screen):
    """
    Nút "Đồng ý" bị lớp phủ che - bấm thường trượt, và bấm ép theo tọa độ cũng
    chỉ trúng lớp phủ. Kiểm bằng kết quả thật (hộp thoại đóng chưa) chứ không
    tin vào giá trị trả về, vì nấc bấm ép trả True cả khi chẳng bấm trúng gì.
    """
    screen.fill("#serial", "SAI-001")
    screen.click("#btn-tim")
    screen.wait_selector("#hop-thoai:not(.an)", timeout=5)

    xml = screen.dump_xml()
    assert "Không tìm thấy serial" in dialog_message(xml)

    assert screen.tap_node(find_dismiss_button(xml)) is True
    assert screen.wait_selector("#hop-thoai", state="hidden", timeout=5) is True


def test_the_backend_types_into_the_focused_field(screen, chrome_page):
    backend = bb.BrowserBackend(chrome_page, screen)
    screen.click("#serial")
    backend.type_serial("OK-777")
    backend.send_enter("enter")

    assert screen.wait_selector("#ket-qua:not(:empty)", timeout=5) is True
    assert "OK-777" in screen.read_selector("#ket-qua")


def test_typing_a_second_serial_replaces_the_first(screen, chrome_page):
    """Không xóa sạch ô là serial sau nối vào serial trước - dòng nào cũng sai."""
    backend = bb.BrowserBackend(chrome_page, screen)
    screen.click("#serial")
    backend.type_serial("OK-111")
    backend.type_serial("OK-222")

    assert screen.page.input_value("#serial") == "OK-222"


def test_a_whole_recipe_runs_a_row_end_to_end(screen, chrome_page):
    steps = [
        Step("web_fill", {"selector": "#serial", "value": "{serial}", "timeout": 5}),
        Step("web_click", {"selector": "#btn-tim", "timeout": 5}),
        Step("web_wait", {"selector": "#ket-qua:not(:empty)", "state": "visible", "timeout": 5}),
        Step("web_read", {"selector": "#ket-qua", "var_name": "ketqua", "timeout": 5}),
        Step("write_cell", {"column": "J", "value": "{var:ketqua}"}),
    ]
    runner = ActionRunner(steps, bb.BrowserBackend(chrome_page, screen), adb_client=None)
    result = runner.run_row(RowContext(row=2, serial="OK-555"))

    assert result.status == "OK"
    assert result.cell_writes["J"] == "Thành công: đã ghi nhận OK-555"


def test_a_failing_row_is_marked_with_the_reason_the_page_gave(screen, chrome_page):
    """Bước "Kiểm tra kết quả" của luồng ADB phải chạy y hệt trên web."""
    steps = [
        Step("web_fill", {"selector": "#serial", "value": "{serial}", "timeout": 5}),
        Step("web_click", {"selector": "#btn-tim", "timeout": 5}),
        Step("web_wait", {"selector": "#hop-thoai:not(.an)", "state": "visible", "timeout": 5}),
        Step("check", {"not_found_keywords": "không tìm thấy", "dismiss_dialog": True}),
    ]
    runner = ActionRunner(steps, bb.BrowserBackend(chrome_page, screen), adb_client=None)
    result = runner.run_row(RowContext(row=3, serial="SAI-777"))

    assert result.status == "ERROR"
    assert result.reason == "NOT_FOUND"
    assert "SAI-777" in result.response_text
    assert result.dismiss_failed is False
    # Đã đóng thật, không phải chỉ gửi lệnh xong rồi coi là xong.
    assert screen.wait_selector("#hop-thoai", state="hidden", timeout=5) is True


def test_the_screenshot_is_a_real_png(screen):
    data = screen.screenshot_png()
    assert data and data.startswith(b"\x89PNG")
