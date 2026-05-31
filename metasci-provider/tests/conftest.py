from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
UNIVERSE_SRC = ROOT.parent / "metasci-universe" / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(UNIVERSE_SRC))
