# Phase 3 requirement and evidence register

Initial inspection: OASG `7593f74b5d6a4701865dc97b079c3e725c4fd7ee`,
1.1.0, Alpha, Python >=3.12; clean main, no open PRs. Existing CI covers
three operating systems. No release workflow or repository AGENTS.md exists.
Existing gate, canonicalization, library CAS/locks, rollback and rejection of
synthetic/demo promotion remain authoritative. Historical model experiments
are not executed for this change.

| Requirement | Existing evidence / extension | Qualification | Status |
| --- | --- | --- | --- |
| P3-A contracts and independent projection | Add bounded opt-in contracts and original-byte sources; keep legacy hashes and models | Closed fields, exact counters, source tampering, independent reconstruction | Local qualification passed |
| P3-B CCR trials | CCR 1.9.0 is released; public register/plan/reserve/lease/signed-result transitions | `test_collective_native.py`, native lease contention in `test_collective_native_guards.py` | Finite native path passes; full qualification pending |
| P3-B VEK | VEK 1.3.0 is released; model-only capacity retained | Native core, complete capacity contract, negative outcome and insufficient-budget checks | Finite native path passes; full qualification pending |
| P3-C OAWM | GitHub 0.2.0b0 distribution is hash-pinned | Native admission, fresh-process retrieval/use, actual later failure, withdrawal and source-bound receipt reconstruction | Local qualification passed |
| Two cycles | Registered routing policy changes actual later execution | Independent line-set reference, existing gate/lifecycle, later eligible CCR task and cost replay | Native test passes; not operational evidence |
| P3-D compatibility | Existing base suite and three-OS CI | Baseline coverage first; new critical modules >=95% statements / >=90% branches | Local gates passed; remote CI pending |
| Delivery | GitHub v1.1.0 exists; public PyPI `oasg` endpoint currently 404 | Verify ownership/pending publisher, protected OIDC; build once; public wheel and sdist checks | Pending; trust not yet verified |
| Wiki | Enabled repository setting, but no first page or Git Wiki repository | Git remote lookup and authenticated GitHub Wiki page inspected | NOT_APPLICABLE per specification; no Wiki created |

The initial public PyPI OAWM endpoints also return 404. GitHub artifacts must
be hash-pinned independently; this observation does not erase historical
publication records or establish current public-index availability.
Companion repositories are read-only. The tested native subset is described in
`collective-profile.md`. This register does not claim publication. Windows/Python
3.14 local results: 194 native collective tests passed; base environment 231
passed and 76 optional native tests skipped. All 19 new modules pass separate
95% statement and 90% branch gates (combined coverage is not the gate).
Candidate wheel and sdist each passed fresh external installation and offline
legacy/native positive/negative two-cycle checks. Final accepted-commit artifact
qualification, remote interpreter/OS CI, trusted publication and public-install
verification remain distinct release gates.

Counterexample mapping: closed/source/grade/evidence/clock/holdout rules are in
`test_collective_boundaries.py`; actual gate controls in `test_collective.py`;
native versions, lease, shared-pool contention and VEK outcomes in
`test_collective_native_guards.py`; current receiver/policy/expiry/dependency
checks in `test_collective_current.py`; original signatures, snapshot tampering
and independent costs in `test_collective_replay_guards.py`; journal/CAS conflicts
in `test_collective_journal.py`; actual second use, negative service, withdrawal,
idempotency and crash windows in `test_collective_native.py`; separately retained
host authority and later reconciliation in `test_collective_host.py`; selected
injected native failures in `test_collective_host_faults.py`; read-only and opt-in
commands in `test_collective_cli.py`. This is selected fault testing, not a
universal mutation campaign. Multi-parent arbitrary workflows and distributed
OAWM writers remain outside this narrow profile.
