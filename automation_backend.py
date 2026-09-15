"""
automation_backend.py
Pluggable input backends for sending a serial into the target app.

AdbBackend talks to the Android app directly over ADB (no window focus
needed, works while the bot runs in the background). PyAutoGuiBackend
keeps the original keyboard-simulation approach as a fallback for setups
without a working adb/ldconsole install.
"""
import logging
import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import pyautogui

logger = logging.getLogger(__name__)

try:
    import pygetwindow as gw
except ImportError:
    gw = None


# LDPlayer không có chỗ cài cố định: máy này C:\LDPlayer\LDPlayer9, máy kia
# D:\Program Files\LDPlayer\LDPlayer9. Trước đây danh sách này ghi cứng ổ C nên
# chuyển bot sang máy khác là chết ngay ở bước kết nối ADB, mà luồng xuất kho
# không có đường lui nào khác.
#
# Thứ tự dò, chắc chắn dần: biến môi trường người dùng tự đặt -> Registry (chỗ
# Windows ghi khi cài) -> mấy chỗ cài quen thuộc.
LDPLAYER_DIR_ENV = "LDPLAYER_DIR"
_LDPLAYER_SUBDIRS = ("LDPlayer9", "LDPlayer64", "LDPlayer4.0")
_LDPLAYER_PARENTS = ("LDPlayer", r"Program Files\LDPlayer", r"Program Files (x86)\LDPlayer")
_LDPLAYER_DRIVES = ("C:", "D:", "E:")


def _registry_install_dirs() -> list[str]:
    """Thư mục cài LDPlayer đọc từ mục Gỡ cài đặt trong Registry."""
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    hives = (
        (winreg.HKEY_LOCAL_MACHINE, uninstall),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node" + uninstall[len("SOFTWARE"):]),
        (winreg.HKEY_CURRENT_USER, uninstall),
    )

    found = []
    for hive, path in hives:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, index)) as entry:
                        name = str(winreg.QueryValueEx(entry, "DisplayName")[0])
                        if "ldplayer" not in name.lower():
                            continue
                        location = str(winreg.QueryValueEx(entry, "InstallLocation")[0]).strip()
                        if location:
                            found.append(location)
                except OSError:
                    continue        # khóa thiếu giá trị là chuyện thường
    return found


def ldplayer_candidate_dirs() -> list[str]:
    """Mọi thư mục có thể chứa ldconsole.exe / adb.exe, theo thứ tự ưu tiên."""
    dirs = []
    override = os.environ.get(LDPLAYER_DIR_ENV, "").strip().strip('"')
    if override:
        dirs.append(override)
    dirs.extend(_registry_install_dirs())
    for drive in _LDPLAYER_DRIVES:
        for parent in _LDPLAYER_PARENTS:
            base = os.path.join(drive + "\\", parent)
            dirs.append(base)
            dirs.extend(os.path.join(base, sub) for sub in _LDPLAYER_SUBDIRS)

    unique = []
    seen = set()
    for path in dirs:
        key = os.path.normcase(os.path.normpath(path))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def find_ldplayer_tool(filename: str) -> str | None:
    """
    Tìm một file của LDPlayer. Trả None nếu không thấy ở đâu cả.

    `adb.exe` còn tra thêm PATH: máy nào cài Android SDK riêng thì dùng được
    luôn, khỏi cần LDPlayer đúng chỗ.
    """
    for directory in ldplayer_candidate_dirs():
        candidate = os.path.join(directory, filename)
        if os.path.exists(candidate):
            return candidate
    if filename.lower().startswith("adb"):
        return shutil.which("adb")
    return None

DEFAULT_TIMEOUT_SECONDS = 8
CLEAR_DEL_COUNT = 20
KEYCODE_MOVE_END = "123"
KEYCODE_CLEAR = "28"
KEYCODE_DEL = "67"
KEYCODE_TAB = "61"
KEYCODE_ENTER = "66"

# Ký tự xuống dòng nằm trong chuỗi của `input text` được máy ảo dịch thành đúng
# KEYCODE_ENTER: bảng ký tự của bàn phím ảo (/system/usr/keychars/Virtual.kcm)
# khai báo `key ENTER { base: '\n' }`, và `input text` chính là tra bảng đó rồi
# bắn ra key event. Gộp được như vậy thì gõ và xác nhận gọn trong MỘT lần gọi
# `input` thay vì hai - mỗi lần gọi là một lần máy ảo dựng tiến trình Java.
#
# Nhưng đây là thứ không được tin theo lý thuyết: máy ảo nào dịch hụt thì serial
# nằm nguyên trong ô, app chưa quét gì mà bot vẫn ghi OK. Nên lối này chỉ bật sau
# khi BotWorker nhìn tận mắt một dòng (xem BotWorker._confirm_text_submit).
TEXT_SUBMIT_SUFFIX = "\n"

