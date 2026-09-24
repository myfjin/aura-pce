#!/usr/bin/env python3
"""cli.py — the `aura-pce` console entry point.

A thin dispatcher over the modules that already carry the mechanism. Every subcommand maps
to a function that also runs standalone (`python3 i_care.py --prove`, etc.), so the CLI adds
convenience, never a second source of truth.

  aura-pce prove              # the provenance proof (self-tests are real + run green)
  aura-pce level              # the two earned metrics, never conflated
  aura-pce selftest           # run every self-test available in this install
  aura-pce watch              # gate REAL local telemetry from your machine (needs [live])
  aura-pce init               # write the sample registry + demo ledger into the data home
  aura-pce list               # mesh emits awaiting a human grade
  aura-pce grade <hash> real|noise ["note"]
  aura-pce where              # print the resolved data home
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def cmd_prove(args) -> int:
    import i_care
    return i_care.prove()


def cmd_level(args) -> int:
    import i_care
    import mesh_grade
    validity = i_care.level()
    mesh = mesh_grade.level()
    print("=== aura-pce — earned metrics (two axes, never conflated) ===\n")
    print(f"  validity LEVEL  (advice gate)      : {validity['cite']}")
    print(f"  mesh precision  (anomaly monitor)  : {mesh['cite']}")
    print("\n  validity LEVEL = P(gated advice HELD), outcome-blind stop-to-think (wisdom lane).")
    print("  mesh precision = P(flagged anomaly was REAL), an OUTCOME metric (human-graded).")
    print("  Both are Beta estimates with n disclosed; at n=0 they print 'unproven', never 50%.")
    return 0


def cmd_selftest(args) -> int:
    """Run every self-test this install can run. Stdlib suites always; the embedder-backed
    ones (embedder, logic_lane live recognition) only when a [live] backend is present."""
    import importlib
    results: list[tuple[str, int | None]] = []

    def run(mod_name: str, fn: str = "selftest") -> None:
        mod = importlib.import_module(mod_name)
        print(f"\n── {mod_name}.{fn}() ──")
        rc = getattr(mod, fn)()
        results.append((mod_name, 0 if rc is None else rc))

    # stdlib suites — always runnable
    for m in ("ontology", "i_care", "mesh_grade", "mesh_bridge", "decompose"):
        run(m)

    # embedder-backed suites — only if a live backend is installed
    try:
        import embedder
        embedder.backend_name()          # raises ImportError if no backend
        run("embedder")
        run("logic_lane")
    except ImportError:
        print("\n── embedder / logic_lane ──\n  ⚠ skipped (no [live] backend; "
              "pip install aura-pce[live] to run live recognition self-tests)")
        results.append(("embedder", None))

    failed = [m for m, rc in results if rc not in (0, None)]
    print("\n=== selftest summary ===")
    for m, rc in results:
        mark = "•skip" if rc is None else ("✓" if rc == 0 else "✗")
        print(f"  {mark}  {m}")
    if failed:
        print(f"\n✗ {len(failed)} suite(s) FAILED: {', '.join(failed)}")
        return 1
    print("\nALL GREEN")
    return 0


def cmd_init(args) -> int:
    import make_sample_data
    make_sample_data.main()
    return 0


def cmd_list(args) -> int:
    import mesh_grade
    mesh_grade.cmd_list()
    return 0


def cmd_grade(args) -> int:
    import mesh_grade
    lv = mesh_grade.grade(args.hash, args.outcome, args.note or "")
    print(f"✓ graded {args.hash} = {args.outcome} → {lv['cite']}")
    return 0


def cmd_calibrate(args) -> int:
    import json
    import calibrate
    import paths
    try:
        m = calibrate.measure(Path(args.registry).expanduser() if args.registry else None)
    except ImportError as e:
        print(f"calibration needs a live embedder ([live] extra):\n  {e}", file=sys.stderr)
        return 1
    chosen = calibrate.choose(m)
    calibrate.report(m, chosen)
    if not args.report:
        out = paths.data_home()
        out.mkdir(parents=True, exist_ok=True)
        p = out / "calibration.json"
        p.write_text(json.dumps({
            "chosen": chosen, "before": calibrate.evaluate(m, 0.30, 0.0), "measurement": m,
            "note": "derived by aura-pce calibrate; re-run per embedder/registry."}, indent=2))
        print(f"\nwrote {p}")
    return 0


def cmd_where(args) -> int:
    import paths
    home = paths.data_home()
    print(home)
    print(f"  exists: {home.exists()}   (run `aura-pce init` to populate the sample data)")
    return 0


def cmd_watch(args) -> int:
    import sources          # lazy: only `watch` needs the telemetry adapters
    return sources.watch(source=args.source, interval=args.interval, window=args.window,
                         z=args.z, iterations=args.iterations, log=args.log,
                         registry=args.registry)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aura-pce", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("prove", help="provenance proof: self-tests are real + run green").set_defaults(fn=cmd_prove)
    sub.add_parser("level", help="the two earned metrics (validity + mesh precision)").set_defaults(fn=cmd_level)
    sub.add_parser("selftest", help="run every self-test available in this install").set_defaults(fn=cmd_selftest)
    sub.add_parser("init", help="write the sample registry + demo ledger").set_defaults(fn=cmd_init)
    sub.add_parser("list", help="mesh emits awaiting a human grade").set_defaults(fn=cmd_list)
    sub.add_parser("where", help="print the resolved data home").set_defaults(fn=cmd_where)

    g = sub.add_parser("grade", help="grade a pending mesh emit real|noise")
    g.add_argument("hash")
    g.add_argument("outcome", choices=["real", "noise"])
    g.add_argument("note", nargs="?", default="")
    g.set_defaults(fn=cmd_grade)

    c = sub.add_parser("calibrate", help="derive the recognition floor from a measured distribution")
    c.add_argument("--registry", default=None, help="registry to calibrate against (default: sample)")
    c.add_argument("--report", action="store_true", help="print only, don't write calibration.json")
    c.set_defaults(fn=cmd_calibrate)

    w = sub.add_parser("watch", help="gate REAL local telemetry from this machine")
    w.add_argument("--source", default="auto",
                   help="telemetry source: auto|psutil|proc|node_exporter:<path|url> (default auto)")
    w.add_argument("--interval", type=float, default=5.0, help="seconds between samples (default 5)")
    w.add_argument("--window", type=int, default=30, help="rolling-baseline window in samples (default 30)")
    w.add_argument("--z", type=float, default=2.0, help="anomaly z-score threshold (default 2.0)")
    w.add_argument("--iterations", type=int, default=0, help="stop after N samples (0 = run forever)")
    w.add_argument("--registry", default=None, help="axiom registry (default: the sample registry)")
    w.add_argument("--log", action="store_true", help="log gated EMITs to the mesh ledger")
    w.set_defaults(fn=cmd_watch)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "fn", None):
        build_parser().print_help()
        return 0
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
