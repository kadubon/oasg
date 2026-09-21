# OASG conformance fixtures

The v1.0 conformance runner creates temporary fixture ledgers and checks the
minimal invariant set required by `theory.md` v1.0:

- bounded `KLB_2` enumeration has exactly 73 trace classes;
- the quickstart candidate reaches `safe_promotion`;
- the optimizer can promote a witness-backed local workflow-policy patch;
- local-command-harness-backed shadow and lease receipts are recorded and bound to observed trial ledgers;
- optimizer seed candidates and manual grade patches do not self-issue automatic positive evidence;
- watch mode can append accepted lease observations after prefix verification;
- scheduler state and executable policy state persist in the workflow library;
- the reference implementation returns conservative statuses when evidence is
  missing, comparison state is invalid, lease caps overflow, or policy surfaces
  are stale/untrusted.

Run:

```bash
uv run oasg conformance run examples/conformance
```

Phase 3 uses separate additive schemas and semantic tests:

```bash
uv sync --locked --group native
uv run --group native pytest tests -k collective --cov=oasg.collective --cov-branch --cov-report=json:coverage.json
uv run python scripts/check_collective_coverage.py coverage.json
```

These tests execute pinned distributed CCR/OAWM/VEK contracts, reconstruct source
maps and signatures, run a later task in a fresh process, and reject substituted,
stale, synthetic and unresolved evidence. Schema parsing alone is not native
conformance. See [the supported subset](../../docs/collective-profile.md).
