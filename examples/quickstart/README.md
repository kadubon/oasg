# OASG quickstart example

Generate the deterministic quickstart artifacts with:

```bash
uv run oasg demo quickstart --out examples/quickstart
uv run oasg gate --baseline examples/quickstart/baseline.jsonl --candidate examples/quickstart/candidate.jsonl --contract examples/quickstart/comparison_contract.json --workload examples/quickstart/workload_manifest.json --witnesses examples/quickstart/positive_evidence_witnesses.json
uv run oasg optimize run --history examples/quickstart/baseline.jsonl --library examples/quickstart/workflow_library.json --out-dir examples/quickstart/optimizer_run
```

The candidate ledger improves `KLB_2.pure_read`. The sidecar witness binds that
claim to the candidate ledger prefix, comparison contract, workload manifest,
and KLB receipt. The reference gate should return `safe_promotion`.
The optimizer command demonstrates the broader pressure/scheduler/mutator loop
and writes an `optimizer_run_receipt.json` plus workflow library state.
