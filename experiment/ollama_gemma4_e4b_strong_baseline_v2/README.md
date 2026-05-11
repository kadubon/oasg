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
   baseline on calibration canaries.
3. `Stage 2`: allow OASG readiness only for Stage 1 qualified incremental candidates.
4. `Stage 3`: run held-out paired evaluation only if OASG readiness passes.

If Stage 1 finds no debt or efficiency headroom, the run stops as
`strong_baseline_ceiling_no_headroom`. If Stage 2 cannot active-promote in the required number of
seeds, the run stops as `promotion_mechanism_failure_vs_strong_baseline`.

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
