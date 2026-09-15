"""
Màn hình nhận hàng chờ xen kẽ: mã sản phẩm -> serial -> mã sản phẩm -> serial...

Cả file chỉ có đúng một mã sản phẩm nên bot nhớ nó, nhưng vẫn phải gõ lại trước
từng serial vì quét xong một serial là app quay về chờ mã sản phẩm. Hai chỗ dễ
hỏng mà không lộ ra ở file kết quả, nên phải khóa lại bằng test:

- App từ chối mã sản phẩm (hết hạn, sai kho, gõ nhầm): serial gõ tiếp sẽ rơi vào
  hộp thoại và Enter đóng luôn nó, dòng đó được ghi OK trong khi chẳng có gì vào
  kho. Bot phải chấm dòng đó là lỗi và KHÔNG gõ serial.
- Hộp thoại của dòng trước tới muộn, hiện đúng lúc sắp gõ mã sản phẩm: kết luận
  phải gán về dòng đã gõ ra nó, chứ không phải dòng đang chạy.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("PyQt6")

from automation_backend import (
    GUARD_FOCUS_MARKER,
    GUARD_SKIP_MARKER,
    GUARD_TYPED_MARKER,
    AdbBackend,
)
from bot_gui import MODE_INBOUND, MODE_SERIAL, BotGUI
from bot_worker import DEFAULT_PRODUCT_CODE_DELAY_SECONDS, BotWorker, SerialItem

FOCUS_MAIN = "  mCurrentFocus=Window{abcd u0 com.app/com.app.MainActivity}"
FOCUS_DIALOG = "  mCurrentFocus=Window{efgh u0 com.app/com.app.AlertDialog}"

CLEAN_SCREEN = (
    '<?xml version="1.0"?><hierarchy>'
    '<node text="" resource-id="app:id/input" class="android.widget.EditText" '
    'bounds="[0,100][720,180]"/>'
    "</hierarchy>"
)
DIALOG_SCREEN = (
    '<?xml version="1.0"?><hierarchy>'
    '<node class="LinearLayout" bounds="[30,380][690,900]">'
    '<node text="Lỗi" bounds="[30,380][690,450]"/>'
    '<node text="Mã sản phẩm không tồn tại" bounds="[60,470][660,520]"/>'
    '<node text="OK" bounds="[280,820][440,890]" clickable="true"/>'
    "</node></hierarchy>"
)

PRODUCT_CODE = "IRVINDRV0380"


class FakeDevice:
    """
    Máy ảo giả, hiểu lệnh gộp 'soi cửa sổ rồi gõ' mà guarded_script dựng ra.

    `dialog_after` = chuỗi mà gõ xong thì app bật hộp thoại, để dựng lại đúng
    tình huống app từ chối mã sản phẩm.
    """

    def __init__(self, focus=FOCUS_MAIN, xml=CLEAN_SCREEN, dialog_after=None):
        self.instance_name = "LDPlayer"
        self.focus = focus
        self.xml = xml
        self.dialog_after = dialog_after
        self.commands = []
        self.typed = []

    def run_shell(self, command, timeout=None):
        self.commands.append(command)
        if GUARD_FOCUS_MARKER in command:
            return self._run_guarded(command)
        if "uiautomator dump" in command:
            return self.xml
        if "dumpsys window" in command:
            return self.focus
        if command.startswith("input tap") or "keyevent 66" in command:
            self.focus, self.xml = FOCUS_MAIN, CLEAN_SCREEN
        if "input text" in command:
            self._type(_typed_text(command))
        return ""

    def _run_guarded(self, command):
        lines = [GUARD_FOCUS_MARKER + self.focus]
        expected = re.search(r"\[ -n '([^']*)' \]", command).group(1)
        if expected and expected != self.focus:
            return "\n".join(lines + [GUARD_SKIP_MARKER])
        if "input text" in command:
            self._type(_typed_text(command))
        return "\n".join(lines + [GUARD_TYPED_MARKER])

    def _type(self, text):
        self.typed.append(text)
        if self.dialog_after and text.startswith(self.dialog_after):
            self.focus, self.xml = FOCUS_DIALOG, DIALOG_SCREEN


def _typed_text(command: str) -> str:
    return re.search(r"input text '([^']*)'", command).group(1)


def make_worker(device, **overrides) -> BotWorker:
    kwargs = dict(
        serials=[SerialItem(row=2, value="A1")],
        instance_name="LDPlayer",
        delay_seconds=0.0,
        verify_result=True,
        error_keywords="loi",
        not_found_keywords="không tồn tại",
        response_timeout=0.1,
        product_code=PRODUCT_CODE,
        product_code_delay=0.0,
    )
    kwargs.update(overrides)
    worker = BotWorker(**kwargs)
    worker.adb_client = device

    backend = AdbBackend(device)
    assert backend.probe_guard()
    worker.backend = backend
    device.commands.clear()
    return worker


def sent(device) -> list[str]:
    """Chuỗi đã gõ, bỏ ký tự Enter gộp cuối để so cho gọn."""
    return [text.rstrip("\n") for text in device.typed]


# --- nhịp gõ ----------------------------------------------------------------

def test_every_serial_is_preceded_by_the_product_code(qapp):
    device = FakeDevice()
    worker = make_worker(
        device, serials=[SerialItem(row=r, value=f"A{r}") for r in (2, 3, 4)]
    )
    worker.run()

    assert sent(device) == [
        PRODUCT_CODE, "A2",
        PRODUCT_CODE, "A3",
        PRODUCT_CODE, "A4",
    ]


def test_an_empty_product_code_keeps_the_old_behaviour(qapp):
    device = FakeDevice()
    worker = make_worker(device, product_code="")
    worker.run()

    assert sent(device) == ["A1"]


def test_the_product_code_is_cleaned_the_same_way_serials_are(qapp):
    """Dán từ Excel hay tin nhắn hay dính khoảng trắng - gõ nguyên là app không nhận."""
    device = FakeDevice()
    worker = make_worker(device, product_code=f"  {PRODUCT_CODE} ")
    worker.run()

    assert sent(device) == [PRODUCT_CODE, "A1"]


def test_the_serial_and_the_code_are_two_separate_trips(qapp):
    """
    Gộp cả hai vào một lệnh thì tiết kiệm được một lượt ADB, nhưng serial sẽ đi
    ra bất kể hộp thoại vừa bật lên vì mã sản phẩm - mất luôn lớp chốt cửa sổ.
    """
    device = FakeDevice()
    worker = make_worker(device)
    worker._dialog_seen_by_dumpsys = True
    worker._clean_focus_raw = FOCUS_MAIN

    worker._process_serial(2, "A1")

    typing = [c for c in device.commands if "input text" in c]
    assert len(typing) == 2
    assert PRODUCT_CODE in typing[0] and "A1" not in typing[0]
    assert "A1" in typing[1]


# --- app từ chối mã sản phẩm -------------------------------------------------

def test_a_rejected_product_code_stops_the_serial_from_being_typed(qapp):
    device = FakeDevice(dialog_after=PRODUCT_CODE)
    worker = make_worker(device)
    worker._dialog_seen_by_dumpsys = True         # đã biết hộp thoại đổi cửa sổ

    result = worker._process_serial(2, "A1")

    assert result["status"] == "ERROR"
    assert "CHƯA được gõ" in result["message"]
    assert sent(device) == [PRODUCT_CODE]         # serial không đi đâu cả
    assert "không tồn tại" in result["response_text"]


def test_a_rejected_product_code_closes_the_dialog_before_the_next_row(qapp):
    """Không đóng thì dòng sau gõ vào màn hình đang kẹt và hỏng dây chuyền."""
    device = FakeDevice(dialog_after=PRODUCT_CODE)
    worker = make_worker(device)
    worker._dialog_seen_by_dumpsys = True

    result = worker._process_serial(2, "A1")

    assert not result.get("dismiss_failed")
    assert any(c.startswith("input tap") for c in device.commands)


def test_the_row_is_published_as_an_error_row(qapp):
    device = FakeDevice(dialog_after=PRODUCT_CODE)
    worker = make_worker(device)
    worker._dialog_seen_by_dumpsys = True

    results = []
    worker.result_ready.connect(results.append)
    worker.run()

    assert [r["row"] for r in results] == [2]
    assert results[0]["status"] == "ERROR"
    assert PRODUCT_CODE in results[0]["message"]


# --- hộp thoại của dòng trước tới muộn ---------------------------------------

def test_a_dialog_waiting_before_the_code_is_charged_to_the_previous_row(qapp):
    """
    Hộp thoại đã hiện TRƯỚC lúc gõ mã sản phẩm = trả lời cho serial dòng trước,
    không phải cho mã sản phẩm. Gán nhầm về dòng này là dòng kia được OK oan.
    """
    device = FakeDevice(focus=FOCUS_DIALOG, xml=DIALOG_SCREEN)
    worker = make_worker(device)
    worker._dialog_seen_by_dumpsys = True
    worker._clean_focus_raw = FOCUS_MAIN
    worker._clean_focus = "abcd u0 com.app/com.app.MainActivity"
    worker._previous_row = 2
    worker._previous_serial = "A1"

    result = worker._process_serial(3, "A2")

    row, verdict = worker._pending_correction
    assert row == 2
    assert verdict["status"] == "ERROR"
    assert result["status"] != "ERROR"                    # dòng này vẫn chạy được
    assert sent(device) == [PRODUCT_CODE, "A2"]           # đóng xong là gõ tiếp


# --- giao diện ---------------------------------------------------------------

@pytest.fixture
def gui(qapp, tmp_path, monkeypatch):
    import bot_gui

    monkeypatch.setattr(bot_gui, "SCREENSHOT_DIR", str(tmp_path))
    window = BotGUI()
    yield window
    window.close()


def test_the_product_code_box_belongs_to_the_serial_mode_only(gui):
    """Luồng theo phiên tự quyết gõ gì vào đâu - để ô này là mời điền thừa."""
    # isHidden() chứ không phải isVisible(): cửa sổ chưa show() trong test nên
    # mọi widget đều "không nhìn thấy", chỉ cờ ẩn của chính nó mới nói lên điều gì.
    gui.run_mode_combo.setCurrentIndex(gui.run_mode_combo.findData(MODE_INBOUND))
    assert gui.product_box.isHidden()
    assert not gui.pick_box.isHidden()

    gui.run_mode_combo.setCurrentIndex(gui.run_mode_combo.findData(MODE_SERIAL))
    assert not gui.product_box.isHidden()
    assert gui.pick_box.isHidden()


def test_the_product_code_survives_a_profile_round_trip(gui):
    gui.product_code_input.setText(PRODUCT_CODE)
    gui.product_delay_input.setValue(0.8)

    values = gui._collect_profile_values()
    other = BotGUI()
    try:
        other._apply_profile_values(values)
        assert other.product_code_input.text() == PRODUCT_CODE
        assert other.product_delay_input.value() == pytest.approx(0.8)
    finally:
        other.close()


def test_an_old_profile_gets_the_default_delay_not_zero(gui):
    """Khóa này chưa có trong profile cũ; rơi về 0 là gõ serial sớm hàng loạt."""
    gui._apply_profile_values({"column": "H"})

    assert gui.product_code_input.text() == ""
    assert gui.product_delay_input.value() == pytest.approx(
        DEFAULT_PRODUCT_CODE_DELAY_SECONDS
    )


def test_a_paste_only_confirm_key_blocks_the_run(gui, monkeypatch):
    """Không có Enter thì mã sản phẩm nằm lại trong ô và serial nối vào sau nó."""
    warned = []
    monkeypatch.setattr(
        "bot_gui.QMessageBox.warning", lambda *args, **kwargs: warned.append(args)
    )
    gui.product_code_input.setText(PRODUCT_CODE)
    gui.enter_mode_combo.setCurrentIndex(gui.enter_mode_combo.findData("none"))

    assert gui._product_code_is_usable() is False
    assert warned

    gui.enter_mode_combo.setCurrentIndex(gui.enter_mode_combo.findData("enter"))
    assert gui._product_code_is_usable() is True


def test_a_recipe_run_says_so_instead_of_silently_dropping_the_code(gui, monkeypatch):
    """Kịch bản chạy đường riêng, không đi qua chỗ gõ mã sản phẩm."""
    monkeypatch.setattr("bot_gui.QMessageBox.warning", lambda *args, **kwargs: None)
    gui.product_code_input.setText(PRODUCT_CODE)
    gui.recipe_combo.addItem("classic", "classic")
    gui.recipe_combo.setCurrentIndex(gui.recipe_combo.findData("classic"))

    assert gui._product_code_is_usable() is False
