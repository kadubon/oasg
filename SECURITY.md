# Security Policy

OASG is local-first and network-free by default. The trusted core should not call model providers,
external APIs, or shell commands unless the user explicitly invokes an adapter or runner that does
so. Workflow optimization is limited to workflow-policy state; OASG does not train model weights.

## Supported Version

Security review currently targets the reference package version in `pyproject.toml`.

## Reporting

When the repository is published, report vulnerabilities through the GitHub security advisory
channel. Until then, report issues directly to the maintainer.

Please include:

- the command or API entrypoint used;
- the input ledger, policy, or receipt shape needed to reproduce the issue;
- whether the issue can create false positive promotion, unsafe external effects, secret exposure,
  or ledger integrity failure.

## Security Model

Security-sensitive invariants:

- Missing, stale, rejected, conflicted, overflowed, or untrusted evidence must not create positive
  credit.
- Unknown taint is treated conservatively.
- External effects are rejected by default unless explicitly enabled by policy and backed by
  receipts.
- `demo-replay` and synthetic evidence are not eligible for production `active_promoted`.
- Automatic promotion requires runner-produced trial ledgers, positive evidence witnesses, shadow
  and lease receipts, rollback availability, and a valid workflow-policy patch.
- Adapters are observation channels only. They cannot act as evaluators or gates.

## Runner Safety

The `local-command` runner is explicit and shell-free:

- command arguments are passed as argv lists, not shell strings;
- common shell executables are rejected;
- stdout/stderr are hashed in receipts;
- a zero exit code without a valid sealed OASG trial ledger is rejected;
- network, financial, communication, secret-touching, and irreversible effects are not enabled by
  default.

## Publication Checklist

Before publishing a release:

```bash
uv run pytest
uv run ruff check
uv run mypy src
uv run oasg conformance run examples/conformance
uv build
```

Also inspect generated artifacts before committing them:

- keep experiment `runs/` directories as local raw output; publish only curated summaries and
  receipts that were deliberately copied into `results/`;
- scan public docs, curated artifacts, and built packages for local absolute paths, local usernames,
  API keys, bearer tokens, authorization headers, and `.env` references;
- confirm wheel contents contain only package files and metadata;
- confirm source distributions do not include raw run payloads beyond intentional
  `runs/.gitignore` placeholders.

Experiment `runs/`, caches, `.env` files, build artifacts, coverage output, and local optimizer
state are intentionally ignored.
