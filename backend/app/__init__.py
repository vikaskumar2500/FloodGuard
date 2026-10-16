import sys
from pathlib import Path

_ML_PATH = Path(__file__).resolve().parents[2] / "ml"
if str(_ML_PATH) not in sys.path:
    sys.path.insert(0, str(_ML_PATH))
