# OASG: Observable-only Autonomic Slack Gradient Theory

Version: 1.0

## Abstract

Observable-only Autonomic Slack Gradient Theory, abbreviated OASG, is a theory
and implementation specification for long-running AI-agent workflows that
improve their operational capability from their own observable history. OASG
does not define improvement as higher answer accuracy, model-weight change, or
approval by an external evaluator. It defines improvement as a certified
increase in the conservative lower bound of future safe, replayable,
rollback-aware, verifiable, authorized, and serviceable actions, or a certified
decrease in protected operational debt, while preserving all protected floors.

The guiding project vision is to build an AI-agent foundation that keeps
operating, learning, and moving without breaking: an autonomous workflow
substrate that metabolizes obligations, failures, evidence gaps, stale memory,
tool effects, replay gaps, rollback gaps, incidents, comparison debt, and
maintenance burden. OASG is the scientific contract for that substrate. It
studies long-term autonomous workflow capability, not semantic truth in general
and not model intelligence in isolation.

OASG uses append-only evidence ledgers, canonical hashing, deterministic
reducers, typed slack dimensions, protected debt vectors, finite-horizon
viability kernels, typed workflow pressure, shadow and lease receipts,
positive-evidence witnesses, and a no-meta dominance gate. Mutations may be
proposed by untrusted mechanisms, including language models, search procedures,
or hand-written heuristics. A mutation is promoted only when trusted receipts
show protected non-regression and concrete witness-backed improvement.

This v1.0 document freezes the pre-implementation theory and the conservative
reference profile for a language-independent OSS implementation. Python with uv
may be used for the reference implementation, but schemas, ledgers, receipts,
and conformance rules are language-independent.

## 1. Project Vision and Scientific Contract

### 1.1 Vision

The project vision is:

```text
Build an AI-agent foundation that does not break, learns operationally, and
continues acting by improving its own workflow from observable history.
```

In scientific terms:

```text
Study long-term autonomous operating capability of the whole agent workflow,
then reduce it to an implementable, receipt-backed self-improvement principle.
```

The unit of study is the workflow, not the model alone. The workflow includes
tasks, tools, memory, validators, replay, rollback, queues, incidents,
maintenance, comparison contracts, external effects, and authority boundaries.

### 1.2 OASG Improvement Claim

OASG improvement is a partial-order claim:

```text
candidate workflow >= baseline workflow
```

only when:

1. all protected coordinates are not worse;
2. finite-horizon future viability is not worse;
3. at least one declared coordinate strictly improves;
4. strict improvement has concrete positive evidence;
5. missing, stale, rejected, conflicted, overflowed, tainted-without-authority,
   migrated-without-bridge, or untrusted data gives no positive credit.

### 1.3 No-Meta Boundary

OASG does not depend on an external evaluator as the improvement oracle.
Semantic validators, human review, external tests, or domain-specific checkers
may appear as observable channels, but they do not replace the OASG gate. They
produce fallible receipts that enter ordinary protected dimensions.

The no-meta boundary is:

```text
untrusted proposal + trusted receipts + deterministic partial-order gate
```

There is no absolute judge inside the theory. There is a small trusted base:
canonical hashing, schemas, reducers, gates, bridge checkers, and effect
policies.

### 1.4 Non-Goals

OASG does not prove:

1. semantic truth of generated content;
2. model-weight improvement;
3. absence of all sandbox escapes;
4. optimality of mutation search;
5. correctness of untrusted tools, sensors, or validators;
6. safety outside declared observation coverage;
7. positive evidence from unobserved facts.

### 1.5 Claim Classes

| Claim class | Meaning | Required support |
| --- | --- | --- |
| Mathematical guarantee | Theorem over formal state and assumptions | Variables, transitions, order, assumptions, proof sketch |
| Operational certificate | Receipt produced by trusted reducers and gates | Ledger prefix, epoch vector, coverage, gate result |
| Engineering policy | Implementation default | Config, schema, tests, failure behavior |
| Empirical claim | Measured deployment result | Frozen comparison, exposure, contamination checks |

Only mathematical guarantees are theorems. Operational certificates are
conditional on trusted-base integrity, declared coverage, and valid ledger
prefixes.

## 2. Preliminaries and Conformance Profiles

### 2.1 Orders and Lattices

For a partially ordered set `(X, <=_X)`, write `x <_X y` when
`x <=_X y` and `x != y`. Product order is pointwise:

```text
x <=_prod y iff for every coordinate k, x_k <=_k y_k.
```

All public OASG dominance coordinates are normalized to better-is-larger order.
If a raw quantity is smaller-is-better, the reducer must reverse the order or
map it into a better-is-larger finite chain before gate comparison.

Each protected coordinate is a bounded lattice:

```text
L_j = (X_j, <=_j, bottom_j, top_j, meet_j, join_j)
```

where `bottom_j` is the worst certified value and `top_j` is the best certified
value.

### 2.2 Versioned Profiles

OASG separates theory version, conformance profile, ledger profile, schema
epoch, and trusted-base epoch.

```text
theory_version: 1.0
conformance_profile: OASG-REF-v0.1
ledger_profile: OASG-LEDGER-1
ledger_profile_epoch: OASG-LEDGER-1:2026-05-08
schema_epoch: schema-specific, record-type specific
trusted_base_epoch: implementation-specific trusted release
```

The theory version explains the mathematics. The conformance profile chooses a
reference implementation subset. The ledger profile fixes byte-level identity.
The schema epoch defines record shape. The trusted-base epoch defines reducer
and gate code.

### 2.3 Canonical Encoding and Hash Domains

Independent implementations must agree on canonical ledger bytes. The v1.0
ledger profile uses:

```text
canonical_profile: OASG-CJ-1
text_encoding: UTF-8 without BOM
line_ending: LF
record_hash_input: canonical JSON bytes without terminal LF
hash_algorithm: SHA-256
hash_display: lowercase hex with sha256: prefix
domain_separator_record: OASG:v1.0:record
domain_separator_integrity: OASG:v1.0:integrity
domain_separator_prefix: OASG:v1.0:prefix
domain_separator_genesis: OASG:v1.0:genesis
domain_separator_receipt: OASG:v1.0:receipt
```

`OASG-CJ-1` canonical JSON means:

1. object keys are sorted lexicographically by Unicode code point;
2. no insignificant whitespace is emitted;
3. strings are JSON escaped deterministically;
4. integers are decimal without leading zeros except `0`;
5. non-integer numbers are not used in hash-critical records unless encoded as
   strings with declared unit;
6. absent optional fields and explicit `null` are distinct;
7. arrays preserve order;
8. `record_type`, `schema_epoch`, `ledger_profile`, and `ledger_profile_epoch`
   are included in the hashed object.

### 2.4 Promotion Levels and Abstraction

OASG uses conservative abstraction when full concrete state, traces, or
receipts are too large to compute.

Concrete domains:

```text
D_X = concrete reduced states
D_T = concrete action traces
D_R = concrete receipt sets
D_G = concrete gate outcomes
```

Abstract domains:

```text
A_X = abstract reduced states
A_T = abstract trace classes
A_R = abstract receipt summaries
A_G = abstract gate outcomes
```

Abstraction and concretization maps:

```text
alpha_X: D_X -> A_X
gamma_X: A_X -> P(D_X)
alpha_T: D_T -> A_T
gamma_T: A_T -> P(D_T)
alpha_R: D_R -> A_R
gamma_R: A_R -> P(D_R)
alpha_G: D_G -> A_G
gamma_G: A_G -> P(D_G)
```

Soundness:

```text
x in gamma_X(alpha_X(x))
tau in gamma_T(alpha_T(tau))
r in gamma_R(alpha_R(r))
```

Forward simulation:

```text
F(tau, x) = x'
  implies
x' in gamma_X(Fhat(alpha_T(tau), alpha_X(x)))
```

Promotion levels:

