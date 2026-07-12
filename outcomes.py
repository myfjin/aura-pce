"""outcomes.py — the earned-frequency estimator.

A reliability figure is never asserted here; it is a Beta estimate over graded outcomes,
and at n=0 it reports itself unproven rather than printing a naked 50%. This is the whole
discipline in one function.
"""
from __future__ import annotations
import math


def beta(hits: int, misses: int) -> dict:
    """Beta(1+hits, 1+misses) — the earned frequency and its spread. At n=0 the estimate
    is flagged UNPROVEN: with no evidence there is no number to cite, only a prior."""
    a, b = 1 + hits, 1 + misses
    mean = a / (a + b)
    var = a * b / ((a + b) ** 2 * (a + b + 1))
    unproven = (hits + misses == 0)
    return {
        "mean": round(mean, 3),
        "std": round(math.sqrt(var), 3),
        "hits": hits, "misses": misses,
        "method": f"Beta({a},{b})" + (" — UNPROVEN (no outcomes yet)" if unproven else ""),
    }
