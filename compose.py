"""compose — fuse three signals into one block, or say nothing.

Given a query, three signals are retrieved and fused into a single block:

    1. relevant historical reasoning components   (from the store)
    2. patterns matching the query                (from the store, once extract has run)
    3. query-scoped slices of current state       (from a snapshot provider YOU supply)

weighted 0.7 / 0.2 / 0.1 — and the result is one block, or ``None``.

## The one place this deliberately differs from the engine it came from

**THE PER-SIGNAL FLOOR.** The engine this was ported from has a single threshold on the *weighted
total*, so a strong signal carries a weak one: components at 0.5 with nothing beside them gives
0.35 and composes. That is defensible when the block is context a reader weighs against their own
judgement. It is **not** defensible when the block *speaks*, because then it is spoken as though
every signal were adequate.

Here every signal must clear its own floor **before** fusion. A signal below its floor is
**excluded**, not carried; the recorded score reflects only the signals that cleared; and if none
clears, ``compose`` returns nothing. **A floor that binds the total but not the parts is not a
floor.** Our independent verifier ruled on exactly this and accepted it as a named divergence
rather than a smuggled change — the alternative would ship a mechanism that composes when its own
condition is unmet.

## What it will not do

No model, no network, no dependency. **Never raises** — a failing retrieval or a broken snapshot
degrades to "that signal is absent" rather than an exception in the middle of someone's turn.
**Additive only**: no empty blocks, no noisy blocks, and nothing when nothing is strong enough.

## What you have to bring

``snapshot_provider`` is optional. With none, the third signal is simply absent and composition
proceeds on two — which is why the per-signal floor matters: absent is handled honestly, and a
weak-but-present signal cannot borrow strength it does not have. The provider is any callable
returning ``{node: {metric: value}}``; ``nodes`` and ``metric_aliases`` describe YOUR topology and
YOUR snapshot schema, because this module has no business assuming either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from store import COLL_PATTERNS, Store

# Weights: the engine's starting points, kept for fidelity. They are tuned from logs, not theory.
_W_COMPONENTS = 0.7
_W_PATTERNS = 0.2
_W_EVIDENCE_BOOST = 0.1

DEFAULT_MIN_SCORE = 0.3      # gate on the fused total
# Gate on EACH signal, before fusion. The default is MEASURED, not chosen: over the reference
# store (distance = 1 - cosine, so 1/(1+d) spans [0.5, 1]) the top hit for a query sharing words
# lands at 0.582-0.706 while an unrelated query lands at 0.500-0.517. The midpoint of that gap is
# 0.55, which is this value. A floor of 0.5 would have admitted unrelated matches.
#
# The number is BACKEND-DEPENDENT, and deliberately so: a store whose distances run to 2 (a
# chroma-style backend) maps to [0.33, 1], where the same floor filters more aggressively. If you
# swap backends, re-measure rather than assuming this carries over.
DEFAULT_SIGNAL_FLOOR = 0.55

Snapshot = Dict[str, Dict[str, Any]]
SnapshotProvider = Callable[[], Optional[Snapshot]]


@dataclass
class ComposedReasoning:
    """One composed block, with the trace that produced it."""

    query: str
    relevant_components: List[Dict[str, Any]] = field(default_factory=list)
    matched_patterns: List[Dict[str, Any]] = field(default_factory=list)
    state: Snapshot = field(default_factory=dict)
    signals_used: List[str] = field(default_factory=list)
    excluded_signals: List[str] = field(default_factory=list)
    score: float = 0.0
    reasoning_trace: List[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Render the block. Every line says which signal it came from, and the header says
        which signals were excluded — a reader should never have to guess what is missing."""
        head = [f"**Composed context** (score {self.score:.2f}; signals: "
                f"{', '.join(self.signals_used) or 'none'}"
                + (f"; below floor: {', '.join(self.excluded_signals)}" if self.excluded_signals else "")
                + ")"]
        lines: List[str] = list(head)
        if self.relevant_components:
            lines.append("")
            lines.append("**Relevant past reasoning**")
            for c in self.relevant_components:
                meta = c.get("metadata") or {}
                text = (c.get("text") or "").replace("\n", " ").strip()
                if len(text) > 140:
                    text = text[:137] + "…"
                lines.append(f"- {meta.get('type', '?')} {(meta.get('timestamp') or '')[:10]}: {text}")
        if self.matched_patterns:
            lines.append("")
            lines.append("**Matched patterns**")
            for p in self.matched_patterns:
                meta = p.get("metadata") or {}
                lines.append(f"- {meta.get('name', '(unnamed)')} "
                             f"(conf {float(meta.get('confidence', 0.0) or 0.0):.2f}): "
                             f"{meta.get('hypothesis', '')}")
        if self.state:
            lines.append("")
            lines.append("**Current state** (scoped to the query)")
            for node, payload in self.state.items():
                lines.append(f"- {node}: {', '.join(f'{k}={_fmt(v)}' for k, v in payload.items())}")
        return "\n".join(lines).rstrip() + "\n"


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") or "0"
    return str(v)


