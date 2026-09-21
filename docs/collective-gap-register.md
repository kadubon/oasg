# Phase 3 requirement and evidence register

Initial inspection: OASG `7593f74b5d6a4701865dc97b079c3e725c4fd7ee`,
1.1.0, Alpha, Python >=3.12; clean main, no open PRs. Existing CI covers
three operating systems. No release workflow or repository AGENTS.md exists.
Existing gate, canonicalization, library CAS/locks, rollback and rejection of
synthetic/demo promotion remain authoritative. Historical model experiments
are not executed for this change.

| Requirement | Existing evidence / extension | Qualification | Status |
| --- | --- | --- | --- |
| P3-A contracts and independent projection | Add bounded opt-in contracts and original-byte sources; keep legacy hashes and models | Closed fields, exact counters, source tampering, independent reconstruction | In progress |
| P3-B CCR trials | CCR 1.9.0 is released; public register/plan/reserve/lease/signed-result transitions | `test_collective_native.py`, native lease contention in `test_collective_native_guards.py` | Finite native path passes; full qualification pending |
| P3-B VEK | VEK 1.3.0 is released; model-only capacity retained | Native core, complete capacity contract, negative outcome and insufficient-budget checks | Finite native path passes; full qualification pending |
| P3-C OAWM | GitHub 0.2.0b0 distribution is hash-pinned | Native admission, fresh-process retrieval/use, withdrawal and source-bound receipt reconstruction | Finite native path passes; broader lifecycle counterexamples pending |
| Two cycles | Registered routing policy changes actual later execution | Independent line-set reference, existing gate/lifecycle, later eligible CCR task and cost replay | Native test passes; not operational evidence |
| P3-D compatibility | Existing base suite and three-OS CI | Baseline coverage first; new critical modules >=95% statements / >=90% branches | In progress |
| Delivery | GitHub v1.1.0 exists; public PyPI `oasg` endpoint currently 404 | Verify ownership/pending publisher, protected OIDC; build once; public wheel and sdist checks | Pending; trust not yet verified |
| Wiki | Enabled repository setting, but no first page or Git Wiki repository | Git remote lookup and authenticated GitHub Wiki page inspected | NOT_APPLICABLE per specification; no Wiki created |

The initial public PyPI OAWM endpoints also return 404. GitHub artifacts must
be hash-pinned independently; this observation does not erase historical
publication records or establish current public-index availability.
Companion repositories are read-only. The tested native subset is described in
`collective-profile.md`. This register does not claim complete Phase 3
qualification or publication. Per-module coverage remains below the requested
95% statement / 90% branch gates; remaining negative/lifecycle, installed-artifact,
interpreter/OS and publication checks must pass before release.