| Level | Meaning |
| --- | --- |
| `safe_non_regression` | no represented concrete receipt violates protected coordinates |
| `safe_promotion` | safe non-regression plus concrete witness-backed strict improvement |
| `full_acceptance` | full concrete gate accepts with all positive and protected evidence |

Gate preservation:

```text
Gate_hat(alpha_R(r)) = safe_non_regression
  implies
forall r' in gamma_R(alpha_R(r)):
  Gate_full(r') does not reject any protected coordinate.
```

Safe promotion additionally requires:

```text
forall improved coordinate k:
  exists PositiveEvidenceWitness(k)
```

An abstract-only strict improvement is insufficient for promotion.

### 2.5 Epochs

| Epoch | Role |
| --- | --- |
| `ledger_profile_epoch` | Ledger byte identity and genesis profile |
| `schema_epoch` | Event and receipt schemas |
| `policy_epoch` | Action, effect, lease, semantic, and scheduler policy |
| `reducer_epoch` | Deterministic reducers |
| `gate_epoch` | Dominance gate predicates |
| `comparison_epoch` | Baseline and candidate comparison contract |
| `graph_epoch` | Boundary dependency graph |
| `trusted_base_epoch` | Trusted checker set and migration rules |

Any cross-epoch claim requires a bridge certificate that preserves protected
order.

## 3. Ledger Semantics

### 3.1 Event History

An event history at append index `n` is:

```text
H_n = (e_1, e_2, ..., e_n)
```

Append order is authoritative for reduction. Event time is an observed field
and may be late, wrong, adversarial, or ambiguous.

Every event record has at least:

```text
record_type
event_id
append_index
event_time
collector_id
ledger_profile
ledger_profile_epoch
schema_epoch
policy_epoch
workflow_id
component_id
parent_event_ids
event_type
payload_hash
payload_pointer
prev_integrity_hash
canonical_record_hash
integrity_hash
ledger_prefix_hash
coverage_scope
authority_scope
rejection_status
supersedes_event_ids
duplicate_policy
```

Payloads may be stored outside the ledger line, but the ledger line must
contain a canonical hash and enough metadata for deterministic reduction.

### 3.2 Hash Chain and Genesis

Let `canon(e_i)` be `OASG-CJ-1` bytes of the event object with
`canonical_record_hash`, `integrity_hash`, and `ledger_prefix_hash` removed.

Genesis depends on the ledger profile, not on the schema epoch:

```text
genesis_hash(ledger_profile_epoch) =
  sha256("OASG:v1.0:genesis" || ledger_profile_epoch)
```

Canonical record hash:

```text
canonical_record_hash(e_i) =
  sha256("OASG:v1.0:record"
         || ledger_profile_epoch
         || schema_epoch
         || record_type
         || canon(e_i))
```

Hash chain:

```text
prev_integrity_hash(e_1) = genesis_hash(ledger_profile_epoch)

integrity_hash(e_i) =
  sha256("OASG:v1.0:integrity"
         || prev_integrity_hash(e_i)
         || canonical_record_hash(e_i))
```

Prefix hash:

```text
ledger_prefix_hash(e_0) = genesis_hash(ledger_profile_epoch)

ledger_prefix_hash(e_i) =
  sha256("OASG:v1.0:prefix"
         || ledger_prefix_hash(e_{i-1})
         || integrity_hash(e_i))
```

### 3.3 Duplicate Policies

Duplicate event policies:

| Policy | Meaning |
| --- | --- |
| `reject_duplicate` | any duplicate `event_id` is rejected |
| `idempotent_same_hash` | duplicate is accepted only if canonical hash matches |
| `supersede_by_record` | update must reference superseded event |
| `quarantine_duplicate` | duplicate creates quarantine for affected scope |

### 3.4 Mixed-Schema Ledgers

A long-lived ledger may contain multiple schema epochs. Mixed-schema validity
requires schema migration records:

```text
schema_migration_record = (
  migration_id,
  from_schema_epoch,
  to_schema_epoch,
  affected_record_types,
  migration_map,
  negative_evidence_preservation,
  quarantine_preservation,
  fixture_results,
  trusted_base_epoch,
  ledger_prefix_hash_before,
  ledger_prefix_hash_after
)
```

Schema migration does not restart the ledger hash chain. It appends a record
under the same ledger profile. Records after migration may use the new schema
epoch, while prior records remain immutable and prefix-verifiable.

### 3.5 Ledger State Machine

Ledger verification produces:

```text
ledger_prefix_valid
rejected_canonical_hash_mismatch
rejected_duplicate_policy
rejected_schema_epoch_missing
rejected_schema_migration_invalid
quarantined_prefix_gap
quarantined_hash_chain_mismatch
quarantined_fork_detected
quarantined_unknown_genesis
```

Only `ledger_prefix_valid` can support positive credit.

State transitions:

```text
valid_prefix + valid_record -> valid_prefix
valid_prefix + rejected_record -> valid_prefix with rejection evidence
valid_prefix + valid_schema_migration -> valid_prefix under new schema epoch
valid_prefix + hash_mismatch -> quarantined_hash_chain_mismatch
valid_prefix + fork_detected -> quarantined_fork_detected
quarantined + trusted_recovery_bridge -> valid_prefix or retired_ledger
```

Supersession appends a new record and never overwrites an old record. Late
contrary evidence appends a supersession or quarantine record; backdating
affects interpretation and future gates, not ledger mutability.

## 4. Workflows, Actions, and Mutation Lifecycle

### 4.1 Workflow State

A workflow state is:

```text
W_n = (C_n, E_n, Pi_n, Tau_n)
```

| Symbol | Meaning |
| --- | --- |
| `C_n` | finite component set |
| `E_n` | workflow dependency graph |
| `Pi_n` | workflow policy and action contracts |
| `Tau_n` | trusted base active at append index `n` |

### 4.2 Action Contract

An action contract is:

```text
a = (
  action_class,
  required_slack,
  required_evidence,
  required_authority,
  semantic_scope,
  effect_class,
  replay_contract,
  rollback_contract,
  validator_contract,
  obligation_delta,
  horizon_transition_class
)
```

The concrete action set `A_n` may be large or unbounded. OASG computes future
viability over a finite abstraction `Ahat_n`.

### 4.3 Mutation Contract

A mutation is:

```text
mu = (
  mutation_id,
  target_components,
  change_type,
  declared_scope,
  dependency_boundary,
  expected_improvement_coordinates,
  protected_coordinates,
  shadow_contract,
  lease_contract,
  effect_policy,
  rollback_policy,
  comparison_contract_id,
  trusted_base_impact
)
```

Mutation generation is untrusted.

### 4.4 Mutation Lifecycle

Mutation lifecycle states:

```text
proposed
shadowed
leased
safe_non_regression
safe_promotion
active_promoted
rejected
inconclusive
quarantined
retired
```

Allowed transitions:

```text
proposed -> shadowed
proposed -> rejected | inconclusive | quarantined
shadowed -> leased
shadowed -> rejected | inconclusive | quarantined
leased -> safe_non_regression
leased -> safe_promotion
leased -> rejected | inconclusive | quarantined
safe_non_regression -> retired | inconclusive
safe_promotion -> active_promoted
safe_promotion -> retired
active_promoted -> retired | quarantined
rejected -> retired
inconclusive -> proposed | retired
quarantined -> retired
```

`safe_promotion` is not the same as active deployment. `active_promoted`
requires workflow-promotion effect policy, valid dominance receipt, and no
unclosed hard-stop incident in the promotion scope.

## 5. Observation Model

### 5.1 Observable-Only Restriction

Reducers may use only:

1. ledger-prefix-valid accepted records;
2. rejection records;
3. coverage certificates;
4. trusted schema and policy definitions;
5. trusted reducer and gate code identified by epoch;
6. payloads whose canonical hash matches the event record.

No unrecorded fact is positive evidence.

### 5.2 Collectors and Append Authority

A collector is:

