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
