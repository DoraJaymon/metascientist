import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

# Let test modules import the shared doubles as `from fakes import ...`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# metasci-universe is a sibling source checkout in this repo.
UNIVERSE_SRC = ROOT.parent / "metasci-universe" / "src"
if UNIVERSE_SRC.exists():
    sys.path.insert(0, str(UNIVERSE_SRC))
