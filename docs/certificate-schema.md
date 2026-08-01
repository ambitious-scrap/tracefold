# TraceFold Preservation Certificate Schema

Status: Phase 0 freeze

Schema ID: `tracefold.preservation-certificate`

Certificate version: `1.0.0`

The preservation certificate binds one final emitted context to its original source manifest, query, tokenizer, source map, independent verification observations, risk status, and recovery history. It is evidence about declared invariants; it is not a proof of downstream answer equivalence.

Source basis: `productSpec.md` §§5.3, 5.8, 9.5, 11, 12, 18–20 and `buildPlan.md` §§2, 5–10. **[PROPOSED PROJECT DECISION]** All canonical field names, nesting, ownership labels, validation rules, and serialization details introduced below are proposed project decisions that make those requirements implementable.

## Normative rules

1. A certificate MUST be valid canonical JSON and include every required field described here.
2. The final certificate is assembled only after the final emitted artifact is independently verified.
3. Compressor values are claims. A field named `verified_*`, `recomputed_*`, or `verification_*` is written from independent observations and MUST NOT be copied from compressor state.
4. Hashes bind exact bytes and use explicit domain separation.
5. The certificate MUST retain raw-attempt identity when restoration, budget expansion, or fallback occurs.
6. `complete` preservation is prohibited when discovery is `partial` or `unknown`.
7. A schema-valid certificate may still have `verification_status: failed` or `indeterminate`.
8. No LLM self-assessment is accepted as independent evidence.

## Field ownership and trust labels

The tables use these labels:

- **C — compressor-generated:** claim emitted by the compressor/certificate generator.
- **V — verifier-recomputed:** independently parsed or recomputed by the verifier.
- **R — recovery/risk-generated:** produced by the risk calibrator or recovery controller; proof-bearing values have an independent recomputation companion.
- **I — informational only:** auditable metadata, not preservation evidence.
- **S — security-critical:** changing the field can change artifact identity, proof interpretation, acceptance, or recovery. It must be canonicalized, schema-validated, and bound into the certificate hash.

A field may have multiple labels. Informational-only fields never cause a preservation pass, even when security-critical for audit/reproducibility.

## Canonical serialization

**[PROPOSED PROJECT DECISION]** Canonical certificates use RFC 8785 JSON Canonicalization Scheme semantics with these project restrictions:

- UTF-8 encoding, no BOM;
- duplicate object keys forbidden;
- JSON strings contain Unicode scalar values; invalid Unicode is rejected;
- finite JSON numbers only; NaN and infinities forbidden;
- all ratio/score values that require stable decimal precision are encoded as strings matching `^(0|1)\.\d{6}$` or `^0\.\d{6}$` as appropriate;
- arrays retain semantic order; maps with identifier keys use canonical object-key ordering;
- timestamps use RFC 3339 UTC with `Z` and microsecond precision;
- unknown extension fields are forbidden in `1.0.0` except under `informational.extensions`.

The certificate's own digest, when stored externally, is:

```text
sha256("tracefold:certificate:1.0.0\0" || canonical_certificate_bytes)
```

## Hash contract

Hash strings match `^sha256:[0-9a-f]{64}$`.

| Hash | Domain and bytes | Ownership/trust |
|---|---|---|
| `artifacts.source.claimed_hash` | `sha256("tracefold:source-manifest:1\0" || canonical_source_manifest)` | C, S |
| `artifacts.source.verified_hash` | Same domain, independently recomputed from original source artifacts | V, S |
| `artifacts.query.claimed_hash` | `sha256("tracefold:query:1\0" || canonical_query_envelope)` | C, S |
| `artifacts.query.verified_hash` | Same domain, independently recomputed from exact query envelope | V, S |
| `artifacts.request.claimed_hash` | `sha256("tracefold:compression-request:1\0" || canonical_request_envelope)` | C, S |
| `artifacts.request.verified_hash` | Same domain, independently recomputed from the caller request | V, S |
| `artifacts.raw_compressed_context.claimed_hash` | Raw candidate UTF-8 bytes with `tracefold:raw-compressed:1` domain | C, S |
| `artifacts.raw_compressed_context.verified_hash` | Same raw domain, independently recomputed for recovery audit | V, S |
| `artifacts.compressed_context.claimed_hash` | Final emitted context UTF-8 bytes with `tracefold:compressed:1` domain | C, S |
| `artifacts.compressed_context.verified_hash` | Same final domain, independently recomputed | V, S |
| `artifacts.source_map.claimed_hash` | Canonical source-map bytes with `tracefold:source-map:1` domain | C, S |
| `artifacts.source_map.verified_hash` | Same domain, independently recomputed | V, S |

