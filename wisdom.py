"""wisdom.py — the fire log.

When the gate emits advice, it appends one PENDING row here. A row is graded later
(held / not held) and the validity level is computed over graded rows only. This module
is deliberately tiny: logging must never break the advice path, so it fails open and
writes nothing to stdout.

(In the full AURA deployment the same ledger is read by a learning loop that proposes
improvements from graded outcomes; that loop is internal and not part of this twin. What
ships here is the honest logging primitive the gate depends on.)
"""
from __future__ import annotations
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths

DATA = paths.data_home()
FIRES = DATA / "fires.jsonl"


def log_fire(*, situation: str, move: str | None, fire: float = 0.0, resolution: str = "",
             directive: str = "", proposed: str = "", trust: str = "", caller: str = "",
             lane: str = "", fires_path: Path | None = None) -> str:
    """Append one PENDING fire row; return its hash. NEVER raises (a logging failure must
    not break the advice) and never writes to stdout."""
    try:
        if not move:
            return ""
        p = fires_path or FIRES
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        h = hashlib.sha1(f"{situation}|{ts}".encode()).hexdigest()[:12]
        p.parent.mkdir(parents=True, exist_ok=True)
        evt = {"fire_hash": h, "ts": ts, "caller": caller, "situation": situation[:500],
               "move": move, "fire": fire, "resolution": resolution,
               "directive": (directive or "")[:200], "proposed": (proposed or "")[:200],
               "trust": str(trust), "lane": lane or "pce", "harvested": False,
               "graded": False}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
        return h
    except Exception as e:  # fail-open, stderr only
        print(f"[wisdom.log_fire] fail-open: {e}", file=sys.stderr)
        return ""