```text
collector = (
  collector_id,
  authority_scope,
  schema_epoch,
  integrity_method,
  compromise_state,
  coverage_contract,
  expiry
)
```

`compromise_state` is:

```text
trusted
suspended
conflicted
compromised
expired
unknown
```

Only `trusted` collectors may create positive evidence. Records from other
states may create debt, incident evidence, or missingness, but cannot improve
slack, viability, or dominance coordinates.

If append authority is compromised, the affected coverage scope enters hard
quarantine until an external trusted-base recovery bridge is provided. OASG
does not self-certify recovery from append-authority compromise.

### 5.3 Coverage and Missingness

A coverage certificate is:

```text
coverage = (
  coverage_id,
  scope,
  append_interval,
  collector_ids,
  observed_event_types,
  known_blind_spots,
  sampling_rule,
  expected_min_records,
  missingness_policy,
  expiry,
  integrity_hash
)
```

Missingness policies:

| Policy | Meaning |
| --- | --- |
| `hard_negative` | Missing evidence violates a hard floor |
| `protected_negative` | Missing evidence worsens a protected coordinate |
| `neutral` | Missing evidence gives no credit and no direct charge |
| `inconclusive` | Gate cannot accept because evidence is insufficient |

If a dimension does not declare a missingness policy, default is
`inconclusive`.

## 6. Trusted Base and Migration

### 6.1 Trusted Base

The trusted base at append index `n` is:

```text
Tau_n = (
  schema_set,
  canonical_hashing,
  reducer_set,
  gate_set,
  bridge_checker_set,
  effect_policy_set,
  collector_authority_table,
  release_manifest
)
```

OASG is no-meta because untrusted proposals are accepted only through this
small trusted base. It is not trustless.

### 6.2 Migration Preorder

Let `D_old` and `D_new` be dominance domains under old and new trusted-base
epochs. A migration bridge defines coordinate maps:

```text
mig_map_j: X_old_j -> X_new_j
```

With better-is-larger normalization:

```text
new_state <=_mig old_state
  iff
forall protected coordinate j in retained_coordinates:
  new_state_j <=_new_j mig_map_j(old_state_j)
```

Migration may preserve or degrade claims, but cannot improve a protected
coordinate by changing schemas, reducers, or gates.

### 6.3 Coordinate Rename, Split, Merge, and Retirement

Trusted-base migration must declare every protected coordinate as:

```text
retained
renamed
split
merged
retired
new_coordinate
```

Rules:

1. `renamed` coordinates use an order-preserving bijective map.
2. `split` coordinates map one old coordinate to several new coordinates, each
   no better than the old evidence supports.
3. `merged` coordinates use the meet of old coordinates unless a bridge proves
   a more precise conservative map.
4. `retired` protected coordinates map to conservative `bottom` in the new
   dominance vector unless an explicit bridge proves the retired claim is
   represented by another protected coordinate.
5. `new_coordinate` starts at `bottom` or `inconclusive` until positive
   evidence exists under the new epoch.

### 6.4 Acyclic Trusted-Base Migration

A mutation changing schemas, reducers, gates, canonical hashing, effect policy,
collector authority, or bridge checkers has `trusted_base_impact != none`. It
cannot be certified by the changed component itself.

Migration from `Tau_old` to `Tau_new` requires:

```text
trusted_base_bridge = (
  bridge_id,
  from_trusted_base_epoch,
  to_trusted_base_epoch,
  changed_components,
  unchanged_checker_root,
  coordinate_maps,
  coordinate_policy,
  historical_migration_relation,
  monotone_migration_proof,
  negative_evidence_preservation,
  quarantine_preservation,
  missingness_preservation,
  prior_receipt_preservation,
  protected_floor_preservation,
  fixture_results,
  release_manifest_hash,
  authority_signature,
  expiry
)
```

Bridge validity:

```text
forall old histories H:
  Migrate(R_old(H)) <=_mig R_old(H)
```

where `Migrate` includes reduced state, receipts, quarantine records, rejected
records, missingness charges, and protected floors. If no acyclic bridge exists,
the mutation is quarantined. A checker never certifies its own promotion.

## 7. Ordered Algebra of Slack and Debt

### 7.1 Slack Dimension Definition

A slack dimension is:

```text
SlackDimension_j = (
  dimension_id,
  carrier X_j,
  order <=_j,
  bottom_j,
  top_j,
  meet_j,
  join_j,
  combine_j,
  degrade_j,
  saturate_j,
  unit,
  orientation,
  capacity_rule cap_j,
  load_charge ell_j,
  debt_charge delta_j,
  risk_charge rho_j,
  missingness_policy miss_j,
  hard_floor floor_j,
  proof_obligation_set_j
)
```

`combine_j` is an ordered commutative monoid operation for accumulating charges
where appropriate. Ordinal dimensions may use lattice joins instead of numeric
addition.

### 7.2 Slack Charge Maps

For reduced state `X_n`:

```text
Cap_j(n)  = cap_j(X_n)
Load_j(n) = ell_j(X_n)
Debt_j(n) = delta_j(X_n)
Risk_j(n) = rho_j(X_n)
```

Slack is:

```text
S_j(n) = saturate_j(
  degrade_j(
    degrade_j(
      degrade_j(Cap_j(n), Load_j(n)),
      Debt_j(n)
    ),
    Risk_j(n)
  )
)
```

Numeric better-is-larger dimensions specialize to bounded subtraction. Ordinal
dimensions never use informal subtraction.

### 7.3 ProofObligation Contract

Every dimension schema must declare a `ProofObligation` set:

```text
ProofObligation = (
  obligation_id,
  obligation_type,
  target_dimension,
  fixture_inputs,
  expected_outputs,
  checker_epoch,
  failure_status
)
```

Required obligation IDs:

| ID | Requirement |
| --- | --- |
| `PO_ORDER_TOTAL_OR_PARTIAL` | Order is explicit and deterministic |
| `PO_BOUNDS` | Top and bottom are tested |
| `PO_MONOTONE_DEGRADE` | More charge never improves value |
| `PO_MONOTONE_CHARGE_MAPS` | Charge maps are deterministic and monotone |
| `PO_MISSINGNESS_NO_CREDIT` | Missingness cannot improve value |
| `PO_SATURATION` | Saturation preserves order and bounds |
| `PO_UNIT_CONVERSION` | Unit conversion is epoch-stable |
| `PO_FLOOR_ENCODING` | Hard floors are encoded in the dimension order |
| `PO_REPAIR_RECEIPT_ONLY` | Repair improves only with valid receipts when repair exists |

Failure behavior:

```text
if any required proof obligation fails:
  dimension_status = unusable_for_positive_credit
  affected_gate_status = inconclusive_missing_evidence or quarantine
```

### 7.4 Obligations and Hard Backlog

An obligation has states:

```text
created
reserved
held
closed
expired
cancelled
quarantined
```

Only `closed` removes active service requirement. `expired`, `held`, and
`quarantined` remain debt unless trusted policy maps them to another protected
charge.

For hard obligation class `q`:

```text
B_q(n) = created_q + reserved_q + held_q + expired_q + quarantined_q
HB_q(n) =
  sum_{obl in B_q(n)} weight_q(obl.state, obl.priority, obl.age)
```

Transition:

```text
HB_q(n+1) <= max(0, HB_q(n) + A_q(n) + U_q(n) + M_q(n) - Served_q(n))
```

### 7.5 Protected Debt Algebra

Protected debt vector:

```text
PD(n) = (
  evidence_debt(n),
  replay_debt(n),
  rollback_debt(n),
  incident_debt(n),
  maintenance_debt(n),
  comparison_debt(n),
  semantic_debt(n),
  boundary_debt(n),
  trusted_base_debt(n)
)
```

Operators:

```text
degrade_PD: PDState x PDCharge -> PDState
repair_PD:  PDState x PDRepair -> PDState
saturate_PD: PDState -> PDState
```

Laws:

