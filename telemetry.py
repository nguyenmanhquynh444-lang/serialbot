"""Structured measurements for comparing identical workloads, including failures."""
import json
import hashlib
import logging
import time
from pathlib import Path
from functools import wraps

from version import APP_VERSION

logger = logging.getLogger(__name__)


def _code_version():
    digest = hashlib.sha256()
    for name in ("bot_worker.py", "pick_runner.py", "inbound_runner.py", "automation_backend.py",
                 "screen_reader.py", "verification.py", "run_journal.py"):
        path = Path(__file__).resolve().parent / name
        if path.is_file():
            digest.update(name.encode())
            digest.update(path.read_bytes())
    return f"{APP_VERSION}+{digest.hexdigest()[:12]}"


CODE_VERSION = _code_version()


def measure(kind):
    def decorator(method):
        @wraps(method)
        def wrapped(self, *args, **kwargs):
            screen = self.screen
            before = {name: getattr(screen, name, 0) for name in
                      ("dump_count", "dump_seconds", "focus_seconds", "screenshot_seconds")}
            client = getattr(self, "adb", None) or getattr(self, "adb_client", None)
            commands = getattr(client, "command_count", 0)
            runner_before = {name: getattr(self, name, 0) for name in
                             ("input_seconds", "wait_seconds", "retry_count")}
            paused_before = getattr(self, "pause_seconds", 0)
            started = time.monotonic()
            status = "failed"
            result = None
            try:
                result = method(self, *args, **kwargs)
                status = result.get("status", "UNKNOWN") if isinstance(result, dict) else getattr(result, "status", "OK")
                return result
            finally:
                timing = result.get("timing", {}) if isinstance(result, dict) else {}
                paused = max(0, getattr(self, "pause_seconds", 0)-paused_before)
                payload = {"kind": kind, "run_id": getattr(self, "run_id", None), "version": CODE_VERSION,
                           "mode": getattr(self, "session_mode", "serial"),
                           "instance": getattr(client, "instance_name", ""),
                           "item": args[0] if args else "", "status": status,
                           "total_ms": round(max(0, time.monotonic() - started - paused)*1000, 3),
                           "pause_ms": round(paused*1000, 3),
                           "commands": getattr(client, "command_count", 0)-commands, **timing}
                for name, value in before.items():
                    delta = getattr(screen, name, 0)-value
                    payload[name.replace("_seconds", "_ms")] = round(delta*1000, 3) if name.endswith("seconds") else delta
                for name, value in runner_before.items():
                    if hasattr(self, name):
                        delta = getattr(self, name)-value
                        payload[name.replace("_seconds", "_ms")] = round(delta*1000, 3) if name.endswith("seconds") else delta
                logger.info("PERF %s", json.dumps(payload, ensure_ascii=False, default=str))
        return wrapped
    return decorator
