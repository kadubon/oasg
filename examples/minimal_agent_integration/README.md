# Minimal Agent Integration

This example shows the smallest useful OASG insertion point:

1. an existing agent emits an observable JSONL ledger;
2. OASG verifies and reduces that ledger;
3. OASG rejects a candidate with no concrete evidence;
4. OASG accepts a trial-backed candidate as `safe_promotion`.

The example is intentionally local-only and dependency-free beyond the `oasg` package.

## Run

```bash
uv run python examples/minimal_agent_integration/minimal_agent.py --out-dir examples/minimal_agent_integration/out
```

Inspect the generated ledgers and gate decisions:

```bash
uv run oasg ledger verify examples/minimal_agent_integration/out/baseline.jsonl
uv run oasg gate --baseline examples/minimal_agent_integration/out/baseline.jsonl --candidate examples/minimal_agent_integration/out/candidate_missing_witness.jsonl --contract examples/minimal_agent_integration/out/comparison_contract_missing_witness.json --workload examples/minimal_agent_integration/out/workload_manifest_missing_witness.json --witnesses examples/minimal_agent_integration/out/positive_evidence_witnesses_missing_witness.json
uv run oasg gate --baseline examples/minimal_agent_integration/out/baseline.jsonl --candidate examples/minimal_agent_integration/out/candidate_trial_backed.jsonl --contract examples/minimal_agent_integration/out/comparison_contract_trial_backed.json --workload examples/minimal_agent_integration/out/workload_manifest_trial_backed.json --witnesses examples/minimal_agent_integration/out/positive_evidence_witnesses_trial_backed.json
```

Expected statuses:

- `candidate_missing_witness` returns `rejected_no_concrete_positive_evidence`.
- `candidate_trial_backed` returns `safe_promotion`.

## What To Copy Into A Real Agent

- Emit one OASG event per meaningful workflow step.
- Include resource usage, retry counts, validation results, replay/rollback receipts, and unresolved
  obligations when available.
- Treat model/framework output as observation only.
- Let OASG reducers, trial receipts, witnesses, and gates decide whether a workflow-policy change
  can be promoted.

The toy `trial_receipt.json` in this example is only a minimal receipt shape. Production promotion
should use runner-produced shadow/lease ledgers from your actual workflow harness.
