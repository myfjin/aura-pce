#!/usr/bin/env python3
"""ontology.py — the type ontology (nouns).

The connective tissue: signatures compose only if patterns share a small controlled
vocabulary of type-nouns. Built EMPIRICALLY from the 330 PY patterns (not top-down) —
the raw annotations collapsed into seven families. Law: the COARSEST vocabulary that
still forms real edges; split a noun ONLY when a false edge forces it (record the
forcing case in SPLITS below so the granularity's growth stays evidenced, never guessed).

  scalar        float · int · bool            (a single number / count / flag)
  vector        List[float] · List[int] · list (a 1-D sequence of numbers)
  matrix        List[List[float]] · List[Tuple[float,float]]  (2-D / rows of tuples)
  result_tuple  Tuple[float,float] · Tuple[...]  (a returned bundle of values)
  text          str · List[str] · List[List[str]]  (strings / tokens / documents)
  keyed_store   Dict[...] · Mapping · Counter      (a lookup by key)
  function      Callable[...]                       (a passed-in function)
  path          Path · PurePath · PosixPath         (a filesystem path — see ADDITIONS)
  bytes         bytes · bytearray · memoryview       (a byte blob — distinct from text)
  + void (None-returning / side-effect) and unknown (Any/Union/unparsed) as honest tails.
  (path + bytes ADDED 2026-07-11, forced by the sysadmin sphere — see ADDITIONS below.)

An edge exists when one pattern's produced noun == another's consumed noun
(A produces `vector` → B consumes `vector`). That is the composability graph the
embeddings can't see — kept whether or not we build a graph engine yet.
"""
from __future__ import annotations

import ast

NOUNS = ("scalar", "vector", "matrix", "result_tuple", "text", "keyed_store", "function",
         "path", "bytes")

# Splits forced by a false edge (empty at settle-time; append {noun, into, forcing_case}
# whenever a real false composition proves a noun too coarse — never split speculatively).
SPLITS: list[dict] = []

# Nouns ADDED after settle-time, each with the forcing case that earned it (same discipline
# as SPLITS: no noun enters speculatively — a real sphere must force it).
ADDITIONS: list[dict] = [
    {"noun": "bytes", "forcing_case": "sysadmin sphere (2026-07-10): bytes is a real Python "
     "type distinct from str — atomic_write(content: bytes) feeding a str-consuming pattern "
     "is a FALSE EDGE. Folding bytes→text would manufacture that edge. 3 sysadmin patterns.",
     "types": ["bytes", "bytearray", "memoryview"], "added": "2026-07-11",
     "forced_by": "i_care type_fit over the sysadmin registry"},
    {"noun": "path", "forcing_case": "sysadmin sphere (2026-07-10): filesystem paths "
     "(pathlib.Path objects) pervade sysadmin patterns (19). A path IS textual but a path "
     "producer feeding a document-text consumer is a false edge; kept distinct from text. "
     "str-typed paths still coarsen to text (the noun follows the ANNOTATION, not intent).",
     "types": ["Path", "PurePath", "PosixPath", "PurePosixPath", "WindowsPath"],
     "added": "2026-07-11", "forced_by": "i_care type_fit over the sysadmin registry"},
]

# OBSERVATIONS — split-candidate SIGNALS seen in the data, recorded not acted on. A signal
# graduates to SPLITS only when a real false composition (not mere density) forces it.
OBSERVATIONS: list[dict] = [
    {"noun": "scalar", "signal": "hub: 338 consumers / 115 producers across 332 patterns",
     "why_not_split_yet": "density != a forced false edge; p_value vs learning_rate would "
     "split by ROLE not TYPE — needs a real wrong composition before splitting. Harmless for "
     "the L4 validation lane (matches a pattern, checks its axiom; does not traverse edges). "
     "Revisit only when the graph ENGINE is built.", "seen": "2026-07-09"},
    {"noun": "vector", "signal": "hub: 241 consumers / 45 producers",
     "why_not_split_yet": "same as scalar — role-vs-type split, defer to a forcing case.",
     "seen": "2026-07-09"},
    # Fable's bridge_fuse run-1 (2026-07-10) surfaced result_tuple/matrix as hubs too. On a
    # registry read they are NOT the same case — the numbers + the roles differ:
    {"noun": "result_tuple", "signal": "role-CONFLATION (not mere density): consumed into "
     "coordinate-POINT slots (p1/p2/point — mds, dbscan, mahalanobis, point_in_polygon) BUT "
     "produced as statistical RESULT-BUNDLES (z/p_value/h, mu/beta/sigma — the stats tests). "
     "Two incompatible meanings under one noun → false edges (a p-value tuple piped into a "
     "polygon's point slot). 93 prod × 15 cons = 1395 edges.",
     "candidate_split": "point_tuple | result_bundle",
     "why_not_split_yet": "STRONGEST candidate, but the split-law's trigger is a GOLD-shelf "
     "role-collision (a semantically-near + structurally-pluggable pair that STILL dies), NOT "
     "SURPRISE-shelf noise — the semantic band already filters this off GOLD (why GOLD "
     "survives). Split when GOLD dialogue-rejects confirm it ~3x. Meanwhile the SURPRISE "
     "drown is better fixed by a semantic FLOOR on SURPRISE than by splitting.",
     "seen": "2026-07-10", "source": "bridge_fuse run-1 + registry read"},
    {"noun": "matrix", "signal": "DENSITY hub (19 prod × 51 cons = 969), uniform 2D-numeric — "
     "no role-conflation visible (unlike result_tuple). Fable lumped them; the data separates.",
     "why_not_split_yet": "density, not a forced false edge — LIKELY never needs a split. "
     "Weakest candidate of the four.", "seen": "2026-07-10", "source": "bridge_fuse run-1"},
]

