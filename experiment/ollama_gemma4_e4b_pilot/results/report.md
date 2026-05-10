# OASG x Ollama gemma4:e4b Pilot Report

Classification: `no_clear_effect`

## Preregistered Claim

This pilot tests whether OASG improves observable workflow operation compared with a fixed non-adaptive workflow. It does not test whether the model became semantically smarter.

## Condition Summary

| metric | baseline_fixed | oasg_adaptive |
|---|---:|---:|
| task_count | 12 | 12 |
| closure_rate | 0.667 | 0.667 |
| validation_failure_rate | 0.333 | 0.333 |
| attempts | 12 | 12 |
| retries | 0 | 0 |
| unresolved_obligations | 4 | 4 |
| duration_ms | 49403 | 25256 |
| approx_char_budget | 3666 | 3666 |

## Paired Effects

- paired_task_count: `12`
- closure_delta: `0`
- retry_delta: `0`
- validation_failure_delta: `0`
- unresolved_obligation_delta: `0`
- duration_ms_delta: `-24147`

## OASG Receipts

- active_promotion_count: `0`
- gate_statuses: `['safe_non_regression', 'rejected_floor_violation', 'safe_non_regression']`
- supervisor_statuses: `['no_valid_candidate', 'no_valid_candidate', 'no_valid_candidate']`
- rejected_gate_count: `1`
- inconclusive_gate_count: `0`

## Integrity

- task_manifest_hash: `sha256:fcf1a95a5b1ac86d7616c14ac34e8239386d275aa76547f2fc2c89350c91b3ba`
- baseline_ledger: `ledger_prefix_valid / sha256:ff60b508326b3c9ebdf834ef422330cadfffc5fc20b293db057613b7f3a842c0`
- adaptive_ledger: `ledger_prefix_valid / sha256:d64b29db28b86a881bf3e565697b43507deddcc734253abe36bad2fb9d2844aa`

## Limits

- One-hour pilot scale; no strong statistical claim.
- Deterministic validators measure operational closure, not semantic truth.
- OASG optimization is workflow-policy adaptation only; model weights are unchanged.
- No LLM judge or external correctness oracle is used.

All failed, rejected, and inconclusive OASG outcomes are retained in the run directory and included in the summary above.
