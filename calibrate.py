#!/usr/bin/env python3
"""calibrate.py — derive the recognition floor from a MEASURED score distribution.

The recognition lane matches a free-text situation to an axiom by cosine similarity. A single
absolute threshold (the inherited 0.30) over-fires out-of-domain: unrelated text still lands a
weak best-match and, above 0.30, would be treated as a recognised concern. This tool fixes
that with EVIDENCE, not a guessed constant.

It runs a labelled probe set — in-domain sysadmin situations that SHOULD recognise an axiom,
and out-of-domain text that should NOT — through the real embedder against a registry, then
sweeps two knobs:

  FLOOR   — the minimum top-1 cosine to fire at all.
  MARGIN  — how far top-1 must beat top-2 (a "domain-confidence" gap: fire only when ONE
            axiom clearly owns the situation, not when several tie in the fuzzy middle).

It picks the gentlest (FLOOR, MARGIN) that keeps 100% in-domain recall while minimising
out-of-domain fires, prints the before/after emit-rate, and writes the measurement +
chosen values to data/calibration.json so the choice is reproducible and auditable.

  python3 calibrate.py                 # measure + choose + write calibration.json
  python3 calibrate.py --report        # measure + print, don't write
  python3 calibrate.py --registry <path>

Needs a [live] embedder (`pip install aura-pce[live]`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import logic_lane
import paths

# In-domain probes: (situation, expected-axiom). These match the SHIPPED sample registry
# (the six sysadmin axioms). Two phrasings per axiom so recall isn't a single-string fluke.
IN_DOMAIN = [
    ("a writer crashed before the file rename completed", "atomic_write_temp_rename"),
    ("the process died mid-write and left a half-written file", "atomic_write_temp_rename"),
    ("a metric reading crossed the z-score anomaly threshold", "zscore_anomaly"),
    ("temperature spiked far above its normal baseline z-score", "zscore_anomaly"),
    ("free disk space dropped below the safety floor", "disk_space_guard"),
    ("the volume is almost full so refuse further writes", "disk_space_guard"),
    ("verify the restored backup matches the original checksum", "backup_verify_checksum"),
    ("a restored backup must match the original bytes", "backup_verify_checksum"),
    ("reclaim a stale lock whose owning process is dead", "stale_lock_detect"),
    ("the lock is held by a process that no longer exists", "stale_lock_detect"),
    ("sustained memory pressure has exceeded the limit", "memory_pressure"),
    ("memory pressure is high and keeps climbing", "memory_pressure"),
]

# Out-of-domain probes: none of these should fire. A mix of the DS questions the old selftest
# wrongly used, casual text, and the kind of spurious operational-sounding string the
# 2026-07-11 dialogue run showed over-firing.
OUT_OF_DOMAIN = [
    "is the difference between my two conversion rates statistically significant",
    "integrate this smooth function to high accuracy",
    "fit an accelerated failure time survival model",
    "boost weak stumps into a strong classifier",
    "what is the weather forecast for tomorrow",
    "draft the release announcement for the blog",
    "recommend a good pizza topping for friday",
    "translate this sentence into French please",
    "authorization granted proceed with the deployment",
    "schedule a meeting for next tuesday afternoon",
]

FLOOR_GRID = [round(0.20 + 0.02 * i, 2) for i in range(21)]   # 0.20 … 0.60
MARGIN_GRID = [round(0.00 + 0.02 * i, 2) for i in range(16)]  # 0.00 … 0.30


def _scores(text: str, registry):
    """Top-1/top-2 cosine + the top axiom name, straight from the recogniser's candidates."""
    r = logic_lane.logic_need(text, defer_log=False, registry=registry)
    cands = r.candidates or [("", 0.0)]
    top = cands[0]
    second = cands[1][1] if len(cands) > 1 else -1.0
    return top[0], float(top[1]), float(second)


def measure(registry) -> dict:
    pos = [{"text": t, "expect": e, "axiom": a, "top": s, "margin": round(s - s2, 4)}
           for (t, e) in IN_DOMAIN for (a, s, s2) in [_scores(t, registry)]]
    neg = [{"text": t, "axiom": a, "top": s, "margin": round(s - s2, 4)}
           for t in OUT_OF_DOMAIN for (a, s, s2) in [_scores(t, registry)]]
    return {"pos": pos, "neg": neg}


def _fires(rec, floor, margin) -> bool:
    return rec["top"] >= floor and rec["margin"] >= margin


def evaluate(m: dict, floor: float, margin: float) -> dict:
    pos_hit = sum(1 for r in m["pos"] if _fires(r, floor, margin) and r["axiom"] == r["expect"])
    neg_fire = sum(1 for r in m["neg"] if _fires(r, floor, margin))
    return {"floor": floor, "margin": margin,
            "pos_recall": round(pos_hit / len(m["pos"]), 3), "pos_hit": pos_hit,
            "neg_fires": neg_fire, "neg_rate": round(neg_fire / len(m["neg"]), 3)}


