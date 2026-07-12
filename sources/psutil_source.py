#!/usr/bin/env python3
"""sources/psutil_source.py — cross-platform cpu/mem/io/thermal via psutil.

This is the default live source on macOS / Windows (where /proc doesn't exist). psutil is an
optional dependency (`pip install aura-pce[live]`). The reading logic is a pure function over
a captured snapshot dict, so the selftest runs with no psutil and no live machine state.
"""
from __future__ import annotations

from .base import MetricSource


def readings_from(snapshot: dict, prev_disk_bytes: float | None = None) -> dict:
    """Turn a psutil snapshot dict into {metric: float}. io is a rate → needs the previous
    total bytes; omitted on the first sample. Pure + deterministic (the whole reason the
    selftest can run anywhere)."""
    out: dict[str, float] = {}
    if snapshot.get("cpu_percent") is not None:
        out["cpu_util"] = float(snapshot["cpu_percent"])
    if snapshot.get("mem_percent") is not None:
        out["mem_used"] = float(snapshot["mem_percent"])
    if snapshot.get("load1") is not None:
        out["cpu_load"] = float(snapshot["load1"])
    disk = snapshot.get("disk_bytes")
    if disk is not None and prev_disk_bytes is not None:
        out["io_bytes"] = max(0.0, float(disk) - float(prev_disk_bytes))
    temps = snapshot.get("temps") or {}
    if temps:
        # highest current reading across all sensors — the one worth watching
        out["thermal_c"] = float(max(temps.values()))
    return out


class PsutilSource(MetricSource):
    name = "psutil"

    def __init__(self):
        self._prev_disk: float | None = None
        try:
            import socket
            self.node = socket.gethostname()
        except OSError:
            self.node = "localhost"

    def available(self) -> bool:
        try:
            import psutil  # noqa: F401
            return True
        except ImportError:
            return False

    def _snapshot(self) -> dict:
        import psutil
        snap: dict = {"cpu_percent": psutil.cpu_percent(interval=None),
                      "mem_percent": psutil.virtual_memory().percent}
        try:
            snap["load1"] = psutil.getloadavg()[0]
        except (AttributeError, OSError):
            pass
        try:
            io = psutil.disk_io_counters()
            if io is not None:
                snap["disk_bytes"] = float(io.read_bytes + io.write_bytes)
        except (AttributeError, OSError):
            pass
        try:
            temps = psutil.sensors_temperatures()
            cur = {f"{chip}:{e.label or i}": e.current
                   for chip, entries in (temps or {}).items()
                   for i, e in enumerate(entries) if e.current is not None}
            if cur:
                snap["temps"] = cur
        except (AttributeError, OSError):
            pass
        return snap

    def sample(self) -> dict:
        snap = self._snapshot()
        out = readings_from(snap, self._prev_disk)
        if snap.get("disk_bytes") is not None:
            self._prev_disk = snap["disk_bytes"]
        return out


# ── captured snapshot + selftest ─────────────────────────────────────────────

_CAP_SNAP_1 = {"cpu_percent": 12.5, "mem_percent": 63.0, "load1": 0.8,
               "disk_bytes": 1_000_000.0, "temps": {"coretemp:Package": 55.0, "coretemp:Core0": 52.0}}
_CAP_SNAP_2 = {"cpu_percent": 91.0, "mem_percent": 64.0, "load1": 3.1,
               "disk_bytes": 1_500_000.0, "temps": {"coretemp:Package": 78.0}}


def selftest() -> int:
    checks = []
    r1 = readings_from(_CAP_SNAP_1, prev_disk_bytes=None)
    checks.append(("first sample: cpu/mem/load present, no io rate yet",
                   r1.get("cpu_util") == 12.5 and r1.get("mem_used") == 63.0
                   and r1.get("cpu_load") == 0.8 and "io_bytes" not in r1))
    checks.append(("thermal = hottest sensor", r1.get("thermal_c") == 55.0))
    r2 = readings_from(_CAP_SNAP_2, prev_disk_bytes=_CAP_SNAP_1["disk_bytes"])
    checks.append(("second sample: io rate = byte delta", r2.get("io_bytes") == 500_000.0))
    checks.append(("all readings are floats",
                   all(isinstance(v, float) for v in {**r1, **r2}.values())))
    ok = sum(1 for _, c in checks if c)
    print("psutil adapter — captured-snapshot readings:")
    for n, c in checks:
        print(f"  {'✓' if c else '✗ FAIL'}  {n}")
    print(f"  {ok}/{len(checks)} passed" + ("" if ok == len(checks) else " — FIX"))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