class PatternComposer:
    """Fuse components, patterns and current state into one block — or nothing."""

    def __init__(
        self,
        store: Store,
        *,
        snapshot_provider: Optional[SnapshotProvider] = None,
        nodes: Sequence[str] = (),
        metric_aliases: Optional[Dict[str, str]] = None,
        weights: Tuple[float, float, float] = (_W_COMPONENTS, _W_PATTERNS, _W_EVIDENCE_BOOST),
        min_score: float = DEFAULT_MIN_SCORE,
        signal_floor: float = DEFAULT_SIGNAL_FLOOR,
    ) -> None:
        self.store = store
        self.snapshot_provider = snapshot_provider
        self.nodes = tuple(nodes)
        self.metric_aliases = dict(metric_aliases or {})
        self.weights = weights
        self.min_score = float(min_score)
        self.signal_floor = float(signal_floor)

    # ── public API ───────────────────────────────────────────────────────────

    def compose(self, query: str, *, top_k_components: int = 5, top_k_patterns: int = 3,
                roles: Optional[List[str]] = None, snapshot: Optional[Snapshot] = None
                ) -> Optional[ComposedReasoning]:
        """Compose for ``query``. ``None`` when nothing clears the floor — cold start, no
        signals, or every signal too weak. Never raises."""
        if not query or not query.strip():
            return None

        where = _role_filter(roles)
        try:
            components = self.store.query_components(query, top_k=top_k_components, where=where)
        except Exception:
            return None                      # no substrate, no composition
        try:
            patterns = self.store.query_patterns(query, top_k=top_k_patterns, where=where)
        except Exception:
            patterns = []                    # the pattern branch is optional, by design

        snap = snapshot
        if snap is None and self.snapshot_provider is not None:
            try:
                snap = self.snapshot_provider()
            except Exception:
                snap = None                  # a broken provider is an absent signal, not a crash

        state = self._scope_state(query, components, snap) if snap else {}

        # ── the per-signal floor ─────────────────────────────────────────────
        c_score = _mean_similarity(components)
        p_score = _mean_similarity(patterns)
        used, excluded = [], []
        for name, score, present in (("components", c_score, bool(components)),
                                     ("patterns", p_score, bool(patterns)),
                                     ("state", 1.0 if state else 0.0, bool(state))):
            if not present:
                excluded.append(f"{name}=absent")
            elif score < self.signal_floor:
                excluded.append(f"{name}={score:.2f}<floor")
            else:
                used.append(name)

        total = (self.weights[0] * (c_score if "components" in used else 0.0)
                 + self.weights[1] * (p_score if "patterns" in used else 0.0)
                 + self.weights[2] * (1.0 if "state" in used else 0.0))
        total = max(0.0, min(1.0, total))
        if not used or total < self.min_score:
            return None

        return ComposedReasoning(
            query=query,
            relevant_components=components if "components" in used else [],
            matched_patterns=patterns if "patterns" in used else [],
            state=state if "state" in used else {},
            signals_used=used, excluded_signals=excluded, score=total,
            reasoning_trace=self._build_trace(components, patterns, state, used, excluded, total),
        )

    # ── steps ────────────────────────────────────────────────────────────────

    def _scope_state(self, query: str, components: List[Dict[str, Any]],
                     snap: Snapshot) -> Snapshot:
        """Keep only the state the query or the retrieved components actually mention — fails
        closed, because an unscoped dump of every metric is noise wearing a table's clothes."""
        nodes, metrics = self._scan_mentions(query, components)
        if not nodes and not metrics:
            return {}
        want_nodes = nodes or list(self.nodes)
        out: Snapshot = {}
        for node in want_nodes:
            payload = snap.get(node) or {}
            kept = {k: v for k, v in payload.items()
                    if not metrics or any(m in k for m in metrics)}
            if kept:
                out[node] = kept
        return out

    def _scan_mentions(self, query: str, components: List[Dict[str, Any]]
                       ) -> Tuple[List[str], List[str]]:
        """Node and metric mentions in the query plus the retrieved component text. Word-boundary
        matching, so "load" does not fire on "overload"."""
        blobs = [query]
        for c in components:
            blobs.append(c.get("text") or "")
            content = c.get("metadata", {}).get("content")
            if isinstance(content, dict):
                for k in ("node", "metric"):
                    if k in content:
                        blobs.append(str(content[k]))
        text = " ".join(blobs).lower()
        nodes = [n for n in self.nodes if n in text]
        metrics = [m for m in ("thermal", "cpu", "memory", "disk", "network", "pressure", "power")
                   if re.search(rf"\b{re.escape(m)}\b", text)]
        return nodes, metrics

    def _build_trace(self, components, patterns, state, used, excluded, score) -> List[str]:
        """One line per signal, plus what was excluded and why. A block that cannot say why it
        exists is a block nobody can argue with."""
        trace = [f"score={score:.3f}", f"signals_used={used}", f"excluded={excluded}",
                 f"components_retrieved={len(components)}", f"patterns_matched={len(patterns)}",
                 f"state_nodes={list(state.keys())}"]
        for c in components:
            sim = 1.0 / (1.0 + max(0.0, float(c.get("distance", 1.0))))
            trace.append(f"  component {c.get('metadata', {}).get('type', '?')} sim={sim:.2f} "
                         f"{(c.get('text') or '')[:60]}")
        return trace


