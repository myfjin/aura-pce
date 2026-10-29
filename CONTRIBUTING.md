# Contributing to aura-pce

The crew is small — one human and five machines (see [`CREW.md`](CREW.md)) — and this project is what it is because of that. We would rather grow it slowly with people who care about substance than fast with people who don't.

If you found this and it interests you, you are welcome. This file is what we ask before you send code, and what we ask about ourselves before we merge it.

---

## How we take contributions

We take **pull requests** on GitHub. We do not use a CLA. Sign-off on every commit is the entire contributor agreement:

    git commit -s -m "your message"

The `-s` adds a `Signed-off-by:` line and asserts the **Developer Certificate of Origin (DCO)** — that you wrote the change or have the right to submit it under Apache-2.0. CI checks it on every commit of every PR.

If you have an idea larger than one PR, **open an issue first** and talk it through with us. Small fixes and typos can skip that step; anything that changes what the gate lets through — a new axiom, a change to one of the four `I CARE` checks, a new telemetry source, a threshold — should be discussed before you write it.

**When you open an issue, please describe what you saw and how to recreate it.** For a wrong emit, that means the telemetry that produced it and, if you captured one, the evidence bundle (`aura-pce evidence show <hash>`). If you cannot reproduce it yet — say so, and share what you have.

---

## The rules that are specific to this project

aura-pce exists to catch one defect: **a claim that outruns its evidence.** Every rule below is that defect, seen from a different side.

- **No code path prints an unearned number.** A metric is printed with its `n`, and on a fresh install it says `unproven [n=0]`. A PR that makes a number look better without new graded evidence will not be merged.
- **Silence and deferral are outputs, not failures.** When the gate cannot verify itself it stays silent or says *"no verified rule"* out loud. Do not "fix" a silence by lowering a check.
- **Every check has a can-fail witness.** `aura-pce prove` shows each of the four checks failing on an input built to fail it. A new check, or a changed one, ships with its witness — a check that has never been red is not a check.
- **Self-tests survive their own linter.** `assert_linter.py` rejects self-tests that cannot fail. If yours is rejected, the test is the problem, not the linter.
- **The core stays standard-library only.** `dependencies = []` is a design decision, not an accident. Anything that needs a third-party package goes behind an extra (`[live]`, `[embed]`) and fails open with a loud message when the extra is missing.
- **Every new module goes into `py-modules` in `pyproject.toml`.** 0.3.0 shipped without its composing path because four modules were added to the repo and not to that list. The `packaging` CI job now builds both artifacts and imports every module from a neutral directory — run `python packaging_check.py` before you push.
- **Grading comes from evidence, not memory.** Changes to the ledger or the grading path keep the evidence bundle attached to the emit it explains.

## The rules the whole crew holds

Each was learned from a specific afternoon where we got it wrong first.

- **Nothing at n=1 is a measurement.** Report the median of ≥3 runs plus the call count, or fail-once as a rate over N≥10. Attribute every figure to the run that produced it.
- **Read the newest state, never the oldest record.**
- **Say "unknown" when you do not know.** Absence of a visible cause is not evidence of no cause.
- **Retract in public.** If a number you published turns out to be wrong, correct it in the same visible place. Silent edits are worse than the original error.
- **No self-scored superiority.** The person who wrote the code does not grade it.
- **Prove-by-revert only inside `mktemp -d`**, never on a served path.
- **A green local run is not evidence about CI.** Reproduce in the environment the gate actually uses.

---

## Before you open a PR

From a clean checkout:

```bash
python -m pip install -e .
aura-pce prove                                          # the provenance proof
aura-pce selftest                                       # every stdlib self-test
python -c "import sources; raise SystemExit(sources.selftest())"
python packaging_check.py                               # needs: pip install build && python -m build
```

If your change touches recognition or live telemetry, also install the extra and run the `live` steps from [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

```bash
python -m pip install -e ".[live]"
python embedder.py --selftest
python logic_lane.py --selftest
aura-pce calibrate --report
```

If the code you touched has no self-test, adding one is welcome as part of the same PR.

---

## What we will not take

- **Real telemetry, ledgers or evidence bundles from anyone's machine.** The demo data in `data/` is authored, and named as demo. Your box's data stays on your box.
- **Backwards-compatibility shims** for hypothetical futures. If you can change the code, change the code.
- **Error handling for scenarios that cannot happen.** Validate at boundaries; trust internal contracts.
- **Comments that describe what the code does.** Comments are for the *why* that is not obvious from the *what*.
- **New abstractions ahead of use.** Three similar lines are better than a premature abstraction.

---

## Register

We work as brothers and friends, not as vendors and customers. Feedback is direct; corrections are welcome from any seat. If a machine reviewer catches something a human missed, that is the design working, not a failure of hierarchy.

If your first PR is small — a typo, a missing comma, a docstring fix — that is a good first PR. Some of ours are the same.

---

## Contact

For anything that does not fit an issue: **ihladkyi2@gmail.com**. Security problems go through [`SECURITY.md`](SECURITY.md), not a public issue.

🖖
