# Changelog

All notable changes to aura-pce.

## [0.4.1] — 2026-10-22

### Documentation only — no code change

Fixes two gaps in the published README that hid the evidence-capture mechanism shipped in
0.4.0:

- **`For reviewers — reproduce the audit in two minutes`** now includes
  `aura-pce evidence prove` and `aura-pce evidence selftest` with their expected output,
  matching the shape of the other reproducible checks.
- **`Point it at your box`** quick-start now shows `aura-pce evidence watch` and
  `aura-pce evidence show <hash>` alongside `aura-pce grade`, so a reviewer who follows the
  quick-start grades from evidence, not from memory.

A README that announces a mechanism without showing the reviewer how to see it is the exact
defect this project exists to catch. The wheel and sdist for 0.4.1 are byte-identical to
0.4.0 except for the embedded README and the version bump; CI runs the same gates.

## [0.4.0] — 2026-10-21

### Added — `aura-pce evidence` — attach evidence to each emit so grading comes from evidence, not memory

A grading decision made from fading memory is a guess with a label on it. The mesh ledger
records what fired, but not what the box looked like when it fired — so when the operator
sits down the next day to call each emit `real` or `noise`, they are reconstructing from
feel, not evidence. This release ships the mechanism that captures the evidence at the
moment of the fire, keyed by `emit_hash`.

Four new subcommands:

    aura-pce evidence watch [--once]   # tail the mesh ledger, capture a bundle per new emit
    aura-pce evidence show <hash>      # print the captured bundle for one emit
    aura-pce evidence prove            # synthetic emit → capture → verify, in a temp dir
    aura-pce evidence selftest         # unit tests, stdlib-only

Each bundle lives at `~/.local/share/aura-pce/evidence/<emit_hash>.json` and records the
snapshot (`loadavg`, `meminfo`, top-N by RSS and recent CPU ticks), events
(`journalctl` tail), and config (user crontab, running systemd services on user and
system busses). Collectors are isolated: a failing collector records an error in the
bundle, never crashes the watcher. No network calls. Dedup is content-based — if the
bundle for a hash already exists, the watcher skips it, making restart a no-op.

Doctrine: `aura-pce evidence prove` is a reproducible proof-by-run matching the shape
of `aura-pce prove`. A reviewer who installed 0.4.0 clean runs it and sees `PROVE: PASS`
on their own machine. Nothing is cited that was not just measured.

Mechanism/data boundary: the watcher, the schema, and the five collectors are public —
same Apache-2.0 as the rest of aura-pce. The *captured bundles themselves* are per-
deployment data that lives only on the operator's own disk; nothing is uploaded.

## [0.3.3] — 2026-10-20

### Documentation only — no code change

Carries the new `For reviewers — reproduce the audit in two minutes` README section into the
PyPI long-description. Four commands, each with the key expected-output lines quoted so a
reader matches against the real run instead of against our prose.

The wheel and sdist for 0.3.3 are byte-identical to 0.3.2 except for the embedded README. CI
runs the same gates; the packaging check verifies all 17 modules still ship.

## [0.3.2] — 2026-10-20

### Fixed — the CLI hint names the public command, not the implementation

A reviewer who ran `pip install aura-pce && aura-pce selftest` without first running
`aura-pce init` saw `logic_lane` FAIL with:

    ✗ FAIL  sample_registry.jsonl missing — run make_sample_data.py first

`make_sample_data.py` is the internal script. The public command the user actually has is
`aura-pce init`. Hint changed to name it. Exit code (1) unchanged; the measurement unchanged;
only the string a reviewer reads when they skip a setup step.

Found by running the project's own reviewer-replica flow against the published 0.3.1 wheel.

## [0.3.1] — 2026-09-28

### Fixed — 0.3.0 shipped without the composing path, and is yanked

**0.3.0 announced the composing path and contained none of it.** `decompose`, `store`, `extract` and
`compose` were added to the repository and never added to `[tool.setuptools] py-modules`, so both the
wheel and the sdist omitted them. A clean install from PyPI gave:

    compose MISSING · store MISSING · extract MISSING · decompose MISSING · i_care ok

**Nothing caught it because every test ran from the checkout**, where the files are on disk whether or
not they are packaged. Eight green suites were measuring the repository, not the artifact — on the one
surface where a mistake is permanent.

- `py-modules` now lists all 17 modules.
- New CI job **`packaging (the claim ships)`**, running `packaging_check.py`: every declared module
  must be **inside both artifacts**, and every module must **import from an installed wheel with the
  process started in a neutral directory**.
- Both checks were made to fail before being trusted: the gate reports RED against a copy reverted to
  the 0.3.0 configuration.

The lesson is in the script and in the commit: **a check must measure the thing that ships.**

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