def _role_filter(roles: Optional[List[str]]) -> Optional[Dict[str, Any]]:
    """Equality for one role, ``$in`` for several — the shape the store understands."""
    if not roles:
        return None
    return {"source_role": roles[0]} if len(roles) == 1 else {"source_role": {"$in": list(roles)}}


def _mean_similarity(items: List[Dict[str, Any]]) -> float:
    """``1/(1+d)`` over the store's distances, in [0, 1]. Kept from the engine that this was
    ported from, for the reason it was chosen there: a plain ``1-d`` collapses to 0 for any
    distance at or above 1, which hides real signal instead of ranking it."""
    if not items:
        return 0.0
    return sum(1.0 / (1.0 + max(0.0, float(it.get("distance", 1.0)))) for it in items) / len(items)


# ── self-test ────────────────────────────────────────────────────────────────
# Mechanism-level assertions. The one that matters most is the per-signal floor, and it is
# demonstrated by REMOVING it and watching a composition appear that should not.

def selftest() -> int:
    import tempfile
    from decompose import Decomposer, ReasoningComponent
    from store import JsonlStore

    fails = 0

    def check(label: str, got, want) -> None:
        nonlocal fails
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"  (got {got!r}, want {want!r})"))
        if not ok:
            fails += 1

    def fresh(components, patterns=()):
        td = tempfile.mkdtemp()
        s = JsonlStore(td)
        if components:
            s.add_components(components)
        if patterns:
            s.add_patterns(list(patterns))
        return s

    d = Decomposer()
    # PREMISE, asserted: this corpus has to actually decompose, or these tests silently become
    # tests of the decomposer's coverage rather than of the composer. That is exactly what went
    # wrong in the first draft of this file — and in extract.py's, twice.
    TEXT = "thermal_avg = 72.4 and the fan curve is broken because the sensor drifted"
    strong = d.decompose(TEXT)
    check("premise: the test corpus decomposes into components", len(strong) >= 1, True)

    # 1. a strong component signal alone can compose — but only because it clears the floor
    s = fresh(strong)
    c = PatternComposer(s).compose("fan curve reading")
    check("a strong component signal composes", bool(c), True)
    check("...and the block says which signals it used", c.signals_used, ["components"])
    check("...and the trace records what was excluded",
          any("absent" in e for e in c.excluded_signals), True)

    # 2. THE FLOOR. A signal present but below the floor must be EXCLUDED, not carried.
    s = fresh(strong)
    strict = PatternComposer(s, signal_floor=0.99).compose("fan curve reading")
    check("a signal below its floor is excluded, so nothing composes", strict, None)
    check("...and with the floor removed the SAME query composes (the floor is load-bearing)",
          bool(PatternComposer(s, signal_floor=0.0).compose("fan curve reading")), True)

    # 3. absent signals are honest, not fatal: no snapshot provider means two signals
    s = fresh(strong)
    c = PatternComposer(s, snapshot_provider=None).compose("fan curve reading")
    check("a missing third signal is reported absent, not invented",
          any("state=absent" in e for e in c.excluded_signals), True)

    # 4. a broken provider degrades instead of raising
    def broken():
        raise RuntimeError("provider down")
    c = PatternComposer(fresh(strong), snapshot_provider=broken).compose("fan curve reading")
    check("a provider that raises is treated as an absent signal, never a crash",
          bool(c) and any("state=absent" in e for e in c.excluded_signals), True)

    # 5. state scoping: only metrics the query mentions, and nodes the caller declared
    s = fresh(strong)
    snap = {".1": {"thermal_avg": 72.4, "disk_free_gb": 12.0}}
    c = PatternComposer(s, snapshot_provider=lambda: snap, nodes=[".1"]).compose(
        "what is the thermal reading?")
    check("state is scoped to what the query mentions",
          list(c.state.get(".1", {}).keys()), ["thermal_avg"])
    c2 = PatternComposer(s, snapshot_provider=lambda: snap, nodes=[".1"]).compose(
        "nothing here relates to any metric at all")
    # The honest outcome, which is better than the one I first expected: no state is attached
    # (nothing was mentioned) AND the component match is weak enough to be below the floor, so
    # nothing composes at all. Silence, not a block padded with an unrelated retrieval.
    check("an unrelated query composes NOTHING (no unscoped state, weak match below floor)",
          c2, None)
    check("...and removing the floor is what makes it compose (the floor is load-bearing here too)",
          bool(PatternComposer(s, snapshot_provider=lambda: snap, nodes=[".1"],
                               signal_floor=0.0).compose(
              "nothing here relates to any metric at all")), True)

    # 6. emptiness, and the shapes
    check("a blank query composes nothing", PatternComposer(fresh([])).compose("   "), None)
    check("an empty store composes nothing", PatternComposer(fresh([])).compose("anything"), None)
    c = PatternComposer(fresh(strong)).compose("fan curve reading")
    check("the block renders without claiming more than it has",
          "below floor" in c.to_markdown() or "signals: components" in c.to_markdown(), True)

    # 7. patterns participate as their own signal, and are reported as such
    from store import Pattern
    s = fresh(strong, patterns=[Pattern(id="p1", name="fan curve failure",
                                        hypothesis="the fan curve breaks when the sensor drifts")])
    c = PatternComposer(s).compose("fan curve sensor drift")
    check("a matching pattern is counted as its own signal",
          "patterns" in c.signals_used, True)
    check("...and the block carries it", len(c.matched_patterns) == 1, True)

    print(f"  {'ALL GREEN' if not fails else str(fails) + ' FAILED'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
