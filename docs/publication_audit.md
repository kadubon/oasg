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
inconclusive, workload-not-sensitive, negative strong-baseline, positive decisive, and positive
time-boxed nonstationary runs.

The decisive weak-baseline result is limited to that experiment's frozen workload, model,
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

The nonstationary strong-baseline profile now has a completed curated run with classification
`oasg_nonstationary_effect_confirmed_timeboxed`. It tested drift recovery and fail-closed
adaptation under a short time-boxed local Ollama run. The final report states that strong static
calibration used Phase A only, primary metrics excluded Phase A, and OASG adaptive used only prior
online observations. The result is positive evidence for post-drift workflow adaptation over a
calibration-selected strong static workflow in this frozen protocol, not a universal effect claim.
Curated artifacts are in
`experiment/ollama_gemma4_e4b_nonstationary_strong_baseline/results/`.

The nonstationary confirmatory follow-up profile has been added as protocol-only public material in
`experiment/ollama_gemma4_e4b_nonstationary_confirmatory/`. It defines four variants: direct full
drift replication, no-mixed-reversion ablation, mixed-reversion-only probe, and delayed-drift
recovery. The protocol was audited so its analysis now separates aggregate, mild-only,
structural-only, mixed-only, and no-Phase-D effects with subset-local denominators. It also emits
drift-class, oracle-headroom-by-class, cost, and retirement/tightening receipts. Mixed-only gains are
classified as narrower phase-specific evidence rather than broad nonstationary support, and
confirmed support requires structural drift support plus acceptable cost-to-close uncertainty. The
checked mock/small run classifies `inconclusive_insufficient_power`; it is a wiring check and does
not support a confirmatory effect claim. A real all-variant Ollama run is required before the root
README may report a confirmatory result.

## Build And Quality Checks

Commands run after public-surface cleanup:

```bash
uv run pytest
uv run ruff check
uv run mypy src
uv run oasg conformance run examples/conformance
uv build
```

Observed results after auditing and tightening the nonstationary confirmatory protocol:

- `pytest`: 111 passed.
- `ruff`: all checks passed.
- `mypy`: no issues in 36 source files.
- `mypy` on the new nonstationary confirmatory experiment scripts: no issues in 5 files.
- conformance: `status: ok`.

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
