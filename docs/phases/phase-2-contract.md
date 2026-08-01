# TraceFold Phase 2 Contract — Protected Obligations and Exact Source Maps

Status: frozen implementation contract for `phase/2-obligations-source-maps`.

## Objective

Add deterministic, training-free discovery of protected obligations and
relations for plain documents, dialogue, JSON, structured logs, and Python
source. Every discovered item carries exact original-source evidence. Phase 2
does not compress, summarize, verify certificates, persist source, or call a
model.

## Allowed implementation surface

Use existing Phase 1 models, canonical serialization, closed hash domains,
UUID validation, and source-map schema. Add only the smallest modules needed:

```text
src/tracefold/schemas/phase2.py
src/tracefold/sources.py
src/tracefold/obligations.py
src/tracefold/relations.py
src/tracefold/extractors.py
src/tracefold/source_maps.py
tests/test_phase2_sources.py
tests/test_phase2_documents.py
tests/test_phase2_json.py
tests/test_phase2_logs.py
tests/test_phase2_python.py
tests/test_phase2_source_maps.py
tests/fixtures/phase2/
```

No compressor, selector, semantic graph, certificate, verifier, source store,
risk, recovery, model adapter, benchmark, frontend, API success endpoint, or
new dependency is allowed.

## Public interfaces

`tracefold.sources`:

```python
ingest_source(source: SourceInput) -> SourceArtifact
source_identity(raw: bytes, input_ordinal: int) -> str
normalize_source(source: SourceArtifact) -> NormalizedSource
SourceCoordinateIndex(raw: bytes)
```

`tracefold.extractors`:

```python
extract_obligations(
    source: SourceArtifact,
    content_type: ContentType | None = None,
) -> ExtractionResult
extract_dialogue(messages: Sequence[DialogueMessage]) -> ExtractionResult
extract_relations(result: ExtractionResult) -> tuple[Relation, ...]
```

`tracefold.source_maps`:

```python
build_source_map(
    result: ExtractionResult,
    *,
    run_id: str,
    attempt_id: str,
    created_at: datetime,
) -> SourceMap
validate_source_map(
    source_map: SourceMap,
    *,
    artifacts: Mapping[str, bytes] | None = None,
    source_manifest: SourceManifest | None = None,
) -> SourceMapValidation
```

`run_id` is validated as lowercase UUIDv4. `created_at` is explicit; no
deterministic fixture or identity silently reads the clock.

## Output models

`SourceArtifact` contains source ID, ordinal, kind, authority, media type,
exact raw bytes, and portable optional file/message/role metadata. Its source
ID is `src:<ordinal>:<first-16-hex-of-raw-sha256>`. Raw artifact identity uses
`tracefold:source-artifact:1`; source IDs use the source-map contract's raw
SHA-256 display rule.

`NormalizedSource` contains original and normalized UTF-8 bytes, both
artifact-domain hashes, ordered normalization operations, and reversible
original-character to normalized-character mappings. Only these operations are
allowed:

- UTF-8 BOM removal;
- CRLF or lone CR to LF line-ending conversion.

No trimming, Unicode normalization, identifier rewriting, case folding,
reordering, comment removal, JSON formatting, or paraphrase is normalization.
An invalid UTF-8 payload raises typed `SourceNormalizationError`.

`SourceCoordinateIndex` uses half-open ranges, zero-based UTF-8 byte offsets,
zero-based Unicode scalar offsets, and one-based line/column coordinates.
Columns count Unicode scalars, not bytes or display cells. CRLF is one line
break; lone CR and LF are line breaks. Byte offsets inside a multibyte scalar
are invalid. Repeated equal text receives distinct spans because span IDs carry
coordinates.

`Obligation` fields:

```text
obligation_id
class_name
value
lexeme
source_id
source_span_ids
owner_span_ids
extraction_method
confidence: exact | inferred | unknown
discovery_status: known | partial | unknown
metadata
```

The 29 frozen obligation class names are:

```text
instruction.system_developer, role.boundary, identifier.generic,
entity.named, numeric.number, numeric.currency, numeric.percentage,
numeric.unit, temporal.date, identifier.version, logic.negation,
logic.quantifier, policy.permission, policy.prohibition, logic.condition,
logic.exception, temporal.correction, dialogue.commitment,
structured.json_schema_path, structured.anomalous_row, log.severity_change,
temporal.timestamp, identifier.trace_request, code.definition, code.import,
code.call, code.constant, code.branch_guard, code.exception_path
```

Obligation IDs are deterministic SHA-256 identifiers over canonical class,
value, and source-span inputs. Exact obligations have parser/lexeme evidence;
heuristic ownership or named-entity detection is `inferred` and never claims
complete discovery.

`Relation` fields:

```text
relation_id
relation_type
obligation_ids
evidence_span_ids
source_ids
extraction_method
discovery_status
exactness: exact | inferred
metadata
```

The 11 frozen relation names are:

```text
relation.value_unit_owner, relation.rule_exception,
relation.condition_consequence, relation.statement_correction,
relation.instruction_scope, relation.definition_use,
relation.caller_callee, relation.import_symbol,
relation.event_timestamp, relation.event_trace,
relation.error_causal_predecessor
```

