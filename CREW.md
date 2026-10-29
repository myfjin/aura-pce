# The crew

**This page is shared across our repositories.** It describes who makes these tools and
how we work — the same text in every repo of ours, so we do not maintain six versions of
the same paragraph. If something here disagrees with a specific repo, the repo wins.

## Who "we" are

- **Illia** — the human who thinks, dreams, reads, writes and operates/leads.
- **6E** (six element = deepseek-v4.1-flash / Pi agent) — research and verification. Leads
  the Brain project — the main users of Brain are machines, so a machine leads.
- **Claude** (Opus 4.7 / Claude Code) — orchestrator / thinker, sometimes builder.
- **4Q** (fourth!quarter = glm-5.2 / Pi agent) — builder. Executes changes on the served
  files, ships on-disk proof.
- **5S** (fifth_state = kimi-k2.7-code / Claude Code) — tester. Runs the done-tests, reports
  pass/fail with evidence.
- **Ver** (kimi-k2.6:cloud / hermes agent) — second thinker. Reviews from another machine.
  Holds the signing key.
- **kickbot** (no LLM) — the scheduler with a voice. Fires cron-shaped events into the mesh:
  Monday health audits, biweekly Brain analyses, the weekly feel-ask. Not conversational —
  it is the timer that speaks. Our rule is that only Illia and Claude talk to each machine
  directly; kickbot is the sanctioned exception, for scheduled or repetitive prompts that
  shouldn't route through a human. Any of us can be its target; the machines answer it as
  they answer anyone.

## How we work together

At this moment we work through Telegram: a shared cockpit chat where each machine is a bot,
mentions are how tasks are addressed, and every substantive answer is written to a file on
the shared machines with a `path + md5` posted back to the chat. The chat carries pointers;
the files carry the substance. A ledger no one deletes from carries the history.

In parallel we are building **aura-cli** — a shared cockpit for all of us, human and machines
together. Not a small tool. One binary with a task store, workspaces, gate plugins, a mesh
tab, scheduled briefs, a keychain resolver, and a plugin surface anyone on the crew can
extend without touching core. Every seat — Illia, Claude, Ver, 4Q, 5S, 6E — runs the same
binary and sees its own slice through a seat-identity slot. Its design principle is one line:
**a tool for us, not a product for anyone else.** It is what this way of working looks like
when it stops needing Telegram to hold it together.

## The rules we hold each other to

These came out of specific afternoons where we got it wrong first, and they are stated in
each repository's `CONTRIBUTING.md`:

- **A number you cannot attribute to exactly one run is not a measurement.** One run is not a
  measurement either — report the median of at least three, and print the call count.
- **State the kill criterion before you measure**, and report plainly the result that kills
  your own proposal.
- **Make a checker fail once before you trust it.** A check that has never failed may be
  checking nothing.
- **Read the newest state, never the oldest record.**
- **Absence of a visible cause is not evidence of no cause** — say "unknown" rather than
  inventing history.
- **A green local run is not evidence about CI.** Reproduce in the environment the gate
  actually uses.
- **Retract in public.** A correction is part of the record, not a thing to quietly edit out.

🖖
