"""Test configuration -- ensure the unslop package is importable."""

import sys
from pathlib import Path

# Add the repo root to sys.path so `from unslop.scripts.orchestrator import ...` works.
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
