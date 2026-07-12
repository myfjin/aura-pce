# aura-pce — the "I CARE" self-test gate

[![CI](https://github.com/myfjin/aura-pce/actions/workflows/ci.yml/badge.svg)](https://github.com/myfjin/aura-pce/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

> An operational advisor that **runs four self-tests before it speaks, and refuses to
> speak when it cannot verify itself.** This repository is the open-mechanism half of
> AURA's Pattern Composition Engine — the part you can install, run, read, and check today.

Most monitors and AI copilots answer whether or not they had grounds, and their reliability
is asserted by their vendors rather than measured in the open. This engine inverts that.
Before emitting any advice ("this is a real anomaly", "this recovery procedure applies") it
pauses and runs the **I CARE** suite:

1. **Axiom** — is this advice backed by a verified rule?
2. **Type fit** — do the situation's input types actually match what the rule consumes?
3. **Robustness** — is the recognition stable when the input is perturbed with noise?
4. **Non-discrimination** — does the answer survive swapping only the identities in it?

If any check cannot pass, the gate stays silent — or defers out loud ("no verified rule").
Silence and deferral are first-class outputs, not failures.

## Install

```bash
pip install aura-pce            # the core: pure standard library, zero dependencies
pip install "aura-pce[live]"    # + a sentence embedder + psutil, for `watch` on your box
```

The **core** needs nothing but Python ≥ 3.10 — the provenance proof, the self-tests and the
earned-metric reports all run on the standard library alone. The **`[live]`** extra adds the
one thing recognition needs (a sentence embedder) plus a cross-platform telemetry reader, so
`aura-pce watch` can gate the real state of the machine you run it on.

## Quick start

```bash
aura-pce prove                 # the provenance proof: the self-tests survive their own
                               # linter, and each of the four checks has a can-fail witness
aura-pce level                 # the two earned metrics — never conflated
aura-pce selftest              # run every self-test this install can run
```

`aura-pce prove` is the honest headline: it proves the self-tests are real and prints the
validity level *with its n*. On a fresh install that level is `unproven [n=0]` for the advice
gate — because no advice emissions have been graded here — which is the correct, non-inflated
output. There is no code path that prints an unearned number.

### Point it at your box

```bash
pip install "aura-pce[live]"
aura-pce init                          # write the sample registry + demo ledger
aura-pce watch --source auto           # gate REAL local telemetry (Ctrl-C to stop)
aura-pce watch --source psutil --log   # cross-platform; log gated EMITs for grading
aura-pce watch --source node_exporter:http://localhost:9100/metrics
```

`watch` samples a telemetry source, keeps a rolling per-metric baseline, and runs every
anomaly through the same gate — a calm machine stays silent, a genuine spike is recognised,
type-checked, and either **EMITted** (gated advice), **WITHHELD** (recognised but not
verifiable) or **DEFERred** (no matching axiom). Grade what it emits:

```bash
aura-pce list                          # gated emits awaiting a human grade
aura-pce grade <hash> real|noise       # dispose each one; the precision earns its n
```

## What this is, and is not

- **It is** the mechanism, and the mechanism is provably honest: the self-tests pass an
  independent linter over themselves (a self-test that cannot fail is not a self-test), and
  each of the four checks ships with a demonstrated can-fail witness.
- **It is not** a correctness oracle. A deterministic self-test verifies *diligence* (the
  engine checked itself in four ways), not *correctness* (that the advice is right). Advice
  can pass all four checks and still be wrong on unusual data — which is exactly what outcome
  grading captures.
- **It does not** ship a reliability percentage. Reliability is *earned* over graded outcomes
  and always reported with its sample size `n`; at `n=0` the code prints `unproven`, never a
  naked 50%.

Two metrics, kept on separate axes and never conflated:

| metric | question | today, on the sample |
|--------|----------|----------------------|
| **validity LEVEL** | of gated advice, how often did it *hold*? (outcome-blind stop-to-think) | `unproven [n=0]` |
| **mesh precision** | of flagged anomalies, how many were *real*? (human-graded outcome) | `0.6 [n=3]` (demo ledger) |

## The sample vs. the real knowledge

This repository ships a small, hand-written **sample registry** (six sysadmin axioms) and a
**synthetic graded ledger** — enough to run every command above and watch the mechanism work.
They are clearly labelled demonstration data.

They are **not** the AURA knowledge base. The full deployment recognises against sovereign
registries of hundreds of machine-verified rules (verified by compiler or real execution, not
by opinion), and earns its reliability number on live infrastructure. That knowledge and that
earned number are the project's product; they are not in this repository. What is here is the
honest machinery, open for anyone to audit.

## Live recognition & the embedder

Recognition matches a free-text situation to an axiom by embedding. In the full deployment a
private module supplies the embedder; here [`embedder.py`](embedder.py) is the public
reference stand-in (`[live]` extra), exposing exactly `embed(list[str]) -> ndarray` of
L2-normalised vectors. It uses `sentence-transformers` (or `chromadb`) — whichever is
installed. The core never imports it, so the base install stays dependency-free.

## Recognition calibration

The acceptance floor is **measured, not guessed**. [`calibrate.py`](calibrate.py) runs a
labelled in-domain / out-of-domain probe set through the real embedder and derives a floor (and
a domain-confidence margin) that separates the two, then writes `calibration.json` into the
data home. On the shipped sample the two clouds separate cleanly (strongest out-of-domain
`0.164` < weakest in-domain `0.291`); the margin gate is the knob that additionally curbs
over-fire on a *large* registry. Re-run it for your own embedder or registry:

```bash
aura-pce calibrate --report            # measure + print the before/after, don't write
aura-pce calibrate                     # + write calibration.json into the data home
```

See [docs/CALIBRATION.md](docs/CALIBRATION.md) for the method and the measured numbers.

## Layout

| File | Role |
|------|------|
| `i_care.py` | the four-check gate + the earned validity level |
| `logic_lane.py` | axiom recognition over a registry of verified rules (the embedder seam) |
| `ontology.py` | the noun type system used by the type-fit check |
| `mesh_bridge.py` | renders telemetry into typed situations and gates them (`gate_typed`) |
| `mesh_grade.py` | logs each emission, grades it, reports precision with `n` |
| `sources/` | telemetry adapters: `proc`, `psutil`, `node_exporter`, `journal` |
| `embedder.py` | the reference sentence embedder for live recognition (`[live]`) |
| `calibrate.py` | derives the recognition floor from a measured distribution |
| `outcomes.py` | the Beta earned-frequency estimator (unproven at n=0) |
| `wisdom.py` | the append-only fire log the gate writes to |
| `assert_linter.py` | classifies assertions by strength; proves the self-tests real |
| `cli.py` | the `aura-pce` console entry point |
| `paths.py` | resolves the one data home (env → clone `./data` → user data dir) |
| `make_sample_data.py` | generates the demonstration registry + ledger |

More: [docs/QUICKSTART.md](docs/QUICKSTART.md) · [docs/API.md](docs/API.md) ·
[docs/CALIBRATION.md](docs/CALIBRATION.md).

## About

Part of **AURA**, a research program in self-testing infrastructure by Reality Optimizer —
[realityoptimizer.app](https://realityoptimizer.app). Sibling open tools:
[folder-nature](https://pypi.org/project/folder-nature/) (semantic identity + signing for file
trees), [whypass](https://pypi.org/project/whypass/) (a claim-discipline linter),
[copresence](https://pypi.org/project/copresence/).

AURA is developed by a small human–AI working group; AI collaborators are named contributors
in its repositories, and every claim in its documentation is written to be checkable rather
than believed.

## License

Apache-2.0. See [LICENSE](LICENSE).
