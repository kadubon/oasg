# OASG

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20107660.svg)](https://doi.org/10.5281/zenodo.20107660)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

Observable-only Autonomic Slack Gradient for local-first AI agent workflow optimization.

OASG is a local-first toolkit for long-running AI-agent workflows. It records what the
agent can observe, reduces that history into operational state, proposes bounded workflow-policy
changes, tests them through receipts, and promotes only changes that improve conservative
operational viability without protected regression.

The project target is not a smarter model. The target is a more durable workflow:

> keep running, learn from observable history, and improve operational capability without using an
> external evaluator as the improvement oracle.

OASG optimizes workflow policy only. It does not fine-tune model weights, does not use an LLM judge,
and does not claim semantic truth. Deterministic validators, replay receipts, rollback receipts,
resource counters, and ledger checks are ordinary observable channels.

## What You Can Do With It

- Wrap any local or remote model as an observation source without making that model trusted.
- Store agent activity as append-only JSONL ledgers with canonical hashes and prefix checks.
- Reduce long-running workflow history into operational debt, pressure, and viability receipts.
- Trial workflow-policy changes through shadow/lease ledgers before promotion.
- Run conservative local optimization loops that can reject, quarantine, roll back, or promote.
- Export JSON Schemas and conformance fixtures for ports in other languages.

Use OASG when you need durable workflow operation, auditability, and fail-closed self-improvement
around an agent. Do not use it as a benchmark score, model trainer, LLM judge, sandbox, or semantic
truth oracle.

If you have five minutes, start with
[`docs/quick_mental_model.md`](docs/quick_mental_model.md), then run the
[`examples/minimal_agent_integration`](examples/minimal_agent_integration) example.

## Contents

- [Quick Mental Model](#quick-mental-model)
- [Why This Is Different](#why-this-is-different)
- [Current Status](#current-status)
- [Quickstart](#quickstart)
- [Use OASG With Your Agent](#use-oasg-with-your-agent)
- [CLI Map](#cli-map)
- [Model Integration](#model-integration)
- [Rejection Guide](#rejection-guide)
- [Experiments and Evidence](#experiments-and-evidence)
- [Development Checks](#development-checks)
- [Citation](#citation)
- [Project Layout](#project-layout)
- [License](#license)

## Quick Mental Model

OASG is like Git + unit tests + CI gate + rollback receipts for an AI agent workflow. Your agent
keeps running in its normal framework. OASG records observable events, checks workflow debt and
viability, trials policy changes, and promotes only changes with receipt-backed evidence.

Read the five-minute explanation:
[`docs/quick_mental_model.md`](docs/quick_mental_model.md).

## Why This Is Different

> OASG turns long-running AI agents into self-maintaining workflow systems that improve only from observable operational evidence, without LLM judges, external rewards, or model-weight updates.

Most agent-improvement systems optimize for answer quality, benchmark scores, human feedback,
LLM-judge feedback, or externally supplied reward functions. OASG instead treats a long-running
agent as an operational system whose future action capacity can expand or collapse.

The core object is not accuracy. It is a conservative partial-order vector over:

- viable future action classes;
- unresolved obligations;
- validation, parse, replay, rollback, and evidence debt;
- budget, queue, context, and maintenance pressure;
- protected semantic, taint, boundary, authority, and effect floors;
- shadow, lease, gate, promotion, quarantine, and rollback receipts.

The improvement loop is:

```text
append-only JSONL observable history
  -> canonical hashing and ledger-prefix verification
  -> deterministic reducers
  -> finite-chain slack/debt state
  -> typed pressure vector and scheduler
  -> bounded workflow-policy mutation batch
  -> runner-produced shadow/lease trial ledgers
  -> finite-horizon KLB_2 viability lower bound
  -> sidecar positive evidence witnesses
  -> no-meta dominance gate
  -> safe_non_regression / safe_promotion / active_promoted / reject / quarantine
```

The Python package is the reference runtime. The portability contract is language-independent:
canonical JSON bytes, SHA-256 domain hashes, JSONL ledgers, JSON receipts, JSON Schemas, and
conformance fixtures.

## Current Status

Package version: `1.1.0`.

This repository is a working reference implementation with a conservative trusted core and an
experimental long-running validation suite. It is suitable for local experiments and controlled
workflow-policy optimization. It should still be treated as an alpha system for production
automation because the safe path intentionally rejects many cases until they have complete receipts.

Implemented:

- OASG-CJ-1 canonical JSON and SHA-256 domain hashing.
- Append-only JSONL ledger sealing, duplicate handling, prefix verification, and quarantine
  receipts.
- Deterministic reducers over finite-chain dimensions and protected debt.
- Bounded `KLB_2` computation over 8 action classes and 73 trace classes.
- Typed pressure vectors and persistent scheduler state.
- Mutator profiles, outcome memory, cooldown, and bounded workflow-policy mutation batches.
- Structured workflow policy state and mutation patches.
- Runner-backed shadow and lease receipt paths.
- `ledger-replay`, explicit shell-free `local-command`, and demo-only `demo-replay` runner modes.
- Positive evidence witnesses bound to ledger prefixes, comparison contracts, workload manifests,
  KLB receipts, and trial receipts.
- No-meta dominance gate with `safe_non_regression`, `safe_promotion`, and conservative rejection.
- `optimize run`, resumable `optimize watch`, and lock-aware `optimize supervise`.
- Workflow library state with active policy, active mutations, rollback snapshots, quarantine,
  retirement, outcome memory, and conflict receipts.
- Model-agnostic adapters that emit observation events rather than evaluator judgments.
- JSON Schema export and conformance fixtures.
- Ollama `gemma4:e4b` experiment profiles with null, inconclusive, positive, interrupted, and
  strong-baseline negative results retained.

Not implemented or not claimed:

- No model-weight training or fine-tuning.
- No semantic truth proof.
- No sandbox guarantee.
- No unconstrained network, financial, communication, secret-touching, or irreversible effects by
  default.
- No active promotion from synthetic/demo evidence.
- No claim that OASG universally improves all agents or all task distributions.
- No claim that `gemma4:e4b` became more intelligent.

## Quickstart

Requirements:

- Python `>=3.12`
- [`uv`](https://docs.astral.sh/uv/)

From a fresh checkout:

```bash
uv sync
uv run oasg demo quickstart
uv run oasg doctor
uv run oasg conformance run examples/conformance
```

Inspect the generated quickstart artifacts:

```bash
uv run oasg ledger verify examples/quickstart/baseline.jsonl
uv run oasg reduce examples/quickstart/candidate.jsonl --out examples/quickstart/reducer_snapshot.json
uv run oasg klb examples/quickstart/reducer_snapshot.json --out examples/quickstart/klb_receipt.json
uv run oasg gate --baseline examples/quickstart/baseline.jsonl --candidate examples/quickstart/candidate.jsonl --contract examples/quickstart/comparison_contract.json --workload examples/quickstart/workload_manifest.json --witnesses examples/quickstart/positive_evidence_witnesses.json
```

Default runtime behavior is local-only and network-free.

### Choose a Path

| goal | start here |
| --- | --- |
| understand the concept in 5 minutes | [`docs/quick_mental_model.md`](docs/quick_mental_model.md) |
| inspect the core receipts | `uv run oasg demo quickstart` |
| see the shortest agent insertion point | [`examples/minimal_agent_integration`](examples/minimal_agent_integration) |
| verify a ledger from another implementation | `uv run oasg ledger verify history.jsonl` |
| wrap an existing agent | [Use OASG With Your Agent](#use-oasg-with-your-agent) |
| run a local optimization cycle | `uv run oasg optimize run --history history.jsonl --library workflow_library.json --out-dir .oasg/run` |
| run repeated local supervision | `uv run oasg optimize supervise --history history.jsonl --library workflow_library.json --state optimizer_state.json --out-dir .oasg/supervise` |
| reproduce the current evidence | [Experiments and Evidence](#experiments-and-evidence) |

## Use OASG With Your Agent

OASG does not require a specific model provider. Your agent, model wrapper, tool runner, or workflow
engine only needs to emit observable events into an OASG JSONL ledger.

### 1. Record Observable Events

For a quick local ledger:

```bash
uv run oasg observe --out history.jsonl --workflow-id my_agent --component-id planner --dimension budget=acceptable --action pure_read=acceptable --assume-complete
```

`--assume-complete` is a demo shortcut. In real workflows, emit the relevant dimensions, action
classes, resources, retry counts, validation results, rollback/evidence receipts, and unresolved
obligations explicitly. Missing data fails closed.

### 2. Inspect Operational Pressure

```bash
uv run oasg pressure history.jsonl --out pressure_vector.json
uv run oasg scheduler history.jsonl --out scheduler_state.json
```

Pressure is diagnostic and typed. It is not a scalar reward and cannot by itself promote a mutation.

### 3. Scaffold a Local Trial Harness

```bash
uv run oasg harness init --out oasg_harness.py
```

Replace the template body with your actual local workflow trial. The command must be deterministic
enough for your use case and must emit a sealed OASG JSONL trial ledger. Promotion evidence must
come from runner-produced trial ledgers, not from mutation metadata or model text.

### 4. Run a Conservative Optimization Cycle

```bash
uv run oasg optimize run --history history.jsonl --library workflow_library.json --out-dir .oasg/run --cycles 1 --runner local-command --runner-arg python --runner-arg oasg_harness.py --runner-arg --mutation --runner-arg "{mutation}" --runner-arg --candidate --runner-arg "{candidate}"
uv run oasg library status --library workflow_library.json
```

The optimizer performs reduce, KLB, pressure, scheduling, mutation proposal, runner-backed
shadow/lease trial derivation, comparison over observed trial ledgers, witness creation, gate
evaluation, and workflow-library update. If receipts are incomplete, the result is rejected or
inconclusive.

### 5. Run as a Long-Running Local Supervisor

```bash
uv run oasg optimize supervise --history history.jsonl --library workflow_library.json --state optimizer_state.json --out-dir .oasg/supervise --max-iterations 1 --runner local-command --runner-arg python --runner-arg oasg_harness.py --runner-arg --mutation --runner-arg "{mutation}" --runner-arg --candidate --runner-arg "{candidate}" --append-lease-observations
uv run oasg optimize state --state optimizer_state.json
uv run oasg library history --library workflow_library.json
```

The supervisor tracks consumed ledger prefixes, pending trials, scheduler state, mutation outcome
memory, library hashes, and append receipts. If history shrinks, forks, or disagrees with the saved
prefix, it emits a stale/fork receipt and does not promote.

## CLI Map

```bash
uv run oasg init
uv run oasg doctor
uv run oasg schema export --out schemas
uv run oasg schema policy --out policy_profile.json

uv run oasg ledger verify history.jsonl
uv run oasg ledger append --ledger history.jsonl --records new_events.jsonl --out history.jsonl
uv run oasg reduce history.jsonl --out reducer_snapshot.json
uv run oasg klb reducer_snapshot.json --out klb_receipt.json
uv run oasg pressure history.jsonl --out pressure_vector.json
uv run oasg scheduler history.jsonl --out scheduler_state.json

uv run oasg compare --baseline baseline.jsonl --candidate candidate.jsonl --out-dir comparison
uv run oasg witness --coordinate KLB_2.pure_read --candidate-snapshot comparison/candidate_snapshot.json --candidate-klb comparison/candidate_klb_receipt.json --contract comparison/comparison_contract.json --workload comparison/workload_manifest.json --out comparison/positive_evidence_witnesses.json
uv run oasg gate --baseline baseline.jsonl --candidate candidate.jsonl --contract comparison/comparison_contract.json --workload comparison/workload_manifest.json --witnesses comparison/positive_evidence_witnesses.json

uv run oasg mutate plan --out-dir mutation --mutation-id mut_001 --coordinate KLB_2.pure_read --action-id pure_read
uv run oasg mutator profile init --out mutators.json

uv run oasg workload manifest --baseline baseline.jsonl --candidate candidate.jsonl --out-dir comparison
uv run oasg workload run --mutation mutation/mutation_record.json --candidate candidate.jsonl --workload comparison/workload_manifest.json --out-dir .oasg/workload --runner ledger-replay --trial-ledger-out observed_trial.jsonl
uv run oasg trial run --phase shadow --mutation mutation/mutation_record.json --candidate candidate.jsonl --workload comparison/workload_manifest.json --out-dir .oasg/trial --runner ledger-replay --trial-ledger observed_trial.jsonl

uv run oasg optimize plan --history history.jsonl --library workflow_library.json --out-dir .oasg/plan
uv run oasg optimize run --history history.jsonl --library workflow_library.json --out-dir .oasg/run --cycles 1
uv run oasg optimize watch --history history.jsonl --library workflow_library.json --state optimizer_state.json --out-dir .oasg/watch --max-iterations 1
uv run oasg optimize supervise --history history.jsonl --library workflow_library.json --state optimizer_state.json --out-dir .oasg/supervise --max-iterations 1

uv run oasg experiment verify-longrun --run-dir experiment/ollama_gemma4_e4b_longrun/runs/latest --out experiment/ollama_gemma4_e4b_longrun/results
uv run oasg experiment diagnose-promotion --run-dir experiment/ollama_gemma4_e4b_longrun/runs/latest --out experiment/ollama_gemma4_e4b_longrun/results
uv run oasg conformance run examples/conformance
```

Operational commands emit deterministic JSON receipts where possible.

## Model Integration

Adapters are convenience wrappers. They are outside the trusted gate and cannot create positive
promotion evidence by themselves.

Included examples:

- `oasg.adapters.invoke_command`: local subprocess observation wrapper.
- `oasg.adapters.invoke_function`: Python callable observation wrapper.
- `oasg.adapters.openai_compatible.invoke_openai_compatible`: optional OpenAI-compatible HTTP
  request wrapper.

The safe pattern is:

1. call your model or tool;
2. convert the result into a `ModelEvent`;
3. seal it into an OASG event record;
4. append the record to the observable ledger;
5. let reducers, gates, and trial receipts decide whether workflow policy can change.

Local Ollama experiments in this repository use only localhost Ollama as the model endpoint.

### Works With Existing Orchestrators

OASG is not a replacement for an agent framework. It can sit beside one:

- plain Python: wrap a function or model call and append an OASG event;
- LangGraph: LangGraph handles durable execution and resume, OASG handles promotion gates;
- CrewAI: CrewAI handles crew/task execution, OASG observes outcomes and gates policy changes;
- any provider: emit JSONL observations and keep provider output outside the trusted gate.

See [`examples/framework_adapters`](examples/framework_adapters) for dependency-free adapter
patterns. LangGraph and CrewAI are optional examples, not package dependencies.

## Rejection Guide

Common statuses:

- `rejected_no_concrete_positive_evidence`: an improved coordinate lacks a valid sidecar witness.
- `rejected_floor_violation`: a protected floor regressed.
- `rejected_contaminated_comparison`: baseline/candidate workload pairing is not equivalent.
- `rejected_effect_policy`: the mutation requests a disallowed effect or promotion class.
- `rejected_semantic_floor_missing`: a claim-emitting action lacks a semantic-floor policy.
- `rejected_secret_taint`: secret or unknown-secret taint reached a protected action.
- `inconclusive_klb_overflow`: bounded `KLB_2` enumeration exceeded the profile cap.
- `no_valid_candidate`: optimizer found no candidate with complete gate, shadow, lease, and witness
  receipts.
- `no_new_work`: watch/supervise saw the same append index and ledger prefix as the prior
  checkpoint.
- `stale_optimizer_state`: saved optimizer state and current ledger prefix/append index disagree.
- `library_conflict`: workflow library changed between load and atomic write.

Rejection is not a runtime error in OASG. It is often the correct fail-closed result.

## Experiments and Evidence

The repository includes local Ollama `gemma4:e4b` experiments. They are designed to test workflow
operation, not model intelligence. All reported runs used deterministic operational validators and
kept failed, rejected, and inconclusive receipts.

Current evidence bottom line:

- OASG showed a practical workflow-operation improvement over a deliberately weak fixed baseline in
  the decisive experiment.
- OASG did not show an incremental improvement over a calibration-selected strong static baseline
  in the strong-baseline v2 experiment.
- Therefore, the scientifically honest claim is conditional: this implementation can improve a
  brittle fixed workflow in the tested setting, but the repository does not yet show added value
  over a strong hand-tuned workflow.

### Evidence Summary

| experiment | classification | key result | interpretation |
| --- | --- | --- | --- |
| `experiment/ollama_gemma4_e4b_pilot` | `no_clear_effect` | 12 tasks; baseline and adaptive both closed 8/12; active promotions 0 | Initial pilot did not establish adaptation. |
| `experiment/ollama_gemma4_e4b_pilot` effect profile | `no_clear_effect` | 48 held-out eval tasks; baseline and adaptive both closed 26/48; active promotions 0 | Workflow-sensitive design still did not activate promotion. |
| `experiment/ollama_gemma4_e4b_longrun` | `inconclusive_no_active_policy` | baseline 276/408 closed; observe-only 277/408 closed; adaptive evaluation was not run because active promotions 0 | Long-run measurement correctly refused to claim OASG effect. |
| `experiment/ollama_gemma4_e4b_definitive` | `workload_not_sensitive` | mechanism qualification blocked Stage B; no effect claim | The positive-control policy did not establish a useful measurement workload. |
| `experiment/ollama_gemma4_e4b_decisive` | `oasg_effect_confirmed` | 5 seeds, 680 paired held-out tasks; adaptive debt AUC 2040 -> 921; closure 0 -> 337; hard-floor regressions 0 | Under this preregistered weak-baseline workload, OASG adaptive produced a practical workflow-operation improvement. |
| `experiment/ollama_gemma4_e4b_strong_baseline` | `promotion_mechanism_failure_vs_strong_baseline` | strong baseline qualified; adaptive readiness active seeds 0/4 required; run interrupted after 7/25 held-out condition blocks | No incremental OASG effect over the strong baseline is claimed. The run was stopped because adaptive activation failed before evaluation, making the primary effect question non-identifiable. |
| `experiment/ollama_gemma4_e4b_strong_baseline_v2` | `no_incremental_effect_vs_strong_baseline` | 5 seeds, 680 paired held-out tasks; strong static debt AUC 434; OASG adaptive debt AUC 436; debt delta `+2`, CI `[0, 5]`; cost delta `+7652`, CI `[1534, 14346]`; hard-floor regressions 0 | Readiness succeeded, but held-out evaluation did not show incremental OASG value over the calibrated strong static workflow. |

### Decisive Run Details

The decisive run is the current strongest positive evidence in this repository.

Artifacts:

- results report: [`experiment/ollama_gemma4_e4b_decisive/results/report.md`](experiment/ollama_gemma4_e4b_decisive/results/report.md)
- metrics: [`experiment/ollama_gemma4_e4b_decisive/results/metrics.json`](experiment/ollama_gemma4_e4b_decisive/results/metrics.json)
- verification: [`experiment/ollama_gemma4_e4b_decisive/results/verification.json`](experiment/ollama_gemma4_e4b_decisive/results/verification.json)
- promotion diagnostic: [`experiment/ollama_gemma4_e4b_decisive/results/promotion_diagnostic.json`](experiment/ollama_gemma4_e4b_decisive/results/promotion_diagnostic.json)

Condition summary from the decisive run:

| condition | tasks | closed | debt AUC | parse failures | validation failures | unresolved obligations | active mutations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline_fixed` | 680 | 0 | 2040 | 680 | 680 | 680 | 0 |
| `oasg_observe_only` | 680 | 0 | 2040 | 680 | 680 | 680 | 0 |
| `forced_policy_positive_control` | 680 | 463 | 434 | 0 | 217 | 217 | 0 |
| `oasg_adaptive` | 680 | 337 | 921 | 235 | 343 | 343 | 6 |

Paired effects:

- Adaptive vs baseline debt AUC delta: `-1119`.
- Adaptive vs baseline debt AUC reduction: `54.85%`.
- Bootstrap CI for adaptive-baseline debt delta: `[-1179, -1050]`.
- Forced positive-control vs baseline debt AUC delta: `-1606`.
- Verification status: `ok`.
- Invalid ledgers: none reported.
- Active seeds: `5/5`.
- Active mutation ids:
  - `mut_family_safe_expr_prompt_safe_python_expression`
  - `mut_receipt_template_only_replay_rollback_receipt`
  - `mut_receipt_template_only_validator_receipt`
  - `mut_schema_keys_only_json_schema_repair`
  - `mut_schema_keys_only_obligation_closure`
  - `mut_strict_json_minimal_code_transform`

Scientific interpretation:

- This is positive evidence that OASG can reduce observable operational debt in the tested
  `gemma4:e4b` workflow setting.
- It is not evidence that the model became smarter.
- It is not evidence of universal OASG effectiveness.
- The baseline was intentionally weak and brittle. The result proves improvement over that fixed
  workflow, not over a strong hand-tuned production workflow.
- The forced positive-control was better than OASG adaptive, so OASG did not find the full available
  policy improvement. It found a substantial subset.
- The observe-only condition matched baseline, which supports the interpretation that improvement
  came from active workflow-policy promotion, not from measurement alone.

Strong-baseline follow-up:

- A later strong-baseline protocol qualified a strong static workflow, but OASG did not produce any
  runner-ledger-backed active policy change from that strong starting point.
- That run was interrupted after readiness failure, with classification
  `promotion_mechanism_failure_vs_strong_baseline`.
- This is negative evidence for the current implementation's ability to add incremental value over
  that strong static workflow, not a general proof that OASG cannot help stronger baselines.
- Artifacts:
  [`experiment/ollama_gemma4_e4b_strong_baseline/results/20260511T113612Z_interrupted/report.md`](experiment/ollama_gemma4_e4b_strong_baseline/results/20260511T113612Z_interrupted/report.md)
  and
  [`experiment/ollama_gemma4_e4b_strong_baseline/results/20260511T113612Z_interrupted/interruption_receipt.json`](experiment/ollama_gemma4_e4b_strong_baseline/results/20260511T113612Z_interrupted/interruption_receipt.json).

Strong-baseline v2 protocol:

- The v2 profile added an explicit `incremental_headroom` gate and then completed held-out
  evaluation after readiness passed.
- Stage 0: `strong_baseline_qualified`; the strong static policy reduced calibration debt AUC by
  `7861` bps versus the weak fixed baseline.
- Stage 1: `debt_headroom_exists`; calibration canaries found 43 incremental candidates.
- Stage 2: `adaptive_from_strong_ready`; active changes appeared in all 5 seeds.
- Stage 3: held-out evaluation did not show incremental gain over strong static:
  - `strong_static_calibrated`: debt AUC `434`, cost units `1580136`, closed `463/680`.
  - `oasg_adaptive_from_strong`: debt AUC `436`, cost units `1587788`, closed `463/680`.
  - primary debt delta `+2`, debt CI `[0, 5]`; primary cost delta `+7652`, cost CI
    `[1534, 14346]`.
- Final classification: `no_incremental_effect_vs_strong_baseline`.
- Interpretation: this is negative evidence for incremental value over this strong static workflow,
  not evidence that OASG cannot help all strong baselines.
- Curated artifacts:
  [`experiment/ollama_gemma4_e4b_strong_baseline_v2/results/report.md`](experiment/ollama_gemma4_e4b_strong_baseline_v2/results/report.md),
  [`experiment/ollama_gemma4_e4b_strong_baseline_v2/results/metrics.json`](experiment/ollama_gemma4_e4b_strong_baseline_v2/results/metrics.json),
  and
  [`experiment/ollama_gemma4_e4b_strong_baseline_v2/results/verification.json`](experiment/ollama_gemma4_e4b_strong_baseline_v2/results/verification.json).

### Reproduce the Decisive Experiment

Requires local Ollama with `gemma4:e4b` installed.

```powershell
cd path\to\oasg
uv sync
ollama list
uv run python experiment\ollama_gemma4_e4b_decisive\scripts\run_decisive_experiment.py --config experiment\ollama_gemma4_e4b_decisive\config_decisive.json
uv run python experiment\ollama_gemma4_e4b_decisive\scripts\analyze_decisive_results.py --run-dir experiment\ollama_gemma4_e4b_decisive\runs\latest --out experiment\ollama_gemma4_e4b_decisive\results
```

The effect claim is limited to the frozen workload, model, prompts, validators, implementation, and
decision thresholds in that experiment profile.

## Development Checks

Before publishing a change or port:

```bash
uv run pytest
uv run ruff check
uv run mypy src
uv run oasg conformance run examples/conformance
```

At the time this README was updated after the strong-baseline v2 result curation, these checks
passed in the current workspace: `97 passed`, `ruff` clean, `mypy` clean, and conformance
`status: ok`.

The current public-readiness review is recorded in
[`docs/publication_audit.md`](docs/publication_audit.md).

## Citation

If you use OASG, cite the archived software release:

- DOI: [10.5281/zenodo.20107660](https://doi.org/10.5281/zenodo.20107660)
- Repository: [github.com/kadubon/oasg](https://github.com/kadubon/oasg)
- Citation metadata: [`CITATION.cff`](CITATION.cff)

```yaml
cff-version: 1.2.0
title: "OASG: Observable-only Autonomic Slack Gradient for Local-first AI Agent Workflow Optimization"
version: 1.1.0
doi: 10.5281/zenodo.20107660
repository-code: "https://github.com/kadubon/oasg"
```

## Keywords

AI agents, agent workflow optimization, long-running agents, local-first AI, model-agnostic agent
framework, no LLM judge, observable ledgers, deterministic reducers, workflow policy optimization,
autonomic agents, JSONL ledger, canonical hashing, Ollama experiments, Python uv.

## Project Layout

```text
theory.md                      v1.0 theory and specification
docs/quick_mental_model.md     five-minute engineering mental model
src/oasg/canonical.py          canonical JSON and hash domains
src/oasg/ledger.py             JSONL sealing and prefix verification
src/oasg/reducers/             deterministic reducers
src/oasg/pressure.py           typed pressure vector calculation
src/oasg/scheduler.py          pressure scheduling and fairness state
src/oasg/mutators.py           workflow-policy mutation proposals
src/oasg/optimizer.py          run/watch/supervise optimizer loops
src/oasg/optimizer_state.py    durable optimizer checkpoints
src/oasg/library.py            workflow library state, rollback, quarantine
src/oasg/policy_state.py       structured workflow policy and mutation patches
src/oasg/harness.py            local harness scaffold
src/oasg/policy_effects.py     demo-only policy-patch smoke semantics
src/oasg/runners.py            ledger-replay/demo-replay/local-command runners
src/oasg/klb.py                bounded KLB_2 enumeration
src/oasg/gate.py               dominance gate and witness validation
src/oasg/schemas/              JSON Schema export
src/oasg/adapters/             model/tool connector contracts
examples/                      quickstart and conformance fixtures
examples/minimal_agent_integration/ shortest agent-to-ledger-to-gate example
examples/framework_adapters/   optional plain Python, LangGraph, and CrewAI patterns
experiment/                    Ollama experiment protocols and results
tests/                         unit, integration, and experiment-script tests
```

## License

Apache-2.0.
