# OASG Nonstationary Confirmatory Experiment Report

Final classification: `inconclusive_insufficient_power`

## Scientific Question

Does OASG adaptive workflow-policy promotion still show post-drift recovery over a Phase-A-calibrated strong static workflow when the prior positive result is replicated across larger variants and ablations?

This protocol does not test whether OASG is strong for nonstationarity in general. It tests whether this implementation shows receipt-backed recovery within the frozen drift classes below.

## Integrity Summary

- Verification: `ok`.
- Completed variants: `delayed_drift_recovery, full_drift_confirmatory, mixed_reversion_only_probe, no_mixed_reversion_ablation`.
- Primary paired post-drift tasks: `20`.
- Active post-drift OASG seeds: `1`.
- Stable A2 active mutation rows: `0`.

## Primary Comparison

- `oasg_adaptive_from_strong` vs `strong_static_calibrated`: debt delta `-12`, debt CI `[-24, -4]`, cost delta `194`, cost CI `[0, 482]`.
- OASG vs observe-only: debt delta `-12`, CI `[-24, 0]`.
- OASG vs rule-adaptive: debt delta `0`, CI `[0, 0]`.

## Ablation Summary

- No-Phase-D aggregate: `0` debt delta, CI `[0, 0]`.
- Mixed-reversion-only aggregate: `-12` debt delta, CI `[-20, 0]`.
- Structural-only aggregate: `0` debt delta, CI `[0, 0]`.
- Mild-only aggregate: `0` debt delta, CI `[0, 0]`.

## Drift-Class Effects

- Interpretation label: `mixed_reversion_or_retirement_specific_support`.
- `delayed_stable`: debt delta `0`, reduction `0` bps, CI `[0, 0]`, cost delta `0`.
- `mild`: debt delta `0`, reduction `0` bps, CI `[0, 0]`, cost delta `0`.
- `mixed`: debt delta `-12`, reduction `3750` bps, CI `[-20, -4]`, cost delta `194`.
- `structural`: debt delta `0`, reduction `0` bps, CI `[0, 0]`, cost delta `0`.

## Cost And Retirement

- Primary cost-to-close delta: `194`, CI `[0, 482]`.
- Active retirement/tightening rows: `0`.
- Mixed retirement/tightening rows: `0`.

## Scientific Interpretation

The run is a protocol or diagnostic run and does not justify a confirmatory claim.

## Claims Not Supported

- This is not evidence that the model became more intelligent.
- This is not a universal OASG effectiveness proof.
- The oracle control is not a deployable baseline.
- Mock/small results are wiring checks only.

## Public Artifacts

- `metrics.json`
- `verification.json`
- `classification_receipt.json`
- `no_leakage_receipt.json`
- `oracle_headroom_receipt.json`
- `adaptation_lag_receipt.json`
- `ablation_receipt.json`
- `drift_class_effect_receipt.json`
- `retirement_effect_receipt.json`
- `variant_table.csv`, `phase_table.csv`, `seed_table.csv`, `epoch_table.csv`
- `paired_task_table.csv`

## Reproduction

```powershell
uv sync
uv run python experiment\ollama_gemma4_e4b_nonstationary_confirmatory\scripts\run_confirmatory_experiment.py --config experiment\ollama_gemma4_e4b_nonstationary_confirmatory\config_confirmatory_small.json --mock-model --all-variants
uv run python experiment\ollama_gemma4_e4b_nonstationary_confirmatory\scripts\analyze_confirmatory_results.py --run-dir experiment\ollama_gemma4_e4b_nonstationary_confirmatory\runs\latest --out experiment\ollama_gemma4_e4b_nonstationary_confirmatory\results
```
