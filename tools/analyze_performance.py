"""Summarize PERF records; accepts files/directories without modifying them."""
import argparse
import json
import math
from pathlib import Path
import statistics


def summarize(values):
    ordered = sorted(values)
    if not ordered:
        return {}
    return {"count": len(ordered), "mean_ms": round(statistics.mean(ordered), 2),
            "median_ms": round(statistics.median(ordered), 2),
            "p95_ms": round(ordered[max(0, math.ceil(len(ordered)*.95)-1)], 2)}


def analyze(paths):
    groups = {}
    for path in paths:
        files = sorted(path.glob("*.log")) if path.is_dir() else [path]
        for file in files:
            for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
                marker = line.find("PERF {")
                if marker < 0:
                    continue
                try:
                    record = json.loads(line[marker+5:])
                except ValueError:
                    continue
                key = (record.get("run_id"), record.get("version"), record.get("mode"), record.get("kind"))
                groups.setdefault(key, []).append(record)
    output = []
    for (run, version, mode, kind), records in groups.items():
        output.append({"run_id": run, "version": version, "mode": mode, "kind": kind,
                       **summarize([r["total_ms"] for r in records]),
                       "failed": sum(r["status"] not in ("OK", "complete") for r in records),
                       "throughput_per_min": round(len(records)*60000 / max(1, sum(r["total_ms"] for r in records)), 2),
                       "dump_mean_ms": round(statistics.mean(r.get("dump_ms", 0) for r in records), 2),
                       "dump_mean_count": round(statistics.mean(r.get("dump_count", 0) for r in records), 2)})
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(analyze(arguments.paths), ensure_ascii=False, indent=2))
