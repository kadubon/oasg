# Publication Audit

Date: 2026-05-10

This audit records the public-readiness checks for the current OASG reference package.

## Scope

Reviewed public surface:

- root README and security policy;
- package metadata;
- CI workflow;
- quickstart and conformance examples;
- architecture documentation;
- security-relevant runner, adapter, library, ledger, and gate surfaces;
- package build artifacts.

## Security Review

Security posture:

- The trusted core is local-first and network-free by default.
- The OpenAI-compatible HTTP adapter is opt-in and validates endpoint scheme and private/local host
  usage.
- The local-command adapter and runner use argv lists and reject shell executables.
- Runner stdout and stderr are hashed in receipts.
- A successful command without a valid sealed OASG trial ledger is rejected for trial evidence.
- `demo-replay` is treated as demo/smoke evidence and is not a production active-promotion source.
- Automatic active promotion requires witness-backed dominance, runner-produced trial ledgers,
  shadow and lease receipts, rollback availability, and a valid workflow-policy patch.
- Unknown secret taint and disallowed effect classes fail closed.

Residual limits:

- OASG does not provide a sandbox. Users running local-command harnesses are responsible for the
  host execution boundary.
- OASG does not prove semantic truth. Semantic validators are observable channels, not absolute
  judges.
- Dependency vulnerability scanning was not performed with `pip-audit` in this workspace.

## Documentation Review

Public entry points are present:

- README explains purpose, uniqueness, limits, quickstart, first-agent integration, CLI map,
  model integration, rejection statuses, experiment evidence, and reproducibility.
- SECURITY describes supported version, reporting, security model, runner safety, and publication
  checklist.
- Architecture documentation states the implementation/theory version distinction.
- Quickstart and conformance examples include runnable commands.

The old `CONTRIBUTING.md` file was intentionally removed.

## Experiment Evidence Review

The README reports all local Ollama `gemma4:e4b` experiment outcomes, including null,
inconclusive, workload-not-sensitive, and positive decisive runs.

The strongest reported result is limited to the decisive experiment's frozen workload, model,
validators, prompts, implementation, and thresholds. It is not presented as universal proof.

## Build And Quality Checks

Commands run after public-surface cleanup:

```bash
uv run pytest
uv run ruff check
uv run mypy src
uv run oasg conformance run examples/conformance
uv build
```

Observed results:

- `pytest`: 83 passed.
- `ruff`: all checks passed.
- `mypy`: no issues in 36 source files.
- conformance: `status: ok`.
- `uv build`: built `oasg-1.1.0` wheel and source distribution.

Package artifact inspection:

- Wheel contains only package files and metadata.
- Wheel does not contain `CONTRIBUTING`, `__pycache__`, `.env`, experiment runs, or generated
  result files.
- Source distribution includes project documentation, tests, examples, and curated experiment
  protocols/results. Generated experiment run contents remain excluded by `.gitignore`.
- Public files and built artifacts were scanned for local absolute paths and the local username;
  no matches remained outside the ignored virtual environment.

## Release Position

The project is public-ready as an alpha research/reference implementation:

- suitable for controlled local workflow-policy optimization and reproducible experiments;
- conservative by design, with rejection preferred over false promotion;
- not a claim of universal agent improvement, sandboxing, semantic truth, or model-weight learning.
