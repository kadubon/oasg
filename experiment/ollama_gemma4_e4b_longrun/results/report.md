# OASG x Ollama Long-Running Experiment Report

Classification: `inconclusive_no_active_policy`
Model: `gemma4:e4b`
Preflight: `ok`

## Primary Endpoint

| condition | eval tasks | closed | debt AUC | unresolved | retries |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline_fixed | 408 | 276 | 272 | 132 | 0 |
| oasg_observe_only | 408 | 277 | 269 | 131 | 0 |
| oasg_adaptive | 0 | 0 | 0 | 0 | 0 |

## Paired Epoch Effects

Adaptive minus baseline debt AUC: `0`
Adaptive minus baseline closure: `0`
Observe-only minus baseline debt AUC: `-3`
Bootstrap CI: `[0, 0]`

## OASG Receipts

Active promotions: `0`
Rejected receipts counted: `36`
Inconclusive receipts counted: `27`
Trial timeouts counted: `0`
Viability regressions counted: `0`

## Interpretation Rule

OASG effect is claimed only when active promotions are present and held-out operational debt improves without hard-floor regression.