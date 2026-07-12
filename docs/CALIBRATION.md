# Recognition calibration

Recognition matches a free-text situation to an axiom by cosine similarity. Whether a match
is *accepted* is governed by two knobs, **derived from a measured distribution — not guessed**:

- **`RECOG_FLOOR`** — the minimum top-1 cosine to fire at all.
- **`RECOG_MARGIN`** — the minimum gap between top-1 and top-2 (a *domain-confidence* gate:
  fire only when one axiom clearly owns the situation, not when several tie in the fuzzy
  middle).

`calibrate.py` runs a labelled probe set — in-domain situations that *should* recognise an
axiom, and out-of-domain text that should *not* — through the real embedder against a registry,
sweeps `(FLOOR, MARGIN)`, and picks the pair that keeps full in-domain recall with zero
out-of-domain fires while **maximising the separation** (centring the floor in the empty band,
robust to both a slightly weaker real concern and a slightly stronger spurious match). The
measurement and the chosen values are written to `calibration.json` in the data home, which
`logic_lane` loads at import. A missing or malformed file falls back to the inherited-safe
`FLOOR = 0.30, MARGIN = 0.0`.

## Measured on the shipped sample (embedder `all-MiniLM-L6-v2`, 6 sysadmin axioms)

| | FLOOR | MARGIN | in-domain recall | out-of-domain fires |
|---|---|---|---|---|
| **before** (inherited single threshold) | 0.30 | 0.00 | 0.917 | **0 / 10** |
| **after** (chosen by evidence) | 0.22 | 0.00 | **1.000** | **0 / 10** |

The two clouds separate cleanly: the strongest out-of-domain probe tops out at **0.164**,
the weakest in-domain probe is **0.291** — a clean gap of **+0.127**. Centring the floor in
that gap (0.22) recovers the one borderline in-domain phrasing (recall 0.917 → 1.000) at
**zero** out-of-domain cost.

## The honest caveat: over-fire is a large-registry phenomenon

On this small sample **there is no out-of-domain over-fire to cut** — the top-score gap alone
already separates, and it does so at the old threshold too. The `~28 emits/hour` flat-baseline
over-fire observed on the full AURA deployment came from a **large** sovereign registry
(hundreds of axioms): the more axioms there are, the more likely a weak spurious match clears
an absolute floor. That is exactly what **`RECOG_MARGIN`** addresses — it demands
domain-confidence, which weak spurious matches (tiny top1−top2 gaps) fail. The margin is wired,
derived, and defaults to `0.0` here because the sample doesn't need it; it rises when
`calibrate.py` is run against a larger registry.

## Re-deriving for your own setup

```bash
aura-pce calibrate --report                          # measure + print, don't write
aura-pce calibrate --registry your_registry.jsonl    # measure against your axioms, write calibration.json
```

The floor is embedder- and registry-specific. Swapping either shifts the score distribution,
so re-run the calibration — the numbers above are the receipt for the shipped default, not a
universal constant.