# Lệnh đọc cửa sổ đang focus, rút gọn còn đúng dòng cần dùng để so sánh.
FOCUS_LINE_COMMAND = "dumpsys window windows | grep mCurrentFocus | head -n1"

# Nhãn đánh dấu trong output của lệnh gõ có kèm chốt cửa sổ. Chọn chuỗi không thể
# trùng với chữ trên màn hình app.
GUARD_FOCUS_MARKER = "__BOTF__"
GUARD_TYPED_MARKER = "__BOTTYPED__"
GUARD_SKIP_MARKER = "__BOTSKIP__"
GUARD_FAIL_MARKER = "__BOTFAIL__"
GUARD_STAGE_MARKER = "__BOTMS__"

_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class AdbUnavailableError(RuntimeError):
    """Raised when an ADB command could not be delivered to the device."""


# `ldconsole adb --command ...` exits with code 0 even when the instance is off,
# and reports the real failure as text on stdout. Exit codes alone are therefore
# not trustworthy - the output has to be inspected too.
ADB_FAILURE_MARKERS = (
    "not found",
    "no devices",
    "no emulators",
    "device offline",
    "device unauthorized",
    "cannot connect",
    "connection refused",
    "daemon not running",
    "error: closed",
    "protocol fault",
)


def looks_like_adb_failure(output: str) -> bool:
    """True if adb/ldconsole output indicates the command never reached a device."""
    if not output:
        return False
    lowered = output.strip().lower()
    if not lowered.startswith(("adb.exe:", "adb:", "error:")) and "adb.exe:" not in lowered:
        # Normal command output can legitimately contain words like "not found"
        # (e.g. a dumped screen), so only treat adb's own diagnostics as failures.
        return lowered.startswith(ADB_FAILURE_MARKERS)
    return any(marker in lowered for marker in ADB_FAILURE_MARKERS)


def _keyevents(keycodes: list[str], batched: bool = True) -> str:
    """
    Chuỗi lệnh gửi một loạt phím.

    Mỗi lần gọi `input` là một lần máy ảo dựng tiến trình Java mất vài trăm ms,
    còn các keycode nằm chung một lệnh thì gửi liền tay - nên gộp lại tiết kiệm
    nhiều hơn hẳn việc cắt bớt số phím.
    """
    if batched:
        return "input keyevent " + " ".join(keycodes)
    return "; ".join(f"input keyevent {code}" for code in keycodes)


def shell_quote(value: str) -> str:
    """Single-quote a value for the remote (device) POSIX-ish shell."""
    return "'" + value.replace("'", "'\\''") + "'"


@dataclass
class GuardedInput:
    """Kết quả của một lệnh 'soi cửa sổ rồi gõ' chạy trong đúng một lượt ADB."""

    focus_line: str             # dòng mCurrentFocus đọc được NGAY TRƯỚC lúc gõ
    typed: bool                 # serial đã được gõ hay chưa
    failed: bool = False        # lệnh gõ chạy nhưng báo lỗi
    stages: tuple = ()          # mốc thời gian từng chặng (epoch ms), khi bật đo
    labels: tuple = ()          # tên các chặng, khớp thứ tự với `stages`

    def stage_report(self) -> str:
        """'xoa=605ms go=1200ms enter=180ms' - chỉ có khi lệnh chạy kèm đo."""
        return " ".join(
            f"{label}={after - before}ms"
            for label, before, after in zip(self.labels, self.stages, self.stages[1:])
        )


def guarded_script(commands: list[str], expected_focus: str, profile: bool = False) -> str:
    """
    Lệnh shell gộp: đọc cửa sổ đang focus, và CHỈ gõ nếu nó đúng như mong đợi.

    Hai việc này phải đi chung một lệnh chứ không tách làm hai lượt gọi ADB. Kẽ
    hở giữa hai lượt là ~130ms, mà hộp thoại lỗi của app hiện ra rơi đúng vào đó
    thì serial gõ ra đi vào hộp thoại chứ không vào ô nhập, Enter lại bấm luôn
    nút mặc định để đóng nó - kết quả là serial biến mất mà cả dòng này lẫn dòng
    trước đều được ghi là thành công. Đi chung một lệnh thì kẽ hở còn vài ms.

    `expected_focus` rỗng nghĩa là chưa biết màn hình sạch trông thế nào - vẫn gõ,
    và vẫn báo về cửa sổ đọc được để bên gọi dùng làm mốc cho bước chấm điểm.
    """
    if profile:
        stamp = f'echo "{GUARD_STAGE_MARKER}$(date +%s%3N)"'
        chain = [stamp]
        for command in commands:
            chain.extend([command, stamp])
    else:
        chain = list(commands)

    expected = shell_quote(expected_focus)
    return (
        f"f=$({FOCUS_LINE_COMMAND}); "
        f'echo "{GUARD_FOCUS_MARKER}$f"; '
        f'if [ -n {expected} ] && [ "$f" != {expected} ]; then '
        f"echo {GUARD_SKIP_MARKER}; "
        f"elif {' && '.join(chain)}; then "
        f"echo {GUARD_TYPED_MARKER}; "
        f"else echo {GUARD_FAIL_MARKER}; "
        "fi"
    )


