"""Analyze the OASG x Ollama pilot run.

The analysis is intentionally descriptive. It reports paired operational
metrics for the fixed baseline and OASG-adaptive conditions, including failed
and inconclusive artifacts.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for import_path in (SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from oasg.canonical import receipt_hash  # noqa: E402
from oasg.io import read_json, write_json  # noqa: E402
from oasg.ledger import verify_jsonl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = analyze_run(run_dir)
    write_json(out_dir / "metrics.json", metrics)
    (out_dir / "report.md").write_text(_render_report(metrics), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "ok", "metrics": str(out_dir / "metrics.json")}, indent=2))
    return 0


def analyze_run(run_dir: Path) -> dict[str, Any]:
    config = _read_optional_json(run_dir / "config.json", {})
    manifest = _read_optional_json(run_dir / "task_manifest.json", {})
    baseline_results = _read_results(run_dir / "baseline_fixed")
    adaptive_results = _read_results(run_dir / "oasg_adaptive")
    baseline_summary = _condition_summary(_phase_results(baseline_results, "evaluation"))
    adaptive_summary = _condition_summary(_phase_results(adaptive_results, "evaluation"))
    calibration_summary = {
        "baseline_fixed": _condition_summary(_phase_results(baseline_results, "calibration")),
        "oasg_adaptive": _condition_summary(_phase_results(adaptive_results, "calibration")),
    }
    all_summary = {
        "baseline_fixed": _condition_summary(baseline_results),
        "oasg_adaptive": _condition_summary(adaptive_results),
    }
    paired = _paired_effects(
        _phase_results(baseline_results, "evaluation"),
        _phase_results(adaptive_results, "evaluation"),
    )
    paired["bootstrap_ci"] = _bootstrap_effect_ci(paired["rows"])
    oasg = _oasg_artifacts(run_dir / "oasg_adaptive")
    ledger_receipts = {
        "baseline_fixed": _ledger_receipt(run_dir / "baseline_fixed" / "history.jsonl"),
        "oasg_adaptive": _ledger_receipt(run_dir / "oasg_adaptive" / "history.jsonl"),
    }
    classification = _classify(
        baseline_summary=baseline_summary,
        adaptive_summary=adaptive_summary,
        paired=paired,
        oasg=oasg,
    )
    return {
        "experiment_id": "ollama_gemma4_e4b_pilot",
        "classification": classification,
        "model": config.get("model"),
        "ollama_endpoint": config.get("ollama_endpoint"),
        "task_manifest": manifest,
        "task_manifest_hash": receipt_hash(manifest) if manifest else None,
        "baseline_fixed": baseline_summary,
        "oasg_adaptive": adaptive_summary,
        "calibration": calibration_summary,
        "all_tasks": all_summary,
        "paired_effects": paired,
        "oasg_artifacts": oasg,
        "ledger_receipts": ledger_receipts,
        "scientific_limits": [
            "One-hour pilot scale; no strong statistical claim.",
            "Deterministic validators measure operational closure, not semantic truth.",
            "OASG optimization is workflow-policy adaptation only; model weights are unchanged.",
            "No LLM judge or external correctness oracle is used.",
        ],
    }


def _read_results(condition_dir: Path) -> list[dict[str, Any]]:
    path = condition_dir / "task_results.json"
    if not path.exists():
        return []
    data = read_json(path)
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _phase_results(results: list[dict[str, Any]], phase: str) -> list[dict[str, Any]]:
    if not any("phase" in item for item in results):
        return results if phase == "evaluation" else []
    return [item for item in results if item.get("phase") == phase]


def _condition_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    closed = sum(1 for item in results if item.get("closed") is True)
    parsed = sum(1 for item in results if item.get("parsed") is True)
    validation_failed = sum(1 for item in results if item.get("validation_passed") is not True)
    attempts = sum(int(item.get("attempts", 0)) for item in results)
    retries = sum(int(item.get("retries", 0)) for item in results)
    latency = sum(int(item.get("latency_ms", 0)) for item in results)
    prompt_chars = sum(int(item.get("prompt_chars", 0)) for item in results)
    output_chars = sum(int(item.get("output_chars", 0)) for item in results)
    unresolved = sum(int(item.get("unresolved_obligations", 0)) for item in results)
    errors = [str(item.get("error")) for item in results if item.get("error")]
    by_family: dict[str, int] = {}
    error_classes: dict[str, int] = {}
    for item in results:
        family = str(item.get("family", "legacy"))
        by_family[family] = by_family.get(family, 0) + 1
        error_class = str(item.get("validator_error_class", "none"))
        error_classes[error_class] = error_classes.get(error_class, 0) + 1
    return {
        "task_count": count,
        "closed": closed,
        "closure_rate": _rate(closed, count),
        "parsed": parsed,
        "parse_rate": _rate(parsed, count),
        "validation_failures": validation_failed,
        "validation_failure_rate": _rate(validation_failed, count),
        "attempts": attempts,
        "retries": retries,
        "duration_ms": latency,
        "prompt_chars": prompt_chars,
        "output_chars": output_chars,
        "approx_char_budget": prompt_chars + output_chars,
        "unresolved_obligations": unresolved,
        "errors": errors,
        "family_counts": by_family,
        "error_classes": error_classes,
    }


def _paired_effects(
    baseline: list[dict[str, Any]],
    adaptive: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_by_id = {str(item.get("task_id")): item for item in baseline}
    adaptive_by_id = {str(item.get("task_id")): item for item in adaptive}
    task_ids = sorted(set(baseline_by_id) & set(adaptive_by_id))
    closure_delta = 0
    retry_delta = 0
    unresolved_delta = 0
    duration_delta = 0
    validation_failure_delta = 0
    paired_rows: list[dict[str, Any]] = []
    for task_id in task_ids:
        base = baseline_by_id[task_id]
        adapt = adaptive_by_id[task_id]
        row = {
            "task_id": task_id,
            "closed_delta": int(bool(adapt.get("closed"))) - int(bool(base.get("closed"))),
            "retry_delta": int(adapt.get("retries", 0)) - int(base.get("retries", 0)),
            "unresolved_delta": int(adapt.get("unresolved_obligations", 0))
            - int(base.get("unresolved_obligations", 0)),
            "duration_ms_delta": int(adapt.get("latency_ms", 0)) - int(base.get("latency_ms", 0)),
            "validation_failure_delta": int(adapt.get("validation_passed") is not True)
            - int(base.get("validation_passed") is not True),
        }
        closure_delta += int(row["closed_delta"])
        retry_delta += int(row["retry_delta"])
        unresolved_delta += int(row["unresolved_delta"])
        duration_delta += int(row["duration_ms_delta"])
        validation_failure_delta += int(row["validation_failure_delta"])
        paired_rows.append(row)
    return {
        "paired_task_count": len(task_ids),
        "closure_delta": closure_delta,
        "retry_delta": retry_delta,
        "unresolved_obligation_delta": unresolved_delta,
        "duration_ms_delta": duration_delta,
        "validation_failure_delta": validation_failure_delta,
        "rows": paired_rows,
    }


def _bootstrap_effect_ci(rows: list[dict[str, Any]], *, samples: int = 1000) -> dict[str, Any]:
    if not rows:
        return {
            "samples": 0,
            "closure_delta_rate_bps_ci": [0, 0],
            "validation_failure_delta_rate_bps_ci": [0, 0],
        }
    rng = random.Random(20260508)
    closure_rates: list[int] = []
    validation_rates: list[int] = []
    n = len(rows)
    for _ in range(samples):
        sample = [rows[rng.randrange(n)] for _ in range(n)]
        closure = sum(int(item["closed_delta"]) for item in sample)
        validation = sum(int(item["validation_failure_delta"]) for item in sample)
        closure_rates.append(int(round(10000 * closure / n)))
        validation_rates.append(int(round(10000 * validation / n)))
    closure_rates.sort()
    validation_rates.sort()
    lower = int(samples * 0.025)
    upper = min(samples - 1, int(samples * 0.975))
    return {
        "samples": samples,
        "closure_delta_rate_bps_ci": [closure_rates[lower], closure_rates[upper]],
        "validation_failure_delta_rate_bps_ci": [validation_rates[lower], validation_rates[upper]],
    }


def _oasg_artifacts(adaptive_dir: Path) -> dict[str, Any]:
    gate_statuses: list[str] = []
    watch_statuses: list[str] = []
    supervisor_statuses: list[str] = []
    active_promotions = 0
    rejected = 0
    inconclusive = 0
    pressure_hashes: list[str] = []
    klb_receipt_hashes: list[str] = []
    if adaptive_dir.exists():
        for path in adaptive_dir.rglob("*.json"):
            try:
                data = read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            receipt_type = data.get("receipt_type") if isinstance(data, dict) else None
            status = str(data.get("status")) if isinstance(data, dict) and "status" in data else None
            if receipt_type == "dominance_gate_receipt" and status is not None:
                gate_statuses.append(status)
                if status.startswith("rejected"):
                    rejected += 1
                if status.startswith("inconclusive"):
                    inconclusive += 1
            if receipt_type == "optimizer_watch_receipt" and status is not None:
                watch_statuses.append(status)
            if receipt_type == "optimizer_supervisor_receipt" and status is not None:
                supervisor_statuses.append(status)
            if receipt_type == "active_promotion_receipt":
                active_promotions += 1
            if receipt_type == "pressure_vector":
                pressure_hashes.append(receipt_hash(data))
            if receipt_type == "klb_receipt":
                klb_receipt_hashes.append(receipt_hash(data))
    return {
        "gate_statuses": gate_statuses,
        "watch_statuses": watch_statuses,
        "supervisor_statuses": supervisor_statuses,
        "active_promotion_count": active_promotions,
        "rejected_gate_count": rejected,
        "inconclusive_gate_count": inconclusive,
        "pressure_receipt_hashes": pressure_hashes,
        "klb_receipt_hashes": klb_receipt_hashes,
    }


def _ledger_receipt(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return verify_jsonl(path).to_dict()


def _classify(
    *,
    baseline_summary: dict[str, Any],
    adaptive_summary: dict[str, Any],
    paired: dict[str, Any],
    oasg: dict[str, Any],
) -> str:
    if paired["paired_task_count"] == 0:
        return "inconclusive"
    if baseline_summary["task_count"] == 0 or adaptive_summary["task_count"] == 0:
        return "inconclusive"
    if adaptive_summary["unresolved_obligations"] > baseline_summary["unresolved_obligations"] and (
        paired["closure_delta"] < 0 or paired["validation_failure_delta"] > 0
    ):
        return "regression_observed"
    paired_count = int(paired["paired_task_count"])
    closure_delta_bps = int(round(10000 * int(paired["closure_delta"]) / paired_count))
    baseline_failures = int(baseline_summary["validation_failures"])
    failure_drop = -int(paired["validation_failure_delta"])
    failure_drop_bps = int(round(10000 * failure_drop / max(1, baseline_failures)))
    if closure_delta_bps >= 1500:
        return "improvement_observed"
    if failure_drop_bps >= 2500 and adaptive_summary["unresolved_obligations"] <= baseline_summary[
        "unresolved_obligations"
    ]:
        return "improvement_observed"
    if oasg["active_promotion_count"] == 0 and oasg["rejected_gate_count"] > 0:
        return "no_clear_effect"
    return "no_clear_effect"


def _render_report(metrics: dict[str, Any]) -> str:
    baseline = metrics["baseline_fixed"]
    adaptive = metrics["oasg_adaptive"]
    calibration = metrics["calibration"]
    paired = metrics["paired_effects"]
    oasg = metrics["oasg_artifacts"]
    lines = [
        "# OASG x Ollama gemma4:e4b Pilot Report",
        "",
        f"Classification: `{metrics['classification']}`",
        "",
        "## Preregistered Claim",
        "",
        "This pilot tests whether OASG improves observable workflow operation compared with a fixed non-adaptive workflow. It does not test whether the model became semantically smarter.",
        "",
        "## Condition Summary",
        "",
        "Primary comparison uses held-out evaluation tasks only. Calibration tasks are reported separately.",
        "",
        "| metric | baseline_fixed | oasg_adaptive |",
        "|---|---:|---:|",
        f"| task_count | {baseline['task_count']} | {adaptive['task_count']} |",
        f"| closure_rate | {_format_rate(baseline['closure_rate'])} | {_format_rate(adaptive['closure_rate'])} |",
        f"| validation_failure_rate | {_format_rate(baseline['validation_failure_rate'])} | {_format_rate(adaptive['validation_failure_rate'])} |",
        f"| attempts | {baseline['attempts']} | {adaptive['attempts']} |",
        f"| retries | {baseline['retries']} | {adaptive['retries']} |",
        f"| unresolved_obligations | {baseline['unresolved_obligations']} | {adaptive['unresolved_obligations']} |",
        f"| duration_ms | {baseline['duration_ms']} | {adaptive['duration_ms']} |",
        f"| approx_char_budget | {baseline['approx_char_budget']} | {adaptive['approx_char_budget']} |",
        "",
        "## Calibration Summary",
        "",
        f"- baseline_fixed calibration tasks: `{calibration['baseline_fixed']['task_count']}`",
        f"- oasg_adaptive calibration tasks: `{calibration['oasg_adaptive']['task_count']}`",
        f"- adaptive calibration validation failures: `{calibration['oasg_adaptive']['validation_failures']}`",
        "",
        "## Paired Effects",
        "",
        f"- paired_task_count: `{paired['paired_task_count']}`",
        f"- closure_delta: `{paired['closure_delta']}`",
        f"- retry_delta: `{paired['retry_delta']}`",
        f"- validation_failure_delta: `{paired['validation_failure_delta']}`",
        f"- unresolved_obligation_delta: `{paired['unresolved_obligation_delta']}`",
        f"- duration_ms_delta: `{paired['duration_ms_delta']}`",
        f"- closure_delta_rate_bps_ci: `{paired['bootstrap_ci']['closure_delta_rate_bps_ci']}`",
        f"- validation_failure_delta_rate_bps_ci: `{paired['bootstrap_ci']['validation_failure_delta_rate_bps_ci']}`",
        "",
        "## OASG Receipts",
        "",
        f"- active_promotion_count: `{oasg['active_promotion_count']}`",
        f"- gate_statuses: `{oasg['gate_statuses']}`",
        f"- supervisor_statuses: `{oasg['supervisor_statuses']}`",
        f"- rejected_gate_count: `{oasg['rejected_gate_count']}`",
        f"- inconclusive_gate_count: `{oasg['inconclusive_gate_count']}`",
        "",
        "## Integrity",
        "",
        f"- task_manifest_hash: `{metrics['task_manifest_hash']}`",
        f"- baseline_ledger: `{_ledger_line(metrics, 'baseline_fixed')}`",
        f"- adaptive_ledger: `{_ledger_line(metrics, 'oasg_adaptive')}`",
        "",
        "## Limits",
        "",
    ]
    lines.extend(f"- {item}" for item in metrics["scientific_limits"])
    lines.append("")
    lines.append("All failed, rejected, and inconclusive OASG outcomes are retained in the run directory and included in the summary above.")
    lines.append("")
    return "\n".join(lines)


def _ledger_line(metrics: dict[str, Any], condition: str) -> str:
    receipt = metrics["ledger_receipts"].get(condition)
    if receipt is None:
        return "missing"
    return f"{receipt.get('status')} / {receipt.get('ledger_prefix_hash')}"


def _read_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return read_json(path)
    except (OSError, json.JSONDecodeError):
        return default


def _format_rate(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "0.000"


def _rate(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.000000"
    return f"{numerator / denominator:.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
