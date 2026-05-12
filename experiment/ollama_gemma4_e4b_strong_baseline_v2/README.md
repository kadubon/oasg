# OASG x Ollama `gemma4:e4b` Strong-Baseline v2 Protocol

This profile tests whether OASG can add measurable workflow-operation value after starting from a
calibration-selected strong static workflow policy. It improves on the first strong-baseline
protocol by requiring an explicit incremental-headroom stage before spending compute on held-out
evaluation.

The claim is limited to local `gemma4:e4b`, this OASG implementation, the frozen workload, and the
predefined thresholds in `config_strong_baseline_v2.json`.

## Stages

1. `Stage 0`: qualify a strong static baseline from calibration tasks only.
2. `Stage 1`: check whether any candidate can improve debt or cost-to-close over that strong
   baseline on preregistered calibration canaries. Stage 1 uses
   `incremental_policy_catalog.json`, which is separate from the Stage 0 strong-baseline catalog.
3. `Stage 2`: allow OASG readiness only for Stage 1 qualified incremental candidates.
4. `Stage 3`: run held-out paired evaluation only if OASG readiness passes.

If Stage 1 finds no debt or efficiency headroom, the run stops as
`strong_baseline_ceiling_no_headroom`. If Stage 2 cannot active-promote in the required number of
seeds, the run stops as `promotion_mechanism_failure_vs_strong_baseline`.

The v2 incremental catalog intentionally includes policies aimed at residual strong-baseline
failure modes observed in the first strong-baseline run, especially `code_transform` exact
identifier receipts and replay/rollback exact receipt templates. These policies are not available
to Stage 0 strong-static selection, so any Stage 1 success measures incremental headroom over the
frozen strong baseline rather than rebuilding the baseline itself.

If calibration does not expose debt for a family, v2 fills the strong static policy with
preregistered defaults from `strong_static_default_policy_by_family`. This prevents an apparently
"strong" baseline from leaving whole families on the weak fixed policy just because calibration did
not happen to trigger that failure mode.

## Classifications

- `oasg_debt_effect_confirmed_vs_strong_baseline`
- `oasg_efficiency_effect_confirmed_vs_strong_baseline`
- `no_incremental_effect_vs_strong_baseline`
- `promotion_mechanism_failure_vs_strong_baseline`
- `strong_baseline_ceiling_no_headroom`
- `workload_not_sensitive`
- `regression_observed`
- `invalid_run`
- `exploratory_only`

## Current Real Result

Latest completed run: `20260511T231627Z`

Final classification: `no_incremental_effect_vs_strong_baseline`

This run is scientifically useful because it passed all preregistered pre-evaluation gates:

- Stage 0 strong baseline qualification: `strong_baseline_qualified`
- Stage 1 incremental headroom: `debt_headroom_exists`
- Stage 2 adaptive readiness: `adaptive_from_strong_ready`
- Stage 3 held-out paired evaluation: completed

The held-out evaluation did not show incremental OASG value over the strong static baseline.

| condition | tasks | closed | debt AUC | cost units | parse failures | validation failures | hard-floor regressions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `strong_static_calibrated` | 680 | 463 | 434 | 1580136 | 0 | 217 | 0 |
| `strong_rule_adaptive_control` | 680 | 463 | 440 | 1602751 | 6 | 217 | 0 |
| `strong_positive_control` | 680 | 463 | 434 | 1575900 | 0 | 217 | 0 |
| `oasg_adaptive_from_strong` | 680 | 463 | 436 | 1587788 | 2 | 217 | 0 |

Primary comparison, `oasg_adaptive_from_strong` vs `strong_static_calibrated`:

- Debt AUC delta: `+2`
- Debt bootstrap CI: `[0, 5]`
- Cost-to-close delta: `+7652`
- Cost bootstrap CI: `[1534, 14346]`
- Closure delta: `0`
- Hard-floor regressions: `0`

Interpretation: OASG readiness succeeded, but the promoted changes did not transfer into a
held-out improvement over the calibrated strong static workflow. This is negative evidence for
incremental value over this strong baseline, not a universal negative result for OASG.

Curated public artifacts are in [`results/`](results/):

- [`results/report.md`](results/report.md)
- [`results/metrics.json`](results/metrics.json)
- [`results/verification.json`](results/verification.json)
- [`results/final_strong_v2_classification_receipt.json`](results/final_strong_v2_classification_receipt.json)

## Commands

```powershell
uv sync
ollama list
uv run python experiment\ollama_gemma4_e4b_strong_baseline_v2\scripts\run_strong_baseline_v2_experiment.py --config experiment\ollama_gemma4_e4b_strong_baseline_v2\config_strong_baseline_v2.json
uv run python experiment\ollama_gemma4_e4b_strong_baseline_v2\scripts\analyze_strong_baseline_v2_results.py --run-dir experiment\ollama_gemma4_e4b_strong_baseline_v2\runs\latest --out experiment\ollama_gemma4_e4b_strong_baseline_v2\results
```

Mock smoke test:

```powershell
uv run python experiment\ollama_gemma4_e4b_strong_baseline_v2\scripts\run_strong_baseline_v2_experiment.py --config experiment\ollama_gemma4_e4b_strong_baseline_v2\config_strong_baseline_v2.json --mock-model
```

Effect is claimed only when all preregistered stages pass and the final classification is one of
the two confirmed-effect classifications.
