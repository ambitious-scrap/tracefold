# TraceFold Phase 3 Contract — Deterministic Content Compression

Status: frozen implementation contract for `phase/3-deterministic-compression`.

## Objective

Add training-free raw compression for one Phase 2 source at a time: document,
dialogue, JSON, structured log, or Python. Compression is extractive or
structural, deterministic, token-budgeted, source-mapped, and honest about
refusal. This phase emits raw compression artifacts only.

Phase 3 does not generate or verify certificates, estimate risk, restore spans,
call models, persist source, or claim downstream answer retention.

## Allowed implementation surface

Use existing Phase 1/2 tokenizers, hashing, canonical serialization, source
ingestion, extraction, obligation, relation, and source-map models. Add only:

```text
docs/phases/phase-3-contract.md
src/tracefold/schemas/phase3.py
src/tracefold/compression.py
src/tracefold/compression_report.py
tests/test_phase3_*.py
tests/fixtures/phase3/
```

Existing `src/tracefold/source_maps.py` and package exports may be extended
only for raw-artifact source-map construction/validation. No new dependency is
permitted.

## Public interfaces

`tracefold.compression` exposes:

```python
build_candidates(source, extraction, tokenizer) -> tuple[CompressionCandidate, ...]
calculate_mandatory_set(candidates, tokenizer) -> MandatorySet
select_candidates(candidates, mandatory, token_budget, tokenizer) -> SelectionResult
compile_document(source, extraction, tokenizer) -> tuple[CompressionCandidate, ...]
compile_json(source, extraction, tokenizer) -> tuple[CompressionCandidate, ...]
compile_logs(source, extraction, tokenizer) -> tuple[CompressionCandidate, ...]
compile_python(source, extraction, tokenizer) -> tuple[CompressionCandidate, ...]
build_compressed_source_map(extraction, candidates, selected, omitted, ...)
compress_source(request, source, registry, extraction=None) -> RawCompressionResult
```

`compress_source` resolves request tokenizer only through supplied
`TokenizerRegistry`. Unknown identities fail; no fallback tokenizer exists.
Dispatcher selects Phase 2 content type and calls one compiler.

`compression_report` provides deterministic offline fixture report command:

```text
python3.11 -m tracefold.compression_report
```

It prints JSON diagnostics only; it is not benchmark or accuracy report.

## Request and result models

`RawCompressionRequest` contains:

```text
run_id: lowercase UUIDv4
source_id: exact Phase 2 source ID
source_kind: document | dialogue | json | log | python
tokenizer_id: existing TokenizerIdentity
target_token_budget: positive integer or null
requested_reduction: strict float in [0, 1) or null
compiler_strategy: auto | deterministic-extractive
deterministic_options: string/bool/integer map
```

At least one of `target_token_budget` and `requested_reduction` is required.
If both are supplied, `target_token_budget` is authoritative. A reduction-only
request derives budget as `max(1, floor(original_tokens * (1 - reduction)))`.
Original count is always measured before deriving this budget.

`CompressionCandidate` contains stable ID, source ID, candidate kind, exact
emitted text, tokenizer cost, priority class, original and normalized
`SourceSpan` records, covered obligation/relation IDs, mandatory flag, source
map mapping IDs when selected, compiler rule, and deterministic tie-break key.
Candidate IDs hash canonical candidate inputs; Python object hashes and set
iteration never affect them.

`OmittedSpan` contains source ID, exact original span ID, normalized span ID
when available, omission reason, intersecting obligation/relation IDs,
`reversible_from_source_map`, and deterministic omission group ID. It does
not copy source text into diagnostics.

`RawCompressionResult` contains:

```text
run_id, source_id, source_hash, normalized_source_hash
tokenizer_id, original_token_count
requested_token_budget, requested_reduction
compressed_token_count, achieved_reduction
status, compiler_strategy, compressed_text
selected_candidate_ids, omitted_spans
obligation_coverage, relation_coverage
minimum_mandatory_token_count, compressed_hash
source_map, warnings, failure, component_version, attempt_id
```

`source_map` is embedded Phase 2-compatible `SourceMap` for successful
outputs. It contains original and normalized artifacts plus a `raw_compressed`
artifact whose hash uses `tracefold:context-artifact:1\0 || compressed UTF-8
bytes`. Output spans and lineage mappings are included. Incompressible and
failed results have no compressed artifact and use `source_map: null` and
`compressed_text: null`.

Obligation/relation coverage reports discovered, mandatory, and represented
counts by canonical class. They are compressor observations, never
verification or certificate claims.

## Statuses, warnings, and failures

Exact status values:

- `compressed`: valid output token count is strictly below original count and
  all mandatory evidence is represented.
- `unchanged`: no useful reduction occurred; exact original bytes are returned.
- `incompressible`: mandatory evidence plus required markers cannot fit
  requested budget. This is a correct refusal, not extraction failure.
- `failed`: typed extraction, normalization, source-map, tokenizer, budget, or
  compiler error prevented a valid raw artifact.

Failures use stable codes and redacted messages. Warnings are typed, stable,
deterministically ordered, and never contain source bodies, credentials, or
authorization values.

## Mandatory preservation and selection

Mandatory set contains every hard Phase 2 obligation span and owner span, all
relation endpoint/evidence spans, role boundaries, system/developer
instructions, latest active user instruction, corrections and commitments,
Python imports/signatures/guards/exception paths, log errors/fatals/severity
transitions/correlation evidence, and JSON anomalies or relation-participating
rows. Ordinary homogeneous JSON row path obligations and general inferred
named-entity observations remain optional unless relation or hard value
requires them.

