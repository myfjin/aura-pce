#!/usr/bin/env python3
"""Generate the DEMONSTRATION data for the public twin.

This is NOT the AURA knowledge base. The real deployment recognises against sovereign
registries of hundreds of machine-verified rules; those are the project's product and are
not shipped here. What ships is a small *sample* whose six axioms each have a runnable
reference implementation in axioms/ — enough that a stranger can reproduce the self-test proof
and the graded-precision report and watch the mechanism work.

Everything below is synthetic and clearly labelled. Each axiom's `verified` flag is set by
actually running its reference impl (see `_prove_by_run`), never hardcoded.
Run: `python3 make_sample_data.py`.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import paths

DATA = paths.data_home()
DATA.mkdir(parents=True, exist_ok=True)


def _prove_by_run(id_):
    """Run this axiom's reference implementation (axioms/<id>.py) and report the REAL result.

    This is what makes 'verified' honest: the flag is set by an actual execution a stranger
    can reproduce (`python3 axioms/<id>.py`), never hardcoded. If the impl is missing or its
    self-test fails, the axiom is marked NOT verified — no false 'proven by run' ships.
    """
    impl = ROOT / "axioms" / f"{id_}.py"
    if not impl.exists():
        return False, {"reference_impl": None, "note": "no reference implementation on disk"}
    try:
        r = subprocess.run([sys.executable, str(impl)], capture_output=True, text=True, timeout=30)
    except Exception as e:  # pragma: no cover
        return False, {"reference_impl": f"axioms/{id_}.py", "error": str(e)[:120]}
    ok = r.returncode == 0
    return ok, {
        "reference_impl": f"axioms/{id_}.py",
        "command": f"python3 axioms/{id_}.py",
        "exit_code": r.returncode,
        "self_test": (r.stdout or "").strip().splitlines()[-1:] and (r.stdout or "").strip().splitlines()[-1] or "",
        "proven_by_run": ok,
    }


def axiom(id_, category, consumes, posts, core, strength):
    """consumes: list of (name, type, noun). posts: list of (expr, msg, tier)."""
    verified, evidence = _prove_by_run(id_)
    grade = "proven by run" if verified else "UNPROVEN (reference impl did not pass)"
    belief = (f"When it runs, {id_.replace('_', ' ')} guarantees "
              + "; ".join(p[1] for p in posts)
              + f" ({strength}-grade: {grade}).")
    return {
        "id": id_, "sphere": "SYS", "category": category,
        "signature": {
            "consumes": [{"name": n, "type": t, "noun": no} for (n, t, no) in consumes],
            "produces": {"type": "", "names": [], "noun": "unknown"},
        },
        "post_conditions": [
            {"expr": e, "msg": m, "tier": ti, "tag": "sample", "verified": verified}
            for (e, m, ti) in posts
        ],
        "invariant_guards": [],
        "core_idea": f"{id_}: {core}",
        "belief_sentence": {"text": belief, "status": "gate-run-sample-v2"},
        "type_nouns_raw": [no for (_, _, no) in consumes],
        "verified_run": verified,
        "strength": strength,
        "is_axiom": True,
        "extraction": {"source": "reference-impl", "impl": f"axioms/{id_}.py"},
        "evidence": evidence,
    }


REGISTRY = [
    axiom("atomic_write_temp_rename", "Crash-safety",
          [("path", "str", "path"), ("payload", "bytes", "bytes")],
          [("results['after_crash'] == results['expected_old']",
            "a crash mid-write must leave the old file intact", "recovery")],
          "Write to a temp file then rename; a crash never leaves a half-written file.",
          "recovery"),
    axiom("zscore_anomaly", "Telemetry",
          [("value", "float", "scalar")],
          [("results['is_anomaly'] == (abs(results['z']) >= 2.0)",
            "flag iff the z-score crosses the threshold", "recovery")],
          "Flag a metric reading as anomalous exactly when its z-score crosses 2.0.",
          "recovery"),
    axiom("disk_space_guard", "Capacity",
          [("free_bytes", "float", "scalar")],
          [("results['refused'] == (results['free_bytes'] < results['floor'])",
            "refuse the write below the floor", "recovery")],
          "Refuse a write when free space is under a floor, before the disk fills.",
          "recovery"),
    axiom("backup_verify_checksum", "Storage",
          [("blob", "bytes", "bytes")],
          [("results['restored_digest'] == results['original_digest']",
            "a restored backup must match the original byte-for-byte", "recovery")],
          "A backup is only trusted after a restored copy matches the original checksum.",
          "recovery"),
    axiom("stale_lock_detect", "Concurrency",
          [("lock_path", "str", "path")],
          [("results['reclaimed'] == results['owner_dead']",
            "reclaim the lock iff its owner process is gone", "weak")],
          "Reclaim a held lock only when the owning process is verifiably dead.",
          "weak"),
    axiom("memory_pressure", "Telemetry",
          [("pressure", "float", "scalar")],
          [("results['alert'] == (results['pressure'] > results['limit'])",
            "alert above the pressure limit", "weak")],
          "Raise a memory-pressure alert when sustained pressure exceeds a limit.",
          "weak"),
]


def graded(h, node, pattern, z, sit, outcome):
    return {"emit_hash": h, "logged_ts": 0.0, "event_ts": "2026-01-01T00:00:00+00:00",
            "stream": "derived-features", "node": node, "situation": sit,
            "pattern": pattern, "score": 0.47, "z_5m": z, "graded": True, "outcome": outcome}


# A synthetic ledger: 2 true events, 1 false positive → precision 0.6 [n=3]. This shows
# the REPORT mechanism. The project's real, earned number lives in its published results,
# graded on its own infrastructure — never invented here.
LEDGER = [
    graded("demo0001aaaa", "demo-node-a", "zscore_anomaly", 3.1,
           "demo-node-a: thermal anomaly, latest 71.0, z-score 3.1 over 900s window", "real"),
    graded("demo0002bbbb", "demo-node-b", "zscore_anomaly", 2.6,
           "demo-node-b: cpu_load anomaly, latest 4.2, z-score 2.6 over 900s window", "real"),
    graded("demo0003cccc", "demo-node-a", "zscore_anomaly", 2.9,
           "demo-node-a: io_pressure anomaly, latest 0.01, z-score 2.9 over 900s window", "noise"),
]


def main():
    reg = DATA / "sample_registry.jsonl"
    reg.write_text("".join(json.dumps(r) + "\n" for r in REGISTRY))
    led = DATA / "mesh-emits.jsonl"
    led.write_text("".join(json.dumps(r) + "\n" for r in LEDGER))
    print(f"wrote {len(REGISTRY)} sample axioms → {reg}")
    print(f"wrote {len(LEDGER)} demonstration graded emits → {led}")
    print("(sample/demonstration data — not the AURA knowledge base)")


if __name__ == "__main__":
    main()
