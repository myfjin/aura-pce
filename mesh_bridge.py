#!/usr/bin/env python3
"""mesh_bridge.py — the telemetry→typed-situation bridge: the sysadmin PCE as a LIVE organ.

Turns raw kernel/mesh telemetry (the aura shared streams) into GATED PCE decisions,
automatically — closing the loop the 2026-07-11 real-data run left open (there I hand-fed
the input type, which was circular). Here the types come from the EVENT's own data.

Three honest steps per event:
  1. RENDER   — a faithful situation string from the telemetry row (per-stream, deterministic;
                never invents a fact the row doesn't carry).
  2. TYPE     — the event's real fields → their Python types (metric value=float, node=str,
                duration=int). This is the DATA the mesh actually has to offer.
  3. FEED+GATE— recognize the sysadmin axiom, then ask the honest precondition question:
                can the event SUPPLY every type the pattern consumes? (consumed ⊆ available).
                If yes → hand i_care exactly those typed inputs → the 4-check gate can EMIT.
                If no → supply nothing → type_fit abstains → gate WITHHOLDS. i_care stays the
                single arbiter; the bridge only feeds it truthfully.

The EMIT surfaces the axiom's CHECKABLE CONSTRAINT (what to weigh the machine-state against)
and the earned LEVEL (unproven until gated emissions are graded — the honesty floor holds).
log=True would log a lane-tagged fire per EMIT (starts earning the LEVEL); default False.

  python3 mesh_bridge.py run [N]        # gate the last N telemetry events, report
  python3 mesh_bridge.py selftest
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import i_care
import logic_lane
import ontology
import paths

DATA = paths.data_home()
STREAMS = DATA / "streams"
SYS_REG = DATA / "sample_registry.jsonl"
# The monitoring organ's OWN ledger, kept separate from the gate's advice-fire log: a
# mesh emission is graded on OUTCOME (was the anomaly real?) — a different axis from the
# outcome-blind advice log, human-graded, never conflated. See mesh_grade.py.
MESH_LEDGER = DATA / "mesh-emits.jsonl"

# A derived-features row is only an ANOMALY worth advising on when a metric's 5m z-score
# clears this. Below it = normal machine state → the PCE stays silent (renders nothing).
# Honesty: don't call z=0.0 an anomaly just because it's the hottest metric in a calm row.
ANOMALY_Z = 2.0


# ── 1. RENDER: telemetry row → faithful situation ────────────────────────────

def _hot_metric(row: dict):
    """The most anomalous metric family in a derived-features row (by |z_5m|)."""
    cands = [(k, m) for k, m in (row.get("raw") or {}).items() if isinstance(m, dict)]
    return max(cands, key=lambda km: abs(km[1].get("z_5m", 0) or 0)) if cands else None


def render(row: dict, stream: str) -> str:
    if stream == "derived-features":
        h = _hot_metric(row)
        if not h or abs(h[1].get("z_5m", 0) or 0) < ANOMALY_Z:
            return ""                          # normal state — nothing to advise on
        k, m = h
        return (f"{row.get('node')}: {k} anomaly, latest {m.get('latest')}, "
                f"z-score {m.get('z_5m')} over {row.get('window_seconds')}s window, "
                f"delta {m.get('delta_5m')}")
    if stream == "synthetic-events":
        return (f"{row.get('intensity')} {row.get('event_type')} induced on {row.get('node')} "
                f"across {','.join(row.get('axes', []))} for {row.get('duration_sec')}s")
    if stream == "network-events":
        return f"network event on node {row.get('node')}: {row.get('event')}"
    return ""


# ── 2. TYPE: the event's real fields → Python type names ─────────────────────

def _tname(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "dict"
    return type(v).__name__


def typed_fields(row: dict, stream: str) -> dict:
    """Field → Python type string, for the fields the event actually offers as inputs.
    These are the REAL data types the mesh has — not the pattern's signature."""
    if stream == "derived-features":
        h = _hot_metric(row)
        out = {"node": "str"}
        if h:
            m = h[1]
            out.update({"value": _tname(m.get("latest")), "z": _tname(m.get("z_5m")),
                        "delta": _tname(m.get("delta_5m")),
                        "window": _tname(row.get("window_seconds"))})
        return out
    if stream == "synthetic-events":
        return {"node": "str", "event_type": "str", "intensity": "str",
                "duration_sec": _tname(row.get("duration_sec")), "axes": "list"}
    if stream == "network-events":
        return {"node": "str", "event": "str"}
    return {}


