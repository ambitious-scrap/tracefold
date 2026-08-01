# TraceFold Source Map Schema

Status: Phase 0 freeze

Approval amendment: the Phase 0 approval gate corrections are recorded in `PHASE_0_APPROVAL.md`. They clarify artifact hash domains and canonical invariant identifiers without changing the product specifications.

Schema ID: `tracefold.source-map`

Source-map version: `1.0.0`

The source map is a hash-bound lineage graph connecting immutable original source, deterministic normalized source, raw compressed output, restored candidates, and final compressed output. It supports exact restoration and bidirectional provenance; it is not merely a list of retained source offsets.

Source basis: `productSpec.md` §§5.3, 5.8–5.9, 7–9, 12, 19.6, and 20 and `buildPlan.md` §§2, 5–7, 9.1, and 10. **[PROPOSED PROJECT DECISION]** All coordinate bases, ID formats, mapping record shapes, normalization rules, and stale-map algorithms introduced below are proposed project decisions.

## Required guarantees

1. Original source bytes are immutable for a run.
2. Every mapped artifact is identified and hash-bound.
3. Every mapping is traversable forward and backward through explicit indexes.
4. Normalization changes are represented; normalized offsets are never treated as original offsets.
5. Deleted, synthesized, aggregated, reordered, and restored content remains represented.
6. Exactness kind is explicit. Semantic lineage is not byte identity.
7. A hash, coordinate, or reverse-index mismatch makes the map stale and blocks certification.

## Coordinate model

**[PROPOSED PROJECT DECISION]** All ranges are half-open: the start is included and the end is excluded.

| Coordinate | Base/unit | Rule |
|---|---|---|
| `byte_start`, `byte_end` | Zero-based bytes | Offsets into the exact artifact byte sequence. Text artifacts use UTF-8. Authoritative for hashing/restoration. |
| `char_start`, `char_end` | Zero-based Unicode scalar values | Count decoded Unicode code points, not UTF-16 code units and not grapheme clusters. Invalid UTF-8 has no character coordinates. |
| `line_start`, `line_end` | One-based lines | `line_end` identifies the line containing the exclusive endpoint. Empty/end-of-line ranges follow the exclusive coordinate. |
| `column_start`, `column_end` | One-based Unicode scalar columns | Columns count code points from the start of the corresponding line. Tabs count as one code point; no display-width interpretation. |

Every textual span MUST contain byte and character coordinates plus line/column coordinates. Structured/symbol/event/message coordinates supplement rather than replace offsets.

The valid empty insertion point at end-of-artifact uses `start == end == artifact length`. Negative, inclusive-end, and mixed-unit ranges are forbidden.

## Stable identifiers

**[PROPOSED PROJECT DECISION]** IDs are stable for identical ordered inputs and deterministic transforms:

- Source ID: `src:<input-ordinal>:<first-16-hex-of-raw-sha256>`.
- Artifact ID: `artifact:<stage>:<source-or-attempt-id>` where stage is `original`, `normalized`, `raw_compressed`, `restored`, or `final_compressed`.
- Span ID: `span:<artifact-id>:<byte-start>:<byte-end>:<kind>:<short-hash>`.
- Mapping ID: `map:<transform-kind>:<short-hash-of-canonical-endpoints>`.
- Python symbol ID: `py:<source-id>:<qualified-name>:<symbol-kind>:<definition-byte-start>`.
- Log event ID: `log:<source-id>:<event-ordinal>:<short-hash-of-original-event-bytes>`.
- Conversation message ID: caller-provided immutable ID when present; otherwise `msg:<ordinal>:<role>:<short-hash-of-original-message-bytes>`.

Collision checks use the full underlying SHA-256 even when an ID displays a shortened digest. A source path is metadata, not identity, because paths can move.

## File paths, JSON paths, symbols, events, and messages

- File paths are UTF-8 POSIX-style paths relative to the declared source root. They use `/`, contain no `.` or `..` segments, and preserve case. Absolute host paths are forbidden in portable maps.
- JSON paths use RFC 6901 JSON Pointer. `~` is escaped as `~0` and `/` as `~1`. The empty string denotes the document root.
- Array positions use numeric pointer tokens. If rows have stable keys, `structured_identity` records the key/value in addition to the index.
- Python symbols use the stable symbol ID plus qualified name and source file ID. Name alone is never sufficient.
- Log events use event ID plus original line/record span; template IDs and trace/request IDs are typed metadata.
- Dialogue spans carry message ID, role, ordinal, and optional speaker ID. Role/speaker metadata is part of authority lineage.

