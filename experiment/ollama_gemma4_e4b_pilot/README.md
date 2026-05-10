# OASG x Ollama `gemma4:e4b` Pilot

This directory contains a preregistered 1-hour local pilot experiment for OASG with Ollama `gemma4:e4b`.

The experiment evaluates workflow operation, not model intelligence. It compares a fixed non-adaptive workflow with an OASG-adaptive workflow on the same 12 deterministic coding-operations tasks.

## Hypothesis

Primary claim tested:

> OASG can reduce observable operational debt/pressure or improve conservative action viability while preserving hard floors, compared with a fixed non-adaptive workflow.

Non-claims:

- No claim that `gemma4:e4b` becomes semantically smarter.
- No claim of general benchmark superiority.
- No external LLM judge.
- Deterministic validators are operational checks, not semantic truth.

## Conditions

- `baseline_fixed`: fixed workflow policy, no OASG promotion.
- `oasg_adaptive`: same initial workflow, appends observations and runs OASG supervision after each batch.

Both conditions use the same `tasks.jsonl`, model name, prompt template, timeout, temperature, and validator code. The task set has 12 tasks in 3 batches of 4.

## Commands

From the repository root:

```powershell
cd path\to\oasg
uv sync
ollama list
uv run python experiment\ollama_gemma4_e4b_pilot\scripts\run_experiment.py --config experiment\ollama_gemma4_e4b_pilot\config.json
uv run python experiment\ollama_gemma4_e4b_pilot\scripts\analyze_results.py --run-dir experiment\ollama_gemma4_e4b_pilot\runs\latest --out experiment\ollama_gemma4_e4b_pilot\results
uv run pytest
uv run ruff check
uv run mypy src
uv run oasg conformance run examples/conformance
```

The run artifacts are written below `runs/`. Bulky run artifacts are ignored by default. Curated summaries can be kept in `results/`.

## Effect-Oriented Profile

The original pilot result is preserved as a small null/no-clear-effect run. To run the redesigned effect-oriented profile:

```powershell
cd path\to\oasg
uv run python experiment\ollama_gemma4_e4b_pilot\scripts\generate_effect_tasks.py --out experiment\ollama_gemma4_e4b_pilot\tasks_effect.jsonl --seed 20260508
uv run python experiment\ollama_gemma4_e4b_pilot\scripts\run_experiment.py --config experiment\ollama_gemma4_e4b_pilot\config_effect.json
uv run python experiment\ollama_gemma4_e4b_pilot\scripts\analyze_results.py --run-dir experiment\ollama_gemma4_e4b_pilot\runs_effect\latest --out experiment\ollama_gemma4_e4b_pilot\results_effect
```

This profile uses 60 deterministic tasks: 12 calibration tasks and 48 held-out evaluation tasks. The primary comparison excludes calibration tasks. OASG may adapt only from calibration observations; baseline remains fixed.

## What Is Measured

Primary operational metrics:

- task closure rate
- attempts and retries
- duration
- approximate prompt/output character budget
- parsed/not parsed
- validation pass/fail
- unresolved obligation count
- protected regression count through OASG receipts where available
- gate statuses
- active promotion count
- KLB and pressure receipt hashes where available

The analysis emits:

- `metrics.json`
- `report.md`

Report classifications:

- `improvement_observed`
- `no_clear_effect`
- `regression_observed`
- `inconclusive`

For the effect-oriented profile, `improvement_observed` requires at least a 15 percentage point held-out closure-rate improvement or at least a 25% held-out validation-failure reduction, with no protected regression.

## Evidence Policy

OASG promotion evidence must come from runner-produced trial ledgers. The pilot uses a local-command trial harness that converts recent observed operational metrics into sealed trial ledgers. It is conservative:

- it rejects manual `set_action_grade` patches;
- it emits no positive evidence if the recent batch has no observed failures or pressure;
- it never modifies model weights;
- it never uses an LLM judge.

This is a pilot harness, not a full counterfactual benchmark harness. Any promotion must still pass OASG gate and receipt checks.

## Scientific Honesty Rules

- Always report all failed, rejected, and inconclusive runs.
- Report exact model, task-list hash, ledger prefix hashes, and OASG receipts.
- Do not hide failed promotions.
- Use paired effect sizes only; do not make strong statistical claims from this pilot.
- Treat deterministic validators as operational closure checks, not proof of semantic truth.

## Files

- `config.json`: model, endpoint, batch size, retry caps, and output paths.
- `tasks.jsonl`: 12 deterministic coding-operations tasks.
- `scripts/run_experiment.py`: runs baseline and adaptive conditions.
- `scripts/oasg_trial_harness.py`: local-command OASG trial harness.
- `scripts/analyze_results.py`: computes paired metrics and writes the report.
- `runs/`: generated run artifacts.
- `results/`: curated summaries.