# ── 3. FEED + GATE ───────────────────────────────────────────────────────────

def feedable_types(consumed_nouns: list, available: dict) -> list | None:
    """Can the event supply every type the pattern CONSUMES? Greedy match each consumed
    noun to an available field of that noun. Returns the concrete type strings to hand
    i_care (so type_fit checks a REAL feed), or None when the event can't satisfy the
    pattern (→ withhold honestly). void/unknown consumes are treated as always-satisfiable
    (the pattern needs nothing typed there)."""
    avail = Counter(ontology.coarsen(t) for t in available.values())
    by_noun = {}
    for field, t in available.items():
        by_noun.setdefault(ontology.coarsen(t), []).append(t)
    picked = []
    need = Counter(n for n in consumed_nouns if n not in ("void", "unknown"))
    for noun, k in need.items():
        if avail.get(noun, 0) < k:
            return None                       # event cannot supply this input type
        picked.extend(by_noun[noun][:k])
    return picked


def gate_typed(sit: str, avail_fields: dict, registry: Path = SYS_REG, rows_cache=None,
               log: bool = False, evidence: dict | None = None) -> dict:
    """The source-agnostic gate: given a rendered situation and the Python types the source
    can actually SUPPLY, run recognition → precondition-fit → the i_care 4-check gate, and
    return the decision. Every telemetry adapter (mesh streams AND live psutil/proc/journal/
    node_exporter) funnels through here, so i_care stays the single arbiter for all of them.

    `avail_fields` = {field_name: python-type-string} the event offers as inputs.
    `evidence` = {node, z, event_ts} carried into the ledger when a gated EMIT is logged."""
    if not sit:
        return {"situation": "", "decision": "SKIP"}
    r = logic_lane.logic_need(sit, defer_log=False, registry=registry)
    if not r.fired:
        return {"situation": sit, "decision": "DEFER", "pattern": None, "score": r.confidence}
    rows = rows_cache if rows_cache is not None else i_care._rows(registry)
    prow = i_care._row_by_id(r.axiom_id, rows)
    consumed = [c["noun"] for c in (prow.get("signature") or {}).get("consumes", [])] if prow else []
    itypes = feedable_types(consumed, avail_fields) if consumed else None
    rep = i_care.i_care(sit, pattern_id=r.axiom_id, input_types=itypes,
                        registry=registry, rows=rows, log=False)   # sovereign log below, not wisdom
    constraint = next((c.meta.get("constraints") for c in rep.checks
                       if c.name == "axiom" and c.passed), None)
    emit_hash = ""
    if rep.gate and log:
        ev = evidence or {}
        emit_hash = _log_emit(ev.get("node"), ev.get("z"), ev.get("event_ts", ""),
                              ev.get("stream", "live"), sit, r.axiom_id, r.confidence)
    return {"situation": sit, "decision": "EMIT" if rep.gate else "WITHHOLD",
            "pattern": r.axiom_id, "score": r.confidence, "feed": itypes,
            "constraint": constraint, "level": rep.level["cite"], "emit_hash": emit_hash}


def gate_event(row: dict, stream: str, rows_cache=None, log: bool = False) -> dict:
    """Gate one mesh-stream telemetry row (render + type it, then defer to gate_typed)."""
    sit = render(row, stream)
    if not sit:
        return {"situation": "", "decision": "SKIP"}
    h = _hot_metric(row) if stream == "derived-features" else None
    evidence = {"node": row.get("node"), "z": h[1].get("z_5m") if h else None,
                "event_ts": str(row.get("ts", "")), "stream": stream}
    return gate_typed(sit, typed_fields(row, stream), registry=SYS_REG,
                      rows_cache=rows_cache, log=log, evidence=evidence)


