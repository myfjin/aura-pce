#!/usr/bin/env python3
"""sources/node_exporter.py — read a Prometheus node_exporter scrape.

Points at a node_exporter `/metrics` endpoint (URL) or a captured scrape (file) and renders
the standard node gauges into the same {metric: float} readings the runner tracks for
anomalies. Pure stdlib: the exposition parser is a plain function tested on a captured
sample; only a URL source uses urllib.

  --source node_exporter:/var/lib/metrics.prom
  --source node_exporter:http://localhost:9100/metrics
"""
from __future__ import annotations

from .base import MetricSource


def parse_prom(text: str) -> list[tuple[str, float]]:
    """Prometheus text exposition → [(metric_name_without_labels, value)]. Ignores # HELP/#
    TYPE comments and unparseable values. Labels are dropped from the key (we aggregate by
    metric family), but the raw line order is preserved for max/first selection."""
    out: list[tuple[str, float]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # split off an optional trailing timestamp: "name{...} value [ts]"
        parts = line.split()
        if len(parts) < 2:
            continue
        key, val = parts[0], parts[1]
        name = key.split("{", 1)[0]
        try:
            out.append((name, float(val)))
        except ValueError:
            continue
    return out


def _first(metrics, name: str) -> float | None:
    for n, v in metrics:
        if n == name:
            return v
    return None


def _max_prefix(metrics, prefix: str) -> float | None:
    vals = [v for n, v in metrics if n.startswith(prefix)]
    return max(vals) if vals else None


def readings_from_prom(metrics: list[tuple[str, float]]) -> dict:
    """The curated node-level gauges worth watching, from a parsed scrape."""
    out: dict[str, float] = {}
    load1 = _first(metrics, "node_load1")
    if load1 is not None:
        out["cpu_load"] = load1
    total = _first(metrics, "node_memory_MemTotal_bytes")
    avail = _first(metrics, "node_memory_MemAvailable_bytes")
    if total and avail is not None and total > 0:
        out["mem_used"] = (1.0 - avail / total) * 100.0
    thermal = _max_prefix(metrics, "node_hwmon_temp_celsius")
    if thermal is None:
        thermal = _max_prefix(metrics, "node_thermal_zone_temp")
    if thermal is not None:
        out["thermal_c"] = thermal
    return out


class NodeExporterSource(MetricSource):
    name = "node_exporter"

    def __init__(self, target: str):
        self.target = target
        self.node = target
        self._is_url = target.startswith(("http://", "https://"))

    def available(self) -> bool:
        if self._is_url:
            return True   # reachability is checked at read time (a scrape may come and go)
        from pathlib import Path
        return Path(self.target).exists()

    def _read_text(self) -> str:
        if self._is_url:
            import urllib.request
            with urllib.request.urlopen(self.target, timeout=5) as r:   # noqa: S310 (user-supplied local target)
                return r.read().decode("utf-8", "replace")
        from pathlib import Path
        return Path(self.target).read_text()

    def sample(self) -> dict:
        try:
            return readings_from_prom(parse_prom(self._read_text()))
        except OSError:
            return {}


# ── captured sample + selftest ───────────────────────────────────────────────

_CAP_PROM = """# HELP node_load1 1m load average.
# TYPE node_load1 gauge
node_load1 3.42
node_load5 1.10
# TYPE node_memory_MemTotal_bytes gauge
node_memory_MemTotal_bytes 1.6384e+10
node_memory_MemAvailable_bytes 4.096e+09
# TYPE node_hwmon_temp_celsius gauge
node_hwmon_temp_celsius{chip="platform",sensor="temp1"} 61.0
node_hwmon_temp_celsius{chip="platform",sensor="temp2"} 74.5
node_cpu_seconds_total{cpu="0",mode="idle"} 12345.6
"""


def selftest() -> int:
    metrics = parse_prom(_CAP_PROM)
    r = readings_from_prom(metrics)
    checks = [
        ("parses labelled + unlabelled lines", len(metrics) >= 6),
        ("skips # comment lines", all(not n.startswith("#") for n, _ in metrics)),
        ("node_load1 → cpu_load", r.get("cpu_load") == 3.42),
        ("mem used = 1 - avail/total (~75%)", abs(r.get("mem_used", 0) - 75.0) < 0.01),
        ("thermal = hottest hwmon sensor", r.get("thermal_c") == 74.5),
    ]
    ok = sum(1 for _, c in checks if c)
    print("node_exporter adapter — captured-scrape parse:")
    for n, c in checks:
        print(f"  {'✓' if c else '✗ FAIL'}  {n}")
    print(f"  {ok}/{len(checks)} passed" + ("" if ok == len(checks) else " — FIX"))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
