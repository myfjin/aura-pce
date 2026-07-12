#!/usr/bin/env python3
"""logic_lane.py — the CONSCIENCE lane: recognise the axiom a situation is in.

Where a recall layer finds WHICH pattern fits a situation, this lane recalls the AXIOM
that pattern PROVED about itself — the checkable constraint the engine weighs its draft
advice against before speaking. The registry's verified patterns become the engine's
conscience.

Laws:
  - ADVISORY: surfaces the axiom + its run-witness; never blocks, never executes.
  - recognition-gated: below THRESHOLD → DEFER, not a forced fire.
  - independent recognition: this lane recognises over the belief-sentences (what the
    axiom CLAIMS) — a different semantic surface than a docstring key (what the method
    DOES).

The ✓ pass / ✗ violation / ? uncertain VERDICT is the downstream pause, NOT here: a true
verdict needs symbolic eval or an LLM second pass. Evaluating a boolean post-condition
against free prose would be theater. This lane's honest job is to put the right
constraint in front of the engine, loud; the catch is the engine's own move.

Registry = a JSONL of run-verified axioms. Fire-logging carries lane="logic" so
wisdom.log_fire tags it; held = the pause happened and the axiom was weighed, outcome-blind.

Run:  python3 logic_lane.py "is my A/B conversion difference significant?"
      python3 logic_lane.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths

DATA = paths.data_home()
REGISTRY = DATA / "sample_registry.jsonl"
# Harvested-source dirs (used only when re-deriving a registry from pattern source — the
# public twin ships a ready-made sample_registry.jsonl and never needs these).
PATTERNS_DIR = DATA / "patterns"
R_PATTERNS_DIR = DATA / "patterns"
SYS_PATTERNS_DIR = DATA / "patterns"
CACHE = DATA / "logic_keys_cache.npz"
QUEUE = HERE / "logic_misses.jsonl"        # sovereign L4 defer log (same schema as ds)
LANE = "logic"


# Registry-scoped cache + defer-queue: recognition can point at ANY registry. Each gets
# its OWN embedding cache and miss queue — pooling them would thrash the cache and cross
# separate streams. registry=None uses the default registry.
def _cache_for(registry) -> Path:
    return CACHE if registry is None else HERE / f"logic_keys_cache_{Path(registry).stem}.npz"


def _queue_for(registry) -> Path:
    return QUEUE if registry is None else HERE / f"{Path(registry).stem}_misses.jsonl"

# Inherited default from ds_need's measured 0.30; VERIFIED against this lane's own
# positives/negatives in selftest (the belief-sentence surface scores differently than
# the docstring surface). Re-calibrate from the queue if either side drifts — never
# widen the accept-set to force a fire (the ds_need KNOWN_MISSES discipline).
THRESHOLD = 0.30
assert 0.2 <= THRESHOLD <= 0.9

# Recognition acceptance uses two knobs, defaulting to the inherited-safe single threshold and
# NO margin (backward-compatible: on the sample registry this already fires 0/10 out-of-domain).
#   RECOG_FLOOR  — minimum top-1 cosine to fire at all.
#   RECOG_MARGIN — minimum top1 − top2 gap ("domain-confidence": fire only when ONE axiom
#                  clearly owns the situation). This is the knob that cuts over-fire on a LARGE
#                  registry, where many axioms let a weak spurious match clear an absolute floor.
# A deployment overrides them from a MEASURED data/calibration.json (written by calibrate.py) —
# evidence, never a guessed constant. A missing/malformed file falls back to the safe defaults.
RECOG_FLOOR = THRESHOLD
RECOG_MARGIN = 0.0


def _load_calibration() -> None:
    global RECOG_FLOOR, RECOG_MARGIN
    try:
        p = DATA / "calibration.json"
        if not p.exists():
            return
        chosen = json.loads(p.read_text()).get("chosen", {})
        if "floor" in chosen:
            RECOG_FLOOR = float(chosen["floor"])
        if "margin" in chosen:
            RECOG_MARGIN = float(chosen["margin"])
    except Exception:      # a bad calibration file must never break recognition
        pass


_load_calibration()


# ── the embedder seam ────────────────────────────────────────────────────────
# Recognition needs a sentence embedder exposing embed(list[str]) -> ndarray of
# L2-normalised row vectors (so K @ v is cosine similarity). In the full AURA deployment
# `brain` supplies it; that module is private and NOT shipped in this twin. Here we fall
# back to embedder.py — the reference embedder in the `[live]` extra. The stdlib paths
# (--prove, --selftest, mesh_grade level) never reach this, so the core stays dependency-free.
_EMBEDDER = None


def _embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        try:
            import brain as _e            # full AURA deployment (private, not in this repo)
        except ImportError:
            import embedder as _e         # public reference embedder (`pip install aura-pce[live]`)
        _EMBEDDER = _e
    return _EMBEDDER


@dataclass
class LogicNeed:
    fired: bool
    axiom_id: str            # top axiom (pattern) name ("" when not fired)
    confidence: float        # top cosine score
    belief: str              # the plain belief-sentence (the conscience's words)
    post_conditions: list    # [{expr, msg, verified, tier}] — the checkable constraints
    witness: str             # runnable proof-of-mechanism ("" when not fired)
    candidates: list         # [(name, score), ...] top-3
    strength: str = "none"   # recovery > weak > none — HOW hard the constraint pins
    is_axiom: bool = False   # False = recognized but hollow-only (no real constraint)
    review: dict = None      # optional external reviewer verdict {trust, source_match, note, ...}
    lane: str = LANE


def _axioms(registry=None) -> list[dict]:
    reg = REGISTRY if registry is None else Path(registry)
    if not reg.exists():
        return []
    return [json.loads(l) for l in reg.read_text().splitlines() if l.strip()]


def _keys(rows: list[dict]) -> list[tuple[str, str]]:
    """(id, key_text) per axiom. The key is what the axiom CLAIMS — belief-sentence +
    core idea + category — deliberately NOT the docstring (that is L3's surface)."""
    out = []
    for r in rows:
        belief = (r.get("belief_sentence") or {}).get("text", "")
        key = (f"{r['id'].replace('_', ' ')}. Category: {r.get('category', '')}. "
               f"{belief} {r.get('core_idea', '')}")
        out.append((r["id"], key[:500]))
    return out


def _index(rows: list[dict], registry=None):
    """Names + embedded keys, cached PER REGISTRY; re-embeds only when that registry's keys
    change. Mirrors ds_need._index (same embedder, local + free — no budget)."""
    import numpy as np
    emb = _embedder()

    cache = _cache_for(registry)
    keys = _keys(rows)
    digest = hashlib.md5(json.dumps(keys).encode()).hexdigest()
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        if str(z["digest"]) == digest:
            return list(z["names"]), z["K"]
    names = [n for n, _ in keys]
    K = np.asarray(emb.embed([k for _, k in keys]), dtype=float)
    np.savez(cache, names=np.array(names), K=K, digest=np.array(digest))
    return names, K


def logic_need(situation: str, defer_log: bool = True, registry=None) -> LogicNeed:
    """Recognize the axiom a situation is in the territory of. `registry` selects the
    sovereign registry to recognize against (None = the DS logic_registry.jsonl, unchanged);
    pass sysadmin_registry.jsonl to give the sysadmin PCE its own recognition lane."""
    import numpy as np

    rows = _axioms(registry)
    if not rows:
        return LogicNeed(False, "", 0.0, "", [], "", [])
    by_id = {r["id"]: r for r in rows}
    names, K = _index(rows, registry)
    v = np.asarray(_embedder().embed([situation])[0], dtype=float)
    scores = K @ v
    order = np.argsort(-scores)[:3]
    cands = [(str(names[i]), round(float(scores[i]), 3)) for i in order]
    top_name, top_score = cands[0]
    second = cands[1][1] if len(cands) > 1 else -1.0
    if top_score >= RECOG_FLOOR and (top_score - second) >= RECOG_MARGIN:
        r = by_id[top_name]
        sphere = r.get("sphere")
        witness = (f"Rscript {R_PATTERNS_DIR / (top_name + '.R')}" if sphere == "R"
                   else f"python3 {SYS_PATTERNS_DIR / (top_name + '.py')}" if sphere == "SYS"
                   else f"python3 {PATTERNS_DIR / (top_name + '.py')}")
        return LogicNeed(
            fired=True, axiom_id=top_name, confidence=top_score,
            belief=(r.get("belief_sentence") or {}).get("text", ""),
            post_conditions=r.get("post_conditions", []),
            witness=witness,
            candidates=cands,
            strength=r.get("strength", "none"), is_axiom=r.get("is_axiom", False),
            review=r.get("review") or {"trust": "unreviewed"})
    if defer_log:
        rec = {"input": situation[:300], "stage": "logic_dispatch",
               "candidates": cands,
               "reason": (f"top {top_score} < floor {RECOG_FLOOR}" if top_score < RECOG_FLOOR
                          else f"margin {round(top_score - second, 3)} < {RECOG_MARGIN}"),
               "review_status": "pending",
               "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with _queue_for(registry).open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return LogicNeed(False, "", top_score, "", [], "", cands)


# Recognition drift, recorded not hidden (same discipline as ds_need.KNOWN_MISSES):
# a known miss is FIXED by a build (rerank / graded feedback), never by widening accept.
KNOWN_MISSES: dict = {}


def selftest() -> int:
    """Known asks → expected top-1 axiom (or accept-set); prose must NOT fire. Prints
    the observed score gap so THRESHOLD stays measured, not asserted."""
    # In-domain sysadmin asks → the axiom they should recognise (the SHIPPED sample registry).
    cases = [
        ("a writer crashed before the file rename completed", {"atomic_write_temp_rename"}),
        ("a metric reading crossed the z-score anomaly threshold", {"zscore_anomaly"}),
        ("free disk space dropped below the safety floor", {"disk_space_guard"}),
        ("verify the restored backup matches the original checksum", {"backup_verify_checksum"}),
        ("reclaim a stale lock whose owning process is dead", {"stale_lock_detect"}),
        ("sustained memory pressure has exceeded the limit", {"memory_pressure"}),
    ]
    negatives = [
        "integrate this smooth function to high accuracy",
        "draft the release announcement for the blog",
        "what is the weather forecast for tomorrow",
        "recommend a good pizza topping for friday",
    ]
    if not REGISTRY.exists():
        print("✗ FAIL  sample_registry.jsonl missing — run make_sample_data.py first")
        return 1

    ok, known, regressions = 0, 0, 0
    pos_scores, neg_scores = [], []
    for q, accept in cases:
        r = logic_need(q, defer_log=False)
        pos_scores.append(r.confidence)
        hit = r.fired and r.axiom_id in accept
        if hit:
            ok += 1
            print(f"  ✓ {q[:56]!r} → {r.axiom_id} ({r.confidence})")
        elif q in KNOWN_MISSES:
            known += 1
            print(f"  ~ KNOWN-MISS {q[:48]!r} → {r.axiom_id or '(defer)'}")
        else:
            regressions += 1
            print(f"  ✗ {q[:56]!r} → {r.axiom_id or '(defer)'} ({r.confidence}) "
                  f"top3={r.candidates}")
    neg_ok = 0
    for q in negatives:
        r = logic_need(q, defer_log=False)
        neg_scores.append(r.confidence)
        good = not r.fired
        neg_ok += good
        print(f"  {'✓' if good else '✗'} NEG {q[:50]!r} → "
              f"{'defer (correct)' if good else f'FIRED {r.axiom_id} ({r.confidence})'}")

    # surface the axiom on a fired case — proving L4 returns the CONSTRAINT, not just a name
    demo = logic_need("verify the restored backup matches the original checksum", defer_log=False)
    axiom_surfaced = bool(demo.fired and demo.belief and demo.post_conditions)
    review_carried = bool(demo.fired and demo.review and demo.review.get("trust"))
    print(f"\n  {'✓' if axiom_surfaced else '✗'} surfaces a checkable axiom on fire:")
    if demo.fired:
        print(f"      belief: {demo.belief[:120]}")
        print(f"      constraints: {[p['expr'] for p in demo.post_conditions][:3]}")
        print(f"      strength={demo.strength}  review-trust={demo.review.get('trust')}")
    print(f"  {'✓' if review_carried else '✗'} carries a review trust tier")

    gap_ok = (min(pos_scores) > max(neg_scores)) if pos_scores and neg_scores else False
    inside = gap_ok and (max(neg_scores) < RECOG_FLOOR <= min(pos_scores))
    print(f"\n  score gap — weakest positive {min(pos_scores):.3f} vs "
          f"strongest negative {max(neg_scores):.3f}  "
          f"(FLOOR={RECOG_FLOOR} MARGIN={RECOG_MARGIN}; "
          f"{'clean gap, FLOOR sits inside' if inside else 'OVERLAP — run calibrate.py'})")
    total = len(cases) + len(negatives)
    passed = ok + neg_ok
    print(f"\n{passed}/{total} passed · {known} known-miss · {regressions} NEW regressions "
          f"· axiom-surfaced={axiom_surfaced} · review-carried={review_carried}")
    return (0 if regressions == 0 and neg_ok == len(negatives)
            and axiom_surfaced and review_carried and gap_ok else 1)


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    if sys.argv[1] == "--selftest":
        raise SystemExit(selftest())
    r = logic_need(" ".join(sys.argv[1:]))
    if r.fired and not r.is_axiom:
        print(f"L4 conscience: {r.axiom_id}  (confidence {r.confidence})")
        print(f"  recognized, but this pattern carries NO checkable axiom "
              f"(hollow asserts only) — I can name the method, I have no constraint to hand you.")
        print(f"  run-witness: {r.witness}")
    elif r.fired:
        trust = (r.review or {}).get("trust", "unreviewed")
        print(f"L4 conscience: {r.axiom_id}  (confidence {r.confidence}, "
              f"strength {r.strength}, trust {trust})")
        print(f"  belief:  {r.belief}")
        print(f"  weigh your draft against: {[p['expr'] for p in r.post_conditions]}")
        if trust == "review-rejected":
            print(f"  ⚠ an external review REJECTED this pattern — read before trusting: "
                  f"{(r.review or {}).get('note', '')[:120]}")
        print(f"  run-witness: {r.witness}")
        print("  ADVISORY — L4 surfaces the constraint; the verdict is yours (the pause).")
    else:
        print(f"L4 conscience: no axiom fired (top {r.candidates}) → queued for review")


if __name__ == "__main__":
    main()