## Normalization contract

**[PROPOSED PROJECT DECISION]** Version `1.0.0` permits only these generic text normalization operations:

1. Decode as strict UTF-8 when a textual media type is declared. Invalid input remains byte-addressable and yields a parser warning; it is not replacement-decoded for certification.
2. Remove a leading UTF-8 BOM from normalized text and record it as a `delete_normalization_marker` mapping.
3. Convert CRLF and lone CR line endings to LF and record each many-byte-to-one-byte normalization mapping.
4. Preserve all other whitespace, tabs, trailing spaces, case, punctuation, and Unicode scalar sequences.
5. Do not apply Unicode normalization (NFC/NFD/NFKC/NFKD), case folding, trimming, tab expansion, quote conversion, or locale transformation.
6. Role/message/file/block boundaries remain typed metadata. Any textual delimiters inserted into a normalized composite are `synthesize_boundary` mappings, not original text.

JSON key ordering/whitespace compaction, log template factoring, code skeletonization, dialogue deduplication, and summarization are compiler transformations, not normalization.

Each normalization event identifies its rule ID, version, exact input/output spans, and exactness kind.

## Source-map envelope

A complete source map contains:

```text
schema_id
source_map_version
map_id
run_id
attempt_id
source_manifest_hash
query_hash
artifacts[]
spans[]
mappings[]
forward_index
reverse_index
coverage
normalization_profile
component_version
created_at
```

### Envelope fields

| Field | Contract |
|---|---|
| `schema_id` | Exact string `tracefold.source-map`. |
| `source_map_version` | Exact string `1.0.0`. |
| `map_id` | Stable map ID derived from canonical map content excluding `map_id` and `created_at`. |
| `run_id` / `attempt_id` | Correlation IDs matching the certificate. |
| `source_manifest_hash` | Aggregate original-source hash from the certificate contract. |
| `query_hash` | Query binding; always present, including null-query hash. |
| `artifacts` | Ordered records for every mapped original, normalized, raw, restored, and final artifact. |
| `spans` | Unique span records keyed by span ID. |
| `mappings` | Typed directed lineage edges. |
| `forward_index` | Object from every source-side span ID to ordered mapping IDs. |
| `reverse_index` | Object from every output-side span ID to ordered mapping IDs. |
| `coverage` | Exact-copy, lineage, protected-item, deleted, synthesized, and restored coverage observations. |
| `normalization_profile` | Exact ID/version and ordered rules used. |
| `component_version` | Source-map generator ID/version/config hash. |
| `created_at` | Informational RFC 3339 UTC timestamp; excluded from identity. |

## Artifact records

Each artifact record contains:

```text
artifact_id
stage
source_id or attempt_id
media_type
encoding
byte_length
char_length
line_count
hash
file_path
message_id
role
```

Fields that do not apply are explicit `null`. **[APPROVAL DECISION A-04]** Artifact hashes use this complete domain registry:

| Artifact stage | Hash domain and byte input |
|---|---|
| `original` | `sha256("tracefold:source-artifact:1\0" || exact original bytes)` |
| `normalized` | `sha256("tracefold:normalized-artifact:1\0" || exact normalized UTF-8 bytes)` |
| `raw_compressed` | `sha256("tracefold:context-artifact:1\0" || exact raw candidate UTF-8 bytes)` |
| `restored` | `sha256("tracefold:context-artifact:1\0" || exact restored-candidate UTF-8 bytes)` |
| `final_compressed` | `sha256("tracefold:context-artifact:1\0" || exact final emitted UTF-8 bytes)` |

Raw, restored, and final lifecycle roles share one content-artifact domain so equal hashes mean equal bytes. Field/stage identity and recovery history retain lifecycle distinctions. Artifact order is original input order followed by deterministic stage/attempt order.

For a multi-source normalized composite, a separate normalized artifact may reference an ordered `composed_from_source_ids` list. Boundaries are synthesized mappings; concatenation without boundary records is forbidden.

## Span records

Each span contains:

```text
span_id
artifact_id
kind
byte_start
byte_end
char_start
char_end
line_start
column_start
line_end
column_end
span_hash
json_path
file_path
code_symbol_id
log_event_id
conversation_message_id
role
structured_identity
```

