# Security policy

The crew maintaining aura-pce is small — one human and five machines — and we take security reports seriously. This file says how to reach us privately, what we treat as in scope, and what you can expect back.

---

## Reporting a vulnerability

**Email:** [ihladkyi2@gmail.com](mailto:ihladkyi2@gmail.com)

**Please do not open a public GitHub issue for a suspected security problem.** A real vulnerability filed there is a disclosure, not a report. Email us first.

Include as much of the following as you have:

- what you saw, and what you expected instead
- how to reproduce it — the minimum sequence of steps or the smallest input
- which version (`pip show aura-pce`) or commit hash you were looking at
- your assessment of the impact, if you have one
- whether you would like to be credited (and how), or would prefer anonymity

If you cannot reproduce it yet but believe something is wrong, say so and share what you have.

---

## What we will do

We are a small crew without a paid on-call rotation, so timing is best-effort — but honest:

- **Acknowledgement** within **7 days** of your email. If you have not heard from us in that window, please assume the email did not arrive and try again.
- **A first assessment** within **30 days** — whether we confirm the issue, cannot reproduce it, or need more information.
- **Coordinated disclosure.** If the report is confirmed, we agree with you on a disclosure timeline. Our default is up to **90 days** from confirmation, extended if a fix is genuinely in flight.
- **Credit** in the release notes and the commit message, in the form you asked for — or anonymity, if you asked for that.

We will not sue researchers acting in good faith. We do not run a bounty program.

---

## Scope

aura-pce runs on the operator's own machine. It reads telemetry, keeps a ledger of what it emitted, and captures evidence bundles to local disk. It does not serve HTTP and does not upload anything.

**In scope:**

- the aura-pce source code and the artifacts published to PyPI from this repository
- handling of untrusted input: telemetry values, a `node_exporter` endpoint's response, journal lines, and registry or ledger files on disk
- anything that makes the gate **emit when it should have stayed silent** through crafted input — a bypass of one of the four `I CARE` checks is a security issue here, not only a bug
- file handling in the data home: path traversal, unsafe writes, or an evidence bundle capturing more than the operator was told it captures

**Out of scope:**

- Third-party dependencies, including those pulled in by the `[live]` extra (numpy, sentence-transformers, psutil) and the embedding model they download. Report those upstream; we will pick up the fix on their release.
- Denial of service through absurd inputs (a multi-gigabyte ledger, a metrics endpoint that never stops streaming). Resource caps are a deployment concern.
- Vulnerabilities that require an already-compromised host (root, or control of the process).
- Automated scanner findings without a demonstrated exploit path — please attach the reproduction, not just the scanner name.

---

## Secrets and private data — how we handle them

This repository ships **code and authored demo data only.** The files in `data/` are written by hand, and their nodes are named `demo-node-*`. The following never belong in a commit; if you ever see one land in a public commit, tell us — that is itself a security bug:

- real telemetry, emit ledgers, grading records or evidence bundles from any machine
- the private rule base behind the public sample registry
- credentials, tokens, environment files, host addresses or private paths, in any form

CI runs a privacy scan on every push and pull request (private paths, credentials, untracked-data patterns).

---

## PGP

We do not currently publish a PGP key. Plain email to `ihladkyi2@gmail.com` is the reporting channel. If your report is sensitive enough that transport encryption matters, mention it in the first mail and we will coordinate a secure channel before you send details.

---

## Thank you

Reporters who take the time to write us privately are doing us a favor, and we know it. 🖖
