"""
Đường lui gõ bàn phím không được để phím rơi vào cửa sổ khác.

pyautogui bắn phím vào hàng đợi input của cả Windows chứ không gửi tới một cửa
sổ cụ thể, nên mọi lớp bảo vệ ở đây đều quy về đúng một câu hỏi: ngay lúc gõ,
cửa sổ đang foreground có phải máy ảo không. Các test dưới dựng lại đúng những
tình huống đã làm serial lọt ra ngoài.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import automation_backend
from automation_backend import PyAutoGuiBackend, WindowFocusError


class FakePyAutoGui:
    FAILSAFE = True
    PAUSE = 0.0

    def __init__(self):
        self.typed = []

    def hotkey(self, *keys):
        self.typed.append(("hotkey", keys))

    def press(self, key):
        self.typed.append(("press", key))

    def write(self, text, interval=0):
        self.typed.append(("write", text))


class FakeWindow:
    def __init__(self, title, desktop, activatable=True):
        self.title = title
        self.isMinimized = False
        self.activated = 0
        self._desktop = desktop
        self._activatable = activatable

    def restore(self):
        self.isMinimized = False

    def activate(self):
        self.activated += 1
        if self._activatable:
            self._desktop.foreground = self.title


class FakeDesktop:
    """Bắt chước pygetwindow: getWindowsWithTitle khớp CHUỖI CON như bản thật."""

    def __init__(self, titles, foreground="", activatable=True):
        self.windows = [FakeWindow(t, self, activatable) for t in titles]
        self.foreground = foreground

    def getWindowsWithTitle(self, title):
        return [w for w in self.windows if title in w.title]

    def getActiveWindow(self):
        for w in self.windows:
            if w.title == self.foreground:
                return w
        return None


@pytest.fixture
def gui(monkeypatch):
    fake = FakePyAutoGui()
    monkeypatch.setattr(automation_backend, "pyautogui", fake)
    return fake


def make_backend(monkeypatch, desktop, name="LDPlayer"):
    """Backend với foreground đọc từ desktop giả, không đụng tới user32 thật."""
    monkeypatch.setattr(automation_backend, "gw", desktop)
    backend = PyAutoGuiBackend(name)
    monkeypatch.setattr(backend, "_foreground_title", lambda: desktop.foreground)
    return backend


# --- soi lại foreground trước MỖI serial ------------------------------------

def test_rechecks_focus_before_every_serial(gui, monkeypatch):
    """
    Nhớ 'đã focus rồi' từ serial đầu là các serial sau gõ mù.

    Máy ảo vẫn đưa lên trước được, nên dòng thứ hai phải chạy tiếp - nhưng chỉ
    sau khi đã tự kéo cửa sổ lên, chứ không phải gõ thẳng vào Excel.
    """
    desktop = FakeDesktop(["LDPlayer"], foreground="LDPlayer")
    backend = make_backend(monkeypatch, desktop)
    window = desktop.windows[0]

    backend.type_serial("SERIAL-001")
    assert window.activated == 0        # đã ở trước sẵn, không cần kéo

    # Người dùng alt-tab sang Excel giữa hai dòng.
    desktop.foreground = "bang ke.xlsx - Excel"
    backend.type_serial("SERIAL-002")

    assert window.activated == 1        # đã soi lại và kéo về, không gõ mù
    assert desktop.foreground == "LDPlayer"
    assert gui.typed[-1] == ("write", "SERIAL-002")


def test_focus_lost_mid_typing_is_reported(gui, monkeypatch):
    """Focus bị cướp giữa lúc gõ: một phần serial đã sang cửa sổ khác."""
    desktop = FakeDesktop(["LDPlayer"], foreground="LDPlayer")
    backend = make_backend(monkeypatch, desktop)

    def steal(text, interval=0):
        gui.typed.append(("write", text))
        desktop.foreground = "Zalo"

    monkeypatch.setattr(gui, "write", steal)

    with pytest.raises(WindowFocusError):
        backend.type_serial("SERIAL-003")


def test_send_enter_also_checks_focus(gui, monkeypatch):
    desktop = FakeDesktop(["LDPlayer"], foreground="Zalo")
    backend = make_backend(monkeypatch, desktop)
    # Cửa sổ máy ảo không tồn tại nữa, và Zalo đang ở trước.
    desktop.windows = []

    with pytest.raises(WindowFocusError):
        backend.send_enter("enter")

    assert gui.typed == []


def test_send_enter_none_mode_needs_no_window(gui, monkeypatch):
    """mode='none' không gõ gì nên không cần cửa sổ nào cả."""
    desktop = FakeDesktop([], foreground="Excel")
    backend = make_backend(monkeypatch, desktop)

    backend.send_enter("none")

    assert gui.typed == []


# --- khớp tiêu đề cửa sổ -----------------------------------------------------

def test_does_not_type_into_a_chrome_tab_named_after_the_emulator(gui, monkeypatch):
    """'serial LDPlayer - Google Chrome' đứng trước máy ảo thật trong danh sách."""
    desktop = FakeDesktop(
        ["serial LDPlayer - Google Chrome", "LDPlayer"],
        foreground="serial LDPlayer - Google Chrome",
    )
    backend = make_backend(monkeypatch, desktop)

    backend.type_serial("SERIAL-004")

    chrome, emulator = desktop.windows
    assert chrome.activated == 0
    assert emulator.activated == 1
    assert desktop.foreground == "LDPlayer"


def test_does_not_type_into_a_different_instance(gui, monkeypatch):
    """'LDPlayer' không được nuốt 'LDPlayer-1' - đó là phiên kiểm đếm khác."""
    desktop = FakeDesktop(["LDPlayer-1"], foreground="LDPlayer-1")
    backend = make_backend(monkeypatch, desktop)

    with pytest.raises(WindowFocusError):
        backend.type_serial("SERIAL-005")

    assert gui.typed == []


def test_accepts_title_with_suffix_after_a_space(gui, monkeypatch):
    """LDPlayer hay treo thêm hậu tố vào tiêu đề; đó vẫn là đúng máy ảo."""
    desktop = FakeDesktop(["LDPlayer - 64bit"], foreground="LDPlayer - 64bit")
    backend = make_backend(monkeypatch, desktop)

    backend.type_serial("SERIAL-006")

    assert ("write", "SERIAL-006") in gui.typed


# --- activate() nói dối ------------------------------------------------------

def test_activate_that_silently_fails_does_not_type(gui, monkeypatch):
    """
    Windows thường từ chối SetForegroundWindow: chỉ nháy taskbar, không đổi
    foreground, mà pygetwindow không báo lỗi gì.
    """
    desktop = FakeDesktop(["LDPlayer"], foreground="Zalo", activatable=False)
    backend = make_backend(monkeypatch, desktop)
    monkeypatch.setattr(backend, "FOCUS_SETTLE_SECONDS", 0.0)

    with pytest.raises(WindowFocusError) as e:
        backend.type_serial("SERIAL-007")

    assert "Zalo" in str(e.value)
    assert gui.typed == []


def test_activate_that_raises_does_not_type(gui, monkeypatch):
    desktop = FakeDesktop(["LDPlayer"], foreground="Zalo")
    backend = make_backend(monkeypatch, desktop)
    monkeypatch.setattr(backend, "FOCUS_SETTLE_SECONDS", 0.0)

    def boom():
        raise OSError("access denied")

    desktop.windows[0].activate = boom

    with pytest.raises(WindowFocusError):
        backend.type_serial("SERIAL-008")

    assert gui.typed == []


def test_minimized_window_is_restored_then_typed(gui, monkeypatch):
    desktop = FakeDesktop(["LDPlayer"], foreground="Zalo")
    backend = make_backend(monkeypatch, desktop)
    monkeypatch.setattr(backend, "FOCUS_SETTLE_SECONDS", 0.0)
    desktop.windows[0].isMinimized = True

    backend.type_serial("SERIAL-009")

    assert desktop.windows[0].isMinimized is False
    assert ("write", "SERIAL-009") in gui.typed


def test_no_window_manager_refuses_to_type(gui, monkeypatch):
    """Thiếu pygetwindow thì không biết gì về cửa sổ - không được gõ liều."""
    monkeypatch.setattr(automation_backend, "gw", None)
    backend = PyAutoGuiBackend("LDPlayer")
    monkeypatch.setattr(backend, "_foreground_title", lambda: "Excel")

    with pytest.raises(WindowFocusError):
        backend.type_serial("SERIAL-010")

    assert gui.typed == []
