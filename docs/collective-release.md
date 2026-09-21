# Collective release qualification

The base CI and mandatory native CI cover Linux, macOS and Windows on Python 3.12
and 3.14. Native missing dependencies fail qualification. Each new module must
reach at least 95% statement and 90% branch coverage, separately; legacy coverage
is recorded without changing its threshold. Security-sensitive branches are not excluded.

```bash
uv sync --locked --group native
uv run ruff check
uv run mypy src
uv run --group native pytest --cov=oasg.collective --cov-branch --cov-report=json:coverage.json
uv run python scripts/check_collective_coverage.py coverage.json
uv run pip-audit -l
```

Native dependencies are distributed artifacts locked by hash, with installed source
and resource hashes in `collective/resources/companions.json`. Audit tools may skip
GitHub-only projects absent from their index; that is not a vulnerability clearance.
Third-party licenses remain in their separately installed distributions.

Release ordering uses exactly one trigger: manually dispatch `release.yml` on the
accepted main commit with its exact unused version. Main's 12 base/native CI checks
must pass. The workflow repeats qualification, builds once, checks metadata and
archive contents, and installs both archives in fresh directories outside checkout.
Dependency retrieval occurs only during setup. Runtime socket use is blocked in
the parent and fresh child. Installed checks include legacy CLI/conformance,
native two-cycle execution, failed later use, withdrawal, replay and reconciliation.

The build emits a source/contract/companion manifest, qualification report and
SHA256SUMS. The minimal publish job downloads those same bytes, checks hashes,
and uses the official PyPA OIDC action with publish attestations. Only that job
has `id-token: write`. Configure environment `pypi` with required owner review and
main-only deployment before dispatch. Register the exact PyPI pending publisher
for owner `kadubon`, repository `oasg`, workflow `release.yml`, environment `pypi`.
A missing registration or approval is a real publication barrier.

After PyPI publication the workflow creates the version tag and GitHub Release
at the qualified source commit, uploads unchanged files, then verifies fresh
no-cache public PyPI wheel and sdist downloads and offline checks. Check public
index hashes and actual publish-attestation identity independently. Checksums,
PyPI publish attestations and source-build provenance are different claims; this
workflow does not claim a source-build attestation.

A failed/skipped job is not completion. Preserve partial state; do not overwrite
tags, rebuild substituted bytes in the publish job, use a token workaround or
delete published artifacts. Report GitHub and PyPI/public-install states separately.
No existing Wiki was found; Wiki updates are NOT_APPLICABLE.