1. `degrade_PD` is monotone pessimistic;
2. `repair_PD` is monotone in valid repair evidence;
3. `repair_PD(x, bottom_repair) = x`;
4. invalid, missing, stale, or untrusted repair maps to `bottom_repair`;
5. `saturate_PD` preserves order and bounds;
6. repair cannot cross a hard floor unless the required receipt class is valid.

Transition:

```text
PD_charged(n) = degrade_PD(PD(n), ChargePD(n))
PD_repaired(n) = repair_PD(PD_charged(n), RepairPD(n))
PD(n+1) = saturate_PD(PD_repaired(n))
```

Missing repair evidence does not repair debt.

## 8. Future Viability Kernel

### 8.1 One-Step Viability

The immediate viable action set is:

```text
V_n = { a in A_n | Viable(a, X_n, W_n) }
```

`Viable` requires accepted precondition evidence, required slack, authority,
permitted effect class, replay and rollback contracts when required, no
hard-stop incident in scope, satisfiable validator and obligation contracts,
semantic-floor policy for claim-emitting actions, and no positive credit from
missing evidence.

One-step viability is not the OASG performance object.

### 8.2 Finite Abstract Action Domain

Let `Ahat_n` be finite for a policy epoch:

```text
alpha_A: A_n -> Ahat_n
gamma_A: Ahat_n -> P(A_n)
```

An abstract action class includes:

```text
(action_class, scope_class, effect_class, authority_class,
 semantic_scope, replay_required, rollback_required,
 validator_class, obligation_delta_class)
```

### 8.3 Abstract Transition Semantics

An abstract state for horizon computation includes:

```text
Xhat = (
  slack_grade_by_dimension,
  protected_debt_grade,
  obligation_summary,
  authority_summary,
  replay_summary,
  rollback_summary,
  semantic_summary,
  taint_summary,
  incident_summary
)
```

Each abstract action class declares:

```text
transition_effect = (
  budget_delta,
  obligation_create_delta,
  obligation_close_delta,
  authority_required,
  authority_consumed_or_preserved,
  replay_delta,
  rollback_delta,
  semantic_floor_delta,
  taint_delta,
  incident_stop_condition
)
```

For each prefix action, `Fhat` degrades budget, creates and closes obligations,
checks authority, updates replay and rollback coverage, enforces semantic
policy, propagates taint, stops at hard incidents, and maps unknown required
effects to `bottom_infeasible` or a worse state.

### 8.4 Bounded Trace Enumeration

For horizon `h`:

```text
That_h(n) = sequences of length <= h over Ahat_n
```

The reference configuration is:

```text
horizon_h = 2
max_action_classes = 8
max_trace_classes = 73
deterministic_action_order = profile order
deterministic_trace_order = length, then lexicographic action order
pruning_strategy = maximal certified lower-bound antichain
overflow_policy = inconclusive_klb_overflow
```

Overflow cannot support positive `KLB_h` improvement.

### 8.5 Fixed Antichain Convention

The reference convention is:

```text
Anti(Khat_h) = maximal trace classes that are certified viable
```

under trace dominance:

```text
tauhat_1 <=_trace tauhat_2
```

meaning `tauhat_2` certifies at least as much future viable capacity as
`tauhat_1` for declared coordinates.

Deterministic pruning:

1. enumerate traces in deterministic trace order;
2. reject infeasible traces immediately;
3. discard a trace if an existing antichain member dominates it;
4. remove existing antichain members dominated by the new trace;
5. tie-break by canonical trace hash;
6. overflow returns `inconclusive_klb_overflow`.

### 8.6 Conservative Kernel Lower Bound

For v0.1, every `KLB_h` coordinate uses:

```text
blocked < critical < degraded < acceptable < surplus
```

Define:

```text
KLB_h(n) = kappa(Anti(Khat_h(W_n)), Xhat_n, policy_epoch)
```

The v0.1 `kappa` is deterministic and count-free for the finite chain:

1. `blocked`: no viable trace supports the coordinate;
2. `critical`: only empty or no-op preservation supports the coordinate;
3. `degraded`: a viable non-no-op trace exists but ends with some protected
   coordinate below `acceptable`;
4. `acceptable`: a viable non-no-op trace exists and all protected coordinates
   end at `acceptable` or better;
5. `surplus`: a viable non-no-op trace exists, all protected coordinates end at
   `acceptable` or better, the target coordinate ends at `surplus`, and no new
   hard obligation, unresolved taint, or rollback gap is introduced.

No undefined trace-independence relation is used by v1.0 `kappa`.

Minimal coordinates:

```text
pure_read
local_reversible
validate_artifact
close_obligation
replay_artifact
rollback_local_effect
emit_claim
promote_workflow
```

Optional count-based extensions may expose certified trace counts, but they
cannot replace the finite-chain coordinates in the v0.1 gate.

## 9. Pressure and Scheduler Fairness

### 9.1 Typed Pressure Vector

Pressure is diagnostic and vector-valued:

```text
P_i(n) = (
  neg_slack_charge_i,
  retry_charge_i,
  queue_age_charge_i,
  missing_evidence_charge_i,
  incident_reachability_charge_i,
  rollback_gap_charge_i,
  replay_gap_charge_i,
  maintenance_due_charge_i,
  comparison_debt_charge_i,
  unattributed_spillover_charge_i
)
```

Pressure is not the acceptance objective.

### 9.2 Scheduler State and Defaults

Scheduler state:

```text
scheduler_state_i(n) = (
  pressure_age_i,
  selection_deadline_i,
  exploration_debt_i,
  last_selected_append_i,
  starvation_violation_i,
  forbidden_by_policy_i
)
```

v0.1 defaults:

```text
pressure_threshold = high
pressure_persistence_window = 16 append steps
selection_deadline = 64 append steps
exploration_debt_increment = 1 per missed deadline
```

If persistent pressure is not selected before `selection_deadline` and is not
forbidden by policy:

```text
starvation_violation_i = true
```

Theorem 4 is then unavailable for that component until the scheduler state is
repaired by a valid selection or policy receipt.

## 10. Scope Algebra, Boundary, and Spillover

### 10.1 Scope Lattice

Scopes form a finite lattice:

```text
Scope = (Scopes, <=_scope, bottom_scope, top_scope, meet_scope, join_scope)
```

`s1 <=_scope s2` means `s1` is contained in `s2`. Unknown overlap is represented
by `top_scope` for safety.

### 10.2 Dependency Graph

Boundary reasoning uses:

```text
G_n = (Scopes_n, Dep_n, graph_epoch)
```

An edge `u -> v` means changes in `u` may affect `v`.

Default edge insertion:

```text
if scopes share data, control, authority, effect channels, artifacts,
memory, taint, semantic validators, or trusted-base components:
  insert may_affect edge
```

Edge merge rule:

```text
positive edge evidence dominates missing negative evidence
unexpired contradiction dominates stale negative evidence
unknown dependency is treated as may_affect
```

Negative edge evidence can remove an edge only within authority, epoch, and
expiry. Dependency closure is deterministic least fixed point over merged
edges.

### 10.3 Boundary Certificates and Scope-Washing

A boundary certificate is valid only if certifier authority covers included and
excluded scopes, graph epoch matches or bridges, negative dependency evidence
covers every path, fixtures exercise the boundary, the certificate is unexpired,
and no later contrary event supersedes it.

A mutation cannot improve by narrowing declared scope. Burden moved outside
declared scope is charged to spillover debt, boundary uncertainty, incident
reachability, and comparison debt unless a valid boundary certificate proves
independence.

## 11. Effects, Taint, Shadow, Lease, and Receipts

### 11.1 Effect Taxonomy

