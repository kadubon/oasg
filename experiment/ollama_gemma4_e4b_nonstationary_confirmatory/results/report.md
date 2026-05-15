# OASG Nonstationary Confirmatory Experiment Report

Final classification: `mixed_reversion_only_effect`

## Scientific Question

Does OASG adaptive workflow-policy promotion still show post-drift recovery over a Phase-A-calibrated strong static workflow when the prior positive result is replicated across larger variants and ablations?

This protocol does not test whether OASG is strong for nonstationarity in general. It tests whether this implementation shows receipt-backed recovery within the frozen drift classes below.

## Integrity Summary

- Verification: `ok`.
- Completed variants: `delayed_drift_recovery, full_drift_confirmatory, mixed_reversion_only_probe, no_mixed_reversion_ablation`.
- Primary paired post-drift tasks: `600`.
- Active post-drift OASG seeds: `5`.
- Stable A2 active mutation rows: `0`.

## Primary Comparison

- `oasg_adaptive_from_strong` vs `strong_static_calibrated`: debt delta `-172`, debt CI `[-225, -126]`, cost delta `-87081`, cost CI `[-104847, -69824]`.
- OASG vs observe-only: debt delta `-172`, CI `[-225, -124]`.
- OASG vs rule-adaptive: debt delta `-98`, CI `[-164, -23]`.

## Ablation Summary

- No-Phase-D aggregate: `-54` debt delta, CI `[-83, -29]`.
- Mixed-reversion-only aggregate: `-118` debt delta, CI `[-158, -78]`.
- Structural-only aggregate: `-4` debt delta, CI `[-12, 0]`.
- Mild-only aggregate: `-50` debt delta, CI `[-72, -28]`.

## Drift-Class Effects

- Interpretation label: `mixed_reversion_or_retirement_specific_support`.
- `delayed_stable`: debt delta `0`, reduction `0` bps, CI `[0, 0]`, cost delta `54`.
- `mild`: debt delta `-50`, reduction `1562` bps, CI `[-76, -28]`, cost delta `-9977`.
- `mixed`: debt delta `-118`, reduction `1639` bps, CI `[-158, -78]`, cost delta `-50893`.
- `structural`: debt delta `-4`, reduction `83` bps, CI `[-12, 0]`, cost delta `-26211`.

## Cost And Retirement

- Primary cost-to-close delta: `-87081`, CI `[-104847, -69824]`.
- Active retirement/tightening rows: `9`.
- Mixed retirement/tightening rows: `5`.

## Scientific Interpretation

The primary comparison favors OASG, but the ablation contract narrows the effect to mixed reversion or policy-retirement-sensitive drift rather than broad confirmatory nonstationary support.

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
