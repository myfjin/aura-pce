# aura-pce — the "I CARE" self-test gate

> An operational advisor that **runs four self-tests before it speaks, and refuses to
> speak when it cannot verify itself.** This repository is the open mechanism half of
> AURA's Pattern Composition Engine — the part you can run, read, and check today.

Most monitors and AI copilots answer whether or not they had grounds, and their
reliability is asserted by their vendors rather than measured in the open. This engine
inverts that. Before emitting any advice ("this is a real anomaly", "this recovery
procedure applies") it pauses and runs the **I CARE** suite:

1. **Axiom** — is this advice backed by a verified rule?
2. **Type fit** — do the situation's input types actually match what the rule consumes?
3. **Robustness** — is the recognition stable when the input is perturbed with noise?
4. **Non-discrimination** — does the answer survive swapping only the identities in it?

If any check cannot pass, the gate stays silent — or defers out loud ("no verified
rule"). Silence and deferral are first-class outputs, not failures.

## What this is, and is not

- **It is** the mechanism, and the mechanism is provably honest: the self-tests pass an
  independent linter over themselves (a self-test that cannot fail is not a self-test),
  and each of the four checks ships with a demonstrated can-fail witness.
- **It is not** a correctness oracle. A deterministic self-test verifies *diligence*
  (the engine checked itself in four ways), not *correctness* (that the advice is right).
  Advice can pass all four checks and still be wrong on unusual data — which is exactly
  what outcome grading captures.
- **It does not** ship a reliability percentage. Reliability is *earned* over graded
  outcomes and always reported with its sample size `n`; at `n=0` the code prints
  `unproven`, never a naked 50%. There is no code path that prints an unearned number.

## Quick start (pure standard library — no dependencies)

```bash
python3 make_sample_data.py      # write the demonstration registry + ledger

python3 i_care.py --prove        # the provenance proof: the self-tests survive their own
                                 # linter, and each of the four checks has a can-fail witness

python3 mesh_grade.py level      # the earned-precision report over graded outcomes
python3 mesh_bridge.py selftest  # the telemetry→gate bridge self-test
```

`i_care.py --prove` is the honest headline: it proves the self-tests are real and prints
the validity level *with its n*. On the shipped sample that level is `unproven [n=0]` for
the advice gate — because no advice emissions have been graded here — which is the correct,
non-inflated output.

## The sample vs. the real knowledge

This repository ships a small, hand-written **sample registry** (`make_sample_data.py`)
and a **synthetic graded ledger** — enough to run every command above and watch the
mechanism work. They are clearly labelled demonstration data.

They are **not** the AURA knowledge base. The full deployment recognises against sovereign
registries of hundreds of machine-verified rules (verified by compiler or real execution,
not by opinion), and earns its reliability number on live infrastructure. That knowledge
and that earned number are the project's product; they are not in this repository. What is
here is the honest machinery, open for anyone to audit.

## Live recognition (optional)

The self-test and reporting paths above need nothing beyond the standard library. The
*live recognition* path (`logic_lane.logic_need`, which matches a free-text situation to
an axiom by embedding) expects an embedder exposing `embed(list[str]) -> ndarray`. Any
sentence embedder satisfies the interface; it is intentionally not bundled, so the core
stays dependency-free and fully runnable on its own.

## Layout

| File | Role |
|------|------|
| `i_care.py` | the four-check gate + the earned validity level |
| `logic_lane.py` | axiom recognition over a registry of verified rules |
| `ontology.py` | the noun type system used by the type-fit check |
| `mesh_bridge.py` | renders live telemetry into typed situations and gates them |
| `mesh_grade.py` | logs each emission, grades it, reports precision with `n` |
| `outcomes.py` | the Beta earned-frequency estimator (unproven at n=0) |
| `wisdom.py` | the append-only fire log the gate writes to |
| `assert_linter.py` | classifies assertions by strength; used to prove the self-tests real |
| `make_sample_data.py` | generates the demonstration registry + ledger |

## About

Part of **AURA**, a research program in self-testing infrastructure by Reality Optimizer —
[realityoptimizer.app](https://realityoptimizer.app). Sibling open tools:
[folder-nature](https://pypi.org/project/folder-nature/) (semantic identity + signing for
file trees), [whypass](https://pypi.org/project/whypass/) (a claim-discipline linter).

AURA is developed by a small human–AI working group; AI collaborators are named
contributors in its repositories, and every claim in its documentation is written to be
checkable rather than believed.

## License

Apache-2.0. See [LICENSE](LICENSE).
