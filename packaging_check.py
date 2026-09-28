#!/usr/bin/env python3
"""packaging_check.py — assert that the artifact contains what the package claims.

Why this exists. **aura-pce 0.3.0 shipped without the composing path.** Four modules were added to
the repo and never added to ``[tool.setuptools] py-modules``, so the wheel and the sdist both
omitted them — and no test could see it, because the suite runs ``python cli.py selftest`` from the
checkout, where the files are on disk whether or not they are packaged. Every green suite was
measuring the repository, not the artifact. A version that announces a feature it does not ship is
the exact defect this project exists to catch, and we published one.

Run after ``python -m build``:

    python packaging_check.py

Two checks, in order of how much they catch:

  1. **Every module declared in ``py-modules`` is INSIDE both artifacts.** This one alone would have
     caught 0.3.0.
  2. **Every module IMPORTS from an installed wheel, with the process started in a NEUTRAL
     directory.** Importing from the repo proves nothing about what was packaged; the cwd has to be
     somewhere else entirely.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def declared_modules() -> list[str]:
    """The module list the packaging config actually declares. Read from pyproject, never
    hardcoded — a hardcoded list would go stale in exactly the way that caused 0.3.0."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib

        return list(tomllib.loads(text)["tool"]["setuptools"]["py-modules"])
    except Exception:
        block = re.search(r"py-modules\s*=\s*\[(.*?)\]", text, re.S)
        if not block:
            raise SystemExit("packaging_check: cannot find py-modules in pyproject.toml")
        return re.findall(r'"([^"]+)"', block.group(1))


def artifacts() -> tuple[str, str]:
    wheels = sorted(glob.glob(str(ROOT / "dist" / "*.whl")))
    sdists = sorted(glob.glob(str(ROOT / "dist" / "*.tar.gz")))
    if not wheels or not sdists:
        raise SystemExit("packaging_check: no artifacts in dist/ — run `python -m build` first")
    return wheels[-1], sdists[-1]


def main() -> int:
    mods = declared_modules()
    whl, sd = artifacts()
    print(f"packaging_check: {len(mods)} modules declared by pyproject.toml")
    print(f"  wheel: {Path(whl).name}")
    print(f"  sdist: {Path(sd).name}")

    with zipfile.ZipFile(whl) as z:
        in_wheel = z.namelist()
    with tarfile.open(sd) as t:
        in_sdist = t.getnames()

    missing = sorted(m for m in mods
                     if not any(n.endswith(f"{m}.py") for n in in_wheel)
                     or not any(n.endswith(f"{m}.py") for n in in_sdist))
    if missing:
        print(f"  ✗ MISSING from an artifact: {missing}")
        return 1
    print(f"  ✓ all {len(mods)} modules are inside both artifacts")

    with tempfile.TemporaryDirectory(prefix="pkgcheck-") as td:
        env = Path(td) / "venv"
        venv.create(env, with_pip=True)
        subprocess.run([str(env / "bin" / "pip"), "install", "-q", whl], check=True)

        # NEUTRAL cwd — the part that matters, and the part my first attempt got wrong by running
        # the import from the repo directory, where the modules exist regardless of packaging.
        probe = Path(td) / "probe.py"
        probe.write_text(
            "import sys\n"
            f"mods = {mods!r}\n"
            "broken = []\n"
            "for m in mods:\n"
            "    try:\n"
            "        __import__(m)\n"
            "    except Exception as e:\n"
            "        broken.append((m, type(e).__name__))\n"
            "print(f'imported {len(mods) - len(broken)}/{len(mods)} from the installed wheel')\n"
            "for m, err in broken:\n"
            "    print(f'  MISSING {m}: {err}')\n"
            "raise SystemExit(1 if broken else 0)\n",
            encoding="utf-8")
        r = subprocess.run([str(env / "bin" / "python"), str(probe)], cwd=td)
        if r.returncode != 0:
            print("  ✗ a module does not import from the installed wheel")
            return 1
        print("  ✓ every module imports from the installed wheel, from a neutral directory")
    print("\npackaging_check: the claim ships.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
