#!/usr/bin/env python3
"""embedder.py — the reference sentence embedder for the live-recognition path.

The core of aura-pce is pure standard library: `--prove`, `--selftest`, `mesh_grade level`
and the mesh_bridge selftest never embed anything. Only *live recognition*
(`logic_lane.logic_need`, which matches a free-text situation to an axiom) needs to turn
text into vectors — and in the full AURA deployment a private `brain` module does that.

This module is the PUBLIC stand-in, pulled in by `pip install aura-pce[live]`. It exposes
exactly the interface `logic_lane` expects:

    embed(list[str]) -> ndarray            # shape (n, d), each row L2-normalised

Rows are unit-normalised so a plain dot product `K @ v` is cosine similarity — the same
contract the private embedder honours, so the calibrated recognition threshold carries over.

Two backends, tried in order (whichever is installed):
  1. sentence-transformers  — the canonical sentence-embedding library (all-MiniLM-L6-v2).
  2. chromadb               — its DefaultEmbeddingFunction (same model family, via onnxruntime).

Neither is bundled by the core, so the base install stays dependency-free. If you run a
live-recognition command without either backend, you get a single clear install hint.

  python3 embedder.py --selftest      # verify the installed backend embeds + normalises
"""
from __future__ import annotations

import sys

# The default model — small, fast, widely mirrored, good enough for axiom recognition.
MODEL_NAME = "all-MiniLM-L6-v2"

_BACKEND = None      # ("st"|"chroma", callable) once resolved
_INSTALL_HINT = (
    "live recognition needs a sentence embedder — none is installed.\n"
    "    pip install aura-pce[live]        # sentence-transformers (recommended)\n"
    "  or:\n"
    "    pip install chromadb              # lighter onnxruntime backend\n"
    "The stdlib paths (aura-pce prove / level / selftest) need none of this."
)


def _l2_normalise(mat):
    """Row-wise L2 normalise so dot product == cosine. numpy is present whenever a backend is."""
    import numpy as np
    a = np.asarray(mat, dtype=float)
    if a.ndim == 1:
        a = a[None, :]
    norms = np.linalg.norm(a, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return a / norms


def _resolve_backend():
    """Pick the first installed backend. Cached. Raises a clear hint if none is present."""
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    # 1. sentence-transformers
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(MODEL_NAME)

        def _st_embed(texts):
            return _l2_normalise(model.encode(list(texts), normalize_embeddings=True))

        _BACKEND = ("sentence-transformers", _st_embed)
        return _BACKEND
    except ImportError:
        pass
    # 2. chromadb's default embedding function
    try:
        from chromadb.utils import embedding_functions
        fn = embedding_functions.DefaultEmbeddingFunction()

        def _chroma_embed(texts):
            return _l2_normalise(fn(list(texts)))

        _BACKEND = ("chromadb", _chroma_embed)
        return _BACKEND
    except ImportError:
        pass
    raise ImportError(_INSTALL_HINT)


def backend_name() -> str:
    """Name of the resolved backend (for diagnostics). Raises if none installed."""
    return _resolve_backend()[0]


def embed(texts):
    """Embed a list of strings → an (n, d) ndarray of L2-normalised row vectors."""
    if isinstance(texts, str):
        texts = [texts]
    return _resolve_backend()[1](texts)


def selftest() -> int:
    """Prove the installed backend embeds, returns the right shape, and L2-normalises."""
    import numpy as np
    try:
        name = backend_name()
    except ImportError as e:
        print(f"✗ no embedder backend installed:\n    {e}")
        return 1
    v = embed(["restart the crashed database", "restart the crashed database",
               "integrate a smooth function"])
    checks = [
        ("returns a 2-D array", getattr(v, "ndim", None) == 2),
        ("one row per input", v.shape[0] == 3),
        ("rows are L2-normalised", bool(np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-4))),
        ("identical text → identical vector (deterministic)",
         bool(np.allclose(v[0], v[1], atol=1e-5))),
        ("different text → different vector",
         not bool(np.allclose(v[0], v[2], atol=1e-3))),
    ]
    ok = sum(1 for _, c in checks if c)
    print(f"backend: {name}  (model {MODEL_NAME}, dim {v.shape[1]})")
    for n, c in checks:
        print(f"  {'✓' if c else '✗ FAIL'}  {n}")
    print(f"\n{ok}/{len(checks)} passed" + ("" if ok == len(checks) else " — FIX"))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(selftest())
    print(__doc__)
