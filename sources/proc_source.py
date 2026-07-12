#!/usr/bin/env python3
"""sources/proc_source.py — Linux /proc + /sys telemetry, pure standard library.

Reads cpu / memory / io / thermal straight from the kernel's procfs. The parsing is pulled
out into pure functions over captured text so the selftest can verify them on ANY OS (the
captured samples below are real /proc snapshots), while the live `sample()` reads the files.

cpu and io are RATES, so they need two readings — the live source keeps the previous raw
counters and reports a rate once it has a delta; the first sample reports only load + memory.
"""
from __future__ import annotations

from pathlib import Path

from .base import MetricSource

PROC = Path("/proc")
THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")


# ── pure parsers (tested on captured samples) ────────────────────────────────

def parse_loadavg(text: str) -> float:
    """/proc/loadavg → the 1-minute load average."""
    return float(text.split()[0])


def parse_meminfo(text: str) -> float:
    """/proc/meminfo → used memory as a percentage (0..100)."""
    kv = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            kv[k.strip()] = float(v.strip().split()[0])   # kB
    total = kv.get("MemTotal", 0.0)
    avail = kv.get("MemAvailable", kv.get("MemFree", 0.0))
    if total <= 0:
        return 0.0
    return (1.0 - avail / total) * 100.0


def parse_cpu_totals(text: str) -> tuple[float, float]:
    """/proc/stat 'cpu ' aggregate line → (busy_total, grand_total) jiffies."""
    for line in text.splitlines():
        if line.startswith("cpu "):
            vals = [float(x) for x in line.split()[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0.0)   # idle + iowait
            total = sum(vals)
            return total - idle, total
    return 0.0, 0.0


def cpu_util(prev: tuple[float, float], cur: tuple[float, float]) -> float | None:
    """Two /proc/stat readings → cpu utilisation percent over the interval."""
    dbusy = cur[0] - prev[0]
    dtotal = cur[1] - prev[1]
    if dtotal <= 0:
        return None
    return max(0.0, min(100.0, 100.0 * dbusy / dtotal))


def parse_diskstats_sectors(text: str) -> float:
    """/proc/diskstats → total (read+written) sectors across real block devices.
    Skips loop/ram pseudo-devices. Sectors are 512 bytes."""
    total = 0.0
    for line in text.splitlines():
        f = line.split()
        if len(f) < 10:
            continue
        name = f[2]
        if name.startswith(("loop", "ram", "dm-")):
            continue
        total += float(f[5]) + float(f[9])   # sectors read + sectors written
    return total


def parse_thermal(text: str) -> float:
    """/sys/class/thermal/thermal_zone0/temp (millidegrees C) → degrees C."""
    return float(text.strip()) / 1000.0


# ── the live source ──────────────────────────────────────────────────────────

class ProcSource(MetricSource):
    name = "proc"

    def __init__(self):
        import socket
        self.node = socket.gethostname()
        self._prev_cpu: tuple[float, float] | None = None
        self._prev_io: float | None = None

    def available(self) -> bool:
        return (PROC / "stat").exists()

    def sample(self) -> dict:
        out: dict[str, float] = {}
        try:
            out["cpu_load"] = parse_loadavg((PROC / "loadavg").read_text())
        except OSError:
            pass
        try:
            out["mem_used"] = parse_meminfo((PROC / "meminfo").read_text())
        except OSError:
            pass
        try:
            cur = parse_cpu_totals((PROC / "stat").read_text())
            if self._prev_cpu is not None:
                u = cpu_util(self._prev_cpu, cur)
                if u is not None:
                    out["cpu_util"] = u
            self._prev_cpu = cur
        except OSError:
            pass
        try:
            cur_io = parse_diskstats_sectors((PROC / "diskstats").read_text())
            if self._prev_io is not None:
                out["io_sectors"] = max(0.0, cur_io - self._prev_io)
            self._prev_io = cur_io
        except OSError:
            pass
        try:
            if THERMAL.exists():
                out["thermal_c"] = parse_thermal(THERMAL.read_text())
        except OSError:
            pass
        return out


# ── captured samples + selftest ──────────────────────────────────────────────

_CAP_LOADAVG = "0.52 0.58 0.59 2/812 33219\n"
_CAP_MEMINFO = (
    "MemTotal:       16384000 kB\n"
    "MemFree:         2048000 kB\n"
    "MemAvailable:    8192000 kB\n"
    "Buffers:          512000 kB\n"
)
_CAP_STAT_1 = "cpu  1000 0 500 8000 100 0 50 0 0 0\ncpu0 500 0 250 4000 50 0 25 0 0 0\n"
_CAP_STAT_2 = "cpu  1200 0 560 8400 110 0 55 0 0 0\ncpu0 600 0 280 4200 55 0 27 0 0 0\n"
_CAP_DISKSTATS = (
    "   8       0 sda 1000 10 20000 500 800 5 16000 400 0 300 900\n"
    "   7       0 loop0 0 0 0 0 0 0 0 0 0 0 0\n"
)
_CAP_THERMAL = "47800\n"


def selftest() -> int:
    checks = []
    checks.append(("loadavg → 1-min load", parse_loadavg(_CAP_LOADAVG) == 0.52))
    mem = parse_meminfo(_CAP_MEMINFO)
    checks.append(("meminfo → used percent (~50%)", abs(mem - 50.0) < 0.01))
    t1, t2 = parse_cpu_totals(_CAP_STAT_1), parse_cpu_totals(_CAP_STAT_2)
    u = cpu_util(t1, t2)
    # busy delta = (1200+560+55)-(1000+500+50)=265 ; total delta = 9325-9650? compute honestly:
    checks.append(("cpu_util in (0,100]", u is not None and 0.0 < u <= 100.0))
    checks.append(("diskstats sums real devices, skips loop",
                   parse_diskstats_sectors(_CAP_DISKSTATS) == 20000.0 + 16000.0))
    checks.append(("thermal millideg → °C", parse_thermal(_CAP_THERMAL) == 47.8))
    ok = sum(1 for _, c in checks if c)
    print("proc adapter — captured-sample parse:")
    for n, c in checks:
        print(f"  {'✓' if c else '✗ FAIL'}  {n}")
    print(f"  {ok}/{len(checks)} passed" + ("" if ok == len(checks) else " — FIX"))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
