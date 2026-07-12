# Quickstart — point aura-pce at your box

## 1. Install

```bash
pip install "aura-pce[live]"     # core + embedder + psutil
```

The bare `pip install aura-pce` is enough for `prove` / `level` / `selftest` (pure standard
library). You only need `[live]` for `watch` (live recognition needs a sentence embedder).

## 2. Prove the mechanism is honest (no setup, no data)

```bash
aura-pce prove
```

This lints the self-tests (a self-test that cannot fail is not a self-test), runs them, and
prints the validity level *with its n* — `unproven [n=0]` on a fresh install, which is the
correct, non-inflated output.

## 3. Populate the sample data

```bash
aura-pce init          # writes the sample registry + demo ledger into the data home
aura-pce where         # shows exactly where that is
```

The data home is resolved once: `$AURA_PCE_HOME` → the repo's `./data` if you're running from
a checkout → otherwise `~/.local/share/aura-pce`.

## 4. Watch your machine

```bash
aura-pce watch --source auto --interval 5 --window 30
```

- `auto` picks `/proc` on Linux, else `psutil` (macOS / Windows).
- The first `--window` samples build a baseline; nothing is scored until then (honest cold start).
- A metric whose rolling z-score clears `--z` (default 2.0) is rendered, recognised, and gated.

Decisions:

| mark | decision | meaning |
|------|----------|---------|
| 🟢 | EMIT | gated advice — all four self-checks passed |
| 🟡 | WITHHOLD | recognised, but a check could not verify (e.g. no typed input) |
| ⚪ | DEFER | no verified axiom matched — the engine stays out of it |

Add `--log` to record gated EMITs so they can be graded and the precision can earn its `n`.

Other sources:

```bash
aura-pce watch --source psutil
aura-pce watch --source journal
aura-pce watch --source node_exporter:/var/lib/node_exporter/metrics.prom
aura-pce watch --source node_exporter:http://localhost:9100/metrics
```

## 5. Grade what it emits

```bash
aura-pce list                      # pending emits + their evidence (node, pattern, z-score)
aura-pce grade <hash> real|noise   # a true machine event, or a false positive
aura-pce level                     # mesh precision earns its number, with n disclosed
```

Only you know the truth on your box — grading is human-disposed by design. There is no
automatic ground truth, so no number is ever fabricated.
