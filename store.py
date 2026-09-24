"""store — where components, patterns and decisions live, and how they are found again.

Three collections, mirroring the three things the composing path produces:

    components  — every ReasoningComponent ``decompose`` extracts
    patterns    — distilled abstractions over many components (``extract`` fills these)
    decisions   — components of type ``decision``, indexed separately because "what did we
                  decide" is the question worth a fast path of its own

## Two backends, one interface

``JsonlStore`` is the reference implementation and it is **stdlib only** — three JSONL files in a
directory, plus lexical retrieval computed here. That is deliberate: a stranger can install this
package, run the whole path, and read every line that produced an answer, with no dependency,
no model and no network.

``ChromaStore`` (separate module, optional extra) is the production backend: a real vector store
with real embeddings. It is never imported by the core, so importing this module costs nothing.

## What "lexical" means here, and what it does not

The reference store finds documents by **words that appear in them**. It tokenises, weights by
term frequency and inverse document frequency over this store's own corpus, hashes each token into
a fixed-dimension vector and compares by cosine. It is deterministic across processes — the token
hash is SHA-1, not Python's salted ``hash()`` — and it is honest about its limit:

    "the fan is spinning too fast"  →  finds  "fan speed anomaly"        (shared words)
    "the fan is spinning too fast"  →  MISSES "cooling failure"          (same meaning, no words in common)

A semantic backend at the ``[live]`` seam closes that gap and nothing here pretends otherwise. This
is a reference implementation, not a smaller version of a language model.

Results carry ``distance`` (``1 - cosine``, so a lower number is nearer) rather than a bare score,
because the composer's weighting was written against a distance and the port keeps that arithmetic
unchanged. ``similarity`` is included for humans.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, runtime_checkable

from decompose import ReasoningComponent

COLL_COMPONENTS = "components"
COLL_PATTERNS = "patterns"
COLL_DECISIONS = "decisions"

VECTOR_DIM = 4096
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
MIN_TOKEN_LEN = 2


@dataclass
class Pattern:
    """A distilled abstraction over many components. ``extract`` produces these."""

    id: str
    name: str
    trigger: Dict[str, Any] = field(default_factory=dict)
    secondary_indicators: List[Dict[str, Any]] = field(default_factory=list)
    hypothesis: str = ""
    confidence: float = 0.0
    action_sequence: List[str] = field(default_factory=list)
    source_component_ids: List[str] = field(default_factory=list)
    occurrence_count: int = 0
    last_observed: str = ""
    source_role: str = "user"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── lexical vectors, computed here, deterministic across processes ────────────

def tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= MIN_TOKEN_LEN]


def _bucket(token: str) -> int:
    """SHA-1, not hash(): Python salts str hashing per process, which would make the same
    corpus produce different vectors in different runs — and a store that cannot reproduce
    its own retrieval is not a reference implementation."""
    return int(hashlib.sha1(token.encode("utf-8")).hexdigest()[:8], 16) % VECTOR_DIM


class LexicalVectorizer:
    """Term-frequency × inverse-document-frequency, hashed into a fixed dimension, L2-normalised.

    Fit it on the corpus you intend to search, so the idf reflects the documents that are there.
    """

    def __init__(self) -> None:
        self.df: Dict[str, int] = {}
        self.n_docs = 0

    def fit(self, documents: Iterable[str]) -> "LexicalVectorizer":
        self.df = {}
        self.n_docs = 0
        for doc in documents:
            self.n_docs += 1
            for token in set(tokenize(doc)):
                self.df[token] = self.df.get(token, 0) + 1
        return self

    def _idf(self, token: str) -> float:
        if not self.n_docs:
            return 1.0
        return math.log((1 + self.n_docs) / (1 + self.df.get(token, 0))) + 1.0

    def vector(self, text: str) -> List[float]:
        counts: Dict[str, int] = {}
        for token in tokenize(text):
            counts[token] = counts.get(token, 0) + 1
        vec = [0.0] * VECTOR_DIM
        for token, tf in counts.items():
            vec[_bucket(token)] += (1.0 + math.log(tf)) * self._idf(token)
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))           # both L2-normalised


# ── the interface ─────────────────────────────────────────────────────────────

@runtime_checkable
class Store(Protocol):
    """What the rest of the path needs from a store. Any implementation may be swapped in."""

    def get_counts(self) -> Dict[str, int]: ...
    def add_components(self, components: Sequence[ReasoningComponent]) -> int: ...
    def add_decisions(self, decisions: Sequence[ReasoningComponent],
                      _from_components: bool = False) -> int: ...
    def add_patterns(self, patterns: Sequence[Pattern]) -> int: ...
    def query_components(self, query: str, top_k: int = 5,
                         where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]: ...
    def query_patterns(self, query: str, top_k: int = 3,
                       where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]: ...


def _matches(metadata: Dict[str, Any], where: Optional[Dict[str, Any]]) -> bool:
    """The subset of filtering this store supports: equality on top-level metadata fields."""
    if not where:
        return True
    return all(metadata.get(k) == v for k, v in where.items())


class JsonlStore:
    """Reference store: three JSONL files in a directory, lexical retrieval computed in-python.

    Persistence is append-free on purpose — every write rewrites the file, so a truncated write
    cannot leave a half-record behind. Suitable for the sample corpus and for tests; a real
    deployment wants the vector backend.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        self.path.mkdir(parents=True, exist_ok=True)
        self._docs: Dict[str, Dict[str, Dict[str, Any]]] = {
            COLL_COMPONENTS: {}, COLL_PATTERNS: {}, COLL_DECISIONS: {},
        }
        self._vectors: Dict[str, Dict[str, List[float]]] = {
            COLL_COMPONENTS: {}, COLL_PATTERNS: {}, COLL_DECISIONS: {},
        }
        for coll in self._docs:
            self._load(coll)
        self._refit()

    # ── persistence ─────────────────────────────────────────────────────────

    def _file(self, coll: str) -> Path:
        return self.path / f"{coll}.jsonl"

    def _load(self, coll: str) -> None:
        p = self._file(coll)
        if not p.exists():
            return
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue                      # a torn final line is skipped, never guessed at
            if isinstance(rec, dict) and rec.get("id"):
                self._docs[coll][rec["id"]] = rec

    def _write(self, coll: str) -> None:
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self._docs[coll].values())
        self._file(coll).write_text(body, encoding="utf-8")

    def _refit(self) -> None:
        for coll in self._docs:
            docs = list(self._docs[coll].values())
            vec = LexicalVectorizer().fit(d.get("text", "") for d in docs)
            self._vectors[coll] = {d["id"]: vec.vector(d.get("text", "")) for d in docs}
            self._vec = vec                     # query vectors use the same fitted idf

    # ── counts ──────────────────────────────────────────────────────────────

    def get_counts(self) -> Dict[str, int]:
        return {coll: len(self._docs[coll]) for coll in self._docs}

    # ── writes ──────────────────────────────────────────────────────────────

    def _put(self, coll: str, rec: Dict[str, Any]) -> None:
        self._docs[coll][rec["id"]] = rec

    def add_components(self, components: Sequence[ReasoningComponent]) -> int:
        """Insert components. A ``decision`` component is mirrored into the decisions
        collection — the same record, indexed twice, so the "what did we decide" path is cheap."""
        if not components:
            return 0
        mirrored = []
        for c in components:
            self._put(COLL_COMPONENTS, {
                "id": c.id, "text": c.source_text_excerpt or "(empty)",
                "metadata": {"timestamp": c.timestamp, "session_id": c.session_id,
                             "source_role": c.source_role, "source_channel": c.source_channel,
                             "type": c.type, "content": c.content},
            })
            if c.type == "decision":
                mirrored.append(c)
        self._write(COLL_COMPONENTS)
        if mirrored:
            self.add_decisions(mirrored, _from_components=True)
        self._refit()
        return len(components)

    def add_decisions(self, decisions: Sequence[ReasoningComponent],
                      _from_components: bool = False) -> int:
        if not decisions:
            return 0
        for d in decisions:
            self._put(COLL_DECISIONS, {
                "id": d.id, "text": d.source_text_excerpt or "(empty)",
                "metadata": {"timestamp": d.timestamp, "session_id": d.session_id,
                             "source_role": d.source_role, "content": d.content,
                             "mirrored_from_components": _from_components},
            })
        self._write(COLL_DECISIONS)
        self._refit()
        return len(decisions)

    def add_patterns(self, patterns: Sequence[Pattern]) -> int:
        if not patterns:
            return 0
        for p in patterns:
            d = p.to_dict()
            self._put(COLL_PATTERNS, {
                "id": p.id, "text": f"{p.name}: {p.hypothesis}".strip() or p.id,
                "metadata": {k: v for k, v in d.items() if k != "id"},
            })
        self._write(COLL_PATTERNS)
        self._refit()
        return len(patterns)

    # ── reads ───────────────────────────────────────────────────────────────

    def _query(self, coll: str, query: str, top_k: int,
               where: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not query or not query.strip() or not self._docs[coll]:
            return []
        qv = self._vec.vector(query)
        scored = []
        for rec in self._docs[coll].values():
            if not _matches(rec.get("metadata") or {}, where):
                continue
            sim = cosine(qv, self._vectors[coll].get(rec["id"], []))
            scored.append((sim, rec))
        scored.sort(key=lambda t: (-t[0], t[1]["id"]))          # deterministic tie-break
        return [{"id": rec["id"], "text": rec["text"], "distance": round(1.0 - sim, 6),
                 "similarity": round(sim, 6), "metadata": rec.get("metadata") or {}}
                for sim, rec in scored[:top_k]]

    def query_components(self, query: str, top_k: int = 5,
                         where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._query(COLL_COMPONENTS, query, top_k, where)

    def query_patterns(self, query: str, top_k: int = 3,
                       where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        return self._query(COLL_PATTERNS, query, top_k, where)


# ── self-test ────────────────────────────────────────────────────────────────
# The negative cases are the point: they fail if the machinery they exercise breaks.

def selftest() -> int:
    import tempfile
    from decompose import Decomposer

    fails = 0

    def check(label: str, got, want) -> None:
        nonlocal fails
        ok = got == want
        print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok else f"  (got {got!r}, want {want!r})"))
        if not ok:
            fails += 1

    with tempfile.TemporaryDirectory() as td:
        s = JsonlStore(td)
        check("a fresh store is empty", s.get_counts(),
              {COLL_COMPONENTS: 0, COLL_PATTERNS: 0, COLL_DECISIONS: 0})

        comps = Decomposer().decompose(
            "thermal_avg = 72.4 and the reading is climbing. This likely means the fan curve is broken. "
            "Restart the fan daemon. We decided to hold the deploy until Friday.")
        added = s.add_components(comps)
        check("components are stored", added, len(comps))
        check("decisions are mirrored, not duplicated by hand",
              s.get_counts()[COLL_DECISIONS], 1)

        hits = s.query_components("fan curve reading", top_k=2)
        check("a lexical query finds the document sharing its words",
              bool(hits) and "fan" in hits[0]["text"].lower(), True)
        check("results carry distance (1 - cosine) and similarity",
              set(hits[0]) >= {"id", "text", "distance", "similarity", "metadata"}, True)
        check("distance and similarity are complementary",
              round(hits[0]["distance"] + hits[0]["similarity"], 5), 1.0)

        # the honest limit, asserted rather than hidden: same MEANING, no shared WORDS
        check("lexical retrieval MISSES a synonym with no words in common (documented limit)",
              s.query_components("cooling failure", top_k=1)[0]["similarity"] < 0.2, True)

        check("an empty query returns nothing", s.query_components("   "), [])
        check("a metadata filter is applied",
              all(h["metadata"].get("type") == "action"
                  for h in s.query_components("restart the daemon", top_k=5, where={"type": "action"})),
              True)

        p = Pattern(id="p1", name="thermal drift", hypothesis="rising temperature precedes fan failure")
        check("patterns store", s.add_patterns([p]), 1)
        check("a pattern query finds it by its hypothesis",
              s.query_patterns("fan failure", top_k=1)[0]["id"], "p1")
        check("an empty patterns query returns nothing", s.query_patterns(""), [])

        # determinism across a reload — the SHA-1 choice, demonstrated
        before = [h["id"] for h in s.query_components("fan reading", top_k=3)]
        s2 = JsonlStore(td)
        after = [h["id"] for h in s2.query_components("fan reading", top_k=3)]
        check("retrieval is reproducible across a fresh load of the same corpus", after, before)

    print(f"  {'ALL GREEN' if not fails else str(fails) + ' FAILED'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
