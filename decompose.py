"""decompose — text → structured reasoning components.

Five kinds are extracted:

    observation · comparison · hypothesis · action · decision

    "thermal_avg = 72.4, up +24C from the 5m baseline. This likely means the fan curve is
     broken. Restart the fan daemon. I decided to hold the deploy until Friday."

    ->  observation  {'metric': 'thermal_avg', 'value': 72.4}
        comparison   {'type': 'delta', 'value': 24.0, 'unit': 'C', 'significance': 'high'}
        hypothesis   {'cause': 'This likely means the fan curve is broken.', 'hedge': 'likely', ...}
        action       {'verb': 'restart', 'target': 'the fan daemon'}
        decision     {'choice': 'hold the deploy until Friday', 'marker': 'decided to'}

Design, stated so it can be argued with:

- **No model, no network, no dependencies.** Pure regex and heuristics — deterministic and
  auditable in one sitting. The same text always yields the same components; ids and timestamps
  vary, contents do not.
- **Lossy and conservative on purpose.** We would rather miss a component than manufacture one.
  A fragment below ``MIN_UNIT_WORDS`` is dropped, because a bare "79%" is telemetry noise rather
  than a unit of reasoning. Precision over recall, explicitly chosen.
- **The sentence is the unit, and only the first match in it counts.** A sentence yields at most
  one component of each kind, and it carries the whole sentence it came from — so anything
  downstream that groups components by meaning groups them by meaning rather than by a bare
  fragment that happened to match. This is deliberate: a sentence making one claim should not be
  counted as three, and two hedges in one clause are still one hypothesis. Splitting is naive
  (``.``/``!``/``?`` followed by whitespace and a capital), which is enough for short conversational
  text and does not break inside numbers or versions.

This is the first half of the composing path: **decompose** produces components, ``extract``
groups them into patterns, ``compose`` fuses them with live evidence. The mechanism ships here;
what you feed it is yours.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Sequence

ComponentType = Literal["observation", "comparison", "hypothesis", "action", "decision"]


@dataclass
class ReasoningComponent:
    """One extracted piece of reasoning.

    Two orthogonal categorical dimensions:

      - ``source_role`` — WHO produced this (free-form: "user", "assistant", a model name)
      - ``source_channel`` — WHAT KIND of conversation it came from (free-form: "dialogue",
        "building", "status", "user_directive", "system_rule")

    Same source produces output across channels; same channel carries multiple sources.
    """

    id: str
    timestamp: str                # ISO8601 UTC
    session_id: str
    source_role: str
    type: ComponentType
    content: Dict[str, Any]
    source_text_excerpt: str      # the sentence this component came from
    source_channel: str = "dialogue"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Extraction patterns ──────────────────────────────────────────────────────

# metric_name = value  OR  metric_name: value
_OBS_RE = re.compile(r"\b([a-zA-Z][\w.]{1,40})\s*[=:]\s*([+-]?\d+(?:\.\d+)?)\b")

# Delta with a unit: +24C, -15%, 230ms, ...
_DELTA_RE = re.compile(r"(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*(°C|°F|%|MB|GB|KB|ms|sec|s\b|min|h\b)")

# Hedge words — when present, the containing sentence is a hypothesis
_HYPOTHESIS_WORDS = (
    "likely", "suggests", "probably", "because", "looks like", "appears to",
    "may be", "could be", "seems to", "implies", "indicates", "is the cause",
)

# Action verbs (sentence-initial, imperative form)
_ACTION_VERBS = {
    "check", "restart", "inspect", "verify", "fix", "install", "remove",
    "deploy", "run", "edit", "update", "configure", "kill", "start",
    "stop", "build", "test", "rotate", "migrate", "patch",
}

# Decision markers — phrases that precede a chosen course of action
_DECISION_MARKERS = (
    "decided to", "chose to", "chose ", "going with", "will use", "recommended",
    "approved", "accepted", "rejected", "we will go with", "let's go with",
    "settled on", "picked ",
)

# Confidence for a hypothesis, by hedge strength. A weaker hedge is a weaker claim.
_HEDGE_CONFIDENCE = {
    "definitely": 0.9, "clearly": 0.9, "certainly": 0.9,
    "indicates": 0.8, "is the cause": 0.8,
    "implies": 0.75, "suggests": 0.7, "likely": 0.7,
    "looks like": 0.65, "because": 0.65,
    "appears to": 0.6, "probably": 0.6,
    "seems to": 0.5,
    "may be": 0.4, "could be": 0.4,
}

# Minimum word count for a fragment to count as a reasoning UNIT rather than a bare value.
# Below this, observation and comparison matches are dropped: a lone "79%" or "30s" is
# telemetry noise, and clustering bare values produces meaningless patterns.
MIN_UNIT_WORDS = 4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _split_sentences(text: str) -> List[str]:
    """Naive sentence split, good enough for short conversational text.

    Splits on . ! ? followed by whitespace and a capital, so it does not break inside
    numbers (3.14) or version-like tokens (v1.2.3).

    Known limit, deliberately left in place: an abbreviation ends a "sentence", so
    "Use e.g. this pattern" splits into "Use e.g." and "this pattern" — both too short to
    yield a component. A real fix (an abbreviation table, or proper boundary detection) would
    be an improvement over the engine this was ported from, which is the opposite of what a
    faithful port is for. If it is fixed, it should be fixed in both.
    """
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\[])", text)
    return [p.strip() for p in parts if p.strip()]


def _excerpt(text: str, max_len: int = 200) -> str:
    text = text.strip()
    return text[:max_len] + ("…" if len(text) > max_len else "")


class Decomposer:
    """Extracts ReasoningComponent records from raw text. Stateless."""

    def decompose(
        self,
        text: str,
        session_id: str = "unknown",
        source_role: str = "user",
        source_channel: str = "dialogue",
    ) -> List[ReasoningComponent]:
        """Return the components found in ``text`` — empty list if none.

        Order is the natural reasoning chain: observations, comparisons, hypotheses,
        actions, decisions.
        """
        if not text or not text.strip():
            return []
        out: List[ReasoningComponent] = []
        for fn in (self._extract_observations, self._extract_comparisons, self._extract_hypotheses,
                   self._extract_actions, self._extract_decisions):
            out.extend(fn(text, session_id, source_role, source_channel))
        return out

    # ── helpers ──────────────────────────────────────────────────────────────

    def _make(self, ctype: ComponentType, content: Dict[str, Any], excerpt: str,
              session_id: str, source_role: str, source_channel: str) -> ReasoningComponent:
        return ReasoningComponent(
            id=_new_id(), timestamp=_now_iso(), session_id=session_id,
            source_role=source_role, source_channel=source_channel,
            type=ctype, content=content, source_text_excerpt=_excerpt(excerpt),
        )

    # ── per-type extractors ──────────────────────────────────────────────────

    def _extract_observations(self, text: str, session_id: str, source_role: str,
                              source_channel: str) -> List[ReasoningComponent]:
        out = []
        for sent in _split_sentences(text):
            if len(sent.split()) < MIN_UNIT_WORDS:
                continue
            for m in _OBS_RE.finditer(sent):
                metric = m.group(1)
                try:
                    value = float(m.group(2))
                except ValueError:
                    continue
                if len(metric) < 2 or metric.lower() in {"e", "v", "id", "if", "is", "no"}:
                    continue
                out.append(self._make("observation", {"metric": metric, "value": value},
                                      sent, session_id, source_role, source_channel))
                break                      # one observation per sentence — the sentence is the unit
        return out

    def _extract_comparisons(self, text: str, session_id: str, source_role: str,
                             source_channel: str) -> List[ReasoningComponent]:
        out = []
        for sent in _split_sentences(text):
            if len(sent.split()) < MIN_UNIT_WORDS:
                continue
            for m in _DELTA_RE.finditer(sent):
                try:
                    value = float(m.group(1))
                except ValueError:
                    continue
                abs_val = abs(value)
                significance = "low" if abs_val < 5 else ("medium" if abs_val < 20 else "high")
                content = {
                    "type": "delta" if m.group(1).startswith(("+", "-")) else "absolute",
                    "value": value, "unit": m.group(2), "significance": significance,
                }
                out.append(self._make("comparison", content, sent,
                                      session_id, source_role, source_channel))
                break
        return out

    def _extract_hypotheses(self, text: str, session_id: str, source_role: str,
                            source_channel: str) -> List[ReasoningComponent]:
        out = []
        for sent in _split_sentences(text):
            lower = sent.lower()
            matched = next((h for h in _HYPOTHESIS_WORDS if h in lower), None)
            if not matched:
                continue
            content = {"cause": sent, "hedge": matched,
                       "confidence": _HEDGE_CONFIDENCE.get(matched, 0.5)}
            out.append(self._make("hypothesis", content, sent,
                                  session_id, source_role, source_channel))
        return out

    def _extract_actions(self, text: str, session_id: str, source_role: str,
                         source_channel: str) -> List[ReasoningComponent]:
        out = []
        for sent in _split_sentences(text):
            m = re.match(r"^\s*([A-Za-z]+)\b", sent)
            if not m:
                continue
            verb = m.group(1).lower()
            if verb not in _ACTION_VERBS:
                continue
            target = sent[m.end():].strip(" ,.:;").split(".")[0].strip()[:120]
            out.append(self._make("action", {"verb": verb, "target": target}, sent,
                                  session_id, source_role, source_channel))
        return out

    def _extract_decisions(self, text: str, session_id: str, source_role: str,
                           source_channel: str) -> List[ReasoningComponent]:
        out = []
        for sent in _split_sentences(text):
            lower = sent.lower()
            matched = next((mk for mk in _DECISION_MARKERS if mk in lower), None)
            if not matched:
                continue
            # The choice is the text after the marker. Deliberately NOT split on a period:
            # that breaks identifiers like v1.2.3, and the sentence is already one bounded
            # unit from _split_sentences.
            idx = lower.find(matched)
            after = sent[idx + len(matched):].strip(" ,.:;")
            choice = after.strip()[:200]
            # Separate the WHAT from the WHY. A causal marker turns the tail into `rationale`
            # and is trimmed out of `choice`, so the two fields never overlap and a reader can
            # see which part of the sentence was the decision and which was the reason for it.
            rationale = ""
            for r_marker in (" because ", " since ", " per ", " — ", " - "):
                if r_marker in lower:
                    r_idx = lower.find(r_marker)
                    rationale = sent[r_idx + len(r_marker):].strip()[:200]
                    choice_lower = choice.lower()
                    if r_marker in choice_lower:
                        choice = choice[:choice_lower.find(r_marker)].strip()[:200]
                    break
            content = {"choice": choice, "marker": matched.strip(), "rationale": rationale}
            out.append(self._make("decision", content, sent,
                                  session_id, source_role, source_channel))
        return out


# ── self-test ────────────────────────────────────────────────────────────────
# A self-test that cannot fail is not a self-test, so the negative cases below are the
# point of the suite: each one fails if the guard it exercises is removed.

def selftest() -> int:
    d = Decomposer()
    fails = 0

    def check(label: str, got, want) -> None:
        nonlocal fails
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"  (got {got!r}, want {want!r})"))
        if not ok:
            fails += 1

    # --- each of the five kinds, on text that is unambiguously about it ---
    c = d.decompose("thermal_avg = 72.4 and cpu_load = 3.1, steady over the window.")
    check("observation carries metric+value",
          [(x.type, x.content.get("metric"), x.content.get("value")) for x in c],
          [("observation", "thermal_avg", 72.4)])

    c = d.decompose("The readout shows +24°C against the five minute baseline we use.")
    comp = [x for x in c if x.type == "comparison"]
    check("comparison records delta + unit + significance",
          (len(comp), comp[0].content["type"], comp[0].content["unit"],
           comp[0].content["significance"]) if comp else None,
          (1, "delta", "°C", "high"))

    c = d.decompose("This likely means the fan curve is broken. That suggests a thermal problem.")
    hyps = [x for x in c if x.type == "hypothesis"]
    check("hypothesis records the hedge and its confidence",
          (len(hyps), hyps[0].content["hedge"], hyps[0].content["confidence"]) if hyps else None,
          (2, "likely", 0.7))

    # ONE match per sentence per kind — two hedges in one clause are still one hypothesis,
    # and the FIRST match wins. This is the rule that surprised me while porting, so it is pinned.
    one = [x for x in d.decompose("This likely means the fan curve is broken, which suggests a thermal problem.")
           if x.type == "hypothesis"]
    check("one sentence yields at most one hypothesis (first hedge wins)",
          (len(one), one[0].content["hedge"]) if one else None, (1, "likely"))

    c = d.decompose("Restart the fan daemon. Check the sensor list. Verify the reading.")
    acts = [x for x in c if x.type == "action"]
    check("action records verb + target, once per sentence",
          (len(acts), acts[0].content["verb"], acts[0].content["target"]) if acts else None,
          (3, "restart", "the fan daemon"))

    c = d.decompose("We decided to hold the deploy until Friday. We are going with the later slot.")
    dec = [x for x in c if x.type == "decision"]
    check("decision records marker + choice, once per sentence",
          (len(dec), dec[0].content["marker"]) if dec else None, (2, "decided to"))

    # The rationale split (caught by the independent verifier, not by me): the WHAT and the
    # WHY are separated, and the marker is trimmed out of the choice so they never overlap.
    c = d.decompose("Decided to patch the service because the log shows a leak.")
    dec = [x for x in c if x.type == "decision"]
    check("decision separates what was decided from why",
          (dec[0].content["choice"], dec[0].content["rationale"]) if dec else None,
          ("patch the service", "the log shows a leak."))
    c = d.decompose("We chose to keep the old schema.")
    dec = [x for x in c if x.type == "decision"]
    check("no causal marker means an empty rationale, not a guessed one",
          (dec[0].content["choice"], dec[0].content["rationale"]) if dec else None,
          ("keep the old schema", ""))   # the trailing period is stripped, as canonical does
    c = d.decompose("Decided to raise the timeout since the queue kept stalling.")
    dec = [x for x in c if x.type == "decision"]
    check("since works as a rationale marker too",
          (dec[0].content["choice"], dec[0].content["rationale"]) if dec else None,
          ("raise the timeout", "the queue kept stalling."))

    # --- the negative cases: these are the can-fail witnesses ---
    check("empty text yields nothing", d.decompose(""), [])
    check("whitespace yields nothing", d.decompose("   \n\t "), [])
    check("a bare value in a short fragment is NOT a component (MIN_UNIT_WORDS)",
          d.decompose("79%"), [])
    check("a sentence with no marker yields nothing",
          d.decompose("The window is open and nothing else is happening here."), [])
    check("single-char metric is rejected",
          [x for x in d.decompose("e = 5 over the whole sampling window right now") if x.type == "observation"],
          [])

    # --- determinism, and the two categorical axes travelling with every component ---
    a = d.decompose("Restart the fan daemon now.", session_id="s1", source_role="tester",
                    source_channel="status")
    b = d.decompose("Restart the fan daemon now.", session_id="s1", source_role="tester",
                    source_channel="status")
    check("same text, same contents (ids differ by design)",
          [(x.type, x.content) for x in a], [(x.type, x.content) for x in b])
    check("role and channel travel with each component",
          (a[0].source_role, a[0].source_channel, a[0].session_id) if a else None,
          ("tester", "status", "s1"))

    print(f"  {'ALL GREEN' if not fails else str(fails) + ' FAILED'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
