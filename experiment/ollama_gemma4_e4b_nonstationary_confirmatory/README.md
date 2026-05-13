# OASG x Ollama Nonstationary Confirmatory Experiment

This profile is a larger follow-up to
`experiment/ollama_gemma4_e4b_nonstationary_strong_baseline`, which produced a
time-boxed positive result for post-drift workflow recovery over a Phase-A-calibrated strong static
workflow.

The purpose here is narrower than a general benchmark claim:

> Test whether the previous nonstationary result is robust, phase-specific, or explained by simpler
> controls.

This experiment does not test model intelligence. It tests workflow operation: observable debt,
closure, cost, adaptation lag, and fail-closed policy promotion.

The audited version separates four questions that were previously too easy to conflate:

- Does OASG show support across multiple drift classes within this frozen protocol?
- Is the effect concentrated in mixed reversion / policy retirement?
- Does structural drift without mixed reversion also improve?
- Does the result remain favorable after cost-to-close and closure-adjusted cost are included?

## Variants

| variant | phases | purpose |
| --- | --- | --- |
| `full_drift_confirmatory` | A, B, C, D | Larger replication of the prior time-boxed protocol. |
| `no_mixed_reversion_ablation` | A, B, C1, C2 | Tests structural drift without mixed reversion. |
| `mixed_reversion_only_probe` | A, D1, D2 | Isolates mixed-reversion and policy-retirement effects. |
| `delayed_drift_recovery` | A, A2, C, D | Tests no unnecessary pre-drift adaptation plus later recovery. |

Phase A is calibration-only. Phase A2 is a stable continuation control and is excluded from the
primary post-drift metric. All primary metrics exclude calibration rows.

## Conditions

Deployable conditions:

- `strong_static_calibrated`
- `oasg_observe_only_from_strong`
- `rule_adaptive_control`
- `oasg_adaptive_from_strong`

Diagnostic controls:

- `weak_fixed`
- `strong_static_oracle_phase_control`

The oracle control may use phase identity and future knowledge only as a non-deployable headroom
diagnostic. It is excluded from OASG effect claims.

## No-Leakage Rules

- The strong static baseline is selected from Phase A calibration tasks only.
- OASG adaptive may use only observations available up to the current online epoch.
- Rule adaptive may use recent observed failure classes but not future phase labels.
- Evaluation/canary task IDs do not enter baseline calibration.
- Single-variant runs are diagnostic. A confirmatory classification requires all required variants
  under the main config.

The run emits `no_leakage_receipt.json`.

## Mock Smoke Run

The mock path verifies the wiring and produces an intentionally non-confirmatory classification.
It does not support any effect claim.

```powershell
uv run python experiment\ollama_gemma4_e4b_nonstationary_confirmatory\scripts\run_confirmatory_experiment.py --config experiment\ollama_gemma4_e4b_nonstationary_confirmatory\config_confirmatory_small.json --mock-model --all-variants
uv run python experiment\ollama_gemma4_e4b_nonstationary_confirmatory\scripts\analyze_confirmatory_results.py --run-dir experiment\ollama_gemma4_e4b_nonstationary_confirmatory\runs\latest --out experiment\ollama_gemma4_e4b_nonstationary_confirmatory\results
```

## Real Local Ollama Run

Requires local Ollama with `gemma4:e4b` installed. This can be run one variant at a time for runtime
management, but single-variant results remain diagnostic until all required variants are combined.

```powershell
uv sync
ollama list
uv run python experiment\ollama_gemma4_e4b_nonstationary_confirmatory\scripts\run_confirmatory_experiment.py --config experiment\ollama_gemma4_e4b_nonstationary_confirmatory\config_confirmatory_main.json --all-variants
uv run python experiment\ollama_gemma4_e4b_nonstationary_confirmatory\scripts\analyze_confirmatory_results.py --run-dir experiment\ollama_gemma4_e4b_nonstationary_confirmatory\runs\latest --out experiment\ollama_gemma4_e4b_nonstationary_confirmatory\results
```

Optional variant run:

```powershell
uv run python experiment\ollama_gemma4_e4b_nonstationary_confirmatory\scripts\run_confirmatory_experiment.py --config experiment\ollama_gemma4_e4b_nonstationary_confirmatory\config_confirmatory_main.json --variant no_mixed_reversion_ablation
```

## Classification

Possible final classifications include:

- `oasg_nonstationary_confirmed`
- `oasg_nonstationary_phase_specific_support`
- `mixed_reversion_only_effect`
- `no_mixed_reversion_support`
- `no_incremental_effect_under_drift`
- `rule_adaptive_explains_effect`
- `observe_only_explains_effect`
- `oracle_headroom_absent`
- `inconclusive_cost_regression`
- `inconclusive_invalid_ledgers`
- `inconclusive_insufficient_power`
- `interrupted_before_primary_evaluation`

Positive confirmation requires all required variants, valid ledgers, post-drift OASG improvement over
strong static, controls that do not explain the effect, structural-drift support, mixed-reversion
support, no excessive cost regression by bootstrap CI, no worse hard floors, active OASG changes
after drift in the configured seed count, and no unnecessary active mutation during the delayed-drift
A2 stable phase. Mixed-only support is classified as narrower phase-specific evidence, not broad
nonstationary support.

Additional receipts:

- `drift_class_effect_receipt.json`: mild / structural / mixed / delayed-stable effects and
  interpretation label.
- `retirement_effect_receipt.json`: active retirement/tightening rows and mixed-reversion counts.
- `oracle_headroom_receipt.json`: aggregate and drift-class-specific oracle headroom.

## Supported And Unsupported Claims

Supported if the main all-variant real run classifies positive:

- OASG showed post-drift operational recovery for this frozen local `gemma4:e4b` workflow protocol.

Unsupported:

- OASG universally improves all agents.
- The model became more intelligent.
- The oracle control is deployable.
- Synthetic/demo evidence is sufficient for promotion.
