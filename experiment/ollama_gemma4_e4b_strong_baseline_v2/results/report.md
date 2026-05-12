# OASG Strong-Baseline v2 Result

Final classification: `no_incremental_effect_vs_strong_baseline`

This run tested whether OASG could add measurable workflow-operation value after starting from a
calibration-selected strong static workflow policy. The answer for this run is no: OASG passed the
readiness stages and active policy changes were available, but held-out evaluation did not show an
incremental improvement over the strong static baseline.

This is not a universal negative result for OASG. It is negative evidence for the current
implementation, local `gemma4:e4b`, this frozen strong-baseline workload, and the preregistered
decision thresholds.

## Integrity

- Model: local Ollama `gemma4:e4b`
- Seeds: `20260509`, `20260510`, `20260511`, `20260512`, `20260513`
- Held-out paired task count: `680`
- Verification status: `ok`
- Invalid ledgers: none reported
- Metrics hash: `sha256:5b941c30abd71ecff639e2fdb76edcb070bb75c1564efef8a594b006eaecdfbc`

## Stage Results

| stage | status | interpretation |
| --- | --- | --- |
| Stage 0: strong baseline qualification | `strong_baseline_qualified` | The calibrated strong static policy improved debt AUC over weak fixed by `7861` bps on calibration tasks. |
| Stage 1: incremental headroom | `debt_headroom_exists` | Canary trials found residual headroom: 43 qualified incremental candidates, including 30 debt-improving and 13 efficiency-improving candidates. |
| Stage 2: adaptive readiness | `adaptive_from_strong_ready` | OASG produced active changes in all 5 seeds, meeting the required `4/5` seed threshold. |
| Stage 3: held-out evaluation | completed | The active changes did not improve held-out performance over the strong static baseline. |

## Held-Out Condition Summaries

| condition | tasks | closed | debt AUC | cost units | parse failures | validation failures | unresolved obligations | hard-floor regressions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `strong_static_calibrated` | 680 | 463 | 434 | 1580136 | 0 | 217 | 217 | 0 |
| `strong_rule_adaptive_control` | 680 | 463 | 440 | 1602751 | 6 | 217 | 217 | 0 |
| `strong_positive_control` | 680 | 463 | 434 | 1575900 | 0 | 217 | 217 | 0 |
| `oasg_adaptive_from_strong` | 680 | 463 | 436 | 1587788 | 2 | 217 | 217 | 0 |

## Primary Comparison

Primary comparison: `oasg_adaptive_from_strong` vs `strong_static_calibrated`

- Closure delta: `0`
- Debt AUC delta: `+2`
- Debt bootstrap CI: `[0, 5]`
- Cost-to-close delta: `+7652`
- Cost bootstrap CI: `[1534, 14346]`
- Parse failure delta: `+2`
- Validation failure delta: `0`
- Retry delta: `0`
- Hard-floor regression count: `0`

The preregistered effect claim required an active OASG change plus a debt AUC reduction or an
efficiency gain over the strong static baseline without hard-floor regression. The observed deltas
went in the wrong direction: OASG was slightly worse on debt AUC and cost-to-close.

## Controls

- `strong_positive_control` matched the strong static baseline on debt AUC and slightly improved
  cost-to-close. This suggests the strong baseline had little remaining debt headroom on held-out
  tasks.
- `strong_rule_adaptive_control` was worse than strong static on debt and cost, so the simple rule
  adaptive control did not explain an unobserved OASG advantage.
- OASG was better than the rule-adaptive control, but the registered primary question was whether
  OASG improved over the strong static baseline. It did not.

## Scientific Interpretation

This result supports three narrow conclusions:

1. The strong-baseline v2 protocol is capable of running through qualification, readiness, and
   held-out evaluation without invalid ledgers.
2. OASG can identify and promote candidate changes during readiness, but those readiness changes
   did not transfer into a held-out incremental improvement in this run.
3. For this workload and model, the calibrated strong static workflow already captured most of the
   operational gain available to the current policy catalog.

This result does not support these claims:

- It does not show that OASG has no effect in general.
- It does not negate the earlier weak-baseline positive result.
- It does not show that the model became more or less intelligent.
- It does not prove that stronger OASG mutators, better canary selection, or a different
  nonstationary workload could not produce incremental gains.

## Public Artifacts

- `metrics.json`: full metrics, comparisons, ledger receipts, paired task rows, and decision data.
- `verification.json`: ledger and pairing integrity summary.
- `strong_baseline_qualification_receipt.json`: Stage 0 receipt.
- `incremental_headroom_receipt.json`: Stage 1 receipt.
- `adaptive_readiness_from_strong_receipt.json`: Stage 2 receipt.
- `promotion_diagnostic.json`: active-change and readiness diagnostic.
- `final_strong_v2_classification_receipt.json`: final classification receipt.
- `seed_table.csv`, `epoch_table.csv`, `paired_task_table.csv`: tabular summaries.