def parse_guarded(output: str) -> GuardedInput | None:
    """None nghĩa là output không có dạng mong đợi - đừng đoán là đã gõ."""
    focus = None
    typed = None
    failed = False
    stages = []

    for raw in output.splitlines():
        line = raw.rstrip("\r")
        if line.startswith(GUARD_FOCUS_MARKER):
            focus = line[len(GUARD_FOCUS_MARKER):]
            continue
        stripped = line.strip()
        if stripped == GUARD_TYPED_MARKER:
            typed = True
        elif stripped == GUARD_SKIP_MARKER:
            typed = False
        elif stripped == GUARD_FAIL_MARKER:
            typed, failed = False, True
        elif stripped.startswith(GUARD_STAGE_MARKER):
            try:
                stages.append(int(stripped[len(GUARD_STAGE_MARKER):]))
            except ValueError:
                pass

    if focus is None or typed is None:
        return None
    return GuardedInput(focus_line=focus, typed=typed, failed=failed, stages=tuple(stages))


def list_ldplayer_instances() -> list[dict]:
    """Return [{"index": str, "name": str, "running": bool}, ...] via `ldconsole list2`."""
    path = find_ldplayer_tool("ldconsole.exe")
    if not path:
        return []

    try:
        result = subprocess.run(
            [path, "list2"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    instances = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 5:
            instances.append({
                "index": parts[0],
                "name": parts[1],
                "running": parts[4] == "1",
            })
    return instances


class AdbClient:
    """
    Runs shell commands against one LDPlayer instance.

    Prefers `ldconsole.exe adb --name <instance>` because it targets the
    right instance even when several are running. Falls back to a plain
    `adb` call when only one device is connected and ldconsole is missing.
    """

    def __init__(self, instance_name: str, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.instance_name = instance_name
        self.timeout = timeout
        self._ldconsole_path: str | None = None
        self._ldconsole_checked = False
        self._adb_path: str | None = None
        self._direct_target: str | None = None
        self._direct_target_resolved = False

    def _find_ldconsole(self) -> str | None:
        if self._ldconsole_checked:
            return self._ldconsole_path
        self._ldconsole_checked = True
        self._ldconsole_path = find_ldplayer_tool("ldconsole.exe")
        if self._ldconsole_path:
            logger.info("Dùng ldconsole: %s", self._ldconsole_path)
        return self._ldconsole_path

    def _find_adb(self) -> str | None:
        if self._adb_path and os.path.exists(self._adb_path):
            return self._adb_path
        self._adb_path = find_ldplayer_tool("adb.exe")
        if self._adb_path:
            logger.info("Dùng adb: %s", self._adb_path)
        return self._adb_path

    def _resolve_direct_target(self, adb: str) -> str | None:
        if self._direct_target_resolved:
            return self._direct_target
        try:
            result = subprocess.run(
                [adb, "devices"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

        devices = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])

        if len(devices) == 1:
            self._direct_target = devices[0]
            self._direct_target_resolved = True
        elif devices:
            # Nhiều máy ảo thì phải biết đúng cái nào mang tên instance này -
            # gửi nhầm máy là serial chạy sang phiên kiểm đếm khác.
            wanted = self._device_for_instance()
            if wanted in devices:
                self._direct_target = wanted
            self._direct_target_resolved = True
        # Chưa thấy máy nào thì đừng nhớ: nhiều khi bot mở trước lúc LDPlayer
        # boot xong, nhớ luôn kết quả rỗng là cả phiên phải đi đường chậm.
        return self._direct_target

    def _device_for_instance(self) -> str:
        """
        Thiết bị adb ứng với instance đang chạy, theo đúng quy ước của ldconsole:
        index 0 -> emulator-5554, index 1 -> emulator-5556, ...

        Quy ước này lấy từ chính ldconsole: chạy lệnh cho instance "LDPlayer-1"
        (index 1) mà máy chưa bật adb thì nó báo "device 'emulator-5556' not
        found". Biết được cặp tên<->thiết bị thì mọi lệnh đều gọi thẳng adb được,
        kể cả khi chạy nhiều máy ảo - vừa nhanh hơn ~430ms mỗi lệnh, vừa tránh
        được lỗi ldconsole làm hỏng tiếng Việt.
        """
        for entry in list_ldplayer_instances():
            if entry.get("name") == self.instance_name:
                try:
                    return f"emulator-{5554 + 2 * int(entry['index'])}"
                except (KeyError, TypeError, ValueError):
                    return ""
        return ""

    def _run_direct(self, adb: str, shell_command: str, timeout: float, target: str | None) -> str | None:
        cmd = [adb]
        if target:
            cmd.extend(["-s", target])
        cmd.extend(["shell", shell_command])
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="ignore",
                text=True,
                timeout=timeout,
                creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            return None
        if result.returncode != 0 or looks_like_adb_failure(result.stdout):
            return None
        return result.stdout

    def run_shell(self, shell_command: str, timeout: float | None = None) -> str | None:
        """Run a shell command on the device. Returns stdout, or None on failure/timeout."""
        timeout = timeout or self.timeout

        # Chỉ có đúng một máy ảo đang chạy thì gọi thẳng adb. ldconsole cũng chỉ
        # đi gọi lại adb, nên đi vòng qua nó là thừa hẳn một lần dựng tiến trình
        # Windows cho MỌI lệnh - mà một serial tốn cả chục lệnh, nên khoản thừa
        # này cộng dồn thành phần lớn thời gian mỗi dòng. Nhiều máy ảo cùng chạy
        # thì vẫn phải qua ldconsole vì chỉ nó biết tên nào ứng với máy nào.
        adb = self._find_adb()
        target = self._resolve_direct_target(adb) if adb else None
        if adb and target:
            output = self._run_direct(adb, shell_command, timeout, target)
            if output is not None:
                return output

        ldconsole = self._find_ldconsole()
        if ldconsole:
            try:
                result = subprocess.run(
                    [
                        ldconsole,
                        "adb",
                        "--name",
                        self.instance_name,
                        "--command",
                        f"shell {shell_command}",
                    ],
                    capture_output=True,
                    encoding="utf-8",
                    errors="ignore",
                    text=True,
                    timeout=timeout,
                    creationflags=_CREATE_NO_WINDOW,
                )
                if result.returncode == 0 and not looks_like_adb_failure(result.stdout):
                    return result.stdout
            except subprocess.TimeoutExpired:
                return None

        if not adb or target:
            # Đã thử đường thẳng ở trên rồi thì không thử lại.
            return None
        return self._run_direct(adb, shell_command, timeout, None)

    def run_exec_out_binary(self, shell_command: str, timeout: float | None = None) -> bytes | None:
        """Run `adb exec-out <cmd>` and return raw bytes (for binary output like screencap)."""
        timeout = timeout or self.timeout
        adb = self._find_adb()
        if not adb:
            return None

        cmd = [adb]
        target = self._resolve_direct_target(adb)
        if target:
            cmd.extend(["-s", target])
        cmd.extend(["exec-out", shell_command])
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            return None
        if result.returncode != 0 or not result.stdout:
            return None
        return result.stdout


ADB_PROBE_ATTEMPTS = 2
ADB_PROBE_RETRY_SECONDS = 0.5


def adb_answers(client: AdbClient, attempts: int = ADB_PROBE_ATTEMPTS) -> bool:
    """
    Máy ảo có trả lời qua ADB không - hỏi lại một lần trước khi kết luận là không.

    Lệnh ADB đầu tiên sau khi máy vừa mở thường rơi đúng lúc adb server còn đang
    tự khởi động: `adb devices` lúc đó trả về danh sách rỗng, không có thiết bị
    nào để nhắm nên cả lệnh cũng hụt theo, dù vài trăm ms sau mọi thứ đều bình
    thường. Hỏi đúng một lần rồi kết luận thì background mode chặn phiên chạy
    ngay ở màn hình Start với lý do sai.

    Chỗ này chấp nhận chờ thêm vì mỗi phiên chỉ hỏi một lần; lệnh trong lúc chạy
    thì KHÔNG được thử lại kiểu này - hỏng thật mà thử lại là mỗi dòng chậm gấp
    đôi và bộ đếm hỏng liên tiếp không bao giờ chạm ngưỡng dừng.
    """
    for attempt in range(max(1, attempts)):
        if client.run_shell("echo ok", timeout=5) is not None:
            return True
        if attempt + 1 < attempts:
            logger.info(
                "ADB chưa trả lời trên '%s', thử lại (adb server có thể đang khởi động)",
                getattr(client, "instance_name", "?"),
            )
            time.sleep(ADB_PROBE_RETRY_SECONDS)
    return False


class AutomationBackend(ABC):
    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def type_serial(self, serial: str) -> None:
        """Clear the focused input field and type the serial into it."""
        ...

    @abstractmethod
    def send_enter(self, mode: str) -> None:
        """mode: 'enter', 'none', or 'tab_enter'."""
        ...

    # Backend thật còn có `clear_field()`: xóa ô nhập mà không gõ gì thêm, cho
    # bước "xóa ô" riêng của kịch bản (xem action_runner). Cố tình KHÔNG khai
    # báo abstract ở đây - backend giả trong test chỉ cần gõ được là đủ, bắt
    # chúng khai thêm một hàm chẳng ai gọi thì chỉ tổ rườm rà.

    def type_and_submit(self, serial: str, mode: str, clear_first: bool = True) -> None:
        """
        Gõ serial rồi gửi luôn phím xác nhận.

        Backend nào gộp được thành một lần gửi thì ghi đè để tiết kiệm một vòng
        đi-về; mặc định vẫn là hai bước như cũ.

        clear_first chỉ có ý nghĩa với backend gộp được (xem AdbBackend); backend
        mặc định luôn xóa ô vì type_serial đã bao gồm việc đó.
        """
        self.type_serial(serial)
        self.send_enter(mode)


class AdbBackend(AutomationBackend):
    """Sends key/text events straight to the device, no window focus needed."""

    def __init__(self, adb_client: AdbClient):
        self.adb = adb_client
        # `input keyevent A B C` gửi nhiều phím trong một lần dựng tiến trình
        # Java thay vì mỗi phím một lần - nhanh hơn nhiều. Bản `input` quá cũ
        # không nhận cú pháp này, nên có đường lui ở _send().
        self._batched_keys_ok = True
        # Gộp Enter vào chính chuỗi của `input text` (xem TEXT_SUBMIT_SUFFIX).
        # Mặc định tắt: chỉ bật khi bên gọi có cách nhìn tận mắt rằng nó chạy.
        self._submit_with_text = False
        self._text_submit_confirmed = False
        # Máy ảo có chạy được lệnh 'soi cửa sổ rồi gõ' trong một lượt không.
        # None = chưa dò.
        self._guard_ok: bool | None = None

    def is_available(self) -> bool:
        return adb_answers(self.adb)

    # ------------------------------------------------ gộp Enter vào input text

    @property
    def submits_with_text(self) -> bool:
        return self._submit_with_text

    def enable_text_submit(self) -> None:
        self._submit_with_text = True

    def confirm_text_submit(self) -> None:
        """Bên gọi đã nhìn tận mắt rằng Enter tới nơi - thôi dò lại nữa."""
        self._text_submit_confirmed = True

    def disable_text_submit(self) -> None:
        self._submit_with_text = False
        self._text_submit_confirmed = False

    # ------------------------------------------------ soi cửa sổ chung một lệnh

    @property
    def guards_focus(self) -> bool:
        return bool(self._guard_ok)

    def probe_guard(self) -> bool:
        """
        Dò xem máy ảo có chạy được lệnh gộp 'soi cửa sổ rồi gõ' không.

        Dò bằng thân lệnh rỗng (`true`) nên không gõ gì vào app: hụt thì chỉ tốn
        một lượt gọi, không có nguy cơ serial bị gửi đi hai lần.
        """
        if self._guard_ok is None:
            output = self.adb.run_shell(guarded_script(["true"], ""))
            parsed = parse_guarded(output) if output else None
            self._guard_ok = bool(parsed and parsed.typed and parsed.focus_line)
            if not self._guard_ok:
                logger.info(
                    "Máy ảo không chạy được lệnh gõ kèm chốt cửa sổ - dùng hai lượt gọi như cũ"
                )
        return self._guard_ok

    def type_serial(self, serial: str) -> None:
        self._send(lambda batched: (
            f"{self._clear_command(batched)}; input text {shell_quote(serial)}"
        ))

    def send_enter(self, mode: str) -> None:
        if self._enter_command(mode, True):
            self._send(lambda batched: self._enter_command(mode, batched))

    def clear_field(self) -> None:
        """
        Xóa ô nhập trong đúng MỘT lần máy ảo dựng tiến trình Java.

        Bước "xóa ô" của kịch bản trước đây gửi ba lệnh `input` rời nhau
        (`input keyevent 123; input keyevent 28; input keyevent 67 67 ...`) - mà
        mỗi lệnh `input` là một lần dựng tiến trình Java, khoản đắt nhất của mọi
        thao tác gõ (đo trên máy thật: ~300ms mỗi lần). Đúng dãy phím ấy gộp làm
        một lệnh thì chỉ còn một lần dựng, và máy ảo nào không nhận cú pháp
        nhiều keycode vẫn có đường lui sẵn trong `_send`.
        """
        self._send(self._clear_command)

    def type_and_submit(self, serial: str, mode: str, clear_first: bool = True) -> None:
        """
        Xóa ô, gõ serial và xác nhận trong đúng một lần gọi ADB.

        clear_first=False bỏ hẳn phần xóa ô. Đo trên máy thật: lệnh xóa là 22
        keyevent, tốn ~605ms mỗi serial - gần bằng cả phần gõ chữ. App nào tự
        dọn ô sau mỗi lần quét thì đó là 605ms vứt đi. Bên gọi phải tự xác nhận
        điều đó trước (xem BotWorker._field_self_clears), vì đoán sai thì serial
        sau nối vào serial trước và gửi đi một mã không có thật.
        """
        self._send(lambda batched: "; ".join(
            command for _, command in self._input_parts(serial, mode, clear_first, batched)
        ))

    def type_and_submit_guarded(
        self,
        serial: str,
        mode: str,
        clear_first: bool = True,
        expected_focus: str = "",
        profile: bool = False,
    ) -> GuardedInput:
        """
        Như `type_and_submit`, nhưng đọc cửa sổ đang focus trong cùng một lượt và
        bỏ qua việc gõ nếu màn hình đã đổi khác (xem `guarded_script`).
        """
        while True:
            parts = self._input_parts(serial, mode, clear_first, self._batched_keys_ok)
            output = self._run_or_raise(
                guarded_script([command for _, command in parts], expected_focus, profile)
            )
            parsed = parse_guarded(output)
            if parsed is None:
                # Không đọc nổi output thì không được đoán là đã gõ hay chưa.
                raise AdbUnavailableError(
                    f"Lệnh gõ trên instance '{self.adb.instance_name}' trả về "
                    f"kết quả không đọc được"
                )
            if not parsed.failed:
                parsed.labels = tuple(label for label, _ in parts)
                return parsed

            # Lệnh chạy nhưng báo lỗi. Thử bỏ dần các lối tắt chưa được xác nhận
            # trước khi kết luận máy ảo hỏng.
            if self._submit_with_text and not self._text_submit_confirmed:
                self.disable_text_submit()
                logger.info(
                    "`input text` không nhận ký tự xuống dòng, quay về gửi Enter riêng"
                )
                continue
            if self._batched_keys_ok:
                self._batched_keys_ok = False
                logger.info(
                    "Máy ảo không nhận `input keyevent` nhiều phím, chuyển sang gửi từng phím"
                )
                continue
            raise AdbUnavailableError(
                f"Lệnh gõ thất bại trên instance '{self.adb.instance_name}'"
            )

    def _input_parts(
        self, serial: str, mode: str, clear_first: bool, batched: bool
    ) -> list[tuple[str, str]]:
        """Các chặng của một lần gõ, kèm tên chặng để còn ghi được mốc thời gian."""
        parts = []
        if clear_first:
            parts.append(("xoa", self._clear_command(batched)))
        if self._submit_with_text and mode == "enter":
            parts.append(("go+enter", f"input text {shell_quote(serial + TEXT_SUBMIT_SUFFIX)}"))
            return parts

        parts.append(("go", f"input text {shell_quote(serial)}"))
        enter = self._enter_command(mode, batched)
        if enter:
            parts.append(("enter", enter))
        return parts

    def type_and_dump(
        self,
        serial: str,
        mode: str,
        dump_command: str,
        settle_seconds: float = 0.5,
        clear_first: bool = True,
    ) -> str:
        """
        Gõ, chờ app chuyển màn hình, rồi đọc màn hình - trong đúng một lần gọi ADB.

        Tách rời thì lần dump đầu tiên gần như luôn bắt được màn hình *cũ* (app
        chưa kịp chuyển cảnh), nên phải dump lần thứ hai - mất không ~1.4s mỗi
        bước. Cho máy ảo tự ngủ một nhịp ngay trước khi dump thì lần đọc đầu
        tiên đã là màn hình mới.

        Nối bằng `;` chứ không phải `&&`: máy nào không có `sleep` phân số thì
        chặng đó hỏng nhưng lệnh dump vẫn chạy - bên gọi chỉ mất nhịp chờ rồi
        quay về vòng poll như cũ, chứ không đổ cả lượt chạy.
        """
        def build(batched: bool) -> str:
            parts = [
                command
                for _, command in self._input_parts(serial, mode, clear_first, batched)
            ]
            return "; ".join(parts + [f"sleep {settle_seconds:.2f}", dump_command])

        try:
            return self._run_or_raise(build(self._batched_keys_ok))
        except AdbUnavailableError:
            if not self._batched_keys_ok:
                raise

        output = self._run_or_raise(build(False))
        self._batched_keys_ok = False
        logger.info("Máy ảo không nhận `input keyevent` nhiều phím, chuyển sang gửi từng phím")
        return output

    def _send(self, build) -> None:
        try:
            self._run_or_raise(build(self._batched_keys_ok))
            return
        except AdbUnavailableError:
            if not self._batched_keys_ok:
                raise

        # Thử lại kiểu tách rời trước khi kết luận máy ảo chết: có thể chỉ là
        # bản `input` cũ không hiểu nhiều keycode trong một lệnh.
        self._run_or_raise(build(False))
        self._batched_keys_ok = False
        logger.info("Máy ảo không nhận `input keyevent` nhiều phím, chuyển sang gửi từng phím")

    @staticmethod
    def _clear_command(batched: bool = True) -> str:
        keys = [KEYCODE_MOVE_END, KEYCODE_CLEAR] + [KEYCODE_DEL] * CLEAR_DEL_COUNT
        return _keyevents(keys, batched)

    @staticmethod
    def _enter_command(mode: str, batched: bool = True) -> str:
        if mode == "none":
            return ""
        if mode == "tab_enter":
            return _keyevents([KEYCODE_TAB, KEYCODE_ENTER], batched)
        return _keyevents([KEYCODE_ENTER], batched)

    def _run_or_raise(self, shell_command: str) -> str:
        """A failed ADB call must never look like a successful keystroke - otherwise
        a dead emulator produces a run full of false 'OK' results."""
        output = self.adb.run_shell(shell_command)
        if output is None:
            raise AdbUnavailableError(
                f"ADB command failed or timed out on instance '{self.adb.instance_name}'"
            )
        return output


class WindowFocusError(RuntimeError):
    """Cửa sổ máy ảo không ở foreground - gõ tiếp là gõ vào app khác."""


class PyAutoGuiBackend(AutomationBackend):
    """
    Đường lui gõ bàn phím: phím đi vào cửa sổ nào đang foreground của Windows.

    pyautogui không gửi phím tới một cửa sổ cụ thể được - nó bắn vào hàng đợi
    input của cả hệ thống, ai đang foreground thì người đó nhận. Nên trước MỖI
    lần gõ phải tự soi lại foreground chứ không được nhớ kết quả lần trước: chỉ
    cần người dùng alt-tab, hay một hộp thoại Windows nhảy lên, là toàn bộ serial
    còn lại chui vào Excel/Chrome mà dòng nào cũng vẫn được ghi OK.

    Soi foreground tốn ~0.002ms, còn gõ một serial tốn ~36ms - lớp chốt này không
    đáng kể so với thứ nó canh.
    """

    KEY_STEP_DELAY_SECONDS = 0.005
    TAB_ENTER_DELAY_SECONDS = 0.02
    TYPING_INTERVAL_SECONDS = 0.003
    US_KEYBOARD_LAYOUT = "00000409"

    # Đưa cửa sổ lên trước rồi đọc lại foreground; Windows cần một nhịp mới đổi.
    FOCUS_SETTLE_SECONDS = 0.08
    FOCUS_ATTEMPTS = 3

    def __init__(self, window_title: str):
        self.window_title = window_title
        self._keyboard_layout_ready = False
        self._user32 = None
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.0

    def is_available(self) -> bool:
        return gw is not None

    # ------------------------------------------------------- chốt cửa sổ đích

    def _matches_target(self, title: str) -> bool:
        """
        Tiêu đề này có đúng là cửa sổ máy ảo cần gõ không.

        Khớp CHÍNH XÁC, hoặc bắt đầu bằng tên rồi tới dấu cách. Khớp chuỗi con
        như trước thì một tab Chrome tên 'serial LDPlayer - Google Chrome' cũng
        tính là hợp lệ, mà nó còn đứng trước máy ảo thật trong danh sách trả về.
        Còn 'bắt đầu bằng' trần thì 'LDPlayer' nuốt luôn 'LDPlayer-1' - gõ serial
        sang máy ảo của phiên kiểm đếm khác.
        """
        title = (title or "").strip()
        return title == self.window_title or title.startswith(self.window_title + " ")

    def _foreground_title(self) -> str:
        """Tiêu đề cửa sổ đang thật sự nhận phím ngay lúc này."""
        if os.name == "nt":
            try:
                import ctypes

                if self._user32 is None:
                    self._user32 = ctypes.WinDLL("user32", use_last_error=True)
                hwnd = self._user32.GetForegroundWindow()
                if not hwnd:
                    return ""
                buffer = ctypes.create_unicode_buffer(512)
                self._user32.GetWindowTextW(hwnd, buffer, 512)
                return buffer.value
            except Exception:
                pass

        if gw is None:
            return ""
        try:
            active = gw.getActiveWindow()
            return getattr(active, "title", "") if active else ""
        except Exception:
            return ""

    def _ensure_focus(self) -> None:
        """
        Đưa cửa sổ máy ảo lên foreground và XÁC MINH nó lên thật, trước mỗi lần gõ.

        Windows hay từ chối SetForegroundWindow khi app khác đang giữ focus: nó
        chỉ nháy nút trên taskbar chứ không đổi foreground, và pygetwindow không
        báo lỗi gì cả. Tin vào activate() mà không đọc lại là gõ thẳng vào cửa sổ
        cũ, nên ở đây chỉ tin thứ đọc được từ foreground thật.
        """
        if self._matches_target(self._foreground_title()):
            return

        if gw is None:
            raise WindowFocusError(
                "Không đọc được danh sách cửa sổ (thiếu pygetwindow) nên không "
                "chắc phím sẽ đi vào đâu - dừng thay vì gõ liều."
            )

        try:
            windows = [
                w for w in gw.getWindowsWithTitle(self.window_title)
                if self._matches_target(getattr(w, "title", ""))
            ]
        except Exception as e:
            raise WindowFocusError(f"Could not find window '{self.window_title}': {e}") from e

        if not windows:
            raise WindowFocusError(f"Could not find window '{self.window_title}'")

        window = windows[0]
        for _ in range(self.FOCUS_ATTEMPTS):
            try:
                if window.isMinimized:
                    window.restore()
                window.activate()
            except Exception:
                # activate() ném lỗi vặt là chuyện thường - cứ đọc foreground
                # rồi kết luận, đó mới là thứ quyết định phím đi đâu.
                pass
            time.sleep(self.FOCUS_SETTLE_SECONDS)
            if self._matches_target(self._foreground_title()):
                return

        raise WindowFocusError(
            f"Cửa sổ '{self.window_title}' có tồn tại nhưng không đưa lên trước được "
            f"(foreground đang là '{self._foreground_title()}') - dừng để phím không "
            f"đi vào cửa sổ đó."
        )

    def _activate_english_keyboard_layout(self):
        if self._keyboard_layout_ready:
            return
        self._keyboard_layout_ready = True
        if os.name != "nt":
            return
        try:
            import ctypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            layout = user32.LoadKeyboardLayoutW(self.US_KEYBOARD_LAYOUT, 1)
            if layout:
                user32.ActivateKeyboardLayout(layout, 0)
        except Exception:
            pass

    # --------------------------------------------------------------- gõ phím

    def type_serial(self, serial: str) -> None:
        self._ensure_focus()
        self._activate_english_keyboard_layout()
        pyautogui.hotkey("ctrl", "a")
        time.sleep(self.KEY_STEP_DELAY_SECONDS)
        pyautogui.press("backspace")
        time.sleep(self.KEY_STEP_DELAY_SECONDS)
        pyautogui.write(serial, interval=self.TYPING_INTERVAL_SECONDS)

        # Soi lại sau khi gõ xong: focus bị cướp giữa chừng thì một phần serial
        # đã nằm ở cửa sổ khác, và phần còn lại trong ô cũng là mã cụt. Dòng này
        # phải được báo hỏng chứ không được đi tiếp tới bước Enter.
        landed = self._foreground_title()
        if not self._matches_target(landed):
            raise WindowFocusError(
                f"Focus bị chuyển sang '{landed}' giữa lúc đang gõ - serial "
                f"'{serial}' có thể đã lọt một phần sang cửa sổ đó."
            )

    def clear_field(self) -> None:
        self._ensure_focus()
        self._activate_english_keyboard_layout()
        pyautogui.hotkey("ctrl", "a")
        time.sleep(self.KEY_STEP_DELAY_SECONDS)
        pyautogui.press("backspace")

    def send_enter(self, mode: str) -> None:
        if mode == "none":
            return
        self._ensure_focus()
        if mode == "tab_enter":
            pyautogui.press("tab")
            time.sleep(self.TAB_ENTER_DELAY_SECONDS)
            pyautogui.press("enter")
        else:
            pyautogui.press("enter")