- `span_hash` hashes exact span bytes with domain `tracefold:span:1`.
- `kind` is one of `text`, `boundary`, `json_value`, `json_key`, `json_container`, `log_event`, `code_node`, `dialogue_turn`, `tombstone`, or `synthesized`.
- Typed location fields are nullable but required when applicable.
- A span cannot cross artifact boundaries.
- Parent/child structure is represented through mappings or typed metadata, not implicit offset nesting.

## Mapping records

Each mapping is:

```text
mapping_id
transform
from_span_ids[]
to_span_ids[]
exactness
ordering
reason_code
obligation_ids[]
relation_ids[]
transform_component
transform_version
metadata
```

Allowed transforms:

- `exact_copy`
- `normalize_line_ending`
- `delete_normalization_marker`
- `synthesize_boundary`
- `deduplicate`
- `reorder`
- `aggregate`
- `delete`
- `synthesize_summary`
- `restore_exact`

Allowed exactness values:

- `byte_exact`
- `character_equivalent` (only declared normalization such as CRLF→LF)
- `structurally_equivalent`
- `semantic_lineage_only`
- `none_deleted`

`ordering` is `preserved`, `declared_reordered`, `many_to_one`, `one_to_many`, or `not_applicable`.

## Bidirectional mapping

Mappings are stored once as directed lineage edges, but both indexes are mandatory:

- `forward_index[span_id]` lists every mapping whose `from_span_ids` contains the span.
- `reverse_index[span_id]` lists every mapping whose `to_span_ids` contains the span.
- Deleted spans have forward entries and no reverse output span; their mapping record and tombstone/insertion anchor provide reverse auditability.
- Synthesized spans have reverse entries pointing to all contributing source spans or an empty source list only for explicit framing. They never masquerade as copied source.

The verifier rebuilds both indexes from `mappings` and requires exact equality. Missing, extra, duplicate, or differently ordered entries make the map stale.

## Overlapping spans

Overlaps are allowed because one byte sequence may participate in multiple obligations or syntax nodes. Rules:

1. Every overlap is explicit through separate span IDs.
2. Spans with identical coordinates but different `kind`/typed identity are allowed.
3. Partial overlaps cannot imply parenthood; parent/child identity must be explicit.
4. Exact restoration merges overlapping byte ranges by interval union while retaining every original span/mapping ID.
5. Conflicting transforms over the same output bytes make the map invalid unless one is a typed parent aggregate and metadata declares that relationship.

## One-to-many and many-to-one mappings

- **One-to-many:** one original/normalized span copied into multiple output locations. All outputs reference the same source span; each output has its own span hash and reverse entry.
- **Many-to-one:** repeated or distributed source spans become one output span. `ordering: many_to_one` records ordered contributors. Exact protected values are preserved only if the output retains them exactly and relation endpoints remain unambiguous.
- **Many-to-many:** represented as multiple simpler mapping records; a single opaque many-to-many record is forbidden.
- Mapping cardinality does not by itself establish semantic preservation.

## Deleted spans

A deleted span uses `transform: delete`, non-empty `from_span_ids`, empty `to_span_ids`, `exactness: none_deleted`, and metadata containing:

- deletion reason code;
- output insertion anchor span/offset when meaningful;
- whether any obligation/relation referenced the span;
- compressor decision ID;
- reversible source-store reference when policy permits.

Deleting a hard-obligation span is a verifier failure even when the tombstone is well formed.

## Synthesized summary spans

A synthesized summary uses `transform: synthesize_summary`, one or more source contributors, non-empty output span(s), and `exactness: semantic_lineage_only`. It records generator/component identity and claim IDs.

Synthesized text:

- cannot satisfy byte-exact protected obligations by paraphrase;
- cannot create identifiers, values, relations, or claims absent from mapped sources;
- counts toward lineage coverage, not exact-copy coverage;
- requires independent semantic checks if used for a soft claim;
- is removed/restored when it conflicts with exact obligations.

## Restored spans

Restoration uses `transform: restore_exact` from original span(s) directly to the restored/final output span. It requires:

- matching original and inserted span hashes;
- `exactness: byte_exact`;
- recovery event and failed-invariant IDs;
- no intermediate synthesized source as authority;
- regenerated artifact hashes, coordinates, indexes, and certificate verification.

Restored ranges that overlap are unioned for bytes but retain individual obligation links.

## Coverage

The map reports separate values:

- `lineage_coverage`: output spans with declared source lineage / all non-boundary output spans;
- `exact_copy_coverage`: byte-exact output bytes / all non-boundary output bytes;
- `protected_item_map_coverage`: verified protected items with valid source and output spans / verified protected items;
- `original_deletion_coverage`: original bytes represented either forward or as deletion tombstones / original bytes;
- `synthesized_span_count`;
- `restored_span_count`.

