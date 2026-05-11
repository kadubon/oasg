# OASG Strong-Baseline Effect Report

Classification: `promotion_mechanism_failure_vs_strong_baseline`
Strong baseline qualification: `strong_baseline_qualified`
Adaptive readiness: `promotion_mechanism_failure_vs_strong_baseline`

## Interruption Note

Run id: `20260511T113612Z`

This run was manually interrupted during Stage 2 held-out evaluation after the adaptive readiness
gate had already failed. The interruption was intentional and scientifically appropriate: the
experiment was designed to test whether OASG adds value after starting from a calibration-selected
strong static workflow, but the prerequisite adaptive mechanism did not activate.

Readiness facts:

- Required active seeds: `4`
- Observed active seeds: `0`
- Trial receipts: `5`
- Trial status count: `trial_not_improved = 5`
- Active OASG policy changes: none

Because no active OASG policy change existed, completing the remaining held-out evaluation would
not measure incremental OASG adaptation. It would mostly compare the same strong static policy
against itself under the `oasg_adaptive_from_strong` label. Therefore no OASG effect claim is made
from this run.

The partial Stage 2 data below is retained as diagnostic evidence only. It is not a confirmatory
effect estimate.

## Condition Summaries

| condition | tasks | closed | debt AUC | retries | active epochs |
| --- | ---: | ---: | ---: | ---: | ---: |
| weak_fixed | 272 | 0 | 816 | 0 | 0 |
| observe_only | 272 | 187 | 170 | 0 | 0 |
| strong_static_calibrated | 136 | 95 | 82 | 0 | 0 |
| strong_rule_adaptive_control | 136 | 95 | 82 | 0 | 0 |
| oasg_adaptive_from_strong | 136 | 95 | 82 | 0 | 0 |

## Primary Strong-Baseline Comparison

OASG vs strong static debt delta: `0`
OASG vs strong static bootstrap CI: `[0, 0]`
OASG vs rule-adaptive debt delta: `0`

Effect is claimed only for `oasg_incremental_effect_confirmed_vs_strong_baseline`.

## Scientific Interpretation

- The workload was sensitive enough to construct a strong static workflow: Stage 0 qualified the
  strong baseline.
- OASG did not find a runner-ledger-backed policy change that improved on that strong baseline
  during readiness.
- The appropriate conclusion is not "OASG has no effect in general." It is: under this strong
  baseline protocol, this implementation did not operationalize an incremental adaptive policy
  improvement before evaluation.
- The interrupted Stage 2 rows are useful for runtime and baseline diagnostics, but they cannot
  rescue the primary OASG effect question because adaptive activation was absent.