A candidate covering any mandatory span is mandatory. A relation cannot be
represented by retaining only its literal value: all endpoint and evidence
candidates are mandatory. Any omitted mandatory span is rejected before result
emission. Mandatory token cost includes separators and every marker. If it
exceeds budget, status is `incompressible`, with responsible
obligation/relation IDs reported.

Optional candidates are selected in descending deterministic priority and
stable tie-break order: mandatory/structural priority, protected evidence,
anomaly/severity, first/last source order, lexical uniqueness, then lower token
cost and candidate ID. Selection is greedy, local, and not semantic graph.
Source order is retained for selected source segments. Equal input, request,
tokenizer, extraction, and component version produce byte-identical output.

## Compiler rules

Document/dialogue compilation segments complete non-empty source lines/turns,
retains authority boundaries and protected instructions, and removes only
exact duplicate/boilerplate segments. Repeated content is represented by a
deterministic marker containing occurrence count and source span IDs. No unique
prose is paraphrased or summarized. Dialogue role markers are synthesized and
source-mapped as metadata.

JSON is parsed through Phase 2. Non-uniform or unsafe structures use compact
JSON with original object order. Uniform object arrays may use deterministic
schema-factored form with one field schema, typed JSON cell values, explicit
null/missing distinction, exact row count, and source-ordered rows. Selective
omission retains anomaly/protected/relation rows and records exact omitted row
spans/ranges. Mixed-type or unsupported structures fall back to compact JSON
or unchanged. Invalid JSON is `failed`.

Logs are parsed through Phase 2. Repeated equivalent normal events may be
grouped only by exact deterministic template fields. First/last event, count,
timestamp range, service, trace/request IDs, errors/fatals/warnings involved
in transitions, protected values, and explicit causal predecessors remain.
No new causality is inferred. Group markers carry exact represented source
spans and counts.

Python uses Phase 2 `ast` observations. Imports, class/function/method
signatures, decorators, parameters/annotations, protected constants, guards,
raised/handled exceptions, required returns, and exact relation participants
remain. Unconnected bodies/comments may be replaced by valid Python comments
containing original line ranges. The emitted skeleton is parsed with
`ast.parse`; syntax failure is `failed`, and dense mandatory code is
`incompressible`.

All generated markers count as emitted tokens. Markers are explicitly
synthesized and never presented as original source.

## Source-map extension

Successful raw maps preserve Phase 2 artifacts/mappings and append one
`raw_compressed` artifact. Exact copied fragments use `exact_copy` plus
`byte_exact`; compact/factored rows use structural lineage; repetition,
aggregation, and Python omission comments use synthesized semantic lineage.
Every emitted fragment has one or more original spans or explicitly
synthesized marker with rule, referenced spans, and stable identity.

Omitted source spans receive deterministic `delete` mappings with
`none_deleted` exactness. Overlapping obligation spans remain distinct. Map
validation recomputes original, normalized, and compressed hashes, bounds,
coordinates, indexes, and byte-exact mappings. Stale source or compressed
artifact rejects result. No restored artifact is created in Phase 3.

## Runtime invariants

Before returning successful result, compressor-side checks require:

1. all mandatory obligation IDs and relation endpoint/evidence spans represented;
2. selected candidate IDs unique and deterministically ordered;
3. omitted spans do not intersect unrepresented mandatory evidence;
4. all source-derived output has valid source-map lineage;
5. synthesized markers labelled and mapped non-byte-exactly;
6. compressed tokens counted from final emitted text, including markers;
7. source-map validation passes against exact artifact bytes;
8. Python output parses when Python compilation was requested.

These are compressor invariants, not proofs, certificates, or independent
verification.

## Acceptance tests

Tests cover request precedence and invalid budgets; mandatory-set floors and
incompressibility; stable IDs/tie breaks/byte-identical reruns; marker token
accounting; unknown tokenizers; omitted mandatory evidence; relation endpoint
protection; document duplicate/correction/commitment/role handling; JSON
compact and schema-factored forms, nested/mixed/null/missing/anomaly cases;
logs grouping, severity transitions, IDs, errors, causal predecessors, and
unrelated traces; Python imports/signatures/decorators/guards/exceptions,
unresolved calls, Unicode offsets, parseable omission comments, dense
incompressibility; source-map exact/lineage/synthesized/omitted mappings,
compressed bounds, stale source/output hashes; all four statuses; deterministic
fixture report output; and no Phase 4 behavior.

## Explicit non-goals

No semantic redundancy detector, semantic dependency graph, graph optimizer,
LLM/embedding/NLI/model call, query relevance, production tokenizer, target
adapter, certificate, independent verifier, calibrated risk, recovery,
fallback orchestration, source persistence, benchmark, competitor baseline,
frontend, TypeScript, deployment, authentication, or database.

## Exit commands

Inherited Phase 1 contract uses CPython `3.11.x`; exact Phase 3 commands are:

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

Known inherited issues remain recorded for final review: pre-existing Ruff
formatting differences in Markdown when checking repository root,
`mypy tracefold` is incompatible with this `src/` layout, and Starlette/httpx
emits an existing TestClient deprecation warning. Phase 3 does not weaken
quality configuration or fix unrelated inherited issues.