The source manifest is an ordered array in caller input order. Each item contains stable source ID, authority/content kind, media type, byte length, and per-source raw-byte hash. Reordering or changing boundaries changes the aggregate source hash.

The query envelope is always present:

```json
{"query": null}
```

or:

```json
{"query": "exact query text"}
```

## Required top-level structure

```text
schema_id
certificate_version
run_id
attempt_id
parent_attempt_id
artifact_role
artifacts
tokenization
reduction
obligations
relations
coverage
failed_invariants
parser_warnings
risk
action
restored_spans
recovery_history
fallback_reason
component_versions
timestamps
verification_status
informational
```

No top-level field is optional. Nullable fields use explicit JSON `null`.

## Top-level field contract

| Field | Type and constraints | Producer / recomputation | Informational | Security-critical |
|---|---|---|---:|---:|
| `schema_id` | Exact string `tracefold.preservation-certificate` | Fixed schema constant; verifier validates | No | Yes |
| `certificate_version` | SemVer string, exactly `1.0.0` for this contract | Generator; verifier validates supported semantics | No | Yes |
| `run_id` | Lowercase RFC 4122 UUID string; correlation only | Gateway/runtime | Yes | No |
| `attempt_id` | Non-empty stable ID unique within run | Orchestrator; verifier checks references | Yes | Yes |
| `parent_attempt_id` | Prior attempt ID or `null` | Orchestrator; verifier checks recovery chain | Yes | Yes |
| `artifact_role` | `raw`, `certified`, or `end_to_end`; final certificate is normally `certified` or `end_to_end` | Orchestrator; verifier checks against recovery | No | Yes |
| `artifacts` | Artifact hash records defined below | C claims plus V recomputation | No | Yes |
| `tokenization` | Tokenizer identity and claimed/verified counts | C plus V | No | Yes |
| `reduction` | Requested and claimed/verified achieved reduction | Request/C plus V | No | Yes |
| `obligations` | Counts by every applicable protected class | C discovery/claims plus V rediscovery/verification | No | Yes |
| `relations` | Per-class relation verification observations | C claims plus V results | No | Yes |
| `coverage` | Certificate/source-map coverage and completeness | V | No | Yes |
| `failed_invariants` | Final verifier failures; empty array allowed | V only | No | Yes |
| `parser_warnings` | Typed warnings from compressor and verifier; empty array allowed | C and V, source labeled | No | Yes when severity is `error`/`unknown_coverage` |
| `risk` | Score, calibration status, model identity, and recomputation | R plus independent recomputation | No | Yes |
| `action` | Selected and independently recomputed action plus policy | R plus independent policy recomputation | No | Yes |
| `restored_spans` | Exact restoration records; empty array allowed | R claims plus V byte/hash checks | No | Yes |
| `recovery_history` | Append-only attempt/action/failure links; empty only for raw `emit` | R records plus V hash/reference checks | No | Yes |
| `fallback_reason` | Typed reason object or `null` | R; verifier validates consistency | Audit-only; cannot prove preservation | Yes |
| `component_versions` | Exact immutable implementation/build version identifiers | Runtime declarations; verifier compares relevant local identities | Yes; never a pass signal | Yes |
| `timestamps` | Created/verification/finalization UTC timestamps | Runtime clocks | Yes | No |
| `verification_status` | `passed`, `failed`, or `indeterminate` | V only | No | Yes |
| `informational` | Human/audit metadata and namespaced extensions | Runtime | Yes | No; descendants cannot affect proof/action |

