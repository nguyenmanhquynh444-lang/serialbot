import os

import pytest


@pytest.fixture(autouse=True)
def isolated_qsettings(tmp_path, monkeypatch):
    """BotGUI() dựng QSettings(APP_ORG, "SerialPasteBot") - đúng chỗ bản cài thật
    lưu cấu hình (trên Windows là registry HKCU\\Software\\SerialBotOrg).

    Không tách ra thì test chạy trên cấu hình thật của người dùng: 'last_profile'
    được nạp ngay trong __init__, nên cửa sổ đã ở một trạng thái nào đó trước khi
    test kịp chạy (profile 'kiem ke' có run_mode=pick là khóa sẵn nửa trang Cấu
    hình) - và lúc close() lại ghi đè last_excel_path cùng geometry của người ta.

    Đổi org/app hay QSettings.setDefaultFormat() đều không cứu được: PyQt6 vẫn
    dựng QSettings(org, app) ở NativeFormat, tức vẫn là registry. Nên thay hẳn
    tên QSettings trong bot_gui bằng một hàm trả về file ini riêng của từng test.
    """
    try:
        from PyQt6.QtCore import QSettings
    except ImportError:
        yield None
        return

    import bot_gui

    ini = tmp_path / "qsettings.ini"

    def throwaway_qsettings(*args, **kwargs):
        # Nuốt luôn cặp org/app gọi vào: mọi đường đều dẫn về file tạm.
        return QSettings(str(ini), QSettings.Format.IniFormat)

    monkeypatch.setattr(bot_gui, "QSettings", throwaway_qsettings)

    from version import APP_ORG

    # Chệch khỏi file tạm nghĩa là đang ghi vào cấu hình thật - hỏng test còn hơn
    # âm thầm sửa profile người dùng đang chạy việc.
    written_to = bot_gui.QSettings(APP_ORG, "SerialPasteBot").fileName()
    assert os.path.normpath(written_to) == os.path.normpath(str(ini)), written_to

    yield ini


@pytest.fixture(autouse=True)
def isolated_device_profile(tmp_path, monkeypatch):
    """
    device_profile ghi vào thư mục dữ liệu của app - chạy từ mã nguồn thì đó
    chính là thư mục dự án. Không tách ra thì test vừa rải file vào dự án, vừa
    có thể dạy nhầm bản cài thật một kết luận rút ra từ máy ảo giả.
    """
    import device_profile

    path = tmp_path / "device_profile.json"
    monkeypatch.setattr(device_profile, "profile_path", lambda: str(path))
    yield path


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """Some modules under test build QThread/QObject subclasses (BotWorker),
    which need a QApplication instance to exist in the process."""
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        yield None
        return

    app = QApplication.instance() or QApplication([])
    yield app