_SCALAR = {"float", "int", "bool", "complex", "number"}
_VECTORISH = {"list", "sequence", "iterable", "set", "frozenset"}
_MAPPISH = {"dict", "mapping", "defaultdict", "ordereddict", "counter"}
_BYTESISH = {"bytes", "bytearray", "memoryview"}          # ADDITIONS 2026-07-11 (sysadmin)
_PATHISH = {"path", "purepath", "posixpath", "pureposixpath", "windowspath", "purewindowspath"}


def _head(node) -> str:
    """Outermost constructor name of a subscripted type, lowercased ('' if not a Name)."""
    if isinstance(node, ast.Subscript):
        v = node.value
        return v.id.lower() if isinstance(v, ast.Name) else ""
    return ""


def _first_arg(node: ast.Subscript):
    """First type argument of List[X]/Sequence[X]/… ; None if unreadable."""
    s = node.slice
    if isinstance(s, ast.Tuple):
        return s.elts[0] if s.elts else None
    return s


def _coarsen_node(node) -> str:
    if isinstance(node, ast.Constant) and node.value is None:
        return "void"
    if isinstance(node, ast.Name):
        n = node.id.lower()
        if node.id == "None" or n == "none":
            return "void"
        if n in _SCALAR:
            return "scalar"
        if n == "str":
            return "text"
        if n in _BYTESISH:
            return "bytes"
        if n in _PATHISH:
            return "path"
        if n == "callable":
            return "function"
        if n == "tuple":
            return "result_tuple"
        if n == "dict":
            return "keyed_store"
        if n in _VECTORISH:
            return "vector"
        return "unknown"
    if isinstance(node, ast.Subscript):
        h = _head(node)
        if h == "callable":
            return "function"
        if h in _MAPPISH:
            return "keyed_store"
        if h == "tuple":
            return "result_tuple"
        if h in _VECTORISH or h == "list":
            inner = _first_arg(node)
            if inner is not None:
                ic = _coarsen_node(inner)
                if ic == "text":                       # List[str] → text sequence
                    return "text"
                if ic in ("vector", "matrix", "result_tuple"):  # List[List..]/List[Tuple..]
                    return "matrix"
                if ic == "scalar":                     # List[float] → vector
                    return "vector"
            return "vector"
        return "unknown"
    return "unknown"


def coarsen(raw: str) -> str:
    """Map a raw type annotation (as written in source) → one of the 7 nouns
    (or 'void'/'unknown'). Deterministic; structural parse, never substring guessing."""
    t = (raw or "").strip()
    if not t:
        return "unknown"
    try:
        return _coarsen_node(ast.parse(t, mode="eval").body)
    except SyntaxError:
        return "unknown"


def selftest() -> None:
    cases = {
        # scalars
        "float": "scalar", "int": "scalar", "bool": "scalar",
        # vectors
        "List[float]": "vector", "List[int]": "vector", "list": "vector",
        "list[float]": "vector", "Set[int]": "vector",
        # matrices — the trap: contains 'tuple'/'list' words but is 2-D
        "List[List[float]]": "matrix", "List[Tuple[float, float]]": "matrix",
        "List[List[int]]": "matrix",
        # result bundles
        "Tuple[float, float]": "result_tuple", "Tuple[float, float, float]": "result_tuple",
        "Tuple[float, ...]": "result_tuple",
        # the nuance a top-level tuple of vectors is STILL a returned bundle
        "Tuple[List[float], List[float]]": "result_tuple",
        # text
        "str": "text", "List[str]": "text", "List[List[str]]": "text",
        # keyed
        "Dict[str, float]": "keyed_store", "Dict[int, List[int]]": "keyed_store",
        # function
        "Callable[[float], float]": "function", "Callable[[], float]": "function",
        # path + bytes (ADDITIONS 2026-07-11, sysadmin forcing case)
        "Path": "path", "PurePath": "path", "PosixPath": "path",
        "bytes": "bytes", "bytearray": "bytes", "memoryview": "bytes",
        # (the distinction that EARNED the nouns: a path/bytes is NOT text; a str holding a
        #  path still coarsens to text above — the noun follows the annotation, not intent)
        # tails
        "None": "void", "": "unknown", "Any": "unknown",
    }
    ok = 0
    for raw, want in cases.items():
        got = coarsen(raw)
        good = got == want
        ok += good
        print(f"  {'✓' if good else '✗ FAIL'}  {raw!r:34} → {got}"
              + ("" if good else f"  (wanted {want})"))
    print(f"\n{ok}/{len(cases)} checks passed"
          + ("" if ok == len(cases) else " — FIX BEFORE TRUSTING"))


if __name__ == "__main__":
    selftest()
