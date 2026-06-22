import os
import sys
from pathlib import Path

os.environ["TRAECLAW_TESTING"] = "1"

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