| Effect class | Examples | Default policy |
| --- | --- | --- |
| `pure` | deterministic local computation | allowed |
| `simulated` | dry-run tool call, mocked network | allowed with simulation receipt |
| `local_reversible` | reversible local state | allowed with rollback receipt |
| `local_irreversible` | destructive migration | rejected by minimal profile |
| `network` | external API call | rejected unless lease permits |
| `financial` | purchase, paid side effect | hard reject by default |
| `communication` | email, chat, issue comment | hard reject by default |
| `workflow_promotion` | changing active workflow/library | requires dominance receipt |
| `secret_touching` | reading or transmitting secrets | hard reject unless explicit authority |

### 11.2 Finite Taint Lattice

Taint uses a finite risk lattice:

```text
public < internal < confidential < secret < unknown_secret
```

`public` is bottom and `unknown_secret` is top. Join is maximum in this order.

A taint record is:

```text
taint = (
  taint_id,
  taint_level,
  authority_label,
  source_event_id,
  propagation_policy,
  declassification_receipt,
  expiry
)
```

Propagation:

```text
taint(output) =
  join(taint(inputs), taint(tool_context), taint(memory_context))
```

Declassification can lower taint only with a valid declassification receipt
whose authority covers the taint level and scope. Missing taint metadata maps
to `unknown_secret`. Under the minimal profile, `unknown_secret` is rejected for
external effects and workflow promotion.

### 11.3 Shadow and Lease

Shadow execution runs a candidate without external effects:

```text
shadow(mu) -> shadow_receipt
```

Lease execution is bounded by max append events, wall time, cost, tokens,
obligations created, permitted scopes, effect classes, stop conditions,
rollback requirements, and coverage requirements. Exceeding a lease cap is a
negative event and cannot be reclassified as improvement.

### 11.4 Receipt Families

Required receipt families:

```text
shadow_receipt
lease_receipt
external_effect_receipt
rollback_receipt
replay_receipt
coverage_receipt
comparison_receipt
klb_receipt
positive_evidence_witness
dominance_gate_receipt
quarantine_receipt
```

Every receipt includes receipt id, mutation id, scope, epoch vector, ledger
prefix hash, input hashes, output hashes, coverage ids, status, protected
coordinate deltas, missingness summary, taint summary, and integrity hash.

## 12. Semantic Validator Integration

Semantic validators and external review are ordinary observable channels. They
are not the OASG improvement oracle and are not meta-evaluators for workflow
promotion.

Semantic policies:

```text
semantic_scope = none
semantic_scope = operational_only
semantic_scope = validator_required(validator_class)
semantic_scope = external_review_required
```

`semantic_scope = none` is valid only for non-claim operational actions. A
claim-emitting or user-facing output action must declare
`validator_required(...)` or `external_review_required`; otherwise it is not
viable. External review, when used, creates a fallible semantic receipt and is
processed like any other observable channel.

OASG can integrate semantic quality floors, but it does not prove semantic
truth.

## 13. Baseline, Candidate, and Comparison Contracts

### 13.1 Workload Manifest

Deterministic comparison uses a canonical workload manifest:

```text
workload_manifest = (
  workload_id,
  canonical_input_order,
  input_hashes,
  baseline_snapshot_hash,
  candidate_snapshot_hash,
  replay_pairing_rule,
  nondeterminism_seed_policy,
  allowed_nondeterminism,
  contamination_policy,
  mismatch_status_policy,
  ledger_prefix_hashes
)
```

The manifest is hash-critical and uses `OASG-CJ-1`.

Mismatch statuses:

```text
paired_valid
rejected_input_mismatch
rejected_replay_mismatch
rejected_exposure_mismatch
rejected_seed_policy_mismatch
rejected_contaminated_baseline
inconclusive_unpaired_workload
```

### 13.2 Comparison Contract

A comparison contract is:

```text
Q = (
  comparison_contract_id,
  workload_manifest_id,
  baseline_workflow_id,
  candidate_mutation_id,
  frozen_baseline_snapshot,
  replay_pairing_rule,
  exposure_assignment_rule,
  strata,
  measurement_window,
  epsilon_by_dimension,
  confidence_method,
  sequential_rule,
  multiple_comparison_budget,
  contamination_checks,
  allowed_epoch_vector,
  bridge_requirements
)
```

Statistical acceptance is disabled in v0.1. Deterministic exact comparison
requires paired traces, replay equivalence, seed policy match, contamination
checks, and verified ledger prefixes.

## 14. Positive Evidence Witnesses

### 14.1 Witness Shape

A positive evidence witness is:

```text
PositiveEvidenceWitness = (
  witness_id,
  mutation_id,
  coordinate_id,
  baseline_receipt_hashes,
  candidate_receipt_hashes,
  evidence_hashes,
  required_receipt_types,
  comparison_contract_id,
  workload_manifest_hash,
  ledger_prefix_hash,
  reducer_epoch,
  gate_epoch,
  status
)
```

Only `status = witness_valid` can support strict improvement.

### 14.2 Per-Coordinate Witness Rules

| Coordinate | Required witness |
| --- | --- |
| `KLB_h` | `klb_receipt`, abstract trace receipt, workload manifest hash |
| `hard_slack_vector` | reducer snapshot and resource/service receipt |
| `protected_debt_vector` | valid repair receipt for the repaired coordinate |
| `replay_vector` | replay receipt over matching artifact hash |
| `rollback_vector` | rollback or compensation receipt |
| `evidence_coverage_vector` | coverage receipt with trusted collector |
| `semantic_floor_vector` | semantic validator or external-review receipt |
| `taint_policy_vector` | taint proof or declassification receipt |
| `comparison_debt_vector` | comparison pairing receipt and contamination pass |
| `trusted_base_vector` | acyclic trusted-base bridge |

No coordinate may strictly improve without a valid witness of its declared type.

## 15. No-Meta Dominance Gate

### 15.1 Dominance Vector

For comparison contract `Q`:

```text
D_Q(n) = (
  KLB_h(n),
  hard_slack_vector(n),
  protected_soft_slack_vector(n),
  hard_obligation_backlog_vector(n),
  protected_debt_vector(n),
  scoped_debt_vector(n),
  spillover_risk_vector(n),
  evidence_coverage_vector(n),
  replay_vector(n),
  rollback_vector(n),
  incident_vector(n),
  maintenance_vector(n),
  comparison_debt_vector(n),
  semantic_floor_vector(n),
  taint_policy_vector(n),
  trusted_base_vector(n)
)
```

### 15.2 Acceptance Predicate

A mutation `mu` reaches `safe_promotion` under `Q` iff:

```text
SafePromote_Q(mu) iff
  LedgerOK(mu)
  and TrustedBaseOK(mu)
  and CoverageOK(mu, Q)
  and ProofObligationsOK(mu)
  and LeaseOK(mu)
  and BoundaryOK(mu)
  and EffectPolicyOK(mu)
  and SemanticPolicyOK(mu)
  and ComparisonOK(mu, Q)
  and KLBStatusOK(mu)
  and D_Q(candidate) >=_prod D_Q(baseline)
  and exists declared coordinate k:
        StrictImprove_k(candidate, baseline, epsilon_k)
  and PositiveEvidenceWitness(k).status == witness_valid
  and no non-positive evidence contributes positive credit
```

`active_promoted` additionally requires workflow-promotion effect policy.

### 15.3 Gate Statuses

Gate outputs:

```text
accepted
safe_non_regression
safe_promotion
active_promoted
rejected_no_concrete_positive_evidence
rejected_ledger_integrity
rejected_floor_violation
rejected_viability_regression
rejected_debt_transfer
rejected_effect_policy
rejected_secret_taint
rejected_semantic_floor_missing
rejected_boundary
rejected_trusted_base
rejected_proof_obligation
rejected_contaminated_comparison
inconclusive_missing_evidence
inconclusive_klb_overflow
quarantined_tamper_or_fork
quarantined_late_contradiction
retired
```

Every status produces a gate receipt.

## 16. Performance Definition

The performance object is:

```text
Perf_Q(W_n) = D_Q(n)
```

with product order. OASG improvement is:

```text
Perf_Q(W_candidate) >=_prod Perf_Q(W_baseline)
and at least one declared coordinate strictly improves
and each strict improvement has a valid PositiveEvidenceWitness.
```

