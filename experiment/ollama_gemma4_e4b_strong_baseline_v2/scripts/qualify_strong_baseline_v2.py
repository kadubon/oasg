"""Stage 0 wrapper: qualify a strong static baseline for v2."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
V1 = ROOT / "experiment" / "ollama_gemma4_e4b_strong_baseline" / "scripts"
for import_path in (V1, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from qualify_strong_baseline import qualify_strong_baseline as _qualify_v1  # type: ignore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args()
    receipt = qualify_strong_baseline_v2(
        config_path=Path(args.config),
        out_dir=Path(args.out_dir),
        mock_model=args.mock_model,
    )
    print(json.dumps({"status": receipt["status"], "out_dir": str(args.out_dir)}, indent=2))
    return 0


def qualify_strong_baseline_v2(
    *,
    config_path: Path,
    out_dir: Path,
    mock_model: bool = False,
) -> dict[str, Any]:
    receipt = _qualify_v1(config_path=config_path, out_dir=out_dir, mock_model=mock_model)
    receipt["profile"] = "strong_baseline_v2"
    return receipt


if __name__ == "__main__":
    raise SystemExit(main())
