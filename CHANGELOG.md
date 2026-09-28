# Changelog

All notable changes to aura-pce.

## [0.3.0] — 2026-09-28

### Added — the composing path

Four modules, stdlib only, each gated in `aura-pce selftest` and independently verified:

- `decompose.py` — text into five kinds of reasoning component (observation, comparison, hypothesis,
  action, decision). Regex and heuristics, no model. Lossy and conservative on purpose: a fragment
  below `MIN_UNIT_WORDS` is dropped rather than counted.
- `store.py` — three collections (components, patterns, decisions) behind a `Store` protocol, with a
  **stdlib reference store**: three JSONL files and lexical retrieval computed in-python.
- `extract.py` — clusters components into patterns. Greedy single-linkage, time-decay weighting,
  pattern ids derived from member ids so re-runs do not duplicate.
- `compose.py` — fuses components, patterns and current state into one block, or returns nothing.

### The honest limits, stated in the modules and asserted in the tests

- **Retrieval is lexical, and says so.** It groups shared words, not shared meaning: near-identical
  wording scores ≈0.706, the same meaning in different words ≈0.084. The synonym *miss* is a test, so
  a semantic backend cannot be swapped in without the docstring changing with it. At the 0.7
  clustering threshold, no cross-topic pair in our corpus cleared it (0 of 73) — the failure mode is
  silence, not nonsense.
- **The clustering threshold stays 0.7**, the value the engine this came from uses for embeddings.
  Lowering it to 0.5 catches the same three pairs in our corpus — zero additional true pairs — so a
  change would be calibration chosen on six pairs. If a real corpus shows true pairs between 0.5 and
  0.7 that 0.7 misses, that is the measurement that justifies changing it, in both.
- **`compose`'s default signal floor (0.55) is measured, not chosen**: over the reference store,
  related top hits score 0.582–0.706 and unrelated ones 0.500–0.517. It is backend-dependent by
  nature — swapping backends means re-measuring.

### One deliberate divergence from the engine we ported from

`compose` gates **each signal** against its own floor before fusion. The original has a single
threshold on the *weighted total*, so a strong signal carries a weak one — defensible when the block
is context a reader weighs against their own judgement, not defensible when the block speaks. Here a
signal below its floor is excluded rather than carried, the score reflects only signals that cleared,
and if none clears, nothing composes. **A floor that binds the total but not the parts is not a
floor.** Ruled on and accepted by our independent verifier, 2026-09-24.

## [0.2.0] — 2026-07-17

### Packaging

- The wheel now ships `axioms/` (the six reference implementations), so a pip install can
  actually prove-by-run: `aura-pce init` executes each impl and stamps `verified_run` from the
  real exit code. (0.2.0 was previously unreleasable — the version was bumped but the axioms
  were not packaged, which would have stamped every sample UNPROVEN for pip users.)

### Fixed — the sample registry now earns its "verified", it no longer asserts it

The initial release shipped a sample registry of six sysadmin axioms whose records
**hardcoded** `"verified": true` / `"verified_run": true` and a belief sentence ending
"proven by run" — with no actual run behind them. They were hand-written demonstration data,
and the surrounding docs said so honestly, but the per-record claim overstated it. On a project
whose whole thesis is *prove, don't claim*, that was our own overclaim, and we're correcting it
in the open rather than quietly.

What changed:

- **Added `axioms/`** — a runnable reference implementation for each of the six sample axioms
  (`atomic_write_temp_rename`, `zscore_anomaly`, `disk_space_guard`, `backup_verify_checksum`,
  `stale_lock_detect`, `memory_pressure`). Each is a small, dependency-free, portable program
  whose self-test asserts the axiom's post-condition. Run any of them: `python3 axioms/<id>.py`.
- **`make_sample_data.py` now proves by running.** It executes each reference implementation and
  sets `verified` / `verified_run` from the real exit code — never hardcoded. If an impl is
  missing or its self-test fails, that axiom is stamped **UNPROVEN**, and no false "proven by
  run" can ship. Every record carries an `evidence` block naming its impl and exit code.
- Registry status bumped `sample-demonstration-v1` → `gate-run-sample-v2`.

Two of the six reference implementations were caught and fixed before they could ship: one read
Linux-only `/proc/meminfo` (would fail on a reviewer's non-Linux machine — rewritten to test the
threshold guarantee portably), and one used test data where the lone outlier was only 1.79σ, so
the assertion was statistically false (given a real baseline + a genuine outlier). Both were
caught by running them through the same execution gate the full library uses — the mechanism
catching its own demo, which is the point.

The distinction the README already drew still holds: this is **demonstration** data, not the
AURA knowledge base. The change is only that the demonstration now proves itself the same way
the real registries do — by execution, reproducibly, not by opinion.