The central future-action coordinate is `KLB_h`, not one-step `V_n`.

## 17. Lemmas and Theorems

### Lemma 1: Ledger Prefix Determinism

#### State Variables

```text
H_n = ledger prefix
profile = ledger profile and canonical profile
prefix_hash(H_n) = deterministic prefix hash
```

#### Assumptions

1. All records use `OASG-CJ-1`.
2. Hash domains and ledger profile are fixed.
3. Schema migrations are explicit records.
4. Duplicate policies are deterministic.

#### Transition Equation

```text
prefix_hash(H_{n+1}) =
  sha256("OASG:v1.0:prefix" || prefix_hash(H_n) || integrity_hash(e_{n+1}))
```

#### Statement

For a fixed byte-identical ledger prefix and profile, all conforming
implementations compute the same prefix verification status and prefix hash.

#### Proof Sketch

Canonical encoding, hash domains, duplicate handling, schema migration records,
and prefix transition are deterministic. Therefore the verifier is a pure
function of ledger bytes and profile.

#### Falsification Criteria

Two conforming implementations produce different prefix hashes or statuses for
the same ledger fixture.

#### Implementation Invariant

The ledger verifier exposes canonical bytes, record hash, integrity hash,
prefix hash, and status for every line.

### Lemma 2: No Positive Credit From Non-Positive Evidence

#### State Variables

```text
R(H_n) = X_n
m_j(n) = missingness state for dimension j
v_j(n) = reduced coordinate value
```

#### Assumptions

1. Each dimension declares missingness policy.
2. Reducers classify absent, stale, rejected, conflicted, untrusted,
   overflowed, taint-unknown, prefix-invalid, or unbridged records as
   non-positive evidence.
3. Charge maps are monotone pessimistic.
4. Gate acceptance uses only declared coordinate values.

#### Transition Equation

```text
if E is non-positive for j:
  contribution_j(E) <=_j neutral_j
```

#### Statement

No reducer, comparison, or gate may derive strict improvement from non-positive
evidence.

#### Proof Sketch

Non-positive evidence contributes at most neutral evidence and may contribute
negative charge. Strict improvement requires concrete positive evidence. Hence
non-positive evidence cannot create strict improvement.

#### Falsification Criteria

A fixture accepting a mutation whose sole improving input is non-positive
evidence falsifies the implementation.

#### Implementation Invariant

Every safe-promotion receipt lists valid positive evidence witness hashes.

### Lemma 3: Positive Evidence Witness Soundness

#### State Variables

```text
Wit_k = PositiveEvidenceWitness for coordinate k
D_Q   = dominance vector
```

#### Assumptions

1. `Wit_k.status == witness_valid`.
2. Witness receipt types match the coordinate witness table.
3. Witness hashes are ledger-prefix-valid.
4. Baseline and candidate receipts are compared under the same contract or
   bridged contract.

#### Transition Equation

```text
Wit_k valid -> supports StrictImprove_k(candidate, baseline, epsilon_k)
```

#### Statement

A valid positive evidence witness is sufficient evidence for strict improvement
in its declared coordinate, subject to the comparison contract.

#### Proof Sketch

The witness binds coordinate id, receipt types, receipt hashes, comparison
contract, workload manifest, reducer epoch, and gate epoch. Validity requires
all coordinate-specific receipt checks. Therefore it supports exactly the
declared strict improvement.

#### Falsification Criteria

A witness-valid fixture with missing, stale, wrong-type, or mismatched receipt
hashes falsifies the implementation.

#### Implementation Invariant

The gate refuses strict improvement when the witness table has no valid witness
for the coordinate.

### Lemma 4: Protected Debt Monotonicity Under Missing Repair

#### State Variables

```text
PD(n)       = protected debt vector
ChargePD(n) = monotone debt charge
RepairPD(n) = certified repair evidence
```

#### Assumptions

1. Every protected debt coordinate is a bounded lattice.
2. `degrade_PD` is monotone pessimistic.
3. `repair_PD` can improve coordinates only with valid receipts.
4. Missing, stale, invalid, or untrusted repair evidence maps to
   `bottom_repair`.

#### Transition Equation

```text
PD_charged(n) = degrade_PD(PD(n), ChargePD(n))
PD_repaired(n) = repair_PD(PD_charged(n), RepairPD(n))
PD(n+1) = saturate_PD(PD_repaired(n))
```

#### Statement

Protected non-queue debt cannot improve without valid repair receipts.

#### Proof Sketch

Degradation cannot improve state. Repair improves only with valid evidence.
Missing repair maps to identity. Therefore debt cannot silently disappear.

#### Falsification Criteria

Protected debt improves without a corresponding valid receipt.

#### Implementation Invariant

Reducer snapshots expose protected debt coordinates, charges, repair receipts,
and missing-repair status.

### Theorem 1: Bounded Hard Obligation Debt

#### State Variables

```text
HB_q(n) = weighted hard backlog
A_q(n)  = arrivals
U_q(n)  = unserviceable additions
M_q(n)  = missingness, incident, conflict, held, and expiration charges
S_q(n)  = served hard backlog
F_n     = sigma(H_n)
```

Lyapunov function:

```text
L_H(n) = sum_q beta_q * HB_q(n)
```

#### Assumptions

1. Processes are adapted to `F_n`.
2. One-step increments are bounded by `Bmax_q`.
3. When `HB_q(n) >= H_q`,
   `E[S_q(n) | F_n] >= E[A_q(n)+U_q(n)+M_q(n) | F_n] + eta_q`.
4. Hard obligations are served by priority then oldest age, or equivalent
   drift is proven.
5. Expired, held, quarantined, and conflicted obligations remain charged.
6. Accepted mutations cannot reduce hard service capacity or hide backlog.

#### Transition Equations

```text
HB_q(n+1) <= max(0, HB_q(n) + A_q(n) + U_q(n) + M_q(n) - S_q(n))
```

For `HB_q(n) >= H_q`:

```text
E[HB_q(n+1) - HB_q(n) | F_n] <= -eta_q
```

#### Statement

Under the assumptions, hard obligation debt is bounded in the standard
Foster-Lyapunov negative-drift sense. In deterministic bounded-load
deployments, the expectation notation may be removed and the same equations
give a deterministic bounded-drift result.

#### Proof Sketch

Above threshold, service exceeds arrivals and monotone charges by a positive
margin. Below threshold, bounded increments limit one-step growth. Gate
restrictions prevent accepted mutations from invalidating the assumptions.

#### Failure Modes and Falsification Criteria

The theorem does not cover load above capacity, unfair service, unbounded
increments, silent cancellation, expiration-as-deletion, missingness credit, or
indefinite service halt.

#### Implementation Invariant

Reducer snapshots expose backlog, arrivals, charges, service, service order,
and whether stochastic or deterministic assumptions are in use.

### Theorem 2: Safe-Promotion Dominance Monotonicity

#### State Variables

```text
D_Q(n)     = dominance vector under comparison contract Q
KLB_h(n)   = finite-horizon viability lower bound
mu_k       = mutation at step k
Q_k        = comparison contract
Bridge_k   = compatibility bridge, if needed
```

#### Assumptions

1. Every promoted mutation satisfies `SafePromote_Q`.
2. Compared states use the same `Q`, or adjacent contracts are bridge-compatible.
3. `KLB_h` is computed by a sound finite abstraction and did not overflow into
   positive credit.
4. Strict improvement has a valid positive evidence witness.
5. Missingness cannot improve any coordinate.
6. Trusted-base changes use acyclic monotone migration bridges.
7. Ledger prefixes verify.

#### Transition Equation

```text
D_Q(W_{k+1}) >=_prod D_Q(W_k)
and exists coordinate r: StrictImprove_r(W_{k+1}, W_k, epsilon_r)
```

#### Statement