## Artifact records

`artifacts` MUST contain:

```text
source: { claimed_hash, verified_hash, match }
query: { claimed_hash, verified_hash, match }
request: { claimed_hash, verified_hash, match }
raw_compressed_context: { claimed_hash, verified_hash, match }
compressed_context: { claimed_hash, verified_hash, match }
source_map: { claimed_hash, verified_hash, match, stale }
```

- `match` is verifier-owned.
- The canonical request envelope binds requested reduction/budget, mode, content hint, target tokenizer identity, source-manifest hash, and query hash; it excludes transport authentication and volatile run/timestamp fields.
- `raw_compressed_context` contains `{claimed_hash, verified_hash, match}` so recovery cannot invent or erase the raw artifact identity.
- `raw_compressed_context.claimed_hash` equals `compressed_context.claimed_hash` only for `emit`.
- For `full_fallback`, the final compressed-context hash binds the exact full prompt envelope delivered to the target adapter; it is not relabeled as a successful raw compression.
- Any `match: false` or `source_map.stale: true` forces `verification_status: failed`.

## Tokenization and reduction

`tokenization.target_tokenizer` contains:

- `implementation`: e.g. adapter family, not an unversioned marketing model name;
- `identifier`: vocabulary/model identifier;
- `revision`: immutable package/vocabulary revision;
- `configuration_hash`: canonical adapter configuration hash.

Counts are objects `{ "claimed": integer, "verified": integer, "match": boolean }`. Counts are non-negative. The verifier tokenizes the original full prompt envelope and final emitted prompt envelope independently with the declared identity.

`reduction` contains:

- `request_kind`: `reduction_ratio` or `token_budget`;
- `requested_reduction`: six-decimal string in `[0, 1)` derived from the request and verified original count;
- `requested_token_budget`: integer or `null`;
- `achieved_reduction`: `{claimed, verified, match}` using six-decimal strings.

The verifier reads request kind, requested ratio/budget, and tokenizer identity from the canonical request envelope, checks its request hash, and rejects any mismatch with these certificate fields.

**[PROPOSED PROJECT DECISION]** Achieved reduction is rounded half-even to six decimal places:

```text
1 - verified_compressed_token_count / verified_original_token_count
```

An original count of zero is invalid input rather than division by zero.

## Obligation counts by class

`obligations.by_class` is an object keyed by canonical class name from `invariants.md`. Every applicable class appears, including zero counts. Each value contains:

```text
applicability: applicable | not_applicable | unknown
compressor_discovered: integer
compressor_claimed_preserved: integer
verifier_discovered: integer
verifier_verified: integer
failed_obligation_ids: string[]
```

- The two `compressor_*` fields are C, S claims.
- The two `verifier_*` fields and `failed_obligation_ids` are V, S observations.
- `compressor_claimed_preserved` MUST NOT be labeled `verified`.
- `verifier_verified <= verifier_discovered`.
- A count mismatch is visible; the verifier does not overwrite the compressor count.

## Relation verification results

`relations.results` contains one record for every applicable canonical relation class:

```text
class_name
compressor_discovered
compressor_claimed_preserved
verifier_discovered
verifier_verified
failed_relation_ids
status: passed | failed | indeterminate | not_applicable
```

The verifier checks endpoint identity, direction, scope, and source binding. Endpoint presence without a verified edge counts as failure.

## Coverage

`coverage` contains:

- `certificate`: `{verified_discovered, verifier_discovered, value}`;
- `source_map`: `{protected_items_with_valid_map, protected_items, value, exact_copy_value, lineage_value}`;
- `discovery_status`: `known`, `partial`, or `unknown`;
- `completeness`: `complete`, `partial`, or `unknown`.

