"""Local-command trial harness for the long-running OASG/Ollama experiment.

The harness emits promotion evidence only from canary workload outcomes. It is
still an experiment harness, not an external judge: all checks are deterministic
validators over local task outputs.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
SCRIPTS = Path(__file__).resolve().parent
for import_path in (SCRIPTS, SRC, ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from oasg.canonical import domain_hash, receipt_hash  # noqa: E402
from oasg.constants import ACTION_CLASSES, grade_max  # noqa: E402
from oasg.events import event_record, observation_payload  # noqa: E402
from oasg.io import read_json, read_jsonl, write_jsonl  # noqa: E402
from oasg.ledger import seal_records  # noqa: E402
from oasg.policy_state import MutationPatch  # noqa: E402
from oasg.reducers.core import reduce_records  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutation", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--trial-ledger-out", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--recent-metrics")
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args()

    mutation = read_json(Path(args.mutation))
    patch = MutationPatch.from_dict(mutation["patch"])
    seed = reduce_records(read_jsonl(Path(args.candidate)))
    config = read_json(Path(args.config))
    tasks = _select_canaries(read_jsonl(Path(args.tasks)), config, args.recent_metrics)

    if patch.op == "set_action_grade":
        records = _rejection_records(mutation, seed, "set_action_grade_self_evidence_rejected")
    else:
        baseline = _run_canary(tasks, config, patch, candidate=False, mock_model=args.mock_model)
        candidate = _run_canary(tasks, config, patch, candidate=True, mock_model=args.mock_model)
        records = _trial_records(mutation, patch, seed, baseline, candidate)

    out = Path(args.trial_ledger_out)
    write_jsonl(out, records)
    for record in records:
        sys.stdout.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


def _select_canaries(
    tasks: list[dict[str, Any]],
    config: dict[str, Any],
    metrics_path: str | None,
) -> list[dict[str, Any]]:
    count = int(config.get("canary_task_count_warmup", config.get("canary_task_count", 1)))
    preferred_burst: str | None = None
    failed_task_ids: list[str] = []
    dominant_failure_class: str | None = None
    failed_by_error: dict[str, list[str]] = {}
    if metrics_path:
        try:
            metrics = read_json(Path(metrics_path))
            preferred_burst = str(metrics.get("dominant_burst", "")) or None
            dominant_failure_class = str(metrics.get("dominant_failure_class", "")) or None
            failed_task_ids = [str(item) for item in metrics.get("failed_task_ids", [])]
            raw_by_error = metrics.get("failed_task_ids_by_error", {})
            if isinstance(raw_by_error, dict):
                failed_by_error = {
                    str(key): [str(item) for item in value]
                    for key, value in raw_by_error.items()
                    if isinstance(value, list)
                }
        except (OSError, json.JSONDecodeError):
            preferred_burst = None
    warmup_tasks = [task for task in tasks if task.get("phase") == "warmup"]
    task_by_id = {str(task.get("task_id")): task for task in warmup_tasks}
    selected: list[dict[str, Any]] = []

    def add(task: dict[str, Any] | None) -> None:
        if task is None:
            return
        if any(item.get("task_id") == task.get("task_id") for item in selected):
            return
        selected.append(task)

    if dominant_failure_class:
        for task_id in failed_by_error.get(dominant_failure_class, []):
            add(task_by_id.get(task_id))
            if len(selected) >= count:
                return selected
    for task_id in failed_task_ids:
        add(task_by_id.get(task_id))
        if len(selected) >= count:
            return selected
    if preferred_burst:
        for task in warmup_tasks:
            if task.get("burst") == preferred_burst:
                add(task)
                if len(selected) >= count:
                    return selected
    for task in warmup_tasks:
        add(task)
        if len(selected) >= count:
            return selected
    return selected


def _run_canary(
    tasks: list[dict[str, Any]],
    config: dict[str, Any],
    patch: MutationPatch,
    *,
    candidate: bool,
    mock_model: bool,
) -> dict[str, Any]:
    max_attempts = 2 if candidate and patch.op in _retry_like_ops() else 1
    strict = candidate and patch.op in _strict_prompt_ops()
    rows: list[dict[str, Any]] = []
    for task in tasks:
        rows.append(
            _run_task(
                task,
                config,
                max_attempts=max_attempts,
                strict=strict,
                mock_model=mock_model,
                candidate=candidate,
            )
        )
    return _summarize(rows)


def _run_task(
    task: dict[str, Any],
    config: dict[str, Any],
    *,
    max_attempts: int,
    strict: bool,
    mock_model: bool,
    candidate: bool,
) -> dict[str, Any]:
    last_error: str | None = None
    attempts = 0
    prompt_chars = 0
    output_chars = 0
    started = time.perf_counter()
    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        prompt = _prompt_for(task, strict=strict, attempt=attempt, last_error=last_error)
        prompt_chars += len(prompt)
        if mock_model:
            output, call_error = _mock_output(task, strict=strict, candidate=candidate)
        else:
            output, call_error = _call_ollama(config, prompt)
        output_chars += len(output)
        if call_error:
            last_error = call_error
            continue
        parsed, valid, reason = _validate_output(task, output)
        if parsed and valid:
            return {
                "task_id": task["task_id"],
                "closed": True,
                "parsed": True,
                "validation_passed": True,
                "attempts": attempts,
                "retries": max(0, attempts - 1),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "prompt_chars": prompt_chars,
                "output_chars": output_chars,
                "error": None,
            }
        last_error = reason or "validation_failed"
    return {
        "task_id": task["task_id"],
        "closed": False,
        "parsed": not str(last_error or "").startswith("json_parse_failed"),
        "validation_passed": False,
        "attempts": attempts,
        "retries": max(0, attempts - 1),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "prompt_chars": prompt_chars,
        "output_chars": output_chars,
        "error": last_error,
    }


def _prompt_for(
    task: dict[str, Any],
    *,
    strict: bool,
    attempt: int,
    last_error: str | None,
) -> str:
    if not strict and attempt == 1:
        return f"Answer the request concisely.\nRequest: {task['instruction']}\n"
    repair = "" if attempt == 1 else f"\nPrevious validator error: {last_error}\n"
    return (
        "Return exactly one minified JSON object. Do not use Markdown or prose.\n"
        f"{_family_rule(str(task['family']))}\n"
        f"{repair}Task: {task['instruction']}\n"
    )


def _call_ollama(config: dict[str, Any], prompt: str) -> tuple[str, str | None]:
    body = {
        "model": config["model"],
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": int(config.get("temperature", 0))},
    }
    request = Request(
        f"{str(config['ollama_endpoint']).rstrip('/')}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(
            request,
            timeout=int(config.get("ollama_timeout_seconds", config["timeout_seconds"])),
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return "", f"ollama_call_failed:{exc}"
    return str(payload.get("response", "")), None


def _mock_output(task: dict[str, Any], *, strict: bool, candidate: bool) -> tuple[str, str | None]:
    if not strict and not candidate:
        return "Here is the answer: not json", None
    if task["validator"] == "python_expr":
        return json.dumps({"expression": str(task["expected_value"])}), None
    if "expected" in task:
        return json.dumps(task["expected"], sort_keys=True), None
    return json.dumps({"status": "ok"}), None


def _validate_output(task: dict[str, Any], output: str) -> tuple[bool, bool, str | None]:
    try:
        parsed = json.loads(_extract_json(output))
    except (json.JSONDecodeError, ValueError) as exc:
        return False, False, f"json_parse_failed:{exc}"
    validator = str(task["validator"])
    if validator == "json_equals":
        passed = parsed == task["expected"]
        return True, passed, None if passed else "json_not_equal"
    if validator == "json_schema":
        return _validate_schema(parsed, task["schema"], task.get("expected"))
    if validator == "python_expr":
        if not isinstance(parsed, dict) or "expression" not in parsed:
            return True, False, "missing_expression"
        return _validate_expr(str(parsed["expression"]), task["expected_value"])
    return True, False, f"unknown_validator:{validator}"


def _extract_json(output: str) -> str:
    stripped = output.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    return stripped[start : end + 1]


def _validate_schema(
    parsed: Any,
    schema: dict[str, str],
    expected: dict[str, Any] | None,
) -> tuple[bool, bool, str | None]:
    if not isinstance(parsed, dict):
        return True, False, "not_object"
    for key, type_name in schema.items():
        if key not in parsed:
            return True, False, f"missing_key:{key}"
        if type_name == "string" and not isinstance(parsed[key], str):
            return True, False, f"type_mismatch:{key}"
        if type_name == "integer" and not isinstance(parsed[key], int):
            return True, False, f"type_mismatch:{key}"
        if type_name == "boolean" and not isinstance(parsed[key], bool):
            return True, False, f"type_mismatch:{key}"
    if expected is not None and parsed != expected:
        return True, False, "schema_values_mismatch"
    return True, True, None


def _validate_expr(expression: str, expected_value: Any) -> tuple[bool, bool, str | None]:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        return True, False, f"expr_syntax:{exc.msg}"
    allowed = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Load,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            return True, False, f"expr_disallowed_node:{type(node).__name__}"
    try:
        value = eval(compile(tree, "<oasg-longrun-expr>", "eval"), {"__builtins__": {}}, {})
    except Exception as exc:  # noqa: BLE001
        return True, False, f"expr_eval_failed:{exc}"
    return True, value == expected_value, None if value == expected_value else "expr_wrong_value"


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    validation_failures = sum(1 for row in rows if row["validation_passed"] is not True)
    parse_failures = sum(1 for row in rows if row["parsed"] is not True)
    unresolved = sum(0 if row["closed"] else 1 for row in rows)
    retries = sum(int(row["retries"]) for row in rows)
    return {
        "rows": rows,
        "task_count": len(rows),
        "closed": sum(1 for row in rows if row["closed"]),
        "validation_failures": validation_failures,
        "parse_failures": parse_failures,
        "unresolved_obligations": unresolved,
        "retries": retries,
        "debt": validation_failures + parse_failures + unresolved + retries,
        "latency_ms": sum(int(row["latency_ms"]) for row in rows),
        "prompt_chars": sum(int(row["prompt_chars"]) for row in rows),
        "output_chars": sum(int(row["output_chars"]) for row in rows),
    }


def _trial_records(
    mutation: dict[str, Any],
    patch: MutationPatch,
    seed: Any,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    debt_delta = int(candidate["debt"]) - int(baseline["debt"])
    supports = debt_delta < 0 and int(candidate["unresolved_obligations"]) <= int(
        baseline["unresolved_obligations"]
    )
    if not supports:
        return _rejection_records(mutation, seed, "no_observed_trial_improvement")

    coordinate = patch.coordinate_id
    evidence_coordinates = _evidence_coordinates(coordinate, patch, baseline, candidate)
    if coordinate not in evidence_coordinates:
        return _rejection_records(mutation, seed, "patch_specific_evidence_not_supported")
    action_grades = dict(seed.action_grades)
    action_grades[patch.target_action_id] = grade_max(
        action_grades.get(patch.target_action_id, "blocked"),
        "surplus",
    )
    evidence_hash = domain_hash(
        "OASG:v1.0:ollama_longrun_trial",
        str(mutation["mutation_id"]),
        patch.op,
        patch.target_action_id,
        coordinate,
        receipt_hash({"baseline": baseline, "candidate": candidate}),
    )
    proof_receipts = [
        {
            "receipt_type": "patch_specific_evidence_receipt",
            "coordinate": item,
            "status": "receipt_valid",
            "patch_op": patch.op,
            "target_action_id": patch.target_action_id,
            "baseline_debt": str(baseline["debt"]),
            "candidate_debt": str(candidate["debt"]),
            "trial_hash": receipt_hash({"baseline": baseline, "candidate": candidate}),
        }
        for item in evidence_coordinates
    ]
    positive_evidence = [
        {"coordinate": item, "evidence_hash": evidence_hash} for item in evidence_coordinates
    ]
    records = [
        event_record(
            event_id=f"evt_longrun_trial_{mutation['mutation_id']}",
            workflow_id="ollama_gemma4_e4b_longrun_trial",
            component_id="workflow_policy",
            event_type="observation",
            payload=observation_payload(
                dimensions=_supported_dimensions(seed, evidence_coordinates),
                action_grades=action_grades,
                protected_debt=_supported_protected_debt(seed, evidence_coordinates),
                proof_obligation_receipts=proof_receipts,
                positive_evidence=positive_evidence,
                policy={
                    "effect_classes": ["pure"],
                    "semantic_scope": "operational_only",
                    "claim_emitting": False,
                    "taint_level": "public",
                    "boundary_status": "valid",
                    "trusted_base_status": "valid",
                    "workflow_promotion_authorized": False,
                },
                model_event={
                    "runner_type": "local-command",
                    "trial_mode": "ollama_longrun_canary",
                    "patch_op": patch.op,
                    "target_action_id": patch.target_action_id,
                    "observed_improvement_coordinate": coordinate,
                    "baseline_debt": baseline["debt"],
                    "candidate_debt": candidate["debt"],
                    "pressure_delta": debt_delta,
                    "queue_age_delta": -1
                    if candidate["unresolved_obligations"] < baseline["unresolved_obligations"]
                    else 0,
                    "retry_delta": candidate["retries"] - baseline["retries"],
                    "validation_debt_delta": candidate["validation_failures"]
                    - baseline["validation_failures"],
                    "evidence_gap_delta": candidate["parse_failures"] - baseline["parse_failures"],
                    "budget_delta": candidate["prompt_chars"] - baseline["prompt_chars"],
                    "rollback_receipt_delta": 1
                    if patch.op in {"set_rollback_requirement", "set_lease_cap"}
                    else 0,
                    "rollback_receipt_available": patch.op
                    in {"set_rollback_requirement", "set_lease_cap"},
                    "semantic_floor_delta": 1 if patch.op == "set_semantic_floor" else 0,
                    "canary_task_count": candidate["task_count"],
                    "baseline_canary_rows": baseline["rows"],
                    "candidate_canary_rows": candidate["rows"],
                    "evidence_coordinates": evidence_coordinates,
                },
            ),
        )
    ]
    return seal_records(records)


def _supported_dimensions(seed: Any, evidence_coordinates: list[str]) -> dict[str, str]:
    dimensions = dict(seed.dimensions)
    for coordinate in evidence_coordinates:
        if coordinate in dimensions:
            dimensions[coordinate] = "acceptable"
    return dimensions


def _supported_protected_debt(seed: Any, evidence_coordinates: list[str]) -> dict[str, str]:
    protected = dict(seed.protected_debt)
    for coordinate in evidence_coordinates:
        if coordinate.startswith("protected_debt."):
            key = coordinate.split(".", 1)[1]
            if key in protected:
                protected[key] = "acceptable"
    return protected


def _rejection_records(mutation: dict[str, Any], seed: Any, reason: str) -> list[dict[str, Any]]:
    records = [
        event_record(
            event_id=f"evt_longrun_trial_rejected_{mutation.get('mutation_id', 'unknown')}",
            workflow_id="ollama_gemma4_e4b_longrun_trial",
            component_id="workflow_policy",
            event_type="observation",
            payload=observation_payload(
                dimensions=dict(seed.dimensions),
                action_grades=dict(seed.action_grades)
                or {action: "acceptable" for action in ACTION_CLASSES},
                protected_debt={
                    **dict(seed.protected_debt),
                    "comparison": "critical",
                },
                model_event={
                    "runner_type": "local-command",
                    "trial_mode": "ollama_longrun_canary",
                    "rejection_reason": reason,
                },
            ),
        )
    ]
    return seal_records(records)


def _evidence_coordinates(
    primary: str,
    patch: MutationPatch,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    coordinates: set[str] = set()
    if int(candidate["unresolved_obligations"]) < int(baseline["unresolved_obligations"]):
        if patch.op in {"set_retry_policy", "set_decomposition_depth", "set_routing_policy"}:
            coordinates.update({"queue", "protected_debt.queue", "KLB_2.close_obligation"})
    if int(candidate["validation_failures"]) < int(baseline["validation_failures"]):
        if patch.op in {"set_validator_policy", "set_semantic_floor", "set_routing_policy"}:
            coordinates.update({"evidence", "protected_debt.evidence", "KLB_2.validate_artifact"})
    if int(candidate["parse_failures"]) < int(baseline["parse_failures"]):
        if patch.op in {"set_context_compression", "set_validator_policy", "set_routing_policy"}:
            coordinates.update({"evidence", "protected_debt.evidence", "KLB_2.validate_artifact"})
    candidate_chars = int(candidate["prompt_chars"]) + int(candidate["output_chars"])
    baseline_chars = int(baseline["prompt_chars"]) + int(baseline["output_chars"])
    if candidate_chars < baseline_chars and patch.op in {"set_context_compression", "adjust_charge"}:
        coordinates.update({"budget", "protected_debt.budget"})
    if patch.op in {"set_rollback_requirement", "set_lease_cap"}:
        coordinates.add("KLB_2.rollback_local_effect")
    if primary in coordinates:
        coordinates.add(primary)
    return sorted(coordinates)


def _retry_like_ops() -> set[str]:
    return {
        "set_retry_policy",
        "set_validator_policy",
        "set_context_compression",
        "set_routing_policy",
        "set_decomposition_depth",
    }


def _strict_prompt_ops() -> set[str]:
    return _retry_like_ops() | {
        "set_rollback_requirement",
        "set_lease_cap",
        "set_semantic_floor",
        "adjust_charge",
        "remove_requirement",
    }


def _family_rule(family: str) -> str:
    if family == "safe_python_expression":
        return "For expression tasks, use only literals and arithmetic operators."
    if family == "json_schema_repair":
        return "For schema tasks, include every required key with exact requested values."
    if family == "validator_receipt":
        return "For receipt tasks, use JSON booleans and integers, not strings."
    if family == "code_transform":
        return "For transform tasks, compute the requested identifier exactly."
    if family == "obligation_closure":
        return "For obligation tasks, close the obligation and set remaining to 0."
    return "For replay and rollback tasks, include both receipt fields exactly."


if __name__ == "__main__":
    raise SystemExit(main())
