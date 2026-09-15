"""
Tìm ldconsole.exe / adb.exe của LDPlayer.

Đây là thứ quyết định bot có chạy nổi trên một máy khác hay không. Đường dẫn
từng ghi cứng vào ổ C, nên máy nào cài LDPlayer sang ổ D là chết ngay ở bước kết
nối - mà luồng xuất kho không có đường lui gõ bàn phím, chết ở đây là không chạy
được gì cả.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import automation_backend as ab
from automation_backend import (
    LDPLAYER_DIR_ENV,
    find_ldplayer_tool,
    ldplayer_candidate_dirs,
)


def test_env_override_is_looked_at_first(monkeypatch):
    """Người dùng đã chỉ tận nơi thì không việc gì phải đoán tiếp."""
    monkeypatch.setenv(LDPLAYER_DIR_ENV, r"D:\Games\LDPlayer9")
    monkeypatch.setattr(ab, "_registry_install_dirs", lambda: [])

    assert ldplayer_candidate_dirs()[0] == r"D:\Games\LDPlayer9"


def test_env_override_tolerates_quotes(monkeypatch):
    """Dán đường dẫn từ Explorer hay dính sẵn dấu nháy."""
    monkeypatch.setenv(LDPLAYER_DIR_ENV, '"D:\\LDPlayer\\LDPlayer9"')
    monkeypatch.setattr(ab, "_registry_install_dirs", lambda: [])

    assert ldplayer_candidate_dirs()[0] == r"D:\LDPlayer\LDPlayer9"


def test_registry_location_beats_the_guessed_paths(monkeypatch):
    """Chỗ Windows ghi lúc cài đáng tin hơn danh sách phỏng đoán."""
    monkeypatch.delenv(LDPLAYER_DIR_ENV, raising=False)
    monkeypatch.setattr(ab, "_registry_install_dirs", lambda: [r"E:\LD\LDPlayer9"])

    dirs = ldplayer_candidate_dirs()
    assert dirs[0] == r"E:\LD\LDPlayer9"
    assert any("LDPlayer9" in d and d.startswith("C:") for d in dirs)   # vẫn dò tiếp


def test_other_drives_are_searched_not_just_c(monkeypatch):
    """Đúng cái làm bot chết khi chuyển sang máy khác."""
    monkeypatch.delenv(LDPLAYER_DIR_ENV, raising=False)
    monkeypatch.setattr(ab, "_registry_install_dirs", lambda: [])

    dirs = [os.path.normcase(d) for d in ldplayer_candidate_dirs()]
    assert os.path.normcase(r"D:\LDPlayer\LDPlayer9") in dirs
    assert os.path.normcase(r"D:\Program Files\LDPlayer\LDPlayer9") in dirs


def test_the_same_folder_is_not_probed_twice(monkeypatch):
    """Registry trỏ đúng chỗ đã đoán sẵn thì đừng kiểm hai lần."""
    monkeypatch.setenv(LDPLAYER_DIR_ENV, r"C:\LDPlayer\LDPlayer9")
    monkeypatch.setattr(ab, "_registry_install_dirs", lambda: [r"C:\LDPlayer\LDPlayer9\\"])

    keys = [os.path.normcase(os.path.normpath(d)) for d in ldplayer_candidate_dirs()]
    assert len(keys) == len(set(keys))


def test_missing_everywhere_returns_none_instead_of_a_bad_path(monkeypatch):
    """
    Trả về đường dẫn không tồn tại thì lỗi nổ ở tận lúc gọi subprocess, đọc
    không ra gì. Trả None để bên gọi báo đúng câu 'chưa tìm thấy LDPlayer'.
    """
    monkeypatch.setattr(ab, "ldplayer_candidate_dirs", lambda: [r"Z:\khong-co"])
    monkeypatch.setattr(ab.shutil, "which", lambda name: None)

    assert find_ldplayer_tool("ldconsole.exe") is None


def test_adb_can_come_from_path_when_ldplayer_is_elsewhere(monkeypatch):
    """Máy có Android SDK riêng thì dùng luôn, khỏi cần LDPlayer đúng chỗ."""
    monkeypatch.setattr(ab, "ldplayer_candidate_dirs", lambda: [r"Z:\khong-co"])
    monkeypatch.setattr(ab.shutil, "which", lambda name: r"C:\sdk\platform-tools\adb.exe")

    assert find_ldplayer_tool("adb.exe") == r"C:\sdk\platform-tools\adb.exe"
    # ldconsole thì không có trên PATH bao giờ - đừng nhận bừa adb thay nó.
    assert find_ldplayer_tool("ldconsole.exe") is None


def test_registry_lookup_never_raises(monkeypatch):
    """
    Registry là thứ ngoài tầm kiểm soát: khóa thiếu giá trị, thiếu quyền đọc,
    máy không phải Windows. Hỏng thì trả danh sách rỗng chứ không được ném lỗi
    làm sập cả app lúc khởi động.
    """
    monkeypatch.setattr(ab.os, "name", "posix")
    assert ab._registry_install_dirs() == []


# --- danh sách máy ảo --------------------------------------------------------
#
# Hai test dưới gọi THẲNG list_ldplayer_instances(), không monkeypatch chính nó.
# Mọi test khác đều thay hàm này bằng bản giả, nên khi thân hàm còn tham chiếu
# một hằng số đã bị xóa lúc refactor (LDCONSOLE_PATHS), cả bộ test vẫn xanh trong
# lúc nút Refresh ngoài app ném NameError.

def test_instance_list_is_empty_when_ldconsole_is_missing(monkeypatch):
    monkeypatch.setattr(ab, "find_ldplayer_tool", lambda name: None)

    assert ab.list_ldplayer_instances() == []


def test_instance_list_parses_ldconsole_output(monkeypatch):
    """`list2` in ra: index,tên,handle,handle,đang-chạy,..."""
    monkeypatch.setattr(ab, "find_ldplayer_tool", lambda name: r"C:\LDPlayer\ldconsole.exe")

    class _Result:
        stdout = "0,LDPlayer,0,0,1,0\n1,LDPlayer-1,0,0,0,0\n"

    monkeypatch.setattr(ab.subprocess, "run", lambda *a, **kw: _Result())

    assert ab.list_ldplayer_instances() == [
        {"index": "0", "name": "LDPlayer", "running": True},
        {"index": "1", "name": "LDPlayer-1", "running": False},
    ]
