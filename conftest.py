import sys
from pathlib import Path

ROOT = Path(__file__).parent
for sub in ("daemon", "client", "shared"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)
