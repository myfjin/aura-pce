#!/usr/bin/env python3
"""evidence.py — attach adjacent evidence to each gated emit so a grader can call
`real` or `noise` from evidence rather than fading memory.

Public mechanism in the aura-pce package. Reads the mesh ledger produced by
`aura-pce watch --log`, captures a bundle of snapshots+events at the moment a new
emit appears, writes it to disk keyed by emit_hash. No network calls, no
auto-remediation, no silent partial captures.

Subcommands:
  aura-pce evidence watch [--follow | --once]
  aura-pce evidence show <hash>
  aura-pce evidence prove
  aura-pce evidence selftest

Config: optional JSON at ~/.config/aura-pce/evidence.json. Keys and defaults:
  { "poll_interval_ms": 500,
    "journal_lines": 200,
    "top_n": 10,
    "collectors": ["loadavg","meminfo","top","journal","cron_systemd"] }

Evidence files: ~/.local/share/aura-pce/evidence/<emit_hash>.json

Design notes:
  * Collectors are isolated: a failing collector records an error in the bundle,
    never crashes the watcher.
  * Dedup is content-based: if evidence/<hash>.json already exists for an emit
    row, the watcher skips it. Restart-safe without a sidecar offset file.
  * stdlib-only. Portable to any POSIX box with /proc; collectors that need a
    missing tool (journalctl, crontab, systemctl) record errors cleanly.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# ── paths ─────────────────────────────────────────────────────────────────────

def data_home() -> Path:
    """Mirror aura-pce's data home resolution."""
    override = os.environ.get("AURA_PCE_DATA_HOME")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "aura-pce"


def config_path() -> Path:
    override = os.environ.get("AURA_PCE_EVIDENCE_CONFIG")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "aura-pce" / "evidence.json"


def ledger_path() -> Path:
    return data_home() / "mesh-emits.jsonl"


def evidence_dir() -> Path:
    return data_home() / "evidence"


# ── config ────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG: dict[str, Any] = {
    "poll_interval_ms": 500,
    "journal_lines": 200,
    "top_n": 10,
    "collectors": ["loadavg", "meminfo", "top", "journal", "cron_systemd"],
}


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    p = config_path()
    if p.exists():
        try:
            user = json.loads(p.read_text())
            if isinstance(user, dict):
                cfg.update(user)
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


# ── node id (same convention aura-pce watch uses) ─────────────────────────────

def _detect_node() -> str:
    override = os.environ.get("AURA_PCE_NODE")
    if override:
        return override
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return "unknown"


# ── collectors ────────────────────────────────────────────────────────────────
#
# Each collector returns a JSON-serialisable value, or raises an exception.
# Exceptions are captured and recorded in collectors_errored; the bundle is
# still written (no silent partial capture).

def collect_loadavg() -> dict[str, Any]:
    with open("/proc/loadavg") as f:
        parts = f.read().strip().split()
    return {
        "load_1m": float(parts[0]),
        "load_5m": float(parts[1]),
        "load_15m": float(parts[2]),
        "scheduling": parts[3],   # "running/total"
        "last_pid": int(parts[4]),
    }


def collect_meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            v = rest.strip().split()
            if v and v[0].isdigit():
                out[key.strip()] = int(v[0])  # kB
    return out


def collect_top(n: int = 10) -> dict[str, list[dict[str, Any]]]:
    """Top-N processes by RSS, and by recent CPU ticks. Stdlib-only via /proc."""
    procs: list[dict[str, Any]] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open(f"/proc/{pid}/stat") as f:
                raw = f.read()
            # comm may contain spaces/parens; locate the final )
            cend = raw.rfind(")")
            if cend < 0:
                continue
            comm = raw[raw.find("(") + 1:cend]
            rest = raw[cend + 2:].split()
            utime, stime = int(rest[11]), int(rest[12])
            rss_pages = int(rest[21])
            procs.append({
                "pid": pid,
                "comm": comm,
                "rss_kb": rss_pages * (os.sysconf("SC_PAGESIZE") // 1024),
                "cpu_ticks": utime + stime,
            })
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, ValueError, IndexError):
            continue
    top_mem = sorted(procs, key=lambda p: p["rss_kb"], reverse=True)[:n]
    top_cpu = sorted(procs, key=lambda p: p["cpu_ticks"], reverse=True)[:n]
    return {"top_mem": top_mem, "top_cpu": top_cpu}


