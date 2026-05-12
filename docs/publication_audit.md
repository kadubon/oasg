# Publication Audit

Date: 2026-05-13

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

- README explains purpose, uniqueness, limits, five-minute mental model, minimal-agent integration,
  CLI map, model integration, rejection statuses, experiment evidence, DOI citation, and
  reproducibility.
- SECURITY describes supported version, reporting, security model, runner safety, and publication
  checklist.
- CITATION.cff contains the Zenodo DOI `10.5281/zenodo.20107660`.
- Architecture documentation states the implementation/theory version distinction.
- Quickstart, minimal-agent integration, framework-adapter, and conformance examples include
  runnable or dependency-guarded commands.

The old `CONTRIBUTING.md` file was intentionally removed.

## Experiment Evidence Review

The README reports all local Ollama `gemma4:e4b` experiment outcomes, including null,
inconclusive, workload-not-sensitive, and positive decisive runs.

The strongest positive result is limited to the decisive experiment's frozen workload, model,
validators, prompts, implementation, and thresholds. It is not presented as universal proof.

The strong-baseline v2 protocol now has a completed real run. Its final classification is
`no_incremental_effect_vs_strong_baseline`: readiness passed, but held-out evaluation did not show
incremental OASG value over the calibrated strong static workflow. The README and experiment report
state this as negative evidence for this implementation/workload/model combination, not as a
universal negative result.

Curated strong-baseline v2 artifacts are in
`experiment/ollama_gemma4_e4b_strong_baseline_v2/results/`. The generated `runs/` directory remains
ignored, while selected receipts, metrics, tables, verification, and report files were copied into
the public results directory after a local-path and secret-string scan.

## Build And Quality Checks

Commands run after public-surface cleanup:

```bash
uv run pytest
uv run ruff check
uv run mypy src
uv run oasg conformance run examples/conformance
uv build
```

Observed results after strong-baseline v2 result curation:

- `pytest`: 97 passed.
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

Additional post-experiment public-surface scan on 2026-05-13:

- No local absolute paths or local username strings were found in the curated strong-baseline v2
  result artifacts.
- No API keys, bearer tokens, or authorization strings were found in the curated artifacts.
- The only localhost references are documented Ollama endpoint checks and not credentials.
- Built wheel and source distribution were scanned for local absolute paths and the local username;
  no matches were found. The wheel contains package files only; the source distribution includes
  curated docs, tests, examples, and experiment result summaries, but not generated run payloads
  beyond the `runs/.gitignore` placeholders.

## Release Position

The project is public-ready as an alpha research/reference implementation:

- suitable for controlled local workflow-policy optimization and reproducible experiments;
- conservative by design, with rejection preferred over false promotion;
- not a claim of universal agent improvement, sandboxing, semantic truth, or model-weight learning.
