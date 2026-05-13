# OASG Nonstationary Strong-Baseline Report

Classification: `oasg_nonstationary_effect_confirmed_timeboxed`

This protocol tests time-ordered workflow drift response, not model intelligence.
It asks whether OASG can recover post-drift operational performance from observable
history while staying fail-closed about promotion.

## Integrity

- Verification status: `ok`
- Paired post-drift task count: `48`
- Metrics hash: `sha256:e6eaf03f0949d71eac9de24602b487d6534642657c6883cd86bdb15fdec891db`

## No-Leakage Statement

Strong static calibration uses Phase A only. Primary metrics exclude Phase A. OASG adaptive
may use only prior online observations. Oracle phase control is non-deployable and excluded
from the primary comparison.

## Workload Drift

- Phase A: pre-drift calibration only.
- Phase B: schema-key aliases and stricter JSON formatting.
- Phase C: receipt, obligation, safe-expression, evidence, and rollback shifts.
- Phase D: mixed old/new requirements to test overfitting and retirement value.

The drift is deterministic and encoded in the frozen task manifest. This is a controlled
operational-workflow drift, not random benchmark noise.

## Controls

- `strong_static_calibrated`: deployable static policy chosen from Phase A only.
- `oasg_observe_only_from_strong`: same initial policy with OASG observation but no promotion.
- `rule_adaptive_control`: simple recent-failure heuristic without OASG promotion receipts.
- `strong_static_oracle_phase_control`: non-deployable phase-knowledge probe for headroom.

## Condition Summaries

| condition | tasks | closed | debt AUC | cost units | hard-floor regressions |
| --- | ---: | ---: | ---: | ---: | ---: |
| `strong_static_calibrated` | 48 | 20 | 112 | 148517 | 0 |
| `oasg_observe_only_from_strong` | 48 | 20 | 113 | 157085 | 0 |
| `rule_adaptive_control` | 48 | 20 | 114 | 163308 | 0 |
| `oasg_adaptive_from_strong` | 48 | 27 | 84 | 137059 | 0 |

## Primary Comparison

- Candidate: `oasg_adaptive_from_strong`
- Baseline: `strong_static_calibrated`
- Debt AUC delta: `-28`
- Debt bootstrap CI: `[-51, -10]`
- Cost-to-close delta: `-11458`
- Cost bootstrap CI: `[-31074, 7272]`
- Adaptation lag: `{'phase_b_mild_drift': 1, 'phase_c_structural_drift': 0, 'phase_d_mixed_reversion': 0}`

## Secondary Comparisons

- OASG vs observe-only debt delta: `-29`; CI `[-52, -11]`.
- OASG vs rule-adaptive debt delta: `-30`; CI `[-50, -12]`.

## Phase-Wise Results

| phase | condition | tasks | closed | debt AUC | cost units | active mutations |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `phase_b_mild_drift` | `strong_static_calibrated` | 16 | 4 | 48 | 52255 | 0 |
| `phase_b_mild_drift` | `oasg_observe_only_from_strong` | 16 | 4 | 49 | 55896 | 0 |
| `phase_b_mild_drift` | `rule_adaptive_control` | 16 | 4 | 48 | 50194 | 0 |
| `phase_b_mild_drift` | `oasg_adaptive_from_strong` | 16 | 4 | 48 | 50358 | 3 |
| `phase_c_structural_drift` | `strong_static_calibrated` | 16 | 7 | 36 | 55413 | 0 |
| `phase_c_structural_drift` | `oasg_observe_only_from_strong` | 16 | 7 | 36 | 59766 | 0 |
| `phase_c_structural_drift` | `rule_adaptive_control` | 16 | 4 | 49 | 60060 | 0 |
| `phase_c_structural_drift` | `oasg_adaptive_from_strong` | 16 | 8 | 32 | 46893 | 4 |
| `phase_d_mixed_reversion` | `strong_static_calibrated` | 16 | 9 | 28 | 40849 | 0 |
| `phase_d_mixed_reversion` | `oasg_observe_only_from_strong` | 16 | 9 | 28 | 41423 | 0 |
| `phase_d_mixed_reversion` | `rule_adaptive_control` | 16 | 12 | 17 | 53054 | 0 |
| `phase_d_mixed_reversion` | `oasg_adaptive_from_strong` | 16 | 15 | 4 | 39808 | 5 |

## Claims Supported

- A positive OASG effect is supported only when the final classification is
  `oasg_nonstationary_effect_confirmed_timeboxed`.
- The claim, if present, is limited to this model, task distribution, implementation,
  thresholds, and time-boxed protocol.

## Claims Not Supported

- This experiment does not test model-weight improvement.
- It does not use or validate an LLM judge.
- It does not prove universal OASG effectiveness.
- Negative or inconclusive classifications remain valid evidence and are not hidden.

## Public Artifacts

- `metrics.json`
- `verification.json`
- `phase_table.csv`
- `seed_table.csv`
- `epoch_table.csv`
- `paired_task_table.csv`
- `final_nonstationary_classification_receipt.json`

## Reproduction

```powershell
uv run python experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\scripts\run_nonstationary_experiment.py --config experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\config_nonstationary.json
uv run python experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\scripts\analyze_nonstationary_results.py --run-dir experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\runs\latest --out experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\results
```

## Scientific Interpretation

Effect is claimed only for `oasg_nonstationary_effect_confirmed_timeboxed`. Other
classifications are negative or inconclusive evidence for this implementation, workload,
model, and threshold set. They are not universal conclusions about OASG.
