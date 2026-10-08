"""Compare operation counts on fake devices, without connecting to LDPlayer.

This is not an elapsed-time benchmark. The baseline is a trusted Git revision
of this same repository; select the pre-change revision after committing.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation_backend import AdbBackend
import pick_runner
from tests.fake_pick_device import FakePickDevice, Session


def compare(revision):
    source = subprocess.check_output(["git", "show", f"{revision}:pick_runner.py"],
                                     cwd=ROOT, text=True, encoding="utf-8")
    baseline = types.ModuleType("baseline_pick_runner")
    sys.modules[baseline.__name__] = baseline
    exec(compile(source, "baseline_pick_runner.py", "exec"), baseline.__dict__)
    rows = []
    for count in (1, 3, 10):
        for name, module in (("baseline", baseline), ("current", pick_runner)):
            device = FakePickDevice([Session("OR1", "PL1", count), Session("OR2", "PL2", 1)])
            runner = module.PickRunner(device, AdbBackend(device),
                module.PickConfig(step_timeout=3, capture_screenshot=False))
            runner.run_bill("OR1", [{"row": i+2, "value": f"S{i}"} for i in range(count)])
            rows.append({"serials": count, "version": name, "commands": len(device.commands),
                         "dumps": runner.screen.dump_count,
                         "clears": sum("input keyevent 123" in c for c in device.commands)})
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="HEAD")
    args = parser.parse_args()
    print(json.dumps(compare(args.baseline_ref), indent=2))