def _separation(m: dict, floor: float, margin: float) -> float:
    """How safely a (floor, margin) sits between the two clouds: the smaller of
    (weakest accepted in-domain top − floor) and (floor − strongest rejected out-of-domain
    top). Maximising it centres the floor in the empty band, robust to BOTH a slightly weaker
    real concern and a slightly stronger spurious match — the opposite of hugging either edge."""
    firing_pos = [r["top"] for r in m["pos"] if _fires(r, floor, margin) and r["axiom"] == r["expect"]]
    rejected_neg = [r["top"] for r in m["neg"] if not _fires(r, floor, margin)]
    high = (min(firing_pos) if firing_pos else floor) - floor
    low = floor - (max(rejected_neg) if rejected_neg else floor)
    return round(min(low, high), 4)


def choose(m: dict) -> dict:
    """The floor/margin that best SEPARATES the two clouds. Prefer configs with full in-domain
    recall and zero out-of-domain fires; among those, maximise the separation (centre the floor
    in the gap). Never widen the accept-band to force a known miss — only into a measured-empty
    band. Falls back to fewest-false-fires when no perfectly-separating config exists."""
    perfect = []
    for margin in MARGIN_GRID:
        for floor in FLOOR_GRID:
            e = evaluate(m, floor, margin)
            if e["pos_recall"] >= 1.0 and e["neg_fires"] == 0:
                e["separation"] = _separation(m, floor, margin)
                perfect.append(e)
    if perfect:
        return max(perfect, key=lambda e: e["separation"])
    # no clean split: minimise false fires, then maximise recall, then separation
    allc = [dict(evaluate(m, f, mg), separation=_separation(m, f, mg))
            for mg in MARGIN_GRID for f in FLOOR_GRID]
    return min(allc, key=lambda e: (e["neg_fires"], -e["pos_recall"], -e["separation"]))


def report(m: dict, chosen: dict) -> None:
    before = evaluate(m, 0.30, 0.0)
    print("=== recognition calibration (measured, not guessed) ===\n")
    print(f"probes: {len(m['pos'])} in-domain · {len(m['neg'])} out-of-domain\n")
    print("in-domain top scores (should fire):")
    for r in m["pos"]:
        print(f"  {r['top']:.3f}  margin {r['margin']:+.3f}  {r['axiom']:<26} {r['text'][:44]}")
    print("\nout-of-domain top scores (should NOT fire):")
    for r in sorted(m["neg"], key=lambda x: -x["top"]):
        print(f"  {r['top']:.3f}  margin {r['margin']:+.3f}  {r['axiom']:<26} {r['text'][:44]}")
    print("\n--- before  (FLOOR=0.30, MARGIN=0.00, the inherited single threshold) ---")
    print(f"  in-domain recall {before['pos_recall']}  ·  out-of-domain fires "
          f"{before['neg_fires']}/{len(m['neg'])} ({before['neg_rate']})")
    print(f"--- after   (FLOOR={chosen['floor']}, MARGIN={chosen['margin']}, chosen by evidence) ---")
    print(f"  in-domain recall {chosen['pos_recall']}  ·  out-of-domain fires "
          f"{chosen['neg_fires']}/{len(m['neg'])} ({chosen['neg_rate']})"
          f"  ·  separation {chosen.get('separation', 0.0):+.3f}")
    dr = before["neg_fires"] - chosen["neg_fires"]
    strongest_neg = max((r["top"] for r in m["neg"]), default=0.0)
    weakest_pos = min((r["top"] for r in m["pos"]), default=0.0)
    print(f"\n  → out-of-domain over-fire: {before['neg_fires']}→{chosen['neg_fires']} "
          f"(cut by {dr}); in-domain recall {before['pos_recall']}→{chosen['pos_recall']}.")
    print(f"  → measured gap on this registry: strongest out-of-domain {strongest_neg:.3f} "
          f"< weakest in-domain {weakest_pos:.3f}  (clean gap {weakest_pos - strongest_neg:+.3f}).")
    print("  Note: the MARGIN gate is what cuts over-fire on a LARGE registry, where many "
          "axioms let a weak\n  spurious match clear an absolute floor; on this small sample "
          "the top-score gap alone already separates.")


def main() -> int:
    args = sys.argv[1:]
    registry = None
    if "--registry" in args:
        registry = Path(args[args.index("--registry") + 1]).expanduser()
    try:
        m = measure(registry)
    except ImportError as e:
        print(f"calibration needs a live embedder:\n  {e}", file=sys.stderr)
        return 1
    chosen = choose(m)
    report(m, chosen)
    if "--report" not in args:
        out = paths.data_home()
        out.mkdir(parents=True, exist_ok=True)
        p = out / "calibration.json"
        p.write_text(json.dumps({
            "embedder": _embedder_name(), "registry": str(registry or "sample"),
            "chosen": chosen, "before": evaluate(m, 0.30, 0.0),
            "measurement": m,
            "note": "FLOOR/MARGIN derived by calibrate.py; re-run for any other embedder or registry.",
        }, indent=2))
        print(f"\nwrote {p}")
    return 0


def _embedder_name() -> str:
    try:
        import embedder
        return embedder.backend_name()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