For any sequence of `safe_promotion` or `active_promoted` mutations under a
fixed comparison contract, or under compatible bridges, the dominance vector is
non-decreasing. In particular, `KLB_h` is non-decreasing.

#### Proof Sketch

The gate requires product-order non-regression and witness-backed strict
improvement. Bridge compatibility preserves order across comparison epochs.
Composition of monotone steps yields monotonicity.

#### Failure Modes and Falsification Criteria

The theorem does not compose across incompatible contracts, invalid prefixes,
abstract-only improvements, unsound kernel abstractions, contaminated baselines,
or unbridged trusted-base changes.

#### Implementation Invariant

Gate receipts store baseline vector, candidate vector, comparison contract,
bridge id, ledger prefix hashes, positive evidence witness hashes, and
coordinate-wise order results.

### Theorem 3: Anti-Goodhart Non-Compensation

#### State Variables

```text
G_local = local metric coordinate
P       = protected coordinate set
M       = missingness coordinates
B       = boundary and spillover coordinates
E       = effect and taint coordinates
D_Q     = dominance vector
```

#### Assumptions

1. Protected dimensions include evidence, replay, rollback, incident,
   authority, hard debt, protected debt, spillover, semantic floor, effect
   policy, taint, and trusted base.
2. Missingness cannot provide positive credit.
3. Boundary exclusions require valid certificates.
4. External effects require permitted class and receipts.
5. Secret taint requires authority or declassification.
6. Gate acceptance requires product-order non-regression over `D_Q`.

#### Transition Equation

Local improvement:

```text
Improve(G_local(c), G_local(b))
```

is insufficient. Acceptance also requires all protected coordinates not worse
and concrete positive evidence for strict improvement.

#### Statement

A local metric improvement cannot count as OASG improvement if it transfers
burden into missing evidence, replay gaps, rollback gaps, obligations,
incidents, stale boundaries, unauthorized effects, taint violations, semantic
floor gaps, comparison debt, trusted-base debt, or abstract-only improvement.

#### Proof Sketch

The gate accepts only product-order dominance. Any transferred burden worsens a
protected coordinate or invalidates a predicate. Protected regression cannot be
compensated by improvement elsewhere.

#### Failure Modes and Falsification Criteria

If a schema omits a protected burden, the theorem does not cover it. A fixture
accepting transferred protected debt falsifies the implementation.

#### Implementation Invariant

Gate receipts include explicit reject reasons for all protected failure modes.

### Theorem 4: Conditional Constructive Improvement Witness

#### State Variables

```text
Mu_n        = proposal set from untrusted mutators
Receipt(mu) = shadow, lease, comparison, boundary, KLB, witness, and gate receipts
Gate        = trusted no-meta gate
D_Q         = dominance vector
Sched       = scheduler fairness state
```

#### Assumptions

1. Some mutation `mu*` in scheduler proposal coverage has true observable effect
   dominating baseline under `Q`.
2. Shadow and lease execution can produce receipts for `mu*` within policy caps.
3. Trusted reducers and gates are sound for `Q`.
4. Scheduler fairness state has no starvation violation for the relevant
   component before the proposal deadline.
5. Scheduler eventually proposes `mu*` or observational equivalent.
6. Missingness, taint uncertainty, overflow, and contaminated comparison cannot
   create false positive credit.

#### Transition Equation

```text
proposal(mu*) -> receipts(mu*) -> Gate(receipts(mu*)) = safe_promotion
```

#### Statement

External answer keys, LLM judges, and absolute meta-evaluators are not required
for a conditional operational improvement witness. If an untrusted proposal
produces trusted receipts satisfying the gate, the resulting workflow is
certified as operationally improved under `Q`.

#### Proof Sketch

The proposal mechanism is not trusted. The trusted content is the receipt set,
positive evidence witnesses, and deterministic gate evaluation.

#### Failure Modes and Falsification Criteria

The theorem does not guarantee discovery. It fails if proposal coverage,
scheduler fairness, receipts, trusted reducers, or comparison evidence fail.

#### Implementation Invariant

Promoted mutations include proposal id, scheduler state, complete receipt set,
dominance delta, positive evidence witness hashes, and gate epoch.

### Theorem 5: Safe Lightweight Acceptance and Promotion

#### State Variables

```text
D_full      = full OASG state domain
D_light     = lightweight implementation domain
alpha       = abstraction from full to lightweight state
gamma       = concretization from lightweight to full states
Gate_full   = full gate
Gate_light  = lightweight gate
```

#### Assumptions

1. `alpha` and `gamma` satisfy state, trace, receipt, and gate soundness.
2. Lightweight reducers are pessimistic for every protected coordinate.
3. Lightweight missingness policy is at least as conservative as full policy.
4. Lightweight effect and taint policy is at least as restrictive as full
   policy.
5. Lightweight `KLB_2` is a lower bound on full `KLB_2`.
6. Lightweight comparison uses exact deterministic pairing.
7. Overflow returns inconclusive rather than acceptance.
8. Lightweight promotion requires positive evidence witnesses for every strict
   improvement coordinate.

#### Transition Equation

Safe non-regression:

```text
Gate_light(alpha_R(receipts)) = safe_non_regression
  implies
forall r in gamma_R(alpha_R(receipts)):
  Gate_full(r) would not reject any protected coordinate
```

Safe promotion:

```text
Gate_light(alpha_R(receipts)) = safe_promotion
  implies safe_non_regression
  and valid PositiveEvidenceWitness exists for each strict improvement coordinate
```

#### Statement

A lightweight implementation has safe acceptance when it certifies protected
non-regression for every represented concrete receipt. It has safe promotion
only when strict improvement is witness-backed. Safe promotion is not
equivalence to full acceptance.

#### Proof Sketch

By abstraction soundness, every represented concrete receipt lies in the
concretization. Pessimistic reducers, restrictive effect policy, conservative
missingness, bounded `KLB_2`, and positive evidence witnesses prevent the
lightweight abstraction from hiding protected regression or inventing strict
improvement.

#### Failure Modes and Falsification Criteria

The theorem fails if lightweight abstraction overstates improvement, drops a
protected dimension, treats missing evidence as positive, permits a rejected
effect class, accepts after overflow, or promotes abstract-only strict
improvement.

#### Implementation Invariant

Every lightweight reducer and gate declares its full-theory coordinate,
`alpha/gamma` rule, pessimism rule, positive evidence rule, and fixture proving
reject-or-inconclusive behavior under unavailable information.

## 18. Mathematical Guarantees Versus Engineering Controls

| Topic | Mathematical guarantee | Engineering control |
| --- | --- | --- |
| Ledger integrity | deterministic prefix validity | canonical hash verifier |
| Missing evidence | no positive credit | rejection ledger and coverage policy |
| Hard debt | bounded under drift assumptions | queue reducer and service logs |
| Protected debt | no silent repair without receipt | protected debt reducer |
| Improvement | monotonicity under safe promotion | gate receipts and witnesses |
| Goodhart resistance | no compensation across protected coordinates | protected schema dimensions |
| Self-improvement | conditional receipt witness | scheduler, shadow, lease |
| Lightweight profile | safe promotion only with witnesses | pessimistic abstraction fixtures |
| Semantic quality | no truth guarantee | semantic floor policy |
| Trusted-base changes | no self-certifying checker change | acyclic monotone bridge |

## 19. Reference v0.1 Architecture and Lightweight Mapping

### 19.1 Normative v0.1 Profile

```text
horizon: h = 2
max_action_classes: 8
max_trace_classes: 73
comparison: deterministic exact with paired replay traces
statistics: disabled
dimension carrier: blocked < critical < degraded < acceptable < surplus
antichain convention: maximal certified lower-bound antichain
effect classes allowed: pure, simulated, local_reversible
trusted-base mutation: rejected unless acyclic bridge exists
semantic validators: optional unless action emits claims
secret taint: unknown taint rejected for external effects and promotion
```

`max_trace_classes = 73` covers length 0, 1, and 2 traces for 8 action classes:

