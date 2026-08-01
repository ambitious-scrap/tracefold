# TraceFold Phase 4 Contract — Proof-Carrying Certificates

Status: frozen implementation contract for `phase/4-proof-certificate-verifier`.

## Objective

Generate an untrusted, schema-valid preservation-certificate candidate from a
Phase 3 raw result, then independently recompute its hashes, token accounting,
obligations, relations, source-map lineage, omissions, coverage, and action.
Return a deterministic verification report. The candidate is not a certificate
of preservation until independent verification passes.

Phase 4 does not calibrate risk, execute recovery, or claim downstream answer
equivalence.

## Allowed implementation surface

```text
docs/phases/phase-4-contract.md
src/tracefold/certificates.py
src/tracefold/verifier.py
src/tracefold/schemas/phase4.py
src/tracefold/schemas/__init__.py
tests/test_phase4_certificates.py
tests/fixtures/phase4/
```

No existing specification or Phase 0–3 contract may change. No dependency is
added. Existing Phase 1–3 schemas, hashing, canonical serialization,
tokenizers, coordinate utilities, extraction parsers, and low-level source-map
validation may be reused.

## Candidate and report models

`CertificateCandidate` wraps the exact `PreservationCertificate` schema plus
`source_id`, `normalized_source_hash`, and a deterministic `certificate_hash`.
The wrapped certificate contains compressor claims, `verification_status` set
to `indeterminate`, empty recovery/restoration state, unavailable calibration,
and proposed action. Its verifier-owned fields are untrusted placeholders.

`VerificationReport` contains:

```text
report_version
certificate_hash
verification_run_id
status: valid | invalid | unverifiable | failed
verified_source_hash
verified_normalized_hash
verified_query_hash
verified_compressed_artifact_hash
verified_tokenizer
original_token_count
compressed_token_count
achieved_reduction
obligation_results
relation_results
source_map_coverage
failed_checks
warnings
recommended_action
verifier_component_version
```

`VerificationEvidence` supplies primary evidence directly: source artifact,
normalization, Phase 2 extraction, raw result, compressed source map, request,
query, and tokenizer registry. The verifier never retrieves hidden state.

## Trust boundary

`certificates.py` assembles claims only. `verifier.py` never imports the
compressor or certificate-generator preservation helpers and never accepts
compressor counts, selected IDs, omission flags, hashes, or action decisions as
proof.

Shared code is limited to immutable schemas; RFC 8785 serialization;
domain-separated hashes; tokenizer registry lookup; source coordinate/index
conversion; `normalize_source`; Phase 2 parsers; and low-level
`validate_source_map`. The modules do not share obligation coverage, relation
coverage, omission intersection, source-map sufficiency, action replay, or
failed-invariant construction.

## Generator interface

```python
generate_certificate(request, source, extraction, raw_result, *, query=None,
                      created_at=FIXED_TIME) -> CertificateCandidate
seal_certificate(candidate, report) -> PreservationCertificate
```

Generation accepts only `compressed` and `unchanged` raw results with a
compressed artifact and source map. `incompressible` and `failed` results raise
a typed generation error; no successful certificate is fabricated.

The generator binds source-manifest, query, request, raw-context, compressed-
context, and source-map claims using the frozen hash domains. It copies only
compressor observations into `compressor_*` fields. `seal_certificate` is
allowed only for a `valid` report and writes independently recomputed fields;
it does not execute recovery.

Phase 3 compression is query-independent. `query` must remain `None`; a
non-`None` query is rejected rather than producing an unusable certificate.

## Independent verification

`verify_certificate(candidate, evidence) -> VerificationReport` independently:

1. Recomputes certificate, source-manifest, query, request, context, normalized,
   and source-map hashes.
2. Resolves the declared tokenizer through the registry and counts final bytes.
3. Recomputes reduction, request-budget consistency, raw status semantics, and
   marker-inclusive token counts.
4. Re-runs Phase 2 extraction from original source and compares supplied
   extraction only as disagreement evidence.
5. Validates every source-map artifact, coordinate, index, path, identity,
   mapping, synthesized marker, and compressed bound.
6. Recomputes hard-obligation representation from source spans, usable output
   mappings, exact/structural evidence, and parsed output where applicable.
7. Recomputes relation endpoint and evidence representation; isolated values
   never satisfy a relation.
8. Recomputes omitted-span intersections without trusting `mandatory=false`.
9. Computes per-class coverage and discovery/completeness without treating zero
   detections as complete.
