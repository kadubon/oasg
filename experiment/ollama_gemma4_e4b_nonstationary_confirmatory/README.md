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

## Final Real Run Result

The completed main all-variant Ollama run classifies:

`mixed_reversion_only_effect`

This is a positive but narrowed result. The primary paired comparison favors
`oasg_adaptive_from_strong` over `strong_static_calibrated`, and both deployable controls also
favor OASG. However, the structural-only effect is below the preregistered support threshold, so
the run does not satisfy the broader `oasg_nonstationary_confirmed` contract.

Integrity and scope:

- run source: `experiment/ollama_gemma4_e4b_nonstationary_confirmatory/runs/latest`;
- curated artifacts: `experiment/ollama_gemma4_e4b_nonstationary_confirmatory/results/`;
- verification: `ok`;
- completed variants: all four required variants;
- paired post-drift tasks: `600`;
- active post-drift OASG seeds: `5`;
- stable A2 active mutation rows: `0`;
- hard-floor regressions: `0`.

Primary comparison:

| comparison | result |
| --- | --- |
| strong static debt AUC | `1524` |
| OASG adaptive debt AUC | `1352` |
| debt delta | `-172`, CI `[-222, -125]` |
| debt reduction | `1129` bps |
| closure | `259/600 -> 300/600` |
| cost-to-close delta | `-87081`, CI `[-104210, -69629]` |

Control comparisons:

| comparison | debt delta | CI |
| --- | ---: | --- |
| OASG vs observe-only | `-172` | `[-222, -125]` |
| OASG vs rule-adaptive | `-98` | `[-169, -28]` |

Ablation and drift-class reading:

| subset | debt delta | reduction | CI | interpretation |
| --- | ---: | ---: | --- | --- |
| mixed-only | `-118` | `1639` bps | `[-158, -78]` | strongest supported effect |
| mild-only | `-50` | `1562` bps | `[-76, -27]` | supported, but not sufficient for broad confirmation |
| no-Phase-D aggregate | `-54` | `672` bps | `[-82, -28]` | support outside Phase D exists |
| structural-only | `-4` | `83` bps | `[-12, 0]` | below the `500` bps support threshold |

Scientific interpretation:

- The result supports post-drift workflow recovery over the Phase-A-calibrated strong static
  workflow in this frozen local `gemma4:e4b` protocol.
- The effect is not explained by observe-only measurement or by the simple rule-adaptive control.
- The strongest support is in mixed reversion / policy-retirement-sensitive drift; mild drift also
  improves, but structural-only support is too small for broad confirmation.
- `classification_receipt.json` sets `effect_claim_allowed` to `false`, because this repository
  reserves broad confirmatory effect claims for `oasg_nonstationary_confirmed`.
- This is not evidence that the model became more intelligent and not a universal OASG
  effectiveness proof.

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

Supported by the completed main all-variant real run:

- OASG adaptive showed post-drift operational recovery over the Phase-A-calibrated strong static
  workflow in this frozen local `gemma4:e4b` protocol.
- The support is strongest for mixed reversion / policy-retirement-sensitive drift, with additional
  mild-drift support.
- The result remains favorable after cost-to-close accounting in the primary comparison.

Not supported by this run:

- A broad `oasg_nonstationary_confirmed` claim across all drift classes.
- Strong structural-only support under the configured `500` bps support threshold.
- OASG universally improves all agents.
- The model became more intelligent.
- The oracle control is deployable.
- Synthetic/demo evidence is sufficient for promotion.
