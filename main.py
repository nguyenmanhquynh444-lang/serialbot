"""
main.py
Entry point for the Serial Paste Bot.
"""
import sys

from PyQt6.QtCore import QSharedMemory
from PyQt6.QtWidgets import QApplication, QMessageBox

from app_icons import app_icon
from bot_gui import BotGUI
from logger_setup import setup_logging
from version import APP_NAME, APP_ORG, APP_VERSION

SINGLE_INSTANCE_KEY = "SerialPasteBot.SingleInstance"

# Tên mutex Windows, khớp với AppMutex trong installer/SerialPasteBot.iss:
# nhờ nó bộ cài/gỡ phát hiện được app đang chạy và nhắc đóng, thay vì thay file
# đang bị khóa rồi lỗi giữa chừng.
SETUP_MUTEX_NAME = "SerialPasteBotSetupMutex"
_setup_mutex = None


def _hold_setup_mutex():
    """Giữ mutex suốt vòng đời tiến trình; bỏ qua nếu không phải Windows."""
    global _setup_mutex
    if sys.platform != "win32":
        return
    try:
        import ctypes

        _setup_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, SETUP_MUTEX_NAME)
    except (OSError, AttributeError):
        _setup_mutex = None


def main():
    _hold_setup_mutex()
    setup_logging()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_ORG)
    app.setWindowIcon(app_icon())

    # Two copies of the bot would drive the same LDPlayer instance over ADB and
    # interleave their keystrokes, so refuse to start a second one.
    guard = QSharedMemory(SINGLE_INSTANCE_KEY)
    if not guard.create(1):
        QMessageBox.warning(
            None,
            APP_NAME,
            f"{APP_NAME} đang chạy rồi.\n\n"
            "Không thể mở hai cửa sổ cùng lúc vì chúng sẽ gửi lệnh chồng nhau "
            "vào cùng một máy ảo LDPlayer.",
        )
        return 1

    window = BotGUI()
    window.show()

    exit_code = app.exec()
    guard.detach()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