Ratios use six-decimal strings. A zero denominator yields `value: null` and never implies complete coverage. `completeness: complete` requires `discovery_status: known`, all applicable analyzers successful, all hard obligations/relations verified, a non-stale source map, and no failed invariant.

## Failed invariants and parser warnings

Each `failed_invariants` record contains:

```text
invariant_id
class_name
kind: obligation | relation | hash | source_map | parser | policy
severity: hard | soft
code
message
source_span_ids
candidate_span_ids
recovery_hint
```

Messages MUST NOT contain source secrets. IDs and typed codes are authoritative; prose is informational.

Each parser warning contains `source` (`compressor` or `verifier`), `component_id`, `code`, `severity`, `source_ids`, and redacted `message`. Required-parser failure sets discovery to `partial`/`unknown` and verification to `indeterminate` unless a harder hash/map failure already makes it `failed`.

## Risk and calibration

`risk` contains:

```text
score
recomputed_score
match
calibration_status: calibrated | uncalibrated | not_available
calibrator_id
calibrator_version
feature_manifest_hash
threshold
```

- `score`, `recomputed_score`, and `threshold` are six-decimal strings or `null`.
- `score` is produced by the risk component (R, S); `recomputed_score` is independently reproduced from the frozen feature manifest/model (V-equivalent recomputation, S).
- Only `calibrated` scores may be described as probabilities.
- `uncalibrated` and `not_available` may not pass a policy requiring calibrated risk.
- Verifier failure cannot be overridden by a low risk score.

## Final actions

The only allowed values are:

| Action | Meaning | Required evidence |
|---|---|---|
| `emit` | Emit the raw compressed candidate unchanged. | Final hash equals raw hash; independent verification passed; policy requirements met. |
| `restore_spans` | Emit a candidate repaired with exact original spans. | Non-empty verified restoration list; final hash differs from raw hash; final artifact independently reverified; raw failure retained. |
| `expand_budget` | Emit a newly compiled candidate at a larger budget. | Recovery event links old/new budgets and hashes; final candidate independently reverified; raw attempt retained. |
| `full_fallback` | Emit the exact full-context prompt envelope when policy permits. | Final artifact identity/hash matches the full prompt envelope; fallback reason present; raw failure retained. |

`action` contains `selected_action`, `recomputed_action`, `match`, `policy_id`, and `policy_version`. The controller produces `selected_action`; an independent deterministic policy replay over the triggering attempt's immutable verifier/risk observations and the full recovery history produces `recomputed_action`. Replaying only the already-repaired final state is invalid. Any mismatch is a hard policy invariant failure.

## Restored spans and fallback reason

Each restored span contains:

```text
restoration_id
source_span_id
original_hash
compressed_span_id
inserted_hash
reason_invariant_ids
byte_exact
verified_byte_exact
```

`verified_byte_exact` is verifier-owned and MUST be true. Restoration records reference source-map IDs; raw source text is not copied into the certificate.

`recovery_history` is an ordered, append-only array. Every record contains `attempt_id`, `artifact_hash`, `verification_status`, `failed_invariant_ids`, `action_taken`, `next_attempt_id`, and verifier-checked `references_valid`. `action_taken` is the controller response to that attempt; therefore a recovered final attempt may record `emit` while top-level `selected_action` remains `restore_spans` or `expand_budget` to describe how the final artifact was produced. The first record identifies the raw attempt. The last record links to the final `attempt_id`; the final attempt's current failures remain in `failed_invariants`. Resolved raw failures remain in history and are never deleted or relabeled as raw successes.

`fallback_reason`, when non-null, contains stable `code`, redacted `message`, `trigger_invariant_ids`, `trigger_attempt_id`, and `correctness_policy`. It is required for `full_fallback` and optional for other actions. A fallback reason is audit-critical but does not turn fallback into raw compression success.

