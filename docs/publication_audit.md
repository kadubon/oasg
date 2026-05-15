# Publication Audit

Date: 2026-05-15

This audit records the public-readiness checks for the current OASG reference package.

## Scope

Reviewed public surface:

- root README and security policy;
- package metadata;
- CI workflow;
- quickstart and conformance examples;
- architecture documentation;
- security-relevant runner, adapter, library, ledger, and gate surfaces;
- repository ignore policy for local/generated outputs;
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

Repository hygiene:

- `.gitignore` excludes Python/tool caches, build outputs, coverage output, local `.env` files,
  editor/OS noise, profiler traces, local OASG optimizer state, and experiment `runs/` trees.
- Raw experiment run directories are treated as local provenance material, not public release
  artifacts. Public claims should reference curated `results/` summaries and receipts only.
- `runs/.gitignore` placeholders are retained so experiment layouts remain reproducible without
  publishing large raw run payloads.

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
inconclusive, workload-not-sensitive, negative strong-baseline, positive decisive, positive
time-boxed nonstationary, and narrowed confirmatory nonstationary runs.

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

The nonstationary confirmatory follow-up profile now has a completed real all-variant Ollama run in
`experiment/ollama_gemma4_e4b_nonstationary_confirmatory/results/`. It defines four variants:
direct full drift replication, no-mixed-reversion ablation, mixed-reversion-only probe, and
delayed-drift recovery. The final classification is `phase_specific_nonstationary_support`:
verification is
`ok`, all four required variants completed, the primary comparison has 600 paired post-drift tasks,
and OASG adaptive reduced debt AUC from `1524` to `1352` versus the Phase-A-calibrated strong static
baseline. Primary debt delta is `-172` with CI `[-220, -121]`; primary cost-to-close delta is
`-87081` with CI `[-104221, -70419]`; closure improves from `259/600` to `300/600`; hard-floor
regressions remain `0`.

The confirmatory result is scientifically positive but narrower than broad nonstationary
confirmation. OASG also beats observe-only (`-172`, CI `[-220, -126]`) and rule-adaptive (`-98`, CI
`[-170, -27]`), so the primary effect is not explained by measurement alone or by the simple
hand-coded adaptation control. The strongest supported class is mixed reversion / policy-retirement
sensitive drift (`-118`, 1639 bps, CI `[-160, -78]`), and mild drift also supports improvement
(`-50`, 1562 bps, CI `[-72, -28]`). The no-Phase-D aggregate is also positive (`-54`, 672 bps, CI
`[-81, -28]`). Structural-only movement is small (`-4`, 83 bps, CI `[-12, 0]`) and below the
configured 500 bps support threshold. Therefore the README reports phase-specific nonstationary
support rather than `oasg_nonstationary_confirmed`; `classification_receipt.json` has
`broad_effect_claim_allowed: false`, `phase_specific_effect_claim_allowed: true`, and legacy
`effect_claim_allowed: false`.

During this update, the drift-class interpretation label was tightened to use the same configured
support threshold as the final classifier, avoiding a misleading broad-support label when
structural-only movement is below threshold. The final classifier now distinguishes
`phase_specific_nonstationary_support` from the narrower `mixed_reversion_only_effect`: mild or
no-Phase-D support lifts the claim to phase-specific support, while mixed-only support remains the
narrower classification. The checked mock/small path remains a wiring check and does not support a
confirmatory effect claim.

The analyzer now reads completed variants in sorted order before bootstrap aggregation. This keeps
the curated confidence intervals and `metrics_hash` stable across repeated analysis processes.

## Build And Quality Checks

Commands run after public-surface cleanup:

```bash
uv run pytest
uv run ruff check
uv run mypy src
uv run oasg conformance run examples/conformance
uv build
```

Observed results after auditing, completing, and tightening the nonstationary confirmatory protocol:

- `pytest`: 113 passed.
- `ruff`: all checks passed.
- `mypy`: no issues in 36 source files.
- `mypy` on the new nonstationary confirmatory experiment scripts: no issues in 5 files.
- conformance: `status: ok`.
- `uv build`: built `dist/oasg-1.1.0.tar.gz` and `dist/oasg-1.1.0-py3-none-any.whl`.

Package artifact inspection:

- Wheel contains only package files and metadata.
- Wheel does not contain `CONTRIBUTING`, `__pycache__`, `.env`, experiment runs, or generated
  result files.
- Source distribution includes project documentation, tests, examples, and curated experiment
  protocols/results. Generated experiment run contents remain excluded by `.gitignore`.
- Public files and built artifacts were scanned for local absolute paths and the local username;
  no matches remained outside the ignored virtual environment.
- Current wheel and source distribution archive scan found `0` high-confidence secret/local-path
  matches and `0` raw run payloads. The source distribution includes only the intentional
  `runs/.gitignore` placeholders for run directories.
- Large-file review found the largest retained public files are curated experiment `results/`
  metrics and tables. They are retained because the README's scientific claims cite those summaries;
  high-volume raw run directories remain ignored.

Additional post-experiment public-surface scan on 2026-05-13:

- No local absolute paths or local username strings were found in the curated strong-baseline v2
  result artifacts.
- No API keys, bearer tokens, or authorization strings were found in the curated artifacts.
- The only localhost references are documented Ollama endpoint checks and not credentials.
- Built wheel and source distribution were scanned for local absolute paths and the local username;
  no matches were found. The wheel contains package files only; the source distribution includes
  curated docs, tests, examples, and experiment result summaries, but not generated run payloads
  beyond the `runs/.gitignore` placeholders.

Additional confirmatory-artifact scan on 2026-05-15:

- No local absolute paths or local username strings were found in
  `experiment/ollama_gemma4_e4b_nonstationary_confirmatory/results/`.
- No API-key, bearer-token, authorization, password, or token patterns were found in the curated
  nonstationary confirmatory result artifacts.
- The final public report and README explicitly mark `phase_specific_nonstationary_support` as
  narrowed phase-specific evidence, not broad `oasg_nonstationary_confirmed` support.

## Release Position

The project is public-ready as an alpha research/reference implementation:

- suitable for controlled local workflow-policy optimization and reproducible experiments;
- conservative by design, with rejection preferred over false promotion;
- not a claim of universal agent improvement, sandboxing, semantic truth, or model-weight learning.