10. Recommends an action without executing it.

Certificate candidate metadata alone never establishes representation.

## Status semantics

- `valid`: all required deterministic checks pass; completeness remains
  `partial` when discovery is partial and never claims complete preservation.
- `invalid`: primary evidence exists but a certificate claim, hash, count,
  mapping, obligation, relation, omission, or action claim is false.
- `unverifiable`: required primary evidence is absent or discovery is unknown;
  no preservation pass is issued.
- `failed`: verifier cannot complete because of tokenizer, parser, schema, or
  internal execution failure.

## Coverage and discovery

Coverage is reported per obligation and relation class. Ratios use six-decimal
strings; zero denominator is `null`. `known`, `partial`, `unknown`, and failed
extraction states remain distinct. Complete coverage is permitted only for
known discovery, successful applicable parsing, valid non-stale maps, and zero
hard failed invariants. Partial discovery may yield a valid partial report but
never a complete-preservation claim.

## Failed invariants

Each failure is a deterministic `FailedInvariant` with stable ID, class, kind,
severity, code, redacted message, source/candidate span IDs, and recovery hint.
Failure IDs hash canonical evidence, not free-form messages. No source body,
query, credential, or secret is copied into messages.

## Hash and source-map rules

Use exact frozen domains and canonical bytes:

```text
certificate       tracefold:certificate:1.0.0
source manifest   tracefold:source-manifest:1
query             tracefold:query:1
request           tracefold:compression-request:1
source artifact   tracefold:source-artifact:1
normalized       tracefold:normalized-artifact:1
context artifact  tracefold:context-artifact:1
source map        tracefold:source-map:1
recovery history  tracefold:recovery-history:1
```

Original, normalized, and compressed bytes are supplied to validation. Any
stale artifact, map, query, manifest, coordinate, index, or hash is invalid.
Synthesized markers require synthesized lineage and cannot satisfy byte-exact
obligations. Omitted spans intersecting hard obligations, relation endpoints or
evidence, authority boundaries, anomalies, guards, or error chains fail.

## Action semantics

Only frozen actions are emitted in reports: `emit`, `restore_spans`,
`expand_budget`, `full_fallback`.

- `emit`: all deterministic checks pass.
- `restore_spans`: small verified missing source-span set could repair evidence;
  no restoration is performed.
- `expand_budget`: verified mandatory floor exceeds requested budget.
- `full_fallback`: hash/map/parser/discovery failure prevents safe proof.

## Acceptance tests

Tests cover candidate generation, schema validation, candidate determinism,
certificate/hash mutation, source/normalized/query/context/map mutations,
tokenizer and count mutations, all 29 obligation classes where fixtures expose
them, relation endpoint/evidence loss, role/negation/quantity/exception/
correction/anomaly/error-chain/branch-guard mutations, omitted mandatory spans,
stale coordinates and JSON paths, synthesized-marker labels, recovery-history
mutation, generator/verifier disagreement, unknown/partial/failed discovery,
all report statuses/actions, unchanged and incompressible raw results, and
byte-identical repeated generation/verification.

Positive fixtures remain synthetic: repeated document exception, dialogue
correction, JSON anomaly row, repetitive logs with error chain, Python guard and
exception path, unchanged context, and incompressible context.

## Explicit non-goals

No risk score/calibration, recovery, restoration, budget execution, fallback
execution, model/LLM/NLI/embedding calls, target integrations, benchmarks,
frontend, TypeScript, deployment, persistence, or semantic graph optimizer.

## Inherited final-audit items

- Phase 3 compression is far below official 70% target.
- Repository-wide Markdown Ruff discrepancy.
- `mypy tracefold` conflicts with repository `src/` layout.
- Starlette/httpx TestClient deprecation warning.
- Phase 1–3 stacked implementation remains unreviewed by final audit.

Unrelated inherited issues are not changed in Phase 4.

## Exit commands

```bash
python3.11 -m pip install -e ".[dev]"
python3.11 -m pytest -q
python3.11 -m ruff check src tests
python3.11 -m ruff format --check src tests
python3.11 -m mypy src tests
python3.11 -m compileall -q src
python3.11 -m build
python3.11 -m tracefold --help
python3.11 -c "from tracefold.api import app; print(app.title)"
git diff --check
```

Additional deterministic fixture command:

```bash
python3.11 -m tracefold.certificates
```