Ratios with zero denominators are `null`, not `1`. Certificate source-map coverage uses `protected_item_map_coverage`; it does not substitute lineage coverage.

## Hash verification and stale-map detection

The verifier MUST:

1. Recompute every artifact hash and byte/character/line length.
2. Recompute every span's bounds and span hash.
3. Reject spans that split a UTF-8 sequence or exceed artifact bounds.
4. Rebuild forward/reverse indexes and compare exactly.
5. Verify every `byte_exact` mapping by byte equality.
6. Replay declared generic normalization rules and compare normalized bytes.
7. Verify JSON pointers, file paths, symbol IDs, event IDs, and message IDs against independently parsed artifacts.
8. Verify source-manifest/query hashes match the certificate.

The map is stale when any bound artifact, manifest, query, coordinate, mapping, index, component/profile identity, or span hash differs. `stale: true` forces certificate failure and recovery/fallback. Updating only hashes without regenerating coordinates/mappings is forbidden.

## JSON mapping examples

The examples are synthetic mapping fragments. They demonstrate schema semantics and do not represent benchmark data. Common envelope/hash fields are omitted only to keep each example focused.

### 1. Document text

CRLF is normalized to LF; the protected value-unit span stays byte-exact.

```json
{
  "example_type": "document",
  "artifacts": [
    {"artifact_id": "artifact:original:src:0:fixture", "text": "Limit: 15 ms.\r\n", "byte_length": 15},
    {"artifact_id": "artifact:normalized:src:0:fixture", "text": "Limit: 15 ms.\n", "byte_length": 14},
    {"artifact_id": "artifact:final_compressed:attempt-1", "text": "Limit: 15 ms.", "byte_length": 13}
  ],
  "spans": [
    {"span_id": "span:doc:original:value-unit", "artifact_id": "artifact:original:src:0:fixture", "kind": "text", "byte_start": 7, "byte_end": 12, "char_start": 7, "char_end": 12, "line_start": 1, "column_start": 8, "line_end": 1, "column_end": 13},
    {"span_id": "span:doc:normalized:value-unit", "artifact_id": "artifact:normalized:src:0:fixture", "kind": "text", "byte_start": 7, "byte_end": 12, "char_start": 7, "char_end": 12, "line_start": 1, "column_start": 8, "line_end": 1, "column_end": 13},
    {"span_id": "span:doc:compressed:value-unit", "artifact_id": "artifact:final_compressed:attempt-1", "kind": "text", "byte_start": 7, "byte_end": 12, "char_start": 7, "char_end": 12, "line_start": 1, "column_start": 8, "line_end": 1, "column_end": 13}
  ],
  "mappings": [
    {"mapping_id": "map:doc:normalize", "transform": "exact_copy", "from_span_ids": ["span:doc:original:value-unit"], "to_span_ids": ["span:doc:normalized:value-unit"], "exactness": "byte_exact", "ordering": "preserved", "obligation_ids": ["obl:numeric.number:fixture", "obl:numeric.unit:fixture"], "relation_ids": ["rel:relation.value_unit_owner:fixture"]},
    {"mapping_id": "map:doc:compress", "transform": "exact_copy", "from_span_ids": ["span:doc:normalized:value-unit"], "to_span_ids": ["span:doc:compressed:value-unit"], "exactness": "byte_exact", "ordering": "preserved", "obligation_ids": ["obl:numeric.number:fixture", "obl:numeric.unit:fixture"], "relation_ids": ["rel:relation.value_unit_owner:fixture"]}
  ]
}
```

### 2. JSON

Byte coordinates and RFC 6901 path identify the exact protected value.

```json
{
  "example_type": "json",
  "source_id": "src:0:fixture-json",
  "original_text": "{\"id\":\"r1\",\"value\":15}",
  "compressed_text": "{\"id\":\"r1\",\"value\":15}",
  "spans": [
    {"span_id": "span:json:original:value", "artifact_id": "artifact:original:src:0:fixture-json", "kind": "json_value", "byte_start": 19, "byte_end": 21, "char_start": 19, "char_end": 21, "line_start": 1, "column_start": 20, "line_end": 1, "column_end": 22, "json_path": "/value", "structured_identity": {"key_path": "/id", "key_value": "r1"}},
    {"span_id": "span:json:compressed:value", "artifact_id": "artifact:final_compressed:attempt-1", "kind": "json_value", "byte_start": 19, "byte_end": 21, "char_start": 19, "char_end": 21, "line_start": 1, "column_start": 20, "line_end": 1, "column_end": 22, "json_path": "/value", "structured_identity": {"key_path": "/id", "key_value": "r1"}}
  ],
  "mappings": [
    {"mapping_id": "map:json:value", "transform": "exact_copy", "from_span_ids": ["span:json:original:value"], "to_span_ids": ["span:json:compressed:value"], "exactness": "byte_exact", "ordering": "preserved", "obligation_ids": ["obl:numeric.number:fixture", "obl:structured.json_schema_path:fixture"], "relation_ids": []}
  ]
}
```

