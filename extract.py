"""extract — cluster components into patterns.

Where the composing path gets its abstractions: many similar components in, one Pattern out,
written to the store's ``patterns`` collection for ``compose`` to find later.

## READ THIS BEFORE TRUSTING A CLUSTER

This clusters on **lexical** vectors — words that appear in the text — so it groups **repeated
wording**, not shared meaning. Measured over the pairs in a small corpus, lexical cosine:

    same claim, near-identical wording   mean 0.706   (3 of 6 pairs clear the 0.7 threshold)
    same claim, different words          mean 0.084   (0 of 6 clear it)
    three real topic clusters, varied    within mean 0.140, strongest cross-pair 0.150
                                         -> the clusters OVERLAP; at 0.7 nothing groups at all

Two consequences, both deliberate and both stated rather than discovered later:

1. **The default threshold is the near-duplicate band.** ``0.7`` is the value the engine this was
   ported from uses for *embeddings*, and it happens to be exactly where lexical vectors separate
   repeated wording from everything else. Left at 0.7 it finds patterns in a log, a repeated alert,
   or a situation described the same way twice — and finds **nothing** in prose that varies. The
   failure mode is silence, not nonsense: it will not hand the composer a cluster it cannot justify.
2. **The semantic path is the ``[live]`` seam.** An embedder closes the synonym gap completely;
   nothing here pretends to approximate one. If you want meaning-based clustering, bring embeddings.

The algorithm is the ported one, unchanged: greedy single-linkage on cosine, time-decay weighting
so recent components count more, a deterministic name from the cluster's most frequent word, and a
pattern id derived from its member ids so re-running over the same components yields the same
pattern rather than a duplicate.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from store import COLL_COMPONENTS, Pattern, Store

DEFAULT_MIN_CLUSTER_SIZE = 3
DEFAULT_SIMILARITY_THRESHOLD = 0.7    # cosine SIMILARITY, not distance. See the module docstring.
DEFAULT_TIME_DECAY_DAYS = 90.0        # half-life for recency weighting
DEFAULT_MAX_COMPONENTS = 5000         # cap the input set, for runtime safety
DEFAULT_PATTERN_NAME_LEN = 60

_NAME_STOPWORDS = {
    "this", "that", "with", "from", "have", "been", "will", "they", "what", "when", "where",
    "would", "could", "should", "there", "their", "about", "which", "after", "before",
}


@dataclass
class ExtractionResult:
    """Patterns plus what the extractor saw — so a caller can tell "found nothing" from
    "found nothing because it looked at nothing" without running it again."""

    patterns: List[Pattern] = field(default_factory=list)
    clusters_examined: int = 0
    components_processed: int = 0
    components_skipped: int = 0
    elapsed_sec: float = 0.0
    notes: List[str] = field(default_factory=list)


class PatternExtractor:
    """Cluster components into patterns. Stateless; safe to share."""

    def __init__(
        self,
        store: Store,
        *,
        min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        time_decay_days: float = DEFAULT_TIME_DECAY_DAYS,
        max_components: int = DEFAULT_MAX_COMPONENTS,
    ) -> None:
        self.store = store
        self.min_cluster_size = max(2, int(min_cluster_size))
        self.similarity_threshold = float(similarity_threshold)
        self.time_decay_days = float(time_decay_days)
        self.max_components = int(max_components)

    # ── public API ───────────────────────────────────────────────────────────

    def extract(self, *, source_role: Optional[str] = None,
                validated_only: bool = False, persist: bool = False) -> ExtractionResult:
        """Cluster the store's components into patterns.

        ``validated_only`` is not implemented and says so rather than quietly returning
        everything: filtering by outcome labels needs outcome labels per component, and this
        package has none. A parameter that silently does nothing is worse than one that refuses.
        """
        if validated_only:
            raise NotImplementedError(
                "validated_only=True needs an outcome label per component, which this package "
                "does not have. Pass validated_only=False, or wire your own labels and filter "
                "the result yourself — the patterns carry their member ids."
            )

        started = datetime.now(timezone.utc)
        where = {"source_role": source_role} if source_role else None
        components = self.store.iter_all(COLL_COMPONENTS, with_vectors=True, where=where)
        if not components:
            return ExtractionResult(notes=["no components in the store — nothing to cluster"])

        no_vector = [c for c in components if not c.get("vector")]
        components = [c for c in components if c.get("vector")]
        if not components:
            return ExtractionResult(
                components_skipped=len(no_vector),
                notes=["the store returned no vectors for any component — this backend cannot "
                       "cluster; embeddings belong at the [live] seam"],
            )

        weighted = self._weight_by_recency(components)
        skipped = len(components) - len(weighted) + len(no_vector)
        if len(weighted) < self.min_cluster_size:
            return ExtractionResult(
                components_processed=len(weighted), components_skipped=skipped,
                notes=[f"only {len(weighted)} components survive time-decay; "
                       f"need >= {self.min_cluster_size} for any cluster"],
            )

        clusters = self._greedy_cluster(weighted)
        valid = [c for c in clusters if len(c) >= self.min_cluster_size]
        skipped += sum(len(c) for c in clusters if len(c) < self.min_cluster_size)

        patterns = [self._cluster_to_pattern(c, i) for i, c in enumerate(valid)]
        if persist and patterns:
            self.store.add_patterns(patterns)

        return ExtractionResult(
            patterns=patterns,
            clusters_examined=len(clusters),
            components_processed=len(weighted),
            components_skipped=skipped,
            elapsed_sec=(datetime.now(timezone.utc) - started).total_seconds(),
            notes=[
                f"greedy single-linkage on LEXICAL vectors (threshold={self.similarity_threshold:.2f}) "
                f"— groups repeated wording, not shared meaning",
                f"{len(clusters) - len(valid)} sub-threshold clusters dropped as noise",
            ],
        )

    # ── steps ────────────────────────────────────────────────────────────────

    def _weight_by_recency(self, components: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Half-life weight: 0.5 ** (age_days / time_decay_days). Older than 4 half-lives is
        dropped outright. A component with no parseable timestamp is treated as recent — we
        cannot say it is stale, and inventing staleness would silently discard real work."""
        now = datetime.now(timezone.utc)
        survivors = []
        for c in components:
            ts_raw = (c.get("metadata") or {}).get("timestamp")
            weight = 1.0
            if ts_raw and isinstance(ts_raw, str):
                try:
                    ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    age_days = (now - ts).total_seconds() / 86400.0
                    if age_days > self.time_decay_days * 4:
                        continue
                    weight = 0.5 ** (age_days / self.time_decay_days)
                except (ValueError, TypeError):
                    pass
            c["recency_weight"] = weight
            survivors.append(c)
        return survivors

    def _greedy_cluster(self, components: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Single-linkage: attach each component to the first cluster whose nearest member is
        within the threshold, else start a new cluster. Deterministic, O(n^2), and no extra
        dependency. Dense substrate at scale wants a real clustering algorithm — the ported
        engine marks the same swap-in point — but that decision belongs with a measured need.
        """
        clusters: List[List[Dict[str, Any]]] = []
        for c in components:
            placed = False
            for cluster in clusters:
                best = max(self._sim(c["vector"], m["vector"]) for m in cluster)
                if best >= self.similarity_threshold:
                    cluster.append(c)
                    placed = True
                    break
            if not placed:
                clusters.append([c])
        return clusters

    def _cluster_to_pattern(self, cluster: List[Dict[str, Any]], cluster_id: int) -> Pattern:
        member_ids = sorted(c["id"] for c in cluster)
        pattern_id = "pat_" + hashlib.sha256("::".join(member_ids).encode()).hexdigest()[:16]

        internal = self._internal_similarity(cluster)
        mean_weight = sum(c.get("recency_weight", 1.0) for c in cluster) / len(cluster)
        confidence = max(0.0, min(1.0, internal * mean_weight))

        name = self._heuristic_name(cluster)
        hypothesis = (f"Cluster of {len(cluster)} components with near-identical wording "
                      f"(internal similarity {internal:.2f}, confidence {confidence:.2f}). "
                      f"Wording-based grouping, not a semantic claim.")

        stamps = [(c.get("metadata") or {}).get("timestamp") for c in cluster]
        stamps = [t for t in stamps if t]
        roles = Counter((c.get("metadata") or {}).get("source_role", "?") for c in cluster)

        return Pattern(
            id=pattern_id, name=name,
            trigger={"metric": "cluster_pattern", "op": "match", "value": name},
            hypothesis=hypothesis, confidence=confidence,
            source_component_ids=member_ids[:50], occurrence_count=len(cluster),
            last_observed=max(stamps) if stamps else "",
            source_role=roles.most_common(1)[0][0],
        )

    # ── math ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _sim(a: Sequence[float], b: Sequence[float]) -> float:
        """Cosine similarity, normalising defensively. Zero vector → 0.0, never a crash."""
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return 0.0 if (na == 0 or nb == 0) else dot / (na * nb)

    def _internal_similarity(self, cluster: List[Dict[str, Any]]) -> float:
        """Mean pairwise similarity. A singleton is trivially 1.0 — it agrees with itself, which
        is not evidence of anything, and the caller is told the size separately."""
        if len(cluster) < 2:
            return 1.0
        sims = [self._sim(a["vector"], b["vector"])
                for i, a in enumerate(cluster) for b in cluster[i + 1:]]
        return sum(sims) / len(sims) if sims else 0.0

    @staticmethod
    def _heuristic_name(cluster: List[Dict[str, Any]]) -> str:
        """The most frequent meaningful word across the cluster, else the first member's text."""
        freq: Counter = Counter()
        for c in cluster:
            for word in (c.get("text") or "").lower().split():
                word = "".join(ch for ch in word if ch.isalnum())
                if len(word) >= 4 and word not in _NAME_STOPWORDS:
                    freq[word] += 1
        if freq:
            return freq.most_common(1)[0][0][:DEFAULT_PATTERN_NAME_LEN]
        for c in cluster:
            if (c.get("text") or "").strip():
                return c["text"].strip()[:DEFAULT_PATTERN_NAME_LEN]
        return f"cluster_{len(cluster)}"


# ── self-test ────────────────────────────────────────────────────────────────
# Mechanism-level assertions: every one of these fails if the machinery it names is broken.
# The lesson from store.py is that a test can pass for a reason unrelated to what it claims.

def selftest() -> int:
    import tempfile
    from decompose import Decomposer
    from store import JsonlStore

    fails = 0

    def check(label: str, got, want) -> None:
        nonlocal fails
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"  (got {got!r}, want {want!r})"))
        if not ok:
            fails += 1

    near_dup = [
        "the data volume is full and writes are being rejected",
        "the data volume is full and writes are rejected",
        "data volume full: writes rejected",
        "the data volume is full; writes are being rejected now",
    ]

    with tempfile.TemporaryDirectory() as td:
        s = JsonlStore(td)
        d = Decomposer()
        for t in near_dup:
            s.add_components(d.decompose(t))

        ex = PatternExtractor(s)
        r = ex.extract()
        # The pairwise similarities here are 0.915 / 0.596 / 0.799 / 0.652 / 0.704 / 0.569, so two
        # pairs sit just BELOW the 0.7 threshold and greedy single-linkage leaves one singleton.
        # Asserting a member count of 4 would have been asserting my guess; these assert the
        # invariants instead — a cluster forms, and every component is either in one or accounted
        # for as noise. A component that is neither would be a bug that loses data silently.
        check("repeated wording forms a cluster", len(r.patterns), 1)
        check("the biggest cluster holds the members that clear the threshold",
              r.patterns[0].occurrence_count >= 3, True)
        check("every component is either clustered or counted as noise (no silent loss)",
              r.patterns[0].occurrence_count + r.components_skipped, 4)
        check("the notes say which vectors it clustered on",
              any("LEXICAL" in n for n in r.notes), True)
        check("the hypothesis does not claim meaning",
              "not a semantic claim" in r.patterns[0].hypothesis, True)

        # idempotency: same components in, same pattern id out
        again = PatternExtractor(s).extract()
        check("re-extraction yields the SAME pattern id (no duplicates from re-runs)",
              again.patterns[0].id, r.patterns[0].id)

        check("extract is side-effect-free unless asked to persist",
              s.get_counts()["patterns"], 0)

    # The documented limit as an assertion: same meaning, different words does NOT cluster.
    # Components are built DIRECTLY here rather than through the decomposer, because 3 of these 4
    # sentences contain nothing the decomposer extracts (no metric, no delta, no hedge, no leading
    # imperative, no decision marker). Measuring that first is the only reason this test is about
    # CLUSTERING rather than quietly being about the decomposer s coverage.
    with tempfile.TemporaryDirectory() as td:
        s = JsonlStore(td)
        from decompose import ReasoningComponent
        for i, t in enumerate(["the data volume is full and writes are being rejected",
                               "storage is exhausted so new records cannot be saved",
                               "there is no room left on the archive for further data",
                               "the archive has run out of capacity and refuses additions"]):
            s.add_components([ReasoningComponent(
                id=f"syn{i}", timestamp="2026-09-24T12:00:00+00:00", session_id="t",
                source_role="user", type="observation", content={"note": t},
                source_text_excerpt=t)])
        r = PatternExtractor(s).extract()
        check("same meaning in different words does NOT cluster (documented lexical limit)",
              len(r.patterns), 0)
        check("...and the emptiness is thresholding, not an empty corpus",
              r.components_processed, 4)

    # a store with no vectors must say so rather than report an empty world
    class NoVectors:
        def iter_all(self, coll, with_vectors=False, where=None):
            return [{"id": "x", "text": "anything at all here", "metadata": {}}]
        def add_patterns(self, patterns):
            return 0

    r = PatternExtractor(NoVectors()).extract()
    check("a backend without vectors reports WHY it cannot cluster",
          any("cannot" in n for n in r.notes), True)

    # the refusal, and the guard below min_cluster_size
    r = PatternExtractor(JsonlStore(tempfile.mkdtemp())).extract()
    check("an empty store is reported as an empty store",
          any("no components" in n for n in r.notes), True)
    try:
        PatternExtractor(JsonlStore(tempfile.mkdtemp())).extract(validated_only=True)
        check("validated_only=True refuses instead of pretending", "raised", "no raise")
    except NotImplementedError as e:
        check("validated_only=True refuses instead of pretending",
              "outcome label" in str(e), True)

    print(f"  {'ALL GREEN' if not fails else str(fails) + ' FAILED'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
