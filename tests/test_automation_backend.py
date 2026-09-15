import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import automation_backend
from automation_backend import AdbClient, shell_quote


def test_shell_quote_plain_value():
    assert shell_quote("ABC123") == "'ABC123'"


def test_shell_quote_escapes_single_quote():
    assert shell_quote("a'b") == "'a'\\''b'"


def test_shell_quote_wraps_metacharacters_in_single_quotes():
    dangerous = "a; rm -rf /; echo $(whoami)"
    quoted = shell_quote(dangerous)
    assert quoted == "'" + dangerous + "'"
    assert quoted.startswith("'") and quoted.endswith("'")


# --- chọn đường gọi ADB ------------------------------------------------------
#
# ldconsole.exe cũng chỉ đi gọi lại adb, nên mỗi lệnh qua nó là thừa một lần dựng
# tiến trình. Nhưng chỉ ldconsole mới biết tên instance nào ứng với máy ảo nào,
# nên không bỏ được khi nhiều máy cùng chạy.

class _FakeRun:
    """Ghi lại mọi lần subprocess.run và trả lời theo kịch bản đặt trước."""

    def __init__(self, devices_output, rc=0, stdout="ok"):
        self.devices_output = devices_output
        self.rc = rc
        self.stdout = stdout
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd[1:] == ["devices"]:
            return subprocess.CompletedProcess(cmd, 0, self.devices_output, "")
        return subprocess.CompletedProcess(cmd, self.rc, self.stdout, "")

    def programs(self):
        return [os.path.basename(c[0]).lower() for c in self.calls]


def _client(monkeypatch, fake):
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(automation_backend.subprocess, "run", fake)
    client = AdbClient("LDPlayer")
    monkeypatch.setattr(client, "_find_adb", lambda: r"C:\fake\adb.exe")
    monkeypatch.setattr(client, "_find_ldconsole", lambda: r"C:\fake\ldconsole.exe")
    return client


ONE_DEVICE = "List of devices attached\nemulator-5554\tdevice\n"
TWO_DEVICES = "List of devices attached\nemulator-5554\tdevice\nemulator-5556\tdevice\n"


def test_single_device_skips_ldconsole_entirely(monkeypatch):
    fake = _FakeRun(ONE_DEVICE)
    client = _client(monkeypatch, fake)

    assert client.run_shell("true") == "ok"

    assert "ldconsole.exe" not in fake.programs()
    assert fake.calls[-1] == [r"C:\fake\adb.exe", "-s", "emulator-5554", "shell", "true"]


def test_device_lookup_happens_once_not_per_command(monkeypatch):
    fake = _FakeRun(ONE_DEVICE)
    client = _client(monkeypatch, fake)

    for _ in range(5):
        client.run_shell("true")

    assert sum(1 for c in fake.calls if c[1:] == ["devices"]) == 1


def test_several_devices_are_told_apart_by_instance_index(monkeypatch):
    """
    Nhiều máy ảo vẫn phải gọi thẳng adb: đi qua ldconsole thì chậm thêm ~430ms
    mỗi lệnh và tiếng Việt bị hỏng. ldconsole đánh số index 0 -> emulator-5554,
    index 1 -> emulator-5556, nên tra được đúng thiết bị của từng instance.
    """
    fake = _FakeRun(TWO_DEVICES)
    monkeypatch.setattr(
        automation_backend, "list_ldplayer_instances",
        lambda: [{"index": "0", "name": "LDPlayer", "running": True},
                 {"index": "1", "name": "LDPlayer-1", "running": True}],
    )

    client = _client(monkeypatch, fake)
    assert client.run_shell("true") == "ok"
    assert fake.calls[-1] == [r"C:\fake\adb.exe", "-s", "emulator-5554", "shell", "true"]
    assert "ldconsole.exe" not in fake.programs()

    other = _client(monkeypatch, fake)
    other.instance_name = "LDPlayer-1"
    assert other.run_shell("true") == "ok"
    assert fake.calls[-1] == [r"C:\fake\adb.exe", "-s", "emulator-5556", "shell", "true"]


def test_unknown_instance_name_falls_back_to_ldconsole(monkeypatch):
    """Tên không khớp instance nào (người dùng gõ tên cửa sổ) thì đừng đoán bừa
    máy nào - gửi nhầm máy là serial chạy sang phiên kiểm đếm khác."""
    fake = _FakeRun(TWO_DEVICES)
    monkeypatch.setattr(
        automation_backend, "list_ldplayer_instances",
        lambda: [{"index": "0", "name": "May chinh", "running": True}],
    )

    client = _client(monkeypatch, fake)
    assert client.run_shell("true") == "ok"

    assert fake.calls[-1][0] == r"C:\fake\ldconsole.exe"
    assert "--name" in fake.calls[-1] and "LDPlayer" in fake.calls[-1]


def test_empty_device_list_is_retried_not_remembered(monkeypatch):
    """
    Bot hay được mở trước lúc LDPlayer boot xong. Nhớ luôn kết quả "chưa có máy
    nào" thì cả phiên chạy phải đi vòng qua ldconsole dù sau đó máy đã lên.
    """
    fake = _FakeRun("List of devices attached\n")
    client = _client(monkeypatch, fake)

    client.run_shell("true")
    assert client._direct_target is None

    fake.devices_output = ONE_DEVICE
    client.run_shell("true")

    assert client._direct_target == "emulator-5554"
    assert fake.calls[-1] == [r"C:\fake\adb.exe", "-s", "emulator-5554", "shell", "true"]


def test_direct_failure_falls_back_to_ldconsole(monkeypatch):
    fake = _FakeRun(ONE_DEVICE, rc=1, stdout="")
    client = _client(monkeypatch, fake)

    client.run_shell("true")

    assert "ldconsole.exe" in fake.programs()