### 3. Logs

Event, severity, timestamp, and trace identity remain connected.

```json
{
  "example_type": "logs",
  "source_id": "src:0:fixture-log",
  "original_text": "2026-08-01T00:00:00Z ERROR trace=t1 failed\n",
  "spans": [
    {"span_id": "span:log:event", "artifact_id": "artifact:original:src:0:fixture-log", "kind": "log_event", "byte_start": 0, "byte_end": 42, "char_start": 0, "char_end": 42, "line_start": 1, "column_start": 1, "line_end": 1, "column_end": 43, "log_event_id": "log:src:0:fixture-log:0:fixture"},
    {"span_id": "span:log:timestamp", "artifact_id": "artifact:original:src:0:fixture-log", "kind": "text", "byte_start": 0, "byte_end": 20, "char_start": 0, "char_end": 20, "line_start": 1, "column_start": 1, "line_end": 1, "column_end": 21, "log_event_id": "log:src:0:fixture-log:0:fixture"},
    {"span_id": "span:log:severity", "artifact_id": "artifact:original:src:0:fixture-log", "kind": "text", "byte_start": 21, "byte_end": 26, "char_start": 21, "char_end": 26, "line_start": 1, "column_start": 22, "line_end": 1, "column_end": 27, "log_event_id": "log:src:0:fixture-log:0:fixture"},
    {"span_id": "span:log:trace", "artifact_id": "artifact:original:src:0:fixture-log", "kind": "text", "byte_start": 33, "byte_end": 35, "char_start": 33, "char_end": 35, "line_start": 1, "column_start": 34, "line_end": 1, "column_end": 36, "log_event_id": "log:src:0:fixture-log:0:fixture"},
    {"span_id": "span:log:compressed-event", "artifact_id": "artifact:final_compressed:attempt-1", "kind": "log_event", "byte_start": 0, "byte_end": 42, "char_start": 0, "char_end": 42, "line_start": 1, "column_start": 1, "line_end": 1, "column_end": 43, "log_event_id": "log:src:0:fixture-log:0:fixture"}
  ],
  "mappings": [
    {"mapping_id": "map:log:event", "transform": "exact_copy", "from_span_ids": ["span:log:event"], "to_span_ids": ["span:log:compressed-event"], "exactness": "byte_exact", "ordering": "preserved", "obligation_ids": ["obl:temporal.timestamp:fixture", "obl:identifier.trace_request:fixture"], "relation_ids": ["rel:relation.event_timestamp:fixture", "rel:relation.event_trace:fixture"]}
  ]
}
```

### 4. Python code

The exact signature maps forward; an omitted non-protected body has a tombstone and synthesized skeleton span.

