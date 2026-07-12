#!/usr/bin/env python3
"""paths.py — one place that decides where aura-pce reads and writes its data.

Resolution order (first hit wins):
  1. $AURA_PCE_HOME                  — an explicit deployment override.
  2. <repo>/data  (if it exists)     — the CLONE case: run straight from a checkout,
                                       keeping `python3 i_care.py --prove` and friends
                                       green exactly as documented.
  3. $XDG_DATA_HOME/aura-pce         — the INSTALLED case (`pip install aura-pce`): a
     else ~/.local/share/aura-pce      user data dir, so sample + live data never land
                                       inside site-packages. `aura-pce init` fills it.

Nothing is ever written outside the resolved root.
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def data_home() -> Path:
    """The single data root. See module docstring for the resolution order."""
    env = os.environ.get("AURA_PCE_HOME")
    if env:
        return Path(env).expanduser()
    local = HERE / "data"
    if local.exists():
        return local
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "aura-pce"


if __name__ == "__main__":
    print(data_home())
