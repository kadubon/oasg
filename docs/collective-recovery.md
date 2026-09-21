# Collective lifecycle and recovery

Use `oasg.collective.api.execute_registered` with a predeclared contract, exact
native registration and host-held private key. `example` constructs a disposable
finite registration and key; it is an executed integration test, not a production
provisioning interface. The key stays in the host process and is never given to
the worker. Retrieved memory is data, never executable configuration.

Durable intents precede native effects; acknowledgments retain original native
results. A crash between them leaves an unresolved operation. `collective status`
and `collective replay` inspect this without creating stores or resending work.
Unresolved operations require owning-system observation; there is no automatic
retry, implicit settlement or cross-store transaction guarantee.

The current host checks the original contract, dependency/code pins, source,
policy/library, receiver qualification, expiry, fresh CCR lease and fence before
actual later use. An old passing receipt cannot replace these checks. Local
withdrawal blocks scope before native memory retirement, signed CCR lifecycle
feedback and existing OASG policy rollback. It does not reverse external effects.
Native OAWM remains single-writer.

`oasg.collective.api.withdraw` requires the registered host key. Reconciliation
through `collective reconcile ROOT --apply` exports actual CCR history, runs native
CAIT analysis, independently checks it in CCR, and admits only that exact feedback.
Repeated identical delivery is idempotent. Changed source revisions produce new
immutable accounting snapshots; the latest pointer does not erase earlier ones.
Read-only replay checks original signatures, receipt manifests and physical event
identities against the acknowledged snapshot. It never authorizes new execution.
