"""
paths.py
Tách thư mục tài nguyên chỉ-đọc khỏi thư mục dữ liệu ghi được.

Khi app đã được cài (Program Files) hoặc chạy từ bản one-file của PyInstaller,
thư mục cạnh file .exe hoặc là chỉ-đọc, hoặc bị xóa lúc thoát. Nên mọi thứ app
ghi ra - log, ảnh chụp, kịch bản người dùng lưu - phải nằm trong
%LOCALAPPDATA%\\SerialBot. Chạy từ mã nguồn thì vẫn ghi cạnh dự án như cũ để
không đổi thói quen lúc phát triển.
"""
import os
import shutil
import sys

APP_DATA_NAME = "SerialBot"

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> str:
    """Thư mục chứa file đi kèm, chỉ đọc (assets/, kịch bản mặc định)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return _PROJECT_DIR


def user_data_dir() -> str:
    """Thư mục ghi được của người dùng hiện tại."""
    if not is_frozen():
        return _PROJECT_DIR
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, APP_DATA_NAME)


def _sub(name: str) -> str:
    path = os.path.join(user_data_dir(), name)
    os.makedirs(path, exist_ok=True)
    return path


def logs_dir() -> str:
    return _sub("logs")


def screenshots_dir() -> str:
    return _sub("screenshots")


def recipes_dir() -> str:
    return _sub("recipes")


def seed_bundled_recipes() -> None:
    """
    Chép kịch bản mặc định từ bản cài sang thư mục người dùng nếu chưa có.
    Chỉ chép file còn thiếu, không ghi đè kịch bản người dùng đã sửa.
    """
    source = os.path.join(resource_dir(), "recipes")
    target = recipes_dir()
    if os.path.normcase(source) == os.path.normcase(target) or not os.path.isdir(source):
        return

    for filename in os.listdir(source):
        if not filename.lower().endswith(".json"):
            continue
        destination = os.path.join(target, filename)
        if os.path.exists(destination):
            continue
        try:
            shutil.copyfile(os.path.join(source, filename), destination)
        except OSError:
            pass
