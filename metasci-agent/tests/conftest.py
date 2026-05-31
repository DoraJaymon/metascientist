from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[0]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(WORKSPACE / "metasci-universe" / "src"))
sys.path.insert(0, "/home/dell/Desktop/OAAgent/alexer/light_agent")