Relations are an edge collection only. Endpoints and evidence must exist in
the same extraction. Exactness is `exact` only for direct parser/lexical
evidence; proximity or heuristic association is `inferred`.

## Extraction behavior

Document extraction deterministically segments lines, role labels, sentences,
and safe lexical spans. It recognizes system/developer instructions, role
boundaries, identifiers, numbers, currencies, percentages, units, dates,
versions, negations, quantifiers, permissions, prohibitions, conditions,
exceptions, corrections, commitments, and conservative named-entity signals.
It preserves latest correction evidence without deleting the superseded span.

Dialogue accepts immutable message IDs, roles, ordinals, and text. It emits
message-owned role/commitment/correction spans and correction relations across
messages. A missing message ID receives the source-map-compatible deterministic
ID `msg:<ordinal>:<role>:<short-hash-of-original-message-bytes>`.

JSON uses a strict standard-library parser with duplicate-key rejection and a
source-offset parser. It emits RFC 6901 JSON Pointers for objects, arrays,
keys, values, nulls, and containers. Successful structural traversal is
`known`; semantic anomaly detection is separately marked `partial` when its
bounded rules do not cover all possible anomalies. It detects clear status
deviations, null-vs-peer values, and peer-key deviations, retaining row spans.

Logs parse one event per original line. Supported deterministic evidence
includes ISO timestamps, severity, service, message, request/trace IDs, error
codes, exception names, event order, severity transitions, and explicit
`caused_by`/`previous_event` links. Same-trace proximity alone never creates
an exact causal relation.

Python uses `ast.parse`. AST byte columns are converted from UTF-8 byte
columns to source character/byte coordinates. It emits imports, imported
bindings, definitions/classes/functions/methods, parameters, calls, constants,
guards, returns, raises, and handled exceptions. Local symbol resolution is
exact when statically bounded; attributes, dynamic calls, reflection, and
cross-file resolution remain partial or unknown.

Unsupported media/kind combinations return `ContentType.UNKNOWN` with
`CoverageState.UNKNOWN` and a typed warning; they are not treated as empty
documents.

## Coverage and failure semantics

`CoverageState` has `known`, `partial`, `unknown`, and `failed`:

- `known`: declared bounded detector/parser completed successfully;
- `partial`: usable observations exist, but declared semantic coverage is
  incomplete or resolution is ambiguous;
- `unknown`: applicability or discovery cannot be established;
- `failed`: required parsing/extraction failed and no valid complete output is
  returned.

Zero detected obligations never implies `known` for general prose. JSON
structural paths after successful parsing and Python syntax facts after valid
AST parsing may be `known`; dynamic calls and arbitrary named entities remain
`partial`/`unknown`.

Malformed JSON, invalid UTF-8, or Python syntax errors produce typed failure
records with stable codes, redacted messages, and no fabricated coordinates.
Warnings remain attached to successful partial output. Invalid relation
endpoints, stale hashes, bad ranges, invalid JSON Pointers, portable-path
violations, and out-of-bounds coordinates are validation failures.

## Source-map construction and validation

Phase 2 maps original and normalized artifacts only; it does not invent
compressed, restored, or synthesized semantic output. Original and normalized
artifact IDs use frozen stage names and artifact hash domains. Evidence spans
are original-source spans. Normalized counterparts and mappings are emitted
when normalization changes coordinates. BOM deletion receives a tombstone;
CRLF conversion uses `normalize_line_ending` and
`character_equivalent`. Synthesized spans are never byte-exact.

`build_source_map` validates source IDs, UUIDv4 run IDs, hashes, coordinates,
span bounds, mapping endpoints, and forward/reverse indexes while constructing
the map. `map_id` is deterministic from canonical map content excluding
`map_id` and `created_at`.

`validate_source_map` recomputes supplied artifact hashes and coordinates when
raw artifact bytes are supplied, optionally recomputes the source-manifest
hash, and returns `SourceMapValidation(valid, stale, errors)`. Stale or
invalid maps are never silently repaired. `assert_valid_source_map` may raise
the typed validation error for callers needing fail-fast behavior.

## Acceptance tests

Tests cover ASCII, multibyte Unicode, combining marks, emoji, CRLF/LF,
trailing newline, empty input, repeated substrings, normalization round trips,
stale and out-of-bounds maps; document/dialogue obligations and corrections;
JSON nested paths, arrays, escaped strings, null/missing peers, anomalies, raw
offsets, duplicate/invalid JSON; log transitions, timestamps, IDs, explicit
causal predecessors, and unrelated events; Python imports, definitions, calls,
constants, guards, returns, raises, handlers, unresolved calls, Unicode, and
syntax errors; relation endpoint/evidence validation and stable IDs; all four
coverage states; and deterministic synthetic fixtures.

## Exit commands

```bash
python3.11 -m pip install -e ".[dev]"
python3.11 -m pytest -q
python3.11 -m ruff check .
python3.11 -m ruff format --check src tests
python3.11 -m mypy src tests
python3.11 -m compileall -q src tests
python3.11 -m build
git diff --check
```

No Phase 3 behavior is authorized by this contract.

## Explicit non-goals

No compression, semantic redundancy scoring, obligation graph optimization,
certificate generation/verification, persistence/restoration/fallback, risk or
calibration, provider/model integration, production tokenizer, benchmark,
frontend, TypeScript, deployment, authentication, or database.
