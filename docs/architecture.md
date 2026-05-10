# OASG Architecture

The current reference package implements the `theory.md` v1.0 contract. The package version may
advance as the implementation, experiments, and public interfaces mature; the theory contract is
versioned separately.

```text
JSONL ledger
  -> ledger verifier
  -> reducer snapshot
  -> KLB_2 trace receipts
  -> pressure vector
  -> scheduler
  -> bounded broad mutation batch
  -> ledger-replay verification or explicit local-command harness trial ledgers
  -> dominance gate over observed trial state
  -> shadow / lease receipts bound to trial-ledger hashes
  -> executable workflow policy patch
  -> conflict-safe workflow library update
  -> durable optimizer checkpoint
```

The trusted path is intentionally small:

- canonical JSON and SHA-256 domain hashing;
- prefix-valid JSONL ledgers;
- deterministic reducers;
- bounded `KLB_2` enumeration with persisted abstract trace receipts;
- typed pressure vectors and persistent scheduler state;
- bounded local workflow-policy mutators over structured mutation patches;
- mutator profiles and outcome memory for cooldown / no-repeat behavior;
- sidecar positive evidence witnesses bound to trusted trial-ledger receipts;
- demo-only policy-effect semantics for smoke tests; production candidates cannot self-issue evidence;
- no-meta dominance gate;
- active promotion only after gate, runner-backed shadow, lease receipts, and a valid policy patch;
- `optimize watch` / lock-protected `optimize supervise` state over pending trials, the last observed append index, and ledger prefix;
- optional append-only ingestion of accepted lease trial ledgers.

Adapters are outside the gate. They may emit observable events, but they do not decide promotion.
