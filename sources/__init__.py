#!/usr/bin/env python3
"""sources — telemetry adapters that feed REAL local machine state to the gate.

`aura-pce watch` picks a source (auto-detected or named), samples it, and runs every
resulting situation through the same i_care gate the mesh bridge uses. A calm machine
produces no situations and the engine stays silent; a genuine anomaly (a metric whose
rolling z-score clears the threshold, or a high-severity journal event) is rendered,
recognised, type-checked and either EMITted (gated advice), WITHHELD (recognised but not
verifiable) or DEFERred (no matching axiom).

  get_source("auto" | "proc" | "psutil" | "journal" | "node_exporter:<path|url>")
  watch(...)   — the live loop the CLI drives
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from .base import EventSource, MetricSource, RollingZ, Situation, Source, anomaly_situation

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))   # i_care, mesh_bridge, embedder live one level up

__all__ = ["get_source", "watch", "Situation", "Source", "MetricSource", "EventSource",
           "RollingZ", "anomaly_situation"]


def get_source(spec: str = "auto") -> Source | None:
    """Resolve a source spec to a Source instance (or None if unknown/unavailable)."""
    spec = (spec or "auto").strip()
    if spec.startswith("node_exporter:"):
        from .node_exporter import NodeExporterSource
        return NodeExporterSource(spec.split(":", 1)[1])
    if spec == "proc":
        from .proc_source import ProcSource
        return ProcSource()
    if spec == "psutil":
        from .psutil_source import PsutilSource
        return PsutilSource()
    if spec == "journal":
        from .journal import JournalSource
        return JournalSource()
    if spec == "auto":
        from .proc_source import ProcSource
        from .psutil_source import PsutilSource
        proc = ProcSource()
        if proc.available():
            return proc
        ps = PsutilSource()
        if ps.available():
            return ps
        return proc   # return proc so the caller can report its unavailability cleanly
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def watch(source: str = "auto", interval: float = 5.0, window: int = 30, z: float = 2.0,
          iterations: int = 0, log: bool = False, registry: str | None = None) -> int:
    """The live loop. Returns a POSIX-style exit code (0 ok, non-zero = couldn't start)."""
    import time
    import i_care
    import mesh_bridge

    # recognition needs an embedder — fail early with a clear hint, don't half-run
    try:
        import embedder
        backend = embedder.backend_name()
    except ImportError as e:
        print(f"[watch] {e}", file=sys.stderr)
        return 1

    src = get_source(source)
    if src is None:
        print(f"[watch] unknown source: {source!r}", file=sys.stderr)
        return 2
    if not src.available():
        print(f"[watch] source {src.name!r} is not available on this machine "
              f"(try --source psutil after `pip install aura-pce[live]`)", file=sys.stderr)
        return 2

    reg = Path(registry).expanduser() if registry else mesh_bridge.SYS_REG
    if not reg.exists():
        print(f"[watch] registry not found: {reg}\n  run `aura-pce init` to write the sample "
              f"registry, or pass --registry <your-registry.jsonl>", file=sys.stderr)
        return 2
    rows_cache = i_care._rows(reg)

    kind = "events" if isinstance(src, EventSource) else "metrics"
    print(f"=== aura-pce watch — source={src.name} ({kind}) · embedder={backend} · "
          f"registry={reg.name} · z≥{z} ===")
    print(f"    node={src.node} · sampling every {interval}s · rolling window {window} · "
          f"{'logging EMITs' if log else 'not logging (pass --log to record)'}\n")
    if kind == "metrics":
        print(f"    (building a {window}-sample baseline before any metric can be scored…)\n")

    tracker = RollingZ(window)
    tally = {"EMIT": 0, "WITHHOLD": 0, "DEFER": 0}
    n = 0
    window_s = int(interval * window)
    try:
        while True:
            situations: list[Situation] = []
            if isinstance(src, EventSource):
                situations = src.poll()
            else:
                for metric, value in src.sample().items():
                    zz = tracker.update(metric, value)
                    if zz is not None and abs(zz) >= z:
                        situations.append(anomaly_situation(src.node, metric, value, zz, window_s))
            for s in situations:
                d = mesh_bridge.gate_typed(
                    s.text, s.fields, registry=reg, rows_cache=rows_cache, log=log,
                    evidence={"node": s.node, "z": s.z, "event_ts": _now_iso(), "stream": src.name})
                dec = d["decision"]
                if dec == "SKIP":
                    continue
                tally[dec] = tally.get(dec, 0) + 1
                mark = {"EMIT": "🟢", "WITHHOLD": "🟡", "DEFER": "⚪"}.get(dec, "·")
                print(f"{mark} {_now_iso()}  {dec}  {s.text[:88]}")
                if d.get("pattern"):
                    print(f"     → {d['pattern']} @{d.get('score')}  feed={d.get('feed')}")
                if dec == "EMIT":
                    print(f"     weigh machine-state against: {d.get('constraint')}")
                    print(f"     LEVEL: {d.get('level')}"
                          + (f"   logged {d['emit_hash']}" if d.get("emit_hash") else ""))
            n += 1
            if iterations and n >= iterations:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[watch] stopped.")
    print(f"\n=== {tally} · EMIT=gated advice · WITHHOLD=recognised-but-unverifiable · "
          f"DEFER=no axiom ===")
    if log and tally["EMIT"]:
        print("    grade the logged emits with `aura-pce list` then `aura-pce grade <hash> real|noise`.")
    return 0


# ── selftest: every adapter's captured-sample parse + the runner end-to-end ──

class _FakeSpikeSource(MetricSource):
    """A deterministic metric source: flat baseline, then one hard spike — so the runner is
    guaranteed to render an anomaly and we can prove the whole watch path EMITs."""
    name = "fake"
    node = "test-node"

    def __init__(self):
        self._i = 0

    def sample(self) -> dict:
        self._i += 1
        return {"thermal_c": 45.0 if self._i <= 10 else 85.0}


def _runner_smoketest(reg: Path) -> tuple[str, bool]:
    """Drive the real runner primitives with a fake spike source + the real embedder + sample
    registry; assert the spike produces an EMIT on zscore_anomaly. Needs a [live] backend."""
    import i_care
    import mesh_bridge
    rows = i_care._rows(reg)
    src = _FakeSpikeSource()
    tracker = RollingZ(window=10)
    emitted = None
    for _ in range(14):
        for metric, value in src.sample().items():
            zz = tracker.update(metric, value)
            if zz is not None and abs(zz) >= 2.0:
                s = anomaly_situation(src.node, metric, value, zz, 100)
                d = mesh_bridge.gate_typed(s.text, s.fields, registry=reg, rows_cache=rows)
                if d["decision"] == "EMIT":
                    emitted = d
    ok = emitted is not None and emitted["pattern"] == "zscore_anomaly"
    return (f"runner: fake spike → EMIT on zscore_anomaly "
            f"({emitted['pattern'] if emitted else 'no EMIT'})", ok)


def selftest() -> int:
    from . import journal, node_exporter, proc_source, psutil_source
    rc = 0
    for mod in (proc_source, psutil_source, node_exporter, journal):
        rc |= mod.selftest()
        print()
    # end-to-end runner test — only when an embedder + sample registry are present
    try:
        import embedder
        import mesh_bridge
        embedder.backend_name()
        reg = mesh_bridge.SYS_REG
        if reg.exists():
            name, ok = _runner_smoketest(reg)
            print(f"runner end-to-end:\n  {'✓' if ok else '✗ FAIL'}  {name}")
            rc |= (0 if ok else 1)
        else:
            print(f"runner end-to-end:\n  ⚠ skipped (no sample registry at {reg}; run `aura-pce init`)")
    except ImportError:
        print("runner end-to-end:\n  ⚠ skipped (no [live] embedder backend installed)")
    print("\n" + ("ALL GREEN" if rc == 0 else "✗ some source self-tests FAILED"))
    return rc


if __name__ == "__main__":
    raise SystemExit(selftest())