## Component versions and timestamps

`component_versions` maps gateway, normalizer, router, analyzer registry, compressor/compiler registry, certificate generator, independent verifier, risk calibrator, recovery policy, source-map generator, canonical serializer, hashing library, and tokenizer adapter to exact immutable implementation/build version identifiers. Behavior-changing configuration hashes remain in their owning security-critical records (for example tokenizer, risk, action/policy, request, and source-map records) rather than being hidden in a display version.

Component metadata is informational but security-critical for reproducibility. Relevant verifier-local IDs are compared to runtime reality; a mismatch makes verification `indeterminate`.

`timestamps` contains `run_started_at`, `verification_started_at`, `verification_completed_at`, and `certificate_finalized_at`. They must be nondecreasing RFC 3339 UTC instants. They are informational only and never prove preservation.

## Complete JSON example

The following is a synthetic schema fixture, not a benchmark run and not a performance claim. Hashes and IDs are illustrative values with valid shapes.

```json
{
  "schema_id": "tracefold.preservation-certificate",
  "certificate_version": "1.0.0",
  "run_id": "123e4567-e89b-42d3-a456-426614174000",
  "attempt_id": "attempt-0002",
  "parent_attempt_id": "attempt-0001",
  "artifact_role": "end_to_end",
  "artifacts": {
    "source": {
      "claimed_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "verified_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "match": true
    },
    "query": {
      "claimed_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "verified_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "match": true
    },
    "request": {
      "claimed_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
      "verified_hash": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
      "match": true
    },
    "raw_compressed_context": {
      "claimed_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "verified_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "match": true
    },
    "compressed_context": {
      "claimed_hash": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      "verified_hash": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      "match": true
    },
    "source_map": {
      "claimed_hash": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
      "verified_hash": "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
      "match": true,
      "stale": false
    }
  },
  "tokenization": {
    "target_tokenizer": {
      "implementation": "fixture-tokenizer",
      "identifier": "fixture-vocabulary",
      "revision": "1.0.0",
      "configuration_hash": "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    },
    "original_token_count": {
      "claimed": 40,
      "verified": 40,
      "match": true
    },
    "compressed_token_count": {
      "claimed": 32,
      "verified": 32,
      "match": true
    }
  },
  "reduction": {
    "request_kind": "reduction_ratio",
    "requested_reduction": "0.500000",
    "requested_token_budget": null,
    "achieved_reduction": {
      "claimed": "0.200000",
      "verified": "0.200000",
      "match": true
    }
  },
  "obligations": {
    "by_class": {
      "numeric.number": {
        "applicability": "applicable",
        "compressor_discovered": 1,
        "compressor_claimed_preserved": 1,
        "verifier_discovered": 1,
        "verifier_verified": 1,
        "failed_obligation_ids": []
      },
      "numeric.unit": {
        "applicability": "applicable",
        "compressor_discovered": 1,
        "compressor_claimed_preserved": 1,
        "verifier_discovered": 1,
        "verifier_verified": 1,
        "failed_obligation_ids": []
      }
    }
  },
  "relations": {
    "results": [
      {
        "class_name": "relation.value_unit_owner",
        "compressor_discovered": 1,
        "compressor_claimed_preserved": 1,
        "verifier_discovered": 1,
        "verifier_verified": 1,
        "failed_relation_ids": [],
        "status": "passed"
      }
    ]
  },
  "coverage": {
    "certificate": {
      "verified_discovered": 3,
      "verifier_discovered": 3,
      "value": "1.000000"
    },
    "source_map": {
      "protected_items_with_valid_map": 3,
      "protected_items": 3,
      "value": "1.000000",
      "exact_copy_value": "1.000000",
      "lineage_value": "1.000000"
    },
    "discovery_status": "known",
    "completeness": "complete"
  },
  "failed_invariants": [],
  "parser_warnings": [],
  "risk": {
    "score": null,
    "recomputed_score": null,
    "match": true,
    "calibration_status": "not_available",
    "calibrator_id": null,
    "calibrator_version": null,
    "feature_manifest_hash": null,
    "threshold": null
  },
  "action": {
    "selected_action": "restore_spans",
    "recomputed_action": "restore_spans",
    "match": true,
    "policy_id": "fixture-safe-policy",
    "policy_version": "1.0.0"
  },
  "restored_spans": [
    {
      "restoration_id": "restore-0001",
      "source_span_id": "span-original-0007",
      "original_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      "compressed_span_id": "span-final-0004",
      "inserted_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      "reason_invariant_ids": [
        "obl:numeric.unit:fixture"
      ],
      "byte_exact": true,
      "verified_byte_exact": true
    }
  ],
  "recovery_history": [
    {
      "attempt_id": "attempt-0001",
      "artifact_hash": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "verification_status": "failed",
      "failed_invariant_ids": [
        "obl:numeric.unit:fixture"
      ],
      "action_taken": "restore_spans",
      "next_attempt_id": "attempt-0002",
      "references_valid": true
    },
    {
      "attempt_id": "attempt-0002",
      "artifact_hash": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      "verification_status": "passed",
      "failed_invariant_ids": [],
      "action_taken": "emit",
      "next_attempt_id": null,
      "references_valid": true
    }
  ],
  "fallback_reason": null,
  "component_versions": {
    "gateway": "fixture-gateway/0.0.0",
    "normalizer": "fixture-normalizer/0.0.0",
    "router": "fixture-router/0.0.0",
    "analyzer_registry": "fixture-analyzers/0.0.0",
    "compiler_registry": "fixture-compilers/0.0.0",
    "certificate_generator": "fixture-generator/0.0.0",
    "independent_verifier": "fixture-verifier/0.0.0",
    "risk_calibrator": "none",
    "recovery_policy": "fixture-safe-policy/1.0.0",
    "source_map_generator": "fixture-source-map/0.0.0",
    "canonical_serializer": "rfc8785-project-profile/1.0.0",
    "hashing": "sha256-domain-profile/1.0.0",
    "tokenizer_adapter": "fixture-tokenizer/1.0.0"
  },
  "timestamps": {
    "run_started_at": "2026-08-01T06:30:00.000000Z",
    "verification_started_at": "2026-08-01T06:30:00.100000Z",
    "verification_completed_at": "2026-08-01T06:30:00.200000Z",
    "certificate_finalized_at": "2026-08-01T06:30:00.300000Z"
  },
  "verification_status": "passed",
  "informational": {
    "note": "Synthetic schema fixture; not a benchmark result.",
    "extensions": {}
  }
}
```

## Validation invariants

1. Every claimed/verified hash pair has `match` equal to strict string equality.
2. Every claimed/verified count and achieved-reduction pair has a verifier-owned correct `match` value.
3. `verification_status: passed` requires all artifact matches true, non-stale map, no hard failed invariant, valid action replay, and completeness compatible with policy.
4. `emit` requires raw and final context hashes to match.
5. `restore_spans` requires at least one restoration and all `verified_byte_exact` values true.
6. `expand_budget` requires a parent attempt and a larger verified token budget/count than the parent candidate.
7. `full_fallback` requires non-null fallback reason and final identity with the full prompt envelope.
8. A non-`emit` action requires `artifact_role: end_to_end` and preserved raw-attempt linkage.
9. `calibration_status: calibrated` requires non-null score, recomputed score, model/version, feature-manifest hash, and exact recomputation match.
10. `completeness: complete` is invalid unless discovery is `known` and certificate/source-map coverage are `1.000000` with nonzero denominators.
11. Timestamps must be ordered but never affect preservation status.
12. Parser warnings and failed invariants are append-only across a recovery chain; resolved raw failures move to recovery history rather than disappearing.
13. `recovery_history` is empty only for `emit`; every non-`emit` certificate starts with the raw attempt and ends at the final attempt.
