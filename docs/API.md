# API reference

Everything is importable directly (flat layout); the same functions back the CLI.

## `i_care` — the gate

```python
i_care.i_care(situation, pattern_id=None, input_types=None, log=True,
              registry=None, rows=None, recognizer=None) -> ICareReport
```
Run the four self-tests on a candidate `(situation → recommended axiom)`. Recognises the
axiom when `pattern_id` is not given. `input_types` is a list of type annotations as written
(e.g. `["List[float]"]`) — the type-fit check coarsens them to nouns. `registry` selects the
sovereign registry (a path); `None` = the default sample registry.

`ICareReport` fields: `.checks` (four `ICareCheck`), `.gate` (bool — all four verified-ok),
`.level` (the earned Beta validity dict), `.fire_hash` (set when a gated fire was logged).

```python
i_care.level(fires_path=None) -> dict     # {mean, n, unproven, cite, method, ...}
i_care.prove() -> int                     # the provenance proof (exit code)
i_care.render(report) -> str              # human-readable report
```

## `logic_lane` — recognition

```python
logic_lane.logic_need(situation, defer_log=True, registry=None) -> LogicNeed
```
Recognise the axiom a situation is in the territory of. `LogicNeed.fired` is gated by
`RECOG_FLOOR` (min top-1 cosine) and `RECOG_MARGIN` (min top1−top2 gap), both loaded from
`calibration.json` when present, else the inherited-safe defaults. `.candidates` is the raw
top-3 `[(axiom_id, score)]` regardless of firing.

The embedder is resolved lazily via `logic_lane._embedder()`: the private `brain` module if
present, else `embedder.py`. Both expose `embed(list[str]) -> ndarray` of L2-normalised rows.

## `mesh_bridge` — telemetry → gate

```python
mesh_bridge.gate_typed(situation, avail_fields, registry=SYS_REG,
                       rows_cache=None, log=False, evidence=None) -> dict
```
The source-agnostic gate. `avail_fields` = `{field_name: python-type-string}` the source can
supply. Returns `{decision: EMIT|WITHHOLD|DEFER|SKIP, pattern, score, feed, constraint,
level, emit_hash}`. Every adapter (mesh streams and live sources) funnels through here, so
`i_care` stays the single arbiter.

## `sources` — telemetry adapters

```python
sources.get_source("auto"|"proc"|"psutil"|"journal"|"node_exporter:<path|url>") -> Source
sources.watch(source="auto", interval=5.0, window=30, z=2.0,
              iterations=0, log=False, registry=None) -> int
```
`MetricSource.sample() -> {metric: float}` (rolling-z tracked by the runner);
`EventSource.poll() -> list[Situation]` (already rendered). Each adapter has a pure parse
core + a `selftest()` over a captured sample.

## `mesh_grade` — the learning loop

```python
mesh_grade.level(p=LEDGER) -> dict                  # mesh precision, Beta with n
mesh_grade.grade(hash, "real"|"noise", note="") -> dict
```

## `outcomes` — the estimator

```python
outcomes.beta(hits, misses) -> dict     # Beta(1+hits, 1+misses); unproven at n=0
```

## `ontology` — the type nouns

```python
ontology.coarsen("List[float]") -> "vector"     # raw annotation → one of nine nouns
```

## `calibrate` — the floor derivation

```python
calibrate.measure(registry) -> {"pos": [...], "neg": [...]}
calibrate.choose(measurement) -> {"floor", "margin", "pos_recall", "neg_fires", "separation"}
```
