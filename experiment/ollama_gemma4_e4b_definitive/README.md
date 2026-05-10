# OASG x Ollama `gemma4:e4b` Definitive Effect Protocol

This profile is designed to classify, without ambiguity, whether this OASG
implementation produces a practical workflow-operation effect on a preregistered
local workload. It does not claim universal proof about OASG theory, model
intelligence, or benchmark superiority.

## Classifications

- `oasg_effect_confirmed`: OASG adaptive improves operational debt by the
  preregistered threshold with active promotion in enough seeds and no hard-floor
  regression.
- `no_practical_oasg_effect`: active promotion works, but the minimum practical
  effect is not observed.
- `promotion_mechanism_failure`: forced positive-control improves the workload,
  but OASG cannot autonomously promote an effective policy.
- `workload_not_sensitive`: even forced workflow policy does not improve the
  calibration workload.
- `regression_observed`: adaptive operation increases protected debt or violates
  hard floors.
- `invalid_run`: ledger, pairing, preflight, or receipt integrity is invalid.

## Protocol

Stage A qualifies the mechanism on calibration tasks only. It compares fixed
baseline, forced positive-control policy, and OASG adaptive promotion readiness.
Stage B runs held-out longrun evaluation only if Stage A returns
`mechanism_qualified`.

The default confirmatory run uses five seeds. A three-seed run is exploratory and
must not emit `oasg_effect_confirmed`.

## Commands

```powershell
cd path\to\oasg
uv sync
ollama list
uv run python experiment\ollama_gemma4_e4b_definitive\scripts\qualify_mechanism.py --config experiment\ollama_gemma4_e4b_definitive\config_definitive.json --out-dir experiment\ollama_gemma4_e4b_definitive\runs\qualification
uv run python experiment\ollama_gemma4_e4b_definitive\scripts\run_definitive_experiment.py --config experiment\ollama_gemma4_e4b_definitive\config_definitive.json
uv run python experiment\ollama_gemma4_e4b_definitive\scripts\analyze_definitive_results.py --run-dir experiment\ollama_gemma4_e4b_definitive\runs\latest --out experiment\ollama_gemma4_e4b_definitive\results
```

Mock smoke tests avoid Ollama:

```powershell
uv run python experiment\ollama_gemma4_e4b_definitive\scripts\run_definitive_experiment.py --config experiment\ollama_gemma4_e4b_definitive\config_definitive.json --mock-model
```

## Scientific Limits

The final claim is limited to the local `gemma4:e4b` model, this OASG
implementation, this deterministic task distribution, and the frozen effect
thresholds in `config_definitive.json`. No model weights are changed, and no LLM
judge or external evaluator oracle is used.