```json
{
  "example_type": "python",
  "file_path": "pkg/example.py",
  "original_text": "def f():\n    return 1\n",
  "compressed_text": "def f():\n    ...\n",
  "spans": [
    {"span_id": "span:py:original:signature", "artifact_id": "artifact:original:src:0:fixture-py", "kind": "code_node", "byte_start": 0, "byte_end": 8, "char_start": 0, "char_end": 8, "line_start": 1, "column_start": 1, "line_end": 1, "column_end": 9, "file_path": "pkg/example.py", "code_symbol_id": "py:src:0:fixture-py:f:function:0"},
    {"span_id": "span:py:compressed:signature", "artifact_id": "artifact:final_compressed:attempt-1", "kind": "code_node", "byte_start": 0, "byte_end": 8, "char_start": 0, "char_end": 8, "line_start": 1, "column_start": 1, "line_end": 1, "column_end": 9, "file_path": "pkg/example.py", "code_symbol_id": "py:src:0:fixture-py:f:function:0"},
    {"span_id": "span:py:original:body", "artifact_id": "artifact:original:src:0:fixture-py", "kind": "code_node", "byte_start": 9, "byte_end": 21, "char_start": 9, "char_end": 21, "line_start": 2, "column_start": 1, "line_end": 2, "column_end": 13, "file_path": "pkg/example.py", "code_symbol_id": "py:src:0:fixture-py:f:function:0"},
    {"span_id": "span:py:compressed:ellipsis", "artifact_id": "artifact:final_compressed:attempt-1", "kind": "synthesized", "byte_start": 9, "byte_end": 16, "char_start": 9, "char_end": 16, "line_start": 2, "column_start": 1, "line_end": 2, "column_end": 8, "file_path": "pkg/example.py", "code_symbol_id": "py:src:0:fixture-py:f:function:0"}
  ],
  "mappings": [
    {"mapping_id": "map:py:signature", "transform": "exact_copy", "from_span_ids": ["span:py:original:signature"], "to_span_ids": ["span:py:compressed:signature"], "exactness": "byte_exact", "ordering": "preserved", "obligation_ids": ["obl:code.definition:fixture"]},
    {"mapping_id": "map:py:body-skeleton", "transform": "synthesize_summary", "from_span_ids": ["span:py:original:body"], "to_span_ids": ["span:py:compressed:ellipsis"], "exactness": "semantic_lineage_only", "ordering": "many_to_one", "obligation_ids": []}
  ]
}
```

### 5. Dialogue

The superseded value is deleted with provenance; the corrected value maps exactly and retains message ownership.

```json
{
  "example_type": "dialogue",
  "messages": [
    {"message_id": "m1", "role": "user", "ordinal": 0, "text": "Use port 80."},
    {"message_id": "m2", "role": "user", "ordinal": 1, "text": "Correction: use port 8080."}
  ],
  "compressed_text": "User correction: use port 8080.",
  "spans": [
    {"span_id": "span:dialogue:m1:value", "artifact_id": "artifact:original:src:0:m1", "kind": "dialogue_turn", "byte_start": 9, "byte_end": 11, "char_start": 9, "char_end": 11, "line_start": 1, "column_start": 10, "line_end": 1, "column_end": 12, "conversation_message_id": "m1", "role": "user"},
    {"span_id": "span:dialogue:m2:value", "artifact_id": "artifact:original:src:1:m2", "kind": "dialogue_turn", "byte_start": 21, "byte_end": 25, "char_start": 21, "char_end": 25, "line_start": 1, "column_start": 22, "line_end": 1, "column_end": 26, "conversation_message_id": "m2", "role": "user"},
    {"span_id": "span:dialogue:compressed:value", "artifact_id": "artifact:final_compressed:attempt-1", "kind": "dialogue_turn", "byte_start": 26, "byte_end": 30, "char_start": 26, "char_end": 30, "line_start": 1, "column_start": 27, "line_end": 1, "column_end": 31, "conversation_message_id": "m2", "role": "user"}
  ],
  "mappings": [
    {"mapping_id": "map:dialogue:old-delete", "transform": "delete", "from_span_ids": ["span:dialogue:m1:value"], "to_span_ids": [], "exactness": "none_deleted", "ordering": "not_applicable", "obligation_ids": [], "relation_ids": ["rel:relation.statement_correction:fixture"], "metadata": {"reason_code": "superseded_value"}},
    {"mapping_id": "map:dialogue:new-copy", "transform": "exact_copy", "from_span_ids": ["span:dialogue:m2:value"], "to_span_ids": ["span:dialogue:compressed:value"], "exactness": "byte_exact", "ordering": "preserved", "obligation_ids": ["obl:numeric.number:fixture", "obl:temporal.correction:fixture"], "relation_ids": ["rel:relation.statement_correction:fixture"]}
  ]
}
```

## Source-map acceptance checks

- Coordinate conversion round-trips for ASCII, multibyte Unicode, CRLF, lone CR, tabs, and empty terminal spans.
- Original→normalized→compressed lookup and compressed→normalized→original lookup return the same declared lineage.
- Overlap union restores exact bytes without dropping obligation IDs.
- One-to-many and many-to-one indexes rebuild deterministically.
- Deleted spans remain discoverable from original coordinates.
- Synthesized spans are never classified byte-exact.
- Restored spans compare byte-identically to original spans.
- JSON pointers resolve after allowed compaction.
- Same-named Python symbols in different scopes retain different IDs.
- Log event and dialogue message ownership survives deduplication.
- Any artifact mutation causes stale-map detection before semantic certification.
