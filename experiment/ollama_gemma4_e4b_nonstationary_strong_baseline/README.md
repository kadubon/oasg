# OASG x Ollama `gemma4:e4b` Nonstationary Strong-Baseline Protocol

This profile tests OASG where it should plausibly matter: long-running operation under explicit
distribution drift. The question is not whether OASG always beats a strong static workflow. The
question is narrower:

> When a strong static workflow is selected from Phase A only, can OASG recover post-drift
> operational performance by promoting runner-ledger-backed, fail-closed workflow-policy changes?

A completed local run is curated in `results/` with classification
`oasg_nonstationary_effect_confirmed_timeboxed`. The default config is a short time-boxed mechanism
test that took roughly five hours on local Ollama `gemma4:e4b` in this workspace. The shorter run is
scientifically meaningful because it keeps the core mechanism intact: Phase A calibration, ordered
Phase B/C/D drift, online observations, and fail-closed adaptation. It has less precision than a
larger 5-seed confirmatory run.

## Curated Result

- Classification: `oasg_nonstationary_effect_confirmed_timeboxed`
- Verification: `ok`
- Paired post-drift tasks: `48`
- Strong static debt AUC: `112`
- OASG adaptive debt AUC: `84`
- Debt delta: `-28`, bootstrap CI `[-51, -10]`
- Closure: `20/48` -> `27/48`
- Hard-floor regressions: `0`
- OASG vs rule-adaptive debt delta: `-30`, bootstrap CI `[-50, -12]`
- Adaptation lag: Phase B `1` epoch, Phase C `0`, Phase D `0`

Interpretation: this is positive time-boxed evidence that fail-closed OASG adaptation can recover
post-drift operational debt over a Phase-A-calibrated strong static workflow in this controlled
`gemma4:e4b` setting. It is not evidence of universal OASG effectiveness or model intelligence
improvement.

## Design

Ordered phases:

1. `phase_a_calibration`: pre-drift strong-static selection only.
2. `phase_b_mild_drift`: schema-key aliases and stricter JSON formatting.
3. `phase_c_structural_drift`: receipt, obligation, safe-expression, evidence, and rollback gaps.
4. `phase_d_mixed_reversion`: old/new requirements mixed to test overfitting and rollback value.

Full-run deployable conditions:

- `strong_static_calibrated`
- `oasg_observe_only_from_strong`
- `rule_adaptive_control`
- `oasg_adaptive_from_strong`

Default size:

- 2 seeds: `20260509`, `20260510`
- 4 ordered phases
- 2 epochs per phase
- 4 tasks per epoch
- primary evaluation excludes Phase A and uses only Phase B/C/D paired rows

Diagnostic controls:

- `weak_fixed`: Phase A plus one post-drift probe epoch.
- `strong_static_oracle_phase_control`: one probe epoch per drift phase using phase knowledge. This
  is an upper-bound control, not a deployable baseline.

## No-Leakage Rule

- Strong static policy selection uses Phase A only.
- OASG adaptive may use only observations up to the current epoch.
- Rule adaptive uses recent observed failures, not future phase labels.
- Oracle phase control is explicitly non-deployable and excluded from the primary comparison.

## Classification

The primary positive classification is `oasg_nonstationary_effect_confirmed_timeboxed`. It requires
valid ledgers, no hard-floor regression versus strong static, active post-drift OASG policy changes,
post-drift debt AUC improvement of at least 15%, a bootstrap CI upper bound below zero, cost
regression no worse than 10%, and improvement not explained by the simple rule-adaptive control.

Other possible outcomes include `partial_nonstationary_support`, `rule_adaptive_explains_effect`,
`no_incremental_effect_under_drift`, `adaptive_readiness_failed`, `oracle_headroom_absent`,
`inconclusive_cost_regression`, `inconclusive_invalid_ledgers`, and
`interrupted_before_primary_evaluation`.

## Commands

Mock smoke run, no Ollama required:

```powershell
uv run python experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\scripts\run_nonstationary_experiment.py --config experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\config_nonstationary.json --mock-model
```

Real local Ollama run:

```powershell
uv sync
ollama list
uv run python experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\scripts\run_nonstationary_experiment.py --config experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\config_nonstationary.json
uv run python experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\scripts\analyze_nonstationary_results.py --run-dir experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\runs\latest --out experiment\ollama_gemma4_e4b_nonstationary_strong_baseline\results
```

Effect is claimed only for the curated result in `results/` and only under the limits stated above.
