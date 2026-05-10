# OASG x Ollama `gemma4:e4b` Long-Running Experiment

This experiment tests whether OASG improves long-running workflow operation for
a local agent workload. It does not test whether `gemma4:e4b` becomes more
intelligent, and it does not use an LLM judge or external evaluator oracle.

## Preregistered Claim

Primary claim under test:

> During continuous operation, OASG can reduce observable operational debt from
> its own history by promoting workflow policy changes backed by runner-produced
> trial ledgers.

Primary endpoint:

`operational_debt_auc = unresolved obligations + validation failures + parse failures + retry pressure`, summed across long-run evaluation epochs.

Decision rules:

- `improvement_observed`: in the confirmatory replicated run, adaptive debt AUC
  is at least 20% lower than fixed baseline, the block-bootstrap CI upper bound
  for the debt AUC delta is below zero, hard-floor regressions are zero, and
  active promotion occurred in enough preregistered seeds.
- `partial_support`: active promotion occurred and debt AUC improved by at least
  10%, but the confirmatory threshold or CI rule was not met.
- `recovery_improvement_observed`: post-burst backlog half-life or MTTR improves
  by at least 25%.
- `inconclusive_no_active_policy`: no active promotion occurred, or a promoted
  policy hash never appears with non-empty active mutation ids in evaluation.
- `pipeline_failure_*`: trial execution, workload pairing, or ledger/gate
  artifacts failed before OASG effect could be evaluated.
- `regression_observed`: hard-floor regression, increased unresolved
  obligations, or increased rollback failure is observed.
- `no_clear_effect`: active promotion occurred, but thresholds were not met.

## Conditions

The same deterministic task stream is run under three conditions:

- `baseline_fixed`: fixed weak prompt, no retry, no OASG.
- `oasg_observe_only`: same workflow plus OASG ledgers/reducers, promotion disabled.
- `oasg_adaptive`: same initial workflow, then OASG supervisor may promote only
  workflow policies backed by trial ledgers.

The default confirmatory configuration runs three deterministic seeds:
`20260509`, `20260510`, and `20260511`. Each seed uses a 20 epoch x 8 task
stream. Epochs 1-3 are warmup/calibration and are excluded from the primary
endpoint. A single-seed run is exploratory and must not be reported as a
confirmatory effect test.

The adaptive condition has an explicit readiness gate. If no active
workflow-policy mutation is promoted by the end of warmup, the adaptive run stops
early and the result is classified as `inconclusive_no_active_policy`; it is not
allowed to proceed as though a policy adaptation had been tested.

Trial execution uses separate timeout budgets: individual Ollama calls use
`ollama_timeout_seconds`, while the local-command trial runner uses
`trial_runner_timeout_seconds`. The runner timeout must cover baseline and
candidate canaries plus margin; otherwise the result is classified as a pipeline
failure, not as evidence against OASG.

## Commands

From the repository root:

```powershell
uv sync
uv run python experiment\ollama_gemma4_e4b_longrun\scripts\generate_longrun_tasks.py --out experiment\ollama_gemma4_e4b_longrun\tasks_longrun.jsonl
ollama list
uv run python experiment\ollama_gemma4_e4b_longrun\scripts\run_longrun_experiment.py --config experiment\ollama_gemma4_e4b_longrun\config_longrun.json
uv run python experiment\ollama_gemma4_e4b_longrun\scripts\analyze_longrun_results.py --run-dir experiment\ollama_gemma4_e4b_longrun\runs\latest --out experiment\ollama_gemma4_e4b_longrun\results
uv run oasg experiment verify-longrun --run-dir experiment\ollama_gemma4_e4b_longrun\runs\latest --out experiment\ollama_gemma4_e4b_longrun\results\verification.json
uv run oasg experiment diagnose-promotion --run-dir experiment\ollama_gemma4_e4b_longrun\runs\latest --out experiment\ollama_gemma4_e4b_longrun\results\promotion_diagnostic.json
```

CI and script smoke tests can avoid Ollama:

```powershell
uv run python experiment\ollama_gemma4_e4b_longrun\scripts\run_longrun_experiment.py --config experiment\ollama_gemma4_e4b_longrun\config_longrun.json --mock-model
```

## Artifact Policy

Generated run artifacts stay under `runs/` and are ignored by default. Curated
summaries can be copied into `results/`.

The report must include:

- model name and Ollama endpoint;
- task manifest hash;
- ledger verification receipts;
- active promotion count;
- all rejected and inconclusive OASG receipts;
- epoch-level debt table.

## Scientific Limits

This is an overnight local experiment, not a benchmark leaderboard. Deterministic
validators are operational checks, not semantic truth. If no active promotion is
produced, the honest conclusion is that this implementation/harness did not
operationalize OASG adaptation strongly enough for this run.
