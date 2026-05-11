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

## Recorded Real Run: `20260511T113612Z`

The first real strong-baseline run was intentionally interrupted during held-out evaluation after
the adaptive readiness gate had already failed.

Result:

- Classification: `promotion_mechanism_failure_vs_strong_baseline`
- Strong baseline qualification: `strong_baseline_qualified`
- Strong static debt reduction over weak fixed during qualification: `7889` bps
- Adaptive readiness: `promotion_mechanism_failure_vs_strong_baseline`
- Active OASG seeds: `0 / 4` required
- Readiness trial receipts: `5`
- Readiness trial status: `trial_not_improved = 5`
- Held-out Stage 2 progress at interruption: `7 / 25` condition blocks completed

Reason for interruption:

The experiment asks whether OASG can produce additional workflow-operation improvement after
starting from a calibration-selected strong static policy. That question requires at least one
runner-ledger-backed active OASG policy change before held-out evaluation. In this run, no active
policy change was produced. Continuing the remaining held-out tasks would mostly compare the strong
static policy against itself under the `oasg_adaptive_from_strong` label, so it would not provide a
valid incremental OASG effect estimate.

Artifacts:

- [`results/20260511T113612Z_interrupted/report.md`](results/20260511T113612Z_interrupted/report.md)
- [`results/20260511T113612Z_interrupted/metrics.json`](results/20260511T113612Z_interrupted/metrics.json)
- [`results/20260511T113612Z_interrupted/interruption_receipt.json`](results/20260511T113612Z_interrupted/interruption_receipt.json)

Interpretation:

This run does not show that OASG is ineffective in general. It shows that, under this strong
baseline protocol and implementation, OASG did not operationalize an incremental active workflow
policy improvement before evaluation. The correct next step is to improve or replace the readiness
mechanism before spending further compute on confirmatory strong-baseline evaluation.
