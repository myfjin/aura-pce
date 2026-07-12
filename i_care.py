#!/usr/bin/env python3
"""i_care.py — THE "I CARE" SELF-TEST SUITE (the engine's pause before it speaks).

Before the engine emits a prediction or piece of advice it PAUSES and runs a series of
self-tests on its own candidate — "am I assuming too much? does this match a validated
rule? am I about to speak on inputs that don't fit?" The pause is the space between the
drafted recommendation and speaking it. "I care" == the pause HAPPENED (deliberation),
measured outcome-blind: even when the advice later proves wrong, the self-check having
run is the thing this metric records. Correctness is measured separately, by grading.

The suite composes small, single-purpose parts:
  - AXIOM CHECK        → logic_lane.logic_need + a registry of verified rules
  - TYPE/PRECOND FIT   → ontology.coarsen (the noun type system) vs the pattern signature
  - ROBUSTNESS         → recognition stability under noise perturbation (logic_need)
  - NON-DISCRIMINATION → recognition invariance under identity swap (logic_need)
  - the LEVEL          → outcomes.beta (earned frequency, never asserted)
  - the fire log       → wisdom.log_fire (append a gradeable record of each emission)
  - the meta-honesty   → assert_linter over THIS file's own selftests

TWO distinct things — do not conflate them (an inflated claim lives in the conflation):
  GATE  (per-emission, deterministic, available NOW): did this one advice pass all four
        self-checks? A diligence gate on a single recommendation.
  LEVEL (aggregate, Beta, EARNED): of all I-CARE-gated advice, how often did it actually
        HOLD? a/(a+b) [n=graded]. This is the citeable trust metric — and today n=0, so
        it prints "unproven", NEVER a naked 50%. The number earns itself from grading.

HONEST BOUNDARY (stated so the claim never inflates): these self-tests verify DILIGENCE
(type fit, a real verified constraint exists, recognition is stable + identity-invariant),
NOT semantic correctness. A pattern can pass all four and still be wrong on weird data —
that is what the grading catches and the Beta records. "I care" is the pause, not an oracle.

  python3 i_care.py "situation text" [--pattern PATTERN_ID] [--types "List[float],float"]
  python3 i_care.py --prove        # the fundraising provenance: lint the selftests + run them
  python3 i_care.py --selftest
  python3 i_care.py --level         # show the earned validity level with its n
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import os

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))   # assert_linter, ontology, logic_lane ship as siblings

import ontology  # pure-stdlib (ast); safe at import time

# All runtime data resolves under one root: the repo's ./data by default, or wherever
# AURA_PCE_HOME points for a real deployment. Nothing is written outside it.
DATA = Path(os.environ.get("AURA_PCE_HOME", HERE / "data"))
REGISTRY = DATA / "sample_registry.jsonl"
FIRES = DATA / "i-care-fires.jsonl"
CALLER = "i_care"
LANE = "i_care"

# Inherited from ds_need/logic_lane's measured 0.30 — the recognition floor. Not asserted;
# re-calibrate from the miss queue if the surface drifts (never widen to force a fire).
THRESHOLD = 0.30
assert 0.2 <= THRESHOLD <= 0.9

# Deterministic perturbations for ROBUSTNESS — NOISE that must not change a robust
# recommendation (casing, punctuation, doubled spaces, a dropped filler word). No RNG:
# a fundraising metric must be reproducible by a stranger, byte-for-byte.
_FILLER = re.compile(r"\b(please|just|really|actually|kind of|sort of|maybe|so)\b", re.I)

# Identity tokens that SHOULD be operationally irrelevant — the same signal must earn the
# same advice regardless of which host / user / environment it came from. Swaps are a fixed
# deterministic map (NON-DISCRIMINATION). Absence of identity ⇒ advice cannot depend on it.
_IDENTITY_SWAP = {
    "production": "staging", "prod": "dev", "staging": "production", "dev": "prod",
    "root": "guest", "admin": "user", "guest": "root", "user": "admin",
    "master": "replica", "replica": "master", "primary": "secondary", "secondary": "primary",
}
_IDENTITY_RE = re.compile(r"\b(" + "|".join(sorted(_IDENTITY_SWAP, key=len, reverse=True))
                          + r"|node-?\d+|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", re.I)

CHECK_NAMES = ("axiom", "type_fit", "robustness", "non_discrimination")


@dataclass
class ICareCheck:
    name: str
    passed: bool | None          # True=verified-ok · False=failed · None=couldn't-check
    reason: str
    meta: dict = field(default_factory=dict)


@dataclass
class ICareReport:
    situation: str
    pattern_id: str              # the recommendation being self-tested ("" = none recognized)
    checks: list                 # [ICareCheck] in CHECK_NAMES order
    level: dict                  # the earned Beta validity level (unproven at n=0)
    method: str                  # method disclosure (reproducibility)
    fire_hash: str = ""          # logged when GATED, else ""

    @property
    def gate(self) -> bool:
        """Did this advice earn emission? ALL four checks verified-ok. A None (couldn't
        check) does NOT inflate the gate — honest-strict: unchecked ≠ passed."""
        return bool(self.checks) and all(c.passed is True for c in self.checks)

    @property
    def n_passed(self) -> int:
        return sum(1 for c in self.checks if c.passed is True)


# ── registry access ─────────────────────────────────────────────────────────

def _rows(registry: Path | None = None) -> list[dict]:
    reg = REGISTRY if registry is None else Path(registry)
    if not reg.exists():
        return []
    return [json.loads(l) for l in reg.read_text().splitlines() if l.strip()]


def _row_by_id(pattern_id: str, rows: list[dict] | None = None) -> dict | None:
    for r in (rows if rows is not None else _rows()):
        if r.get("id") == pattern_id:
            return r
    return None


def _default_recognizer(text: str, registry: Path | None = None) -> str:
    """Recognize the top axiom for a situation (the PCE's own recognition), against the
    given sovereign registry (None = the DS logic_registry). Returns the axiom id, or ""
    when nothing fires. Lazy import: brain/numpy live in the venv."""
    import logic_lane
    r = logic_lane.logic_need(text, defer_log=False, registry=registry)
    return r.axiom_id if r.fired else ""


# ── the four self-tests — each REAL (proven can-fail in selftest) ────────────

def check_axiom(row: dict | None) -> ICareCheck:
    """AXIOM CHECK: does the advice rest on a REAL, verified, checkable constraint?
    Passes iff the pattern carries a run-verified non-hollow axiom of graded strength.
    Fails on: unknown pattern · hollow (is_axiom=False — "I can name the method, I have
    no constraint to hand you") · strength 'none' · not verified by run."""
    if row is None:
        return ICareCheck("axiom", False, "no pattern recognized — no axiom to stand on")
    if not row.get("is_axiom"):
        return ICareCheck("axiom", False,
                          f"{row.get('id')} recognized but HOLLOW (no checkable constraint)")
    strength = row.get("strength", "none")
    if strength not in ("recovery", "weak"):
        return ICareCheck("axiom", False, f"{row.get('id')} strength={strength} (no pin)")
    if not row.get("verified_run"):
        return ICareCheck("axiom", False, f"{row.get('id')} axiom not verified by run")
    belief = (row.get("belief_sentence") or {}).get("text", "")
    return ICareCheck("axiom", True,
                      f"verified {strength}-strength axiom",
                      {"belief": belief[:160],
                       "constraints": [p.get("expr") for p in row.get("post_conditions", [])][:3],
                       "trust": (row.get("review") or {}).get("trust", "unreviewed")})


def check_type_fit(row: dict | None, input_types: list[str] | None) -> ICareCheck:
    """TYPE/PRECONDITION FIT: the situation's declared input nouns must be consumed by the
    pattern. No declared types → None (couldn't check; honestly NOT a pass). A mismatch → fail."""
    if row is None:
        return ICareCheck("type_fit", False, "no pattern to fit against")
    consumed = {c.get("noun") for c in (row.get("signature") or {}).get("consumes", [])}
    if not input_types:
        return ICareCheck("type_fit", None,
                          "no input types declared — cannot verify precondition fit",
                          {"pattern_consumes": sorted(x for x in consumed if x)})
    got = {ontology.coarsen(t) for t in input_types}
    unmet = {n for n in got if n not in consumed and n not in ("unknown", "void")}
    if unmet:
        return ICareCheck("type_fit", False,
                          f"type mismatch: pattern consumes {sorted(consumed)}, got {sorted(got)}",
                          {"unmet": sorted(unmet)})
    return ICareCheck("type_fit", True, f"input nouns {sorted(got)} ⊆ consumed {sorted(consumed)}")


def _perturbations(s: str) -> list[str]:
    """Deterministic noise variants — a robust recommendation survives all of them."""
    return [
        s.lower(),
        re.sub(r"[^\w\s]", "", s),                 # punctuation stripped
        re.sub(r"\s+", "  ", s.strip()),           # spacing perturbed
        _FILLER.sub("", s).strip(),                # a filler word dropped
    ]


def check_robustness(situation: str, expect_id: str, recognizer=None,
                     k: int = 4) -> ICareCheck:
    """ROBUSTNESS: does the recommendation survive NOISE? Re-recognize under k deterministic
    perturbations; passes iff the same axiom wins every time. A recommendation that flips
    when you rephrase the ask was never really recommended."""
    if not expect_id:
        return ICareCheck("robustness", None, "no recommendation to stress")
    rec = recognizer or _default_recognizer
    variants = _perturbations(situation)[:k]
    got = [rec(v) for v in variants]
    flips = [(v[:40], g) for v, g in zip(variants, got) if g != expect_id]
    if flips:
        return ICareCheck("robustness", False,
                          f"recommendation flipped under {len(flips)}/{len(variants)} noise variants",
                          {"flips": flips})
    return ICareCheck("robustness", True, f"stable across {len(variants)} noise perturbations")


def _identity_swaps(s: str) -> list[str]:
    """Identity-swapped variants of the situation (host/user/env tokens replaced). Empty
    when the situation carries no identity — then advice provably cannot depend on it."""
    if not _IDENTITY_RE.search(s):
        return []

    def sub(m):
        tok = m.group(0)
        low = tok.lower()
        if low in _IDENTITY_SWAP:
            repl = _IDENTITY_SWAP[low]
            return repl.upper() if tok.isupper() else repl.capitalize() if tok[0].isupper() else repl
        if low.startswith("node"):
            return "node-0"
        return "10.0.0.0"                          # neutral host
    return [_IDENTITY_RE.sub(sub, s)]


def check_nondiscrimination(situation: str, expect_id: str, recognizer=None) -> ICareCheck:
    """NON-DISCRIMINATION: the same operational signal must earn the same advice regardless
    of WHO/WHERE it came from. Swap identity tokens; passes iff the recommendation is
    invariant. No identity present → vacuously invariant (advice cannot depend on it)."""
    if not expect_id:
        return ICareCheck("non_discrimination", None, "no recommendation to test")
    swaps = _identity_swaps(situation)
    if not swaps:
        return ICareCheck("non_discrimination", True,
                          "no identity tokens — advice cannot depend on identity (vacuously invariant)")
    rec = recognizer or _default_recognizer
    got = [rec(s) for s in swaps]
    diverged = [(s[:40], g) for s, g in zip(swaps, got) if g != expect_id]
    if diverged:
        return ICareCheck("non_discrimination", False,
                          "identity swap CHANGED the recommendation — advice discriminates on identity",
                          {"diverged": diverged})
    return ICareCheck("non_discrimination", True, "recommendation invariant to identity swap")


# ── the earned validity LEVEL (Beta; unproven at n=0, never a naked 50%) ─────

def level(fires_path: Path | None = None) -> dict:
    """P(I-CARE-gated advice HOLDS) = Beta(1+held, 1+failed) over GRADED i_care fires.
    Earned frequency, never asserted. At n=0 → 'unproven' (Beta(1,1)), never printed 50%."""
    import outcomes
    fp = fires_path or FIRES
    held = failed = 0
    if fp.exists():
        for line in fp.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("caller") == CALLER and r.get("graded"):
                if r.get("grade_held"):
                    held += 1
                else:
                    failed += 1
    b = outcomes.beta(held, failed)
    n = held + failed
    b["n"] = n
    b["unproven"] = (n == 0)
    b["cite"] = (f"unproven [n=0] — no graded I-CARE emissions yet" if n == 0
                 else f"{b['mean']} [n={n}] (Beta({1 + held},{1 + failed}), held/graded)")
    b["method"] = ("validity LEVEL = earned frequency that advice passing all four I-CARE "
                   "self-checks HELD, Beta(1+held,1+failed) over graded fires (caller=i_care); "
                   "held is outcome-blind stop-to-think per the wisdom loop; n disclosed always")
    return b


# ── orchestration ────────────────────────────────────────────────────────────

def i_care(situation: str, pattern_id: str | None = None,
           input_types: list[str] | None = None, log: bool = True,
           fires_path: Path | None = None, recognizer=None,
           rows: list[dict] | None = None, registry: Path | None = None) -> ICareReport:
    """Run the four self-tests on a candidate (situation → recommended pattern) BEFORE the
    PCE speaks. Recognizes the pattern when not named. Logs a lane-tagged fire iff GATED.
    `registry` selects the sovereign conscience (None = DS; sysadmin_registry.jsonl for the
    fundraising sysadmin PCE) — it drives BOTH the axiom rows AND recognition. `rows` /
    `recognizer` override those directly (selftest injection)."""
    rows = _rows(registry) if rows is None else rows
    rec = recognizer or (lambda t: _default_recognizer(t, registry))
    pid = pattern_id or rec(situation)
    row = _row_by_id(pid, rows) if pid else None

    checks = [
        check_axiom(row),
        check_type_fit(row, input_types),
        check_robustness(situation, pid, recognizer=rec),
        check_nondiscrimination(situation, pid, recognizer=rec),
    ]
    lvl = level(fires_path)
    reg_name = Path(registry).name if registry else REGISTRY.name
    method = (f"I CARE self-test suite v1 (registry={reg_name}): axiom · type_fit(ontology) · "
              "robustness(noise-perturbation stability) · non_discrimination(identity-swap "
              "invariance). GATE = all four verified-ok. " + lvl["method"])
    report = ICareReport(situation, pid, checks, lvl, method)

    if log and report.gate:
        try:
            import wisdom
            profile = ",".join(f"{c.name}:ok" for c in checks)
            report.fire_hash = wisdom.log_fire(
                situation=situation, move=pid, fire=lvl["mean"], resolution="I_CARE_GATE",
                directive=f"I-CARE passed [{profile}]", proposed=f"apply {pid}",
                trust=lvl["cite"], caller=CALLER, lane=LANE, fires_path=fires_path)
        except Exception as e:  # fail-open: logging must never break the advice
            print(f"[i_care] fire-log fail-open: {e}", file=sys.stderr)
    return report


def render(r: ICareReport) -> str:
    mark = {True: "✓", False: "✗", None: "?"}
    lines = [f"— I CARE self-test: {r.situation[:64]!r} → {r.pattern_id or '(none)'} —"]
    for c in r.checks:
        lines.append(f"  {mark[c.passed]} {c.name:<18} {c.reason}")
        if c.name == "axiom" and c.passed and c.meta.get("constraints"):
            lines.append(f"      weigh against: {c.meta['constraints']}  "
                         f"(trust {c.meta.get('trust')})")
    lines.append(f"  GATE: {'EMIT' if r.gate else 'WITHHOLD'} "
                 f"({r.n_passed}/4 checks verified-ok)")
    lines.append(f"  validity LEVEL: {r.level['cite']}")
    if r.fire_hash:
        lines.append(f"  logged fire {r.fire_hash} (lane=i_care) — earns its grade in the wisdom loop")
    lines.append("  held = the pause happened (I care), outcome-blind. LEVEL earns its number from grading.")
    return "\n".join(lines)


# ── the fundraising provenance: the selftests must themselves be REAL ────────

def lint_selftests(path: Path | None = None):
    """Run assert_linter over THIS file — the selftest that can't fail is not a selftest.
    PASS iff the file carries ≥1 recovery-tier assert (a claim pinned to a planted truth)."""
    import assert_linter
    return assert_linter.lint_file(str(path or Path(__file__).resolve()))


def selftest() -> int:
    """Deterministic. Proves EACH of the four checks can both PASS and FAIL — a can-fail
    witness per check — then pins the two load-bearing facts with recovery-tier asserts
    (so assert_linter vets this selftest as real). Uses synthetic rows + a stub recognizer
    so the proof is registry-independent and needs no embedder."""
    demonstrated_can_fail = 0     # +1 each time a check is WITNESSED returning False
    clean_passes = 0              # checks that pass on the all-clean scenario

    real_row = {"id": "good_axiom", "is_axiom": True, "strength": "recovery",
                "verified_run": True, "belief_sentence": {"text": "when it runs, x holds"},
                "post_conditions": [{"expr": "abs(x - target) < 1e-9"}],
                "signature": {"consumes": [{"noun": "vector"}]}, "review": {"trust": "corroborated"}}
    hollow_row = {"id": "hollow", "is_axiom": False, "strength": "none", "verified_run": True,
                  "signature": {"consumes": [{"noun": "vector"}]}}

    # 1. AXIOM — passes on a real verified axiom, fails on a hollow pattern.
    if check_axiom(real_row).passed is True:
        clean_passes += 1
    if check_axiom(hollow_row).passed is False:
        demonstrated_can_fail += 1

    # 2. TYPE_FIT — passes when input noun ⊆ consumed, fails on a mismatch.
    if check_type_fit(real_row, ["List[float]"]).passed is True:     # List[float] → vector
        clean_passes += 1
    if check_type_fit(real_row, ["str"]).passed is False:            # str → text ≠ vector
        demonstrated_can_fail += 1

    # 3. ROBUSTNESS — with a STABLE recognizer it passes; with an unstable one it fails.
    stable = lambda t: "good_axiom"
    unstable = lambda t: "good_axiom" if t.isupper() else "OTHER"    # flips under lowercase noise
    if check_robustness("Boost Weak Stumps", "good_axiom", recognizer=stable).passed is True:
        clean_passes += 1
    if check_robustness("Boost Weak Stumps", "good_axiom", recognizer=unstable).passed is False:
        demonstrated_can_fail += 1

    # 4. NON-DISCRIMINATION — identity-free ⇒ pass; identity-swap flip ⇒ fail.
    if check_nondiscrimination("boost weak stumps", "good_axiom", recognizer=stable).passed is True:
        clean_passes += 1
    disc = lambda t: "good_axiom" if "prod" in t.lower() else "DENIED"  # treats prod ≠ dev
    if check_nondiscrimination("restart the prod database node-13", "good_axiom",
                               recognizer=disc).passed is False:
        demonstrated_can_fail += 1

    # GATE + LEVEL on a synthetic clean report (temp fire stream — real one untouched).
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        fp = Path(td) / "fires.jsonl"
        rep = i_care("boost weak stumps into a strong classifier", pattern_id="good_axiom",
                     input_types=["List[float]"], recognizer=stable, fires_path=fp,
                     rows=[real_row])
        gate_ok = rep.gate
        lvl = rep.level
        fire_logged = bool(rep.fire_hash) and fp.exists() and any(
            json.loads(l).get("caller") == CALLER and json.loads(l).get("lane") == LANE
            for l in fp.read_text().splitlines() if l.strip())

        # LEVEL round-trip: grade the gated fire held=True → the Beta must MOVE off unproven.
        rows_f = [json.loads(l) for l in fp.read_text().splitlines() if l.strip()]
        for r in rows_f:
            if r.get("fire_hash") == rep.fire_hash:
                r["graded"], r["grade_held"] = True, True
        fp.write_text("".join(json.dumps(r) + "\n" for r in rows_f))
        lvl_after = level(fires_path=fp)

    # ── recovery-tier asserts: pin the load-bearing facts to planted truths ──
    assert demonstrated_can_fail == 4, f"not every check can fail ({demonstrated_can_fail}/4)"
    assert clean_passes == 4, f"clean scenario should pass all 4 ({clean_passes}/4)"
    assert lvl["n"] == 0, "fresh level must have n==0"
    assert lvl["mean"] == 0.5, "Beta(1,1) mean is 0.5 — but printed as unproven, never as 50%"
    assert lvl_after["n"] == 1, "after grading one gated fire the level must have n==1"
    assert lvl_after["mean"] == 0.667, "one held grade → Beta(2,1) mean 0.667 — the number earns itself"

    ok = (demonstrated_can_fail == 4 and clean_passes == 4 and gate_ok and fire_logged
          and lvl["unproven"] and lvl["cite"].startswith("unproven")
          and lvl_after["n"] == 1 and not lvl_after["unproven"])
    print(f"  ✓ each of the 4 checks demonstrated a can-fail witness ({demonstrated_can_fail}/4)")
    print(f"  ✓ all 4 checks pass on the clean scenario ({clean_passes}/4)")
    print(f"  {'✓' if gate_ok and fire_logged else '✗'} GATE emits + logs an i_care-lane fire when all four verified-ok")
    print(f"  {'✓' if lvl['unproven'] else '✗'} LEVEL is unproven at n=0, printed as {lvl['cite']!r} (not 50%)")
    print(f"  {'✓' if lvl_after['n'] == 1 and not lvl_after['unproven'] else '✗'} LEVEL earns its number: after 1 held grade → {lvl_after['cite']}")

    verdict, _ = lint_selftests()
    print(f"  {'✓' if verdict == 'PASS' else '✗'} assert_linter over this file: {verdict} "
          f"(the selftests are themselves real — recovery-tier asserts)")
    ok = ok and verdict == "PASS"
    print(f"\n{'ALL GREEN' if ok else '✗ FIX BEFORE TRUSTING'}")
    return 0 if ok else 1


def prove() -> int:
    """The fundraising provenance, reproducible by a stranger: (a) the selftests are REAL
    (assert_linter), (b) they run green, (c) the LEVEL is measured with its n + method."""
    print("=== I CARE — provenance (prove-then-cite) ===\n")
    verdict, detail = lint_selftests()
    tags = sorted({t for _, t in detail})
    print(f"[a] selftests are REAL — assert_linter: {verdict}  tiers={tags}")
    print("[b] selftests run:")
    rc = selftest()
    lvl = level()
    print(f"\n[c] validity LEVEL (measured, not asserted): {lvl['cite']}")
    print(f"    method: {lvl['method']}")
    print("\nCITE ONLY: level + method + n. Today the honest citation is "
          "'suite verified real (assert_linter PASS); validity level unproven, n=0 — "
          "earns its number as gated emissions are graded.'")
    return rc


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__); return
    if args[0] == "--selftest":
        raise SystemExit(selftest())
    if args[0] == "--prove":
        raise SystemExit(prove())
    if args[0] == "--level":
        print(json.dumps(level(), indent=2)); return
    pattern = types = registry = None
    if "--pattern" in args:
        pattern = args[args.index("--pattern") + 1]
    if "--types" in args:
        types = [t.strip() for t in args[args.index("--types") + 1].split(",")]
    if "--registry" in args:
        registry = Path(args[args.index("--registry") + 1]).expanduser()
    consumed = {pattern, str(registry) if registry else None, *(types or [])}
    situation = " ".join(a for a in args if not a.startswith("--") and a not in consumed)
    print(render(i_care(situation, pattern_id=pattern, input_types=types, registry=registry)))


if __name__ == "__main__":
    main()
