#!/usr/bin/env python3
"""sources/journal.py — systemd journal as an event source.

Reads `journalctl -o json` and renders high-severity entries (priority ≤ warning) into
situations. Journal entries carry no numeric input types, so the gate will typically
WITHHOLD or DEFER on them — which is the honest, correct behaviour: the engine recognises a
possible concern but refuses to *advise* without a verifiable, typed precondition. The
adapter's job is faithful rendering + typing; the gate decides. (This is defense-in-depth
made visible on real logs.)

Pure rendering lives in `render_entry`, tested on captured `journalctl -o json` lines.
"""
from __future__ import annotations

import json

from .base import EventSource, Situation

# journald PRIORITY: 0 emerg … 3 err, 4 warning, 5 notice, 6 info, 7 debug. We surface ≤ this.
SEVERITY = 4


def parse_lines(text: str) -> list[dict]:
    """journalctl -o json output → list of entry dicts (one JSON object per line)."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def render_entry(entry: dict) -> Situation | None:
    """A journal entry → a Situation, or None when it's below the severity floor. The message
    and unit are text (no numeric input the gate could type-check) — so advice on a log line
    must clear recognition on the words alone, and type-fit will honestly abstain."""
    try:
        prio = int(entry.get("PRIORITY", 6))
    except (TypeError, ValueError):
        prio = 6
    if prio > SEVERITY:
        return None
    host = entry.get("_HOSTNAME", "localhost")
    unit = entry.get("_SYSTEMD_UNIT") or entry.get("SYSLOG_IDENTIFIER") or "system"
    msg = (entry.get("MESSAGE") or "").strip()
    if isinstance(msg, list):   # journal can encode MESSAGE as a byte array
        msg = bytes(msg).decode("utf-8", "replace")
    text = f"{host}: {unit} reported (priority {prio}): {msg}"[:300]
    return Situation(text=text, fields={"unit": "str", "message": "str"},
                     node=host, metric=unit)


class JournalSource(EventSource):
    name = "journal"

    def __init__(self, lines: int = 50):
        self.lines = lines
        self._seen_ts = 0
        try:
            import socket
            self.node = socket.gethostname()
        except OSError:
            self.node = "localhost"

    def available(self) -> bool:
        import shutil
        return shutil.which("journalctl") is not None

    def poll(self) -> list:
        import subprocess
        try:
            raw = subprocess.run(
                ["journalctl", "-o", "json", "--no-pager", "-p", str(SEVERITY),
                 "-n", str(self.lines)],
                capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        sits = []
        for entry in parse_lines(raw):
            try:
                ts = int(entry.get("__REALTIME_TIMESTAMP", 0))
            except (TypeError, ValueError):
                ts = 0
            if ts <= self._seen_ts:
                continue
            self._seen_ts = max(self._seen_ts, ts)
            s = render_entry(entry)
            if s is not None:
                sits.append(s)
        return sits


# ── captured sample + selftest ───────────────────────────────────────────────

_CAP_ERR = json.dumps({
    "__REALTIME_TIMESTAMP": "1720000000000000", "PRIORITY": "3",
    "_HOSTNAME": "node-a", "_SYSTEMD_UNIT": "postgresql.service",
    "MESSAGE": "database system was interrupted; last known up at 2026-07-13"})
_CAP_INFO = json.dumps({
    "__REALTIME_TIMESTAMP": "1720000001000000", "PRIORITY": "6",
    "_HOSTNAME": "node-a", "_SYSTEMD_UNIT": "cron.service", "MESSAGE": "job finished"})


def selftest() -> int:
    entries = parse_lines(_CAP_ERR + "\n" + _CAP_INFO)
    err = render_entry(entries[0])
    info = render_entry(entries[1])
    checks = [
        ("parses two json lines", len(entries) == 2),
        ("err entry renders a situation", err is not None),
        ("situation carries unit + message text", err and "postgresql.service" in err.text
         and "interrupted" in err.text),
        ("fields are text-only (gate will honestly abstain on type-fit)",
         err and set(err.fields.values()) == {"str"}),
        ("info entry below severity → None (filtered)", info is None),
    ]
    ok = sum(1 for _, c in checks if c)
    print("journal adapter — captured journalctl -o json:")
    for n, c in checks:
        print(f"  {'✓' if c else '✗ FAIL'}  {n}")
    print(f"  {ok}/{len(checks)} passed" + ("" if ok == len(checks) else " — FIX"))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