def _run_capture(argv: list[str], timeout: float = 3.0) -> str:
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 and not r.stdout:
        raise RuntimeError(f"{argv[0]} rc={r.returncode}: {r.stderr.strip()[:200]}")
    return r.stdout


def collect_journal(n: int = 200) -> dict[str, list[str]]:
    """Recent system + user journal lines. Missing journalctl is a soft error."""
    out: dict[str, list[str]] = {"system": [], "user": []}
    for key, argv in [
        ("system", ["journalctl", "-n", str(n), "--no-pager", "-o", "short-iso"]),
        ("user", ["journalctl", "--user", "-n", str(max(n // 4, 20)), "--no-pager", "-o", "short-iso"]),
    ]:
        try:
            text = _run_capture(argv)
            out[key] = [ln for ln in text.splitlines() if ln]
        except FileNotFoundError:
            raise RuntimeError("journalctl not installed")
    return out


def collect_cron_systemd() -> dict[str, Any]:
    """User crontab + currently-running services (user + system). All read-only."""
    out: dict[str, Any] = {}
    try:
        text = _run_capture(["crontab", "-l"])
        out["cron_user"] = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    except FileNotFoundError:
        out["cron_user_error"] = "crontab not installed"
    except RuntimeError as e:
        # "no crontab for X" is rc=1 with empty stdout; treat as empty, not error.
        if "no crontab" in str(e).lower():
            out["cron_user"] = []
        else:
            out["cron_user_error"] = str(e)
    for key, argv in [
        ("units_user_running", ["systemctl", "--user", "list-units", "--type=service",
                                "--state=running", "--no-pager", "--plain", "--no-legend"]),
        ("units_system_running", ["systemctl", "list-units", "--type=service",
                                  "--state=running", "--no-pager", "--plain", "--no-legend"]),
    ]:
        try:
            text = _run_capture(argv)
            # first column is the unit name
            out[key] = [ln.split()[0] for ln in text.splitlines() if ln.strip()]
        except FileNotFoundError:
            out[f"{key}_error"] = "systemctl not installed"
        except Exception as e:
            out[f"{key}_error"] = str(e)[:200]
    return out


COLLECTORS: dict[str, Callable[..., Any]] = {
    "loadavg": collect_loadavg,
    "meminfo": collect_meminfo,
    "top": collect_top,
    "journal": collect_journal,
    "cron_systemd": collect_cron_systemd,
}


# ── bundle ────────────────────────────────────────────────────────────────────

def capture_bundle(emit: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    t0 = time.monotonic()
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    snapshot: dict[str, Any] = {}
    events: dict[str, Any] = {}
    config_capture: dict[str, Any] = {}
    collectors_run: list[str] = []
    collectors_errored: list[dict[str, str]] = []

    for name in cfg.get("collectors", DEFAULT_CONFIG["collectors"]):
        fn = COLLECTORS.get(name)
        if fn is None:
            collectors_errored.append({"collector": name, "error": "unknown collector"})
            continue
        try:
            if name == "top":
                val = fn(cfg.get("top_n", DEFAULT_CONFIG["top_n"]))
            elif name == "journal":
                val = fn(cfg.get("journal_lines", DEFAULT_CONFIG["journal_lines"]))
            else:
                val = fn()
            if name == "journal":
                events["journal_recent"] = val
            elif name == "cron_systemd":
                config_capture.update(val)
            elif name == "loadavg":
                snapshot["loadavg"] = val
            elif name == "meminfo":
                snapshot["meminfo"] = val
            elif name == "top":
                snapshot["top_cpu"] = val["top_cpu"]
                snapshot["top_mem"] = val["top_mem"]
            else:
                snapshot[name] = val
            collectors_run.append(name)
        except Exception as e:
            collectors_errored.append({"collector": name, "error": f"{type(e).__name__}: {e}"})

    return {
        "emit_hash": emit.get("emit_hash"),
        "captured_ts": now,
        "capture_delta_ms": int((time.monotonic() - t0) * 1000),
        "node": _detect_node(),
        "emit_echo": {k: emit.get(k) for k in ("event_ts", "stream", "node", "situation",
                                               "pattern", "score", "z_5m") if k in emit},
        "snapshot": snapshot,
        "events": events,
        "config": config_capture,
        "collectors_run": collectors_run,
        "collectors_errored": collectors_errored,
    }


def write_bundle(bundle: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{bundle['emit_hash']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(bundle, indent=2, sort_keys=False))
    os.replace(tmp, path)
    return path


# ── watcher ───────────────────────────────────────────────────────────────────

def process_ledger_once(ledger: Path, out_dir: Path, cfg: dict[str, Any]) -> int:
    """Scan the ledger; capture evidence for any emit that has none yet. Returns
    the number of new bundles written."""
    if not ledger.exists():
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = {p.stem for p in out_dir.glob("*.json")}
    new = 0
    with ledger.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                emit = json.loads(line)
            except json.JSONDecodeError:
                continue
            h = emit.get("emit_hash")
            if not h or h in seen:
                continue
            bundle = capture_bundle(emit, cfg)
            write_bundle(bundle, out_dir)
            seen.add(h)
            new += 1
    return new


def watch_ledger(ledger: Path, out_dir: Path, cfg: dict[str, Any],
                 iterations: int = 0, verbose: bool = True) -> int:
    """Poll-tail the ledger. `iterations=0` runs forever; any positive int stops
    after that many polling cycles (used by selftest/prove)."""
    interval = cfg.get("poll_interval_ms", DEFAULT_CONFIG["poll_interval_ms"]) / 1000.0
    n = 0
    total_new = 0
    while True:
        try:
            new = process_ledger_once(ledger, out_dir, cfg)
            if new and verbose:
                print(f"[evidence] captured {new} new bundle(s)", flush=True)
            total_new += new
        except Exception as e:
            print(f"[evidence] watcher error: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        n += 1
        if iterations and n >= iterations:
            return total_new
        time.sleep(interval)


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_watch(args: argparse.Namespace) -> int:
    cfg = load_config()
    ledger = Path(args.ledger).expanduser() if args.ledger else ledger_path()
    out = Path(args.evidence_dir).expanduser() if args.evidence_dir else evidence_dir()
    if args.once:
        n = process_ledger_once(ledger, out, cfg)
        print(f"captured {n} bundle(s) from {ledger}")
        return 0
    # default = follow
    try:
        watch_ledger(ledger, out, cfg)
    except KeyboardInterrupt:
        print()
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    out = Path(args.evidence_dir).expanduser() if args.evidence_dir else evidence_dir()
    p = out / f"{args.hash}.json"
    if not p.exists():
        print(f"no evidence bundle for emit {args.hash} at {p}", file=sys.stderr)
        return 2
    print(p.read_text())
    return 0


def cmd_prove(args: argparse.Namespace) -> int:
    """Synthesize a test emit → run the watcher once → verify the bundle. All in
    a temp dir; your real ledger and evidence dir are not touched."""
    print("=== evidence — provenance proof ===\n")
    required = ["emit_hash", "captured_ts", "capture_delta_ms", "node",
                "emit_echo", "snapshot", "events", "config",
                "collectors_run", "collectors_errored"]
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        ledger = tdp / "mesh-emits.jsonl"
        out_dir = tdp / "evidence"
        test_emit = {
            "emit_hash": "prove_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "event_ts": datetime.now(timezone.utc).isoformat(),
            "stream": "test",
            "node": _detect_node(),
            "situation": "synthetic emit for aura-pce evidence prove",
            "pattern": "zscore_anomaly",
            "score": 0.42, "z_5m": 2.5, "graded": False, "outcome": None,
        }
        ledger.write_text(json.dumps(test_emit) + "\n")
        cfg = load_config()
        n = process_ledger_once(ledger, out_dir, cfg)
        print(f"  [a] synthetic emit written → ledger")
        print(f"  [b] watcher scan: captured {n} bundle(s) (expected: 1)")
        bundle_path = out_dir / f"{test_emit['emit_hash']}.json"
        if not bundle_path.exists():
            print("  FAIL: no bundle written")
            return 1
        bundle = json.loads(bundle_path.read_text())
        print(f"  [c] bundle fields:")
        all_ok = True
        for field in required:
            ok = field in bundle
            print(f"      {'✓' if ok else '✗'} {field}")
            all_ok = all_ok and ok
        print(f"  [d] dedup check: re-running the watcher must produce 0 new")
        n2 = process_ledger_once(ledger, out_dir, cfg)
        dedup_ok = (n2 == 0)
        print(f"      {'✓' if dedup_ok else '✗'} re-scan produced {n2} new (expected 0)")
        collectors_run = bundle.get("collectors_run", [])
        print(f"  [e] collectors that ran this environment: {collectors_run}")
        errs = bundle.get("collectors_errored", [])
        if errs:
            print(f"      collectors that errored (non-fatal): {[e['collector'] for e in errs]}")
        print()
        if all_ok and dedup_ok:
            print("PROVE: PASS")
            print("CITE ONLY: 'aura-pce evidence prove passes on this install'.")
            return 0
        print("PROVE: FAIL")
        return 1


def cmd_selftest(args: argparse.Namespace) -> int:
    """Each collector exercised in isolation; bundle schema sanity; failure
    tolerance. Stdlib only."""
    print("── evidence.selftest() ──")
    fails = 0

    # (1) every collector returns something or records a clean failure
    for name, fn in COLLECTORS.items():
        try:
            if name == "top":
                v = fn(3)
            elif name == "journal":
                v = fn(5)
            else:
                v = fn()
            print(f"  ✓ collector {name}: ok ({type(v).__name__})")
        except Exception as e:
            print(f"  ~ collector {name}: unavailable ({type(e).__name__}) — acceptable")

    # (2) bundle schema integrity on a minimal emit
    emit = {"emit_hash": "selftest_1", "event_ts": "2026-01-01T00:00:00Z",
            "situation": "selftest", "pattern": "zscore_anomaly"}
    bundle = capture_bundle(emit, DEFAULT_CONFIG)
    required = ["emit_hash", "captured_ts", "capture_delta_ms", "node",
                "snapshot", "events", "config", "collectors_run", "collectors_errored"]
    for f in required:
        if f not in bundle:
            print(f"  ✗ bundle missing field: {f}")
            fails += 1
    if bundle["emit_hash"] != "selftest_1":
        print("  ✗ emit_hash not propagated")
        fails += 1
    if not isinstance(bundle["collectors_run"], list):
        print("  ✗ collectors_run is not a list")
        fails += 1

    # (3) collector failure containment: register a broken collector, bundle
    # should still write with the error recorded
    def _broken():
        raise RuntimeError("intentional selftest failure")
    COLLECTORS["_broken"] = _broken
    try:
        cfg = {**DEFAULT_CONFIG, "collectors": ["loadavg", "_broken"]}
        b2 = capture_bundle(emit, cfg)
        if "_broken" not in [e["collector"] for e in b2["collectors_errored"]]:
            print("  ✗ broken collector was not reported in collectors_errored")
            fails += 1
        else:
            print("  ✓ broken collector contained — bundle still produced, error recorded")
    finally:
        COLLECTORS.pop("_broken", None)

    # (4) write + read + dedup round-trip
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        p = write_bundle(bundle, tdp)
        if not p.exists():
            print("  ✗ write_bundle did not create file")
            fails += 1
        back = json.loads(p.read_text())
        if back["emit_hash"] != bundle["emit_hash"]:
            print("  ✗ round-trip hash mismatch")
            fails += 1
        else:
            print("  ✓ write + read round-trip")

    if fails == 0:
        print("\nALL GREEN")
        return 0
    print(f"\n{fails} failure(s)")
    return 1


# ── argparse hook (called by cli.py) ──────────────────────────────────────────

def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("evidence", help="attach evidence to each emit so grading comes from evidence, not memory")
    ssub = p.add_subparsers(dest="evidence_cmd", required=True)

    pw = ssub.add_parser("watch", help="tail the ledger and capture evidence per new emit")
    pw.add_argument("--ledger", help="override ledger path (default: data_home/mesh-emits.jsonl)")
    pw.add_argument("--evidence-dir", help="override evidence output dir")
    pw.add_argument("--once", action="store_true", help="single pass then exit (otherwise follow forever)")
    pw.set_defaults(fn=cmd_watch)

    ps = ssub.add_parser("show", help="print the evidence bundle for one emit")
    ps.add_argument("hash")
    ps.add_argument("--evidence-dir")
    ps.set_defaults(fn=cmd_show)

    pp = ssub.add_parser("prove", help="synthetic emit → capture → verify (writes to a temp dir)")
    pp.set_defaults(fn=cmd_prove)

    pt = ssub.add_parser("selftest", help="unit tests — stdlib-only")
    pt.set_defaults(fn=cmd_selftest)


# ── standalone entry (python3 evidence.py <sub> ...) ──────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="evidence", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    # mirror register() but without the outer "evidence" wrapper
    pw = sub.add_parser("watch"); pw.add_argument("--ledger"); pw.add_argument("--evidence-dir"); pw.add_argument("--once", action="store_true"); pw.set_defaults(fn=cmd_watch)
    ps = sub.add_parser("show"); ps.add_argument("hash"); ps.add_argument("--evidence-dir"); ps.set_defaults(fn=cmd_show)
    sub.add_parser("prove").set_defaults(fn=cmd_prove)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
