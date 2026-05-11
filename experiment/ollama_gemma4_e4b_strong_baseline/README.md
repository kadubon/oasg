# OASG x Ollama `gemma4:e4b` Strong-Baseline Protocol

This profile tests a narrower claim than the decisive experiment:

> Does OASG produce additional workflow-operation improvement after starting from a
> calibration-selected strong static workflow policy?

It does not test model intelligence, universal OASG effectiveness, or semantic truth in general.
The claim is limited to local `gemma4:e4b`, this implementation, the frozen workload, and the
predefined decision thresholds.

## Conditions

- `weak_fixed`: weak fixed workflow, reference only.
- `observe_only`: strong static policy with observation but no promotion.
- `strong_static_calibrated`: best policy per family selected only from calibration tasks.
- `strong_rule_adaptive_control`: simple non-OASG policy switch by burst/failure class.
- `oasg_adaptive_from_strong`: starts from the same strong static policy and applies only
  trial-backed OASG policy changes.

## Classifications

- `oasg_incremental_effect_confirmed_vs_strong_baseline`
- `partial_incremental_support`
- `no_incremental_effect_vs_strong_baseline`
- `rule_baseline_sufficient`
- `promotion_mechanism_failure_vs_strong_baseline`
- `workload_not_sensitive`
- `regression_observed`
- `invalid_run`
- `exploratory_only`

## Commands

```powershell
uv sync
ollama list
uv run python experiment\ollama_gemma4_e4b_strong_baseline\scripts\run_strong_baseline_experiment.py --config experiment\ollama_gemma4_e4b_strong_baseline\config_strong_baseline.json
uv run python experiment\ollama_gemma4_e4b_strong_baseline\scripts\analyze_strong_baseline_results.py --run-dir experiment\ollama_gemma4_e4b_strong_baseline\runs\latest --out experiment\ollama_gemma4_e4b_strong_baseline\results
```

Mock smoke test:

```powershell
uv run python experiment\ollama_gemma4_e4b_strong_baseline\scripts\run_strong_baseline_experiment.py --config experiment\ollama_gemma4_e4b_strong_baseline\config_strong_baseline.json --mock-model
```

Effect is claimed only for `oasg_incremental_effect_confirmed_vs_strong_baseline`.