```text
1 + 8 + 8^2 = 73
```

### 19.2 Reference Modules

The first implementation wave should expose these modules:

| Module | Responsibility |
| --- | --- |
| `canonical` | OASG-CJ-1 encoding and SHA-256 domain hashing |
| `ledger` | JSONL prefix verification, duplicate policy, schema migration records |
| `reducers` | deterministic reducer snapshots for slack, debt, pressure, and KLB inputs |
| `klb` | bounded `KLB_2` trace enumeration and antichain pruning |
| `gate` | dominance comparison, witness checking, gate receipt emission |
| `fixtures` | conformance fixtures for ledger, algebra, KLB, gate, and migration |
| `cli` | validate ledgers, reduce snapshots, evaluate mutations, print reports |

### 19.3 Minimal I/O Boundary

Inputs:

```text
baseline.jsonl
candidate.jsonl
comparison_contract.json
workload_manifest.json
policy_profile.json
```

Outputs:

```text
ledger_integrity_receipt.json
reducer_snapshot.json
klb_receipt.json
positive_evidence_witness.json
dominance_gate_receipt.json
quarantine_record.json when needed
```

Every positive promotion includes:

```text
ledger_prefix_hash
comparison_manifest_hash
klb_receipt_hash when KLB changes
positive_evidence_witness_hashes
gate_receipt_hash
```

### 19.4 Minimal Dimensions

Required dimensions:

```text
budget
queue
evidence
replay
rollback
incident
authority
maintenance
comparison
boundary
trusted_base
taint
KLB_2
```

Optional protected dimension:

```text
semantic_floor
```

Every dimension initially uses explicit charge tables over:

```text
blocked < critical < degraded < acceptable < surplus
```

Ad hoc numeric scoring is not part of v0.1 acceptance.

### 19.5 Minimal Abstract Viability

The eight v0.1 action classes are:

```text
pure_read
local_reversible
validate_artifact
close_obligation
replay_artifact
rollback_local_effect
emit_claim
promote_workflow
```

Rules:

1. `emit_claim` requires semantic-floor policy;
2. `promote_workflow` requires dominance receipt and positive evidence witness;
3. network, financial, communication, irreversible, and secret-touching classes
   are absent unless explicitly enabled;
4. `KLB_2` enumerates length-0, length-1, and length-2 abstract traces;
5. enumeration uses canonical class order as listed above;
6. pruning uses fixed maximal antichain convention;
7. overflow returns `inconclusive_klb_overflow`.

### 19.6 Minimal Schema Families

```text
event_record.schema.json
schema_migration_record.schema.json
ledger_integrity_receipt.schema.json
rejection_record.schema.json
coverage_certificate.schema.json
reducer_snapshot.schema.json
slack_dimension.schema.json
proof_obligation.schema.json
proof_obligation_receipt.schema.json
obligation_record.schema.json
protected_debt_record.schema.json
abstract_action_class.schema.json
abstract_trace_receipt.schema.json
klb_receipt.schema.json
positive_evidence_witness.schema.json
pressure_vector.schema.json
scheduler_state.schema.json
scope_graph.schema.json
mutation_record.schema.json
mutation_lifecycle_record.schema.json
shadow_receipt.schema.json
lease_receipt.schema.json
workload_manifest.schema.json
comparison_contract.schema.json
comparison_pairing_receipt.schema.json
boundary_certificate.schema.json
taint_record.schema.json
semantic_validator.schema.json
trusted_base_bridge.schema.json
dominance_gate_receipt.schema.json
quarantine_record.schema.json
```

Schemas are language-independent. Python with uv is only the reference runtime.

### 19.7 Minimal Gate Algorithm

```text
verify canonical encoding and ledger prefix hashes
reduce baseline and candidate ledgers
validate coverage, trusted-base epoch, comparison contract, boundary, effect policy
validate proof obligations for all positive-credit dimensions
validate workload manifest and replay pairing
validate taint and semantic-floor policy
compute protected debt vector and KLB_2
reject if any hard floor is worse
return safe_non_regression if protected coordinates are not worse but no witness-backed improvement exists
reject if KLB_2 is worse or overflow is used as positive evidence
reject if protected debt, scoped debt, or spillover is worse
reject if improvement depends on missingness, stale evidence, or invalid migration
return safe_promotion only if at least one coordinate strictly improves with a valid witness
return active_promoted only if workflow-promotion effect policy also passes
otherwise inconclusive
```

### 19.8 Required Conformance Scenarios

1. canonical hash equality across implementations;
2. hash mismatch quarantine;
3. mixed-schema migration remains prefix-verifiable;
4. duplicate reject, idempotent, and supersede behavior;
5. fork quarantine;
6. late supersession without overwrite;
7. reject missing positive evidence witness;
8. return `safe_non_regression` without strict improvement;
9. accept `safe_promotion` with witness-backed `KLB_2` improvement;
10. reject protected debt repair without receipt;
11. deterministic enumeration of 73 traces;
12. antichain pruning agreement;
13. overflow inconclusive;
14. semantic claim rejection without semantic policy;
15. taint propagation rejection;
16. scheduler starvation disables Theorem 4 applicability;
17. stale boundary certificate charges spillover;
18. workload manifest mismatch rejects comparison;
19. trusted-base coordinate removal cannot improve claims.

## 20. Falsifiability and Empirical Evaluation

Implementation falsification:

```text
An implementation is wrong if fixtures show safe_promotion or active_promoted
despite protected regression, invalid ledger prefix, missingness credit,
unpermitted effect, taint violation, stale boundary certificate, contaminated
comparison, KLB overflow, unbridged trusted-base change, workload mismatch,
abstract-only improvement, or protected debt repair without receipt.
```

Empirical method failure:

```text
On fixed task distribution, model, budget, and observation policy, OASG fails
as an operational method if it cannot reduce or stabilize hard debt, protected
debt, queue age, missingness, replay gaps, rollback gaps, incident reachability,
maintenance burden, or KLB_2 regression compared with a non-mutating baseline.
```

Empirical failure does not disprove the formal theorems. It shows that proposal
coverage, instrumentation, service margin, or mutation family is insufficient.

## 21. Relationship to Existing Systems

OASG is compatible with local-first evidence ledgers, canonical hashing,
deterministic reducers, replay receipts, service accounting, and fail-closed
claim checking. These systems can provide the ledger substrate.

OASG differs from metric optimizers, LLM-judge pipelines, reflexive critique
loops, skill-library growth systems, and benchmark-driven workflow search by
making operational slack, future viability, protected debt conservation, and
receipt-backed partial-order dominance the primary improvement object.

Durable execution systems provide checkpoint and recovery substrate. OASG adds
a rule for deriving local workflow improvement pressure and accepting mutations
from operational evidence.

## 22. Minimal OASG Cycle

```text
append event, rejection, and coverage records
verify canonical encoding and ledger integrity chain
reduce ledger into state snapshot
compute typed slack and protected debt
compute KLB_2 over finite abstract action traces
compute typed pressure vectors
schedule bounded mutation proposals
run shadow execution
run lease execution if shadow permits
compare against frozen paired workload manifest
check positive evidence witnesses
apply no-meta dominance gate
append safe_non_regression, safe_promotion, active_promoted, rejected,
inconclusive, or quarantine receipt
```

## 23. Design Principle

```text
An agent workflow improves only when its observable, receipt-backed future
operational options expand or its protected debt decreases with concrete
positive evidence, without reducing future viability, hiding burden, weakening
floors, relying on missing evidence, overflowing a finite abstraction into
positive credit, violating taint or semantic policy, repairing debt without
receipt, or changing the checker that certifies the claim without an acyclic
monotone bridge.
```

This is the precise no-meta form of OASG. It does not claim that the agent
knows more truth. It claims that, under its observable trusted boundary, it has
a larger certified set of future safe, replayable, rollback-aware, verifiable,
and serviceable operational possibilities.
