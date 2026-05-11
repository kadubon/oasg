"""Task generator wrapper for the strong-baseline v2 experiment."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V1 = ROOT / "experiment" / "ollama_gemma4_e4b_strong_baseline" / "scripts"
for import_path in (V1, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from generate_strong_tasks import FAMILIES, generate_strong_tasks, main  # type: ignore  # noqa: E402,F401


if __name__ == "__main__":
    raise SystemExit(main())
