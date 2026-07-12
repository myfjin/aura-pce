#!/usr/bin/env python3
"""sources/base.py — the telemetry-adapter contract + the rolling-z runner.

An adapter turns REAL local telemetry into the exact typed situations the gate already
understands. There are two shapes:

  MetricSource  — emits {metric_name: float} each sample. The runner keeps a rolling
                  baseline per metric and renders an anomaly situation only when a
                  metric's z-score clears the threshold (the same z→zscore_anomaly path
                  the mesh bridge uses; a calm machine stays silent).
  EventSource   — emits already-rendered Situations per poll (discrete log/journal events).

Every situation, whichever shape it came from, is fed to mesh_bridge.gate_typed, so
i_care remains the single arbiter for live telemetry exactly as for the mesh streams.
"""
from __future__ import annotations

import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class Situation:
    """A rendered situation plus the Python types the source can actually SUPPLY as inputs
    (so the gate's type-fit check runs on real data, not a guess)."""
    text: str
    fields: dict = field(default_factory=dict)   # field_name -> python type-string
    node: str = "localhost"
    metric: str = ""
    value: float | None = None
    z: float | None = None


class Source:
    name = "base"
    node = "localhost"

    def available(self) -> bool:
        return True


class MetricSource(Source):
    """Emits {metric_name: float} each sample; the runner tracks rolling z per metric."""

    def sample(self) -> dict:
        raise NotImplementedError


class EventSource(Source):
    """Emits already-rendered Situations per poll (discrete log/journal events)."""

    def poll(self) -> list:
        raise NotImplementedError


class RollingZ:
    """Per-metric rolling baseline → z-score of the latest reading. The z is computed over
    PRIOR history only (the current value doesn't contaminate its own baseline), and stays
    None until enough samples exist to have a baseline at all — honest cold-start."""

    def __init__(self, window: int = 30):
        self.window = window
        self.min_n = max(5, window // 3)
        self.hist: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))

    def update(self, metric: str, value: float) -> float | None:
        h = self.hist[metric]
        z = None
        if len(h) >= self.min_n:
            mu = statistics.fmean(h)
            sd = statistics.pstdev(h)
            z = 0.0 if sd == 0 else (value - mu) / sd
        h.append(value)
        return z


def anomaly_situation(node: str, metric: str, value: float, z: float, window_s: int) -> Situation:
    """Render a metric anomaly in the SAME shape the mesh bridge uses, so recognition lands
    on zscore_anomaly and the value (a scalar) can be fed to the type-fit check."""
    return Situation(
        text=(f"{node}: {metric} anomaly, latest {round(value, 3)}, "
              f"z-score {round(z, 2)} over {window_s}s window"),
        fields={"value": "float", "node": "str"},
        node=node, metric=metric, value=float(value), z=float(z),
    )