def _log_emit(node, z, event_ts: str, stream: str, sit: str, pattern: str, score: float) -> str:
    """Append a mesh emit PROPOSAL to the sovereign ledger (ungraded). Evidence (z-score,
    node, ts) travels with it so the human grade is informed. Idempotent-ish: an
    (event_ts, pattern, situation) hash so the same event re-run doesn't double-log."""
    import hashlib
    ev_ts = str(event_ts)
    eh = hashlib.sha1(f"{ev_ts}|{pattern}|{sit}".encode()).hexdigest()[:12]
    MESH_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if MESH_LEDGER.exists():
        existing = {json.loads(l)["emit_hash"] for l in MESH_LEDGER.read_text().splitlines() if l.strip()}
    if eh in existing:
        return eh
    rec = {"emit_hash": eh, "logged_ts": __import__("time").time(), "event_ts": ev_ts,
           "stream": stream, "node": node, "situation": sit[:200],
           "pattern": pattern, "score": round(score, 3), "z_5m": z,
           "graded": False, "outcome": None}
    with MESH_LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return eh


def _load_stream(stream: str, n: int) -> list:
    p = STREAMS / f"{stream}.jsonl"
    if not p.exists():
        return []
    lines = p.read_text().splitlines()
    return [json.loads(l) for l in lines[-n:] if l.strip()]


def run(n: int = 12, log: bool = False) -> None:
    rows_cache = i_care._rows(SYS_REG)
    tally = Counter()
    print(f"=== mesh_bridge — sysadmin PCE over live telemetry (last ~{n}/stream) ===\n")
    for stream in ("derived-features", "synthetic-events", "network-events"):
        evs = _load_stream(stream, n)
        # for derived-features, prefer the anomalous ones
        if stream == "derived-features":
            evs = sorted(evs, key=lambda r: -abs((_hot_metric(r) or (None, {}))[1].get("z_5m", 0) or 0))[:n]
        seen = set()
        for row in evs:
            d = gate_event(row, stream, rows_cache=rows_cache, log=log)
            if d["decision"] == "SKIP" or d["situation"] in seen:
                continue
            seen.add(d["situation"])
            tally[d["decision"]] += 1
            mark = {"EMIT": "🟢", "WITHHOLD": "🟡", "DEFER": "⚪"}[d["decision"]]
            print(f"{mark} [{stream}] {d['situation'][:72]}")
            if d["pattern"]:
                print(f"     → {d['pattern']} @{d.get('score')}  feed={d.get('feed')}  {d['decision']}")
            if d["decision"] == "EMIT":
                print(f"     weigh machine-state against: {d['constraint']}")
                print(f"     LEVEL: {d['level']}")
    print(f"\n=== {dict(tally)} · EMIT=advise (gated) · WITHHOLD=recognized-but-unverifiable · DEFER=no axiom ===")


def selftest() -> int:
    checks = []
    # feedable: pattern needs scalar, event offers a float → satisfiable
    checks.append(("feed: scalar need, float avail → satisfiable",
                   feedable_types(["scalar"], {"value": "float"}) == ["float"]))
    # not feedable: pattern needs text, event offers only floats
    checks.append(("feed: text need, only floats → None (withhold)",
                   feedable_types(["text"], {"value": "float", "z": "float"}) is None))
    # void/unknown consumes never block
    checks.append(("feed: void consume is always satisfiable",
                   feedable_types(["void"], {"node": "str"}) == []))
    # render faithfulness
    df = {"node": "node-a", "window_seconds": 900,
          "raw": {"thermal_c": {"latest": 47.8, "z_5m": 3.0, "delta_5m": 0.8}}}
    s = render(df, "derived-features")
    checks.append(("render carries the real node + z-score", "node-a" in s and "3.0" in s))
    checks.append(("typed_fields reads metric as float",
                   typed_fields(df, "derived-features").get("value") == "float"))
    ne = {"node": "node-b", "event": "failover_attempted"}
    checks.append(("network render", "failover_attempted" in render(ne, "network-events")))
    ok = sum(1 for _, p in checks if p)
    for n, p in checks:
        print(f"  {'✓' if p else '✗ FAIL'}  {n}")
    print(f"\n{ok}/{len(checks)} passed" + ("" if ok == len(checks) else " — FIX"))
    return 0 if ok == len(checks) else 1


def main():
    a = sys.argv[1:]
    if a and a[0] == "selftest":
        raise SystemExit(selftest())
    n = int(a[1]) if len(a) > 1 and a[1].isdigit() else 12
    run(n, log="--log" in a)


if __name__ == "__main__":
    main()
