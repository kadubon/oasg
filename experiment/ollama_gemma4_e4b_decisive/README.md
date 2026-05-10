# OASG x Ollama `gemma4:e4b` Decisive Effect Protocol

This profile tests whether this OASG implementation improves long-running
workflow operation for a frozen local workload. It does not test model
intelligence, semantic truth in general, or universal OASG validity.

The decisive change from the previous profile is Stage 0 policy qualification:
candidate workflow policies are evaluated one at a time, by family, before OASG
is asked to discover and promote them. If no forced policy improves calibration
debt, the run stops as `workload_not_sensitive`.

## Classifications

- `oasg_effect_confirmed`
- `no_practical_oasg_effect`
- `promotion_mechanism_failure`
- `workload_not_sensitive`
- `regression_observed`
- `invalid_run`
- `exploratory_only`

## Commands

```powershell
cd path\to\oasg
uv sync
ollama list
uv run python experiment\ollama_gemma4_e4b_decisive\scripts\run_decisive_experiment.py --config experiment\ollama_gemma4_e4b_decisive\config_decisive.json
uv run python experiment\ollama_gemma4_e4b_decisive\scripts\analyze_decisive_results.py --run-dir experiment\ollama_gemma4_e4b_decisive\runs\latest --out experiment\ollama_gemma4_e4b_decisive\results
```

Mock smoke test:

```powershell
uv run python experiment\ollama_gemma4_e4b_decisive\scripts\run_decisive_experiment.py --config experiment\ollama_gemma4_e4b_decisive\config_decisive.json --mock-model
```

Effect is claimed only when the final classification is `oasg_effect_confirmed`.
