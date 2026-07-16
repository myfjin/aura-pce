# Changelog

All notable changes to aura-pce.

## [0.2.0] — 2026-07-17

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
