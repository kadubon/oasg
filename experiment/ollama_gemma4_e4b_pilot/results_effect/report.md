# OASG x Ollama gemma4:e4b Pilot Report

Classification: `no_clear_effect`

## Preregistered Claim

This pilot tests whether OASG improves observable workflow operation compared with a fixed non-adaptive workflow. It does not test whether the model became semantically smarter.

## Condition Summary

Primary comparison uses held-out evaluation tasks only. Calibration tasks are reported separately.

| metric | baseline_fixed | oasg_adaptive |
|---|---:|---:|
| task_count | 48 | 48 |
| closure_rate | 0.542 | 0.542 |
| validation_failure_rate | 0.458 | 0.458 |
| attempts | 48 | 48 |
| retries | 0 | 0 |
| unresolved_obligations | 22 | 22 |
| duration_ms | 1626059 | 1593919 |
| approx_char_budget | 12639 | 12639 |

## Calibration Summary

- baseline_fixed calibration tasks: `12`
- oasg_adaptive calibration tasks: `12`
- adaptive calibration validation failures: `5`

## Paired Effects

- paired_task_count: `48`
- closure_delta: `0`
- retry_delta: `0`
- validation_failure_delta: `0`
- unresolved_obligation_delta: `0`
- duration_ms_delta: `-32140`
- closure_delta_rate_bps_ci: `[0, 0]`
- validation_failure_delta_rate_bps_ci: `[0, 0]`

## OASG Receipts

- active_promotion_count: `0`
- gate_statuses: `['safe_non_regression', 'safe_non_regression', 'safe_non_regression', 'safe_non_regression', 'safe_non_regression', 'safe_non_regression']`
- supervisor_statuses: `['no_valid_candidate', 'no_valid_candidate']`
- rejected_gate_count: `0`
- inconclusive_gate_count: `0`

## Integrity

- task_manifest_hash: `sha256:49789db14741fcd6db0e60b59d736ab5fbe8ddf6fea6a2ed6273381c217f4a0a`
- baseline_ledger: `ledger_prefix_valid / sha256:cc2edb1137b641923fc36803dbb458df8a2c345e3eacb8188aef7d261d5e4ca6`
- adaptive_ledger: `ledger_prefix_valid / sha256:6685963eab2c776d0152658393aaff4f81c3db3097493249e6343cdfdb92c317`

## Limits

- One-hour pilot scale; no strong statistical claim.
- Deterministic validators measure operational closure, not semantic truth.
- OASG optimization is workflow-policy adaptation only; model weights are unchanged.
- No LLM judge or external correctness oracle is used.

All failed, rejected, and inconclusive OASG outcomes are retained in the run directory and included in the summary above.
