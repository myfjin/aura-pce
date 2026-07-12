#!/usr/bin/env python3
"""mesh_grade.py — the LEARNING loop for the mesh monitoring organ.

The mesh PCE emits anomaly advice (mesh_bridge.py, sovereign ledger mesh-emits.jsonl).
This closes the loop the honest way — machine proposes, HUMAN disposes:

  - There is NO clean automatic ground truth for the z-anomaly emits: induced stress-event
    logs generally don't line up with the z-spikes (stale timestamps, wrong node, no window
    overlap), so auto-grading against them would fabricate a precision number — the cardinal sin.
  - So each emit is a PROPOSAL. A human (or a future OBJECTIVE signal) grades whether the
    flagged anomaly was REAL (a true machine event) or NOISE (a false positive).
  - The LEVEL is OUTCOME precision — P(emitted anomaly was real) = Beta(1+real, 1+noise) —
    a DIFFERENT axis from the wisdom loop's outcome-blind `held` (which is meaningless for an
    autonomous monitor: the gate always ran). Two sovereign metrics, never conflated.

The number earns SLOWLY and HONESTLY. Until real grades exist: unproven [n=0], never faked.

  python3 mesh_grade.py list                 # pending emits + evidence, for the human
  python3 mesh_grade.py grade <hash> real|noise ["note"]
  python3 mesh_grade.py level                 # earned mesh precision (Beta, with n)
  python3 mesh_grade.py selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import outcomes
import paths

DATA = paths.data_home()
LEDGER = DATA / "mesh-emits.jsonl"


def _load(p: Path = LEDGER) -> list:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def _save(rows: list, p: Path = LEDGER) -> None:
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def level(p: Path = LEDGER) -> dict:
    """Mesh precision = Beta over graded emits (real=hit, noise=miss). Unproven at n=0."""
    rows = _load(p)
    real = sum(1 for r in rows if r.get("graded") and r.get("outcome") == "real")
    noise = sum(1 for r in rows if r.get("graded") and r.get("outcome") == "noise")
    b = outcomes.beta(real, noise)
    n = real + noise
    b.update({"n": n, "unproven": n == 0, "real": real, "noise": noise,
              "pending": sum(1 for r in rows if not r.get("graded"))})
    b["cite"] = (f"unproven [n=0] — {b['pending']} emits pending human grade"
                 if n == 0 else
                 f"mesh precision {b['mean']} [n={n}] (Beta({1+real},{1+noise}); {real} real / {noise} noise)")
    b["method"] = ("mesh LEVEL = P(emitted anomaly was REAL) = Beta(1+real,1+noise) over "
                   "human-graded mesh emits; OUTCOME metric (not wisdom's outcome-blind held); "
                   "n disclosed; no automatic ground truth exists so grades are human-disposed")
    return b


def grade(h: str, outcome: str, note: str = "", p: Path = LEDGER) -> dict:
    if outcome not in ("real", "noise"):
        raise ValueError("outcome must be real|noise")
    rows = _load(p)
    row = next((r for r in rows if r.get("emit_hash") == h), None)
    if row is None:
        raise ValueError(f"no mesh emit with hash {h}")
    row["graded"] = True
    row["outcome"] = outcome
    if note:
        row["note"] = note
    _save(rows, p)
    return level(p)


def cmd_list(p: Path = LEDGER) -> None:
    rows = _load(p)
    pending = [r for r in rows if not r.get("graded")]
    print(f"=== {len(pending)} mesh emit(s) awaiting grade ({len(rows)-len(pending)} graded) ===")
    for r in pending:
        print(f"\n  hash={r['emit_hash']}  {r.get('node')}  {r.get('pattern')} @{r.get('score')}"
              f"  z={r.get('z_5m')}")
        print(f"    {r.get('situation')}")
        print(f"    → grade: python3 mesh_grade.py grade {r['emit_hash']} real|noise")
    print("\nreal = a true machine event · noise = false positive. Only you know the truth on the box.")


def selftest() -> int:
    """Deterministic, temp ledger — the real mesh ledger is never touched. Proves the LEVEL
    is unproven at n=0 and earns a REAL number as emits are graded."""
    import tempfile
    checks = []
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "mesh.jsonl"
        _save([{"emit_hash": f"h{i}", "pattern": "zscore_anomaly", "graded": False,
                "outcome": None} for i in range(4)], p)
        lv0 = level(p)
        checks.append(("fresh ledger: unproven, n=0", lv0["unproven"] and lv0["n"] == 0))
        checks.append(("cite names pending count", "4 emits pending" in lv0["cite"]))
        grade("h0", "real", p=p)
        grade("h1", "real", p=p)
        grade("h2", "noise", p=p)
        lv = level(p)
        # 2 real, 1 noise → Beta(3,2) mean 0.6
        checks.append(("after 2 real / 1 noise → n=3", lv["n"] == 3))
        checks.append(("precision earns a real number Beta(3,2)=0.6", lv["mean"] == 0.6))
        checks.append(("not unproven once graded", not lv["unproven"]))
        checks.append(("cite shows measured precision + n",
                       "mesh precision 0.6 [n=3]" in lv["cite"]))
        try:
            grade("nope", "real", p=p)
            checks.append(("unknown hash raises", False))
        except ValueError:
            checks.append(("unknown hash raises", True))
    ok = sum(1 for _, c in checks if c)
    for n, c in checks:
        print(f"  {'✓' if c else '✗ FAIL'}  {n}")
    print(f"\n{ok}/{len(checks)} passed" + ("" if ok == len(checks) else " — FIX"))
    return 0 if ok == len(checks) else 1


def main():
    a = sys.argv[1:]
    if not a or a[0] == "list":
        cmd_list()
    elif a[0] == "grade" and len(a) >= 3:
        lv = grade(a[1], a[2], a[3] if len(a) > 3 else "")
        print(f"✓ graded {a[1]} = {a[2]} → {lv['cite']}")
    elif a[0] == "level":
        print(json.dumps(level(), indent=2))
    elif a[0] == "selftest":
        raise SystemExit(selftest())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
