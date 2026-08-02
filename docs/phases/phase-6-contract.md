# TraceFold Phase 6 Contract — CPRGC Adaptive High-Ratio Compression

Status: frozen implementation contract for `phase/6-adaptive-high-ratio-compression`.

## Objective

Implement CPRGC, the **Constraint-Protected Relation Graph Compiler**. CPRGC
selectively losslessly compiles supported document, dialogue, JSON, log, and
Python context into a compact, readable, source-mapped representation. It
preserves exact protected obligations and required relation bridges, then lets
the existing Phase 4 verifier and Phase 5 recovery controller decide whether
the result can be emitted, repaired, expanded, or rejected.

Phase 6 measures local structural compression only. It does not estimate
downstream answer retention and does not call a target model.

## Allowed implementation surface

New implementation modules may be added under `src/tracefold/`, including:

```text
schemas/phase6.py
context_ir.py
graph.py
cprgc.py
compact_verifier.py
phase6_report.py
phase6_fixtures.py
```

Existing extraction, normalization, source-map, hashing, certificate,
verification, tokenizer, compression, and recovery interfaces remain the
source of truth. Existing Phase 0 documentation and Phase 1–5 contracts are
immutable. No new dependency is authorized.

Inherited final-audit items remain open:

- Phases 1 through 5 remain unreviewed.
- Phase 3 and Phase 5 fixture reductions remain below 70%.
- Phase 5 Brier/ECE use only three synthetic validation records; they are not
  real-world calibration.
- Repository-wide Markdown Ruff discrepancy remains.
- `mypy tracefold` does not match the `src/` layout.
- Starlette/httpx deprecation warning remains.

## CPRGC stages

1. Ingest and normalize one source through the existing interfaces.
2. Reuse the Phase 2 obligation and relation extractors.
3. Build deterministic `ContextIR` nodes and a relation graph.
4. Compute protected closure before optional scoring.
5. Apply optional query conditioning and fixed lexical/graph scores.
6. Allocate the requested budget across compact envelope, closure, structural
   summaries, anomalies, and optional evidence.
7. Compile content-specific exact representations and measure their final
   token cost including every delimiter and omission marker.
8. Select the lowest-token verifier-compatible representation.
9. Build the existing source map and certificate candidate.
10. Run the existing independent verifier plus the independent compact-fact
    verifier. Invoke Phase 5 recovery for failed verification.

## ContextIR and graph schema

`ContextIR` contains typed `ExactSpanNode`, `FactNode`, `RelationNode`,
`StructureNode`, `AggregateNode`, and `OmissionNode` records. Every node has a
stable ID derived from canonical bytes, source IDs, source spans, and its exact
payload. Fact ownership and scope are required for compact facts; ambiguous
facts remain exact spans. A compact fact never masquerades as original text.

The graph uses deterministic `GraphEdge` records. Allowed edge categories are:

```text
contains, source_order, obligation_evidence, relation_endpoint,
relation_evidence, scope, correction, condition, exception, ownership,
definition_use, caller_callee, event_trace, event_time, error_predecessor,
structural_parent
```

Edges come only from explicit extraction records or structural containment.
No unlabeled inferred semantic edge is added. Node and edge ordering is by
stable ID after source-order tie breaking.

Protected closure includes all hard obligation nodes, exact relation endpoints
and evidence, role/instruction boundaries, and the smallest bridge needed to
interpret each protected item. Preference order is:

1. verified compact fact or relation;
2. exact minimal source span;
3. larger structural span when compact ownership or syntax is ambiguous.

The frozen 29 obligation classes and 11 relation classes are unchanged.

## Query conditioning

Query is optional. When present, its canonical Phase 5 query hash binds the
source map, certificate, diagnostics, and result. Query terms are lower-cased
Unicode word/path tokens. No query still follows the same deterministic path.

For node document `d`, query term set `Q`, term frequency `tf`, document
frequency `df`, corpus size `N`, document length `|d|`, and average document
length `avgdl`, CPRGC uses:

```text
idf(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
bm25(d,Q) = sum(tf(t,d) * 2.2 / (tf(t,d) + 1.2 *
                   (0.25 + 0.75 * |d| / avgdl)) * idf(t))
```

Fixed bonuses: exact identifier `+40`, exact number/date/path/symbol `+32`,
normalized term overlap `+8` per matched term, relation-neighborhood `+12`,
graph distance penalty `-2 * distance`. These are ranking signals only;
query never removes hard obligations.

## Utility score

All values are fixed-point hundredths. For node `n`:

```text
utility(n) = 10000*hard_requirement
           + 100*query_relevance
           + 80*relation_bridge_value
           + 60*structural_value
           + 60*anomaly_value
           + 40*uniqueness_value
           + 20*recency_value
           + 40*severity_value
           - 30*redundancy_penalty
           - 10*token_cost
           - 80*ambiguity_penalty
```

Hard nodes bypass optional ranking. Ties use `(source_order, node_id)`.

## Budget and modes

Default requested reductions are conservative `0.50`, target `0.70`, and
aggressive `0.80`. An explicit token budget wins over a mode. Allocation order:
envelope, protected closure, query-critical neighborhoods, anomalies/errors,
structure, optional evidence, then recovery-marker reserve. Unused section
budget is redistributed in source order. If closure plus required envelope is
over budget, status is `incompressible`; evidence is never deleted to force a
ratio.

## Compact envelope and exactness

The only final grammar is:

```text
[TRACEFOLD CONTEXT v1]
[SOURCE <short-label> kind=<kind>]
[INSTRUCTIONS]
...
[FACTS]
- key = exact value [owner=exact scope=exact polarity=exact]
[RELATIONS]
- type: exact endpoint -> exact endpoint
[STRUCTURE]
...
[SELECTED EVIDENCE]
...
[OMISSIONS]
- exact count/range and deterministic reason
[/TRACEFOLD]
```

All headings and markers count toward token totals. Exact identifiers,
numbers, units, dates, versions, polarity, owners, scopes, correction order,
relation endpoints, trace IDs, and code symbols remain byte-exact in a compact
rendering. Ambiguous ownership or scope uses the smallest complete source
sentence/turn/row/event/AST range.

Documents preserve coherent sentence/paragraph boundaries; dialogue preserves
system/developer messages, latest request, corrections, commitments,
prohibitions, and preferences; JSON chooses measured whitespace-free JSON,
schema-factored rows, or a query/anomaly slice with exact totals and omitted
ranges; logs factor only byte-equivalent templates and retain error chains,
trace/request links, transitions, and exact first/last timestamps; Python emits
a parseable AST slice with imports, signatures, guards, exception paths, and
caller/callee closure. No free-form generated paraphrase is emitted.

Compact synthesized facts use `synthesized` source-map spans and explicit
semantic lineage. Exact source copies use `exact_copy`. Every compact fact and
relation is independently checked against source bytes, source-map ownership,
hashes, values, units, polarity, scope, endpoints, and evidence.

## Recovery compatibility

CPRGC produces the existing `RawCompressionResult` and `CertificateCandidate`
interfaces. Failed compact verification is passed to Phase 5 recovery. Exact
span restoration, deterministic budget expansion, full fallback, append-only
history, and independent re-verification remain mandatory. Raw reduction and
final repaired reduction are reported separately. Fallback has zero reduction.

## Statuses and gates

Allowed final statuses are `verified_compressed`, `verified_repaired`,
`verified_fallback`, `incompressible`, and `failed`. The target fixture gate is
mean final reduction at least 70%, at least four of five compressible fixtures
at least 70%, none below 60%, valid verification, 100% hard-obligation and
required-relation coverage, and valid source maps. Aggressive mode records raw
failures and final repaired/fallback outcomes without requiring every case to
remain above 80%. A dense protected fixture must refuse, expand, or fall back.

Synthetic fixture metrics are local structural metrics, not downstream model
accuracy or real-world calibration.

## Determinism

Canonical JSON, sorted mappings/sets, stable IDs, fixed constants, stable
example-ID splits, fixed timestamps, and the existing tokenizer are required.
Repeated identical inputs produce byte-identical IR, graph, compact context,
source map, certificate, verification report, recovery result, and canonical
diagnostics. Wall-clock latency is excluded from canonical report JSON.

## Explicit non-goals

No target-model calls, answer comparison, LLM/NLI/embedding models, neural
training, external datasets, competitor or LLMLingua/DAC adapters, production
tokenizers, databases, persistence, background workers, frontend, TypeScript,
deployment, cost estimation, or broad refactoring.

## Acceptance tests

Tests cover stable typed IR IDs, ambiguous-fact rejection, graph closure and
edge ordering, query hash/scoring, fixed budget modes, measured representation
choice, exact compact-fact tamper detection, document/dialogue/JSON/log/Python
compilers, parseability, source-map validation, certificate/verifier support,
Phase 5 repair/fallback integration, dense incompressibility, required
long-fixture gates, raw/final reporting, and byte-identical reruns.

## Exact exit commands

```bash
python -m pip install -e ".[dev]"
pytest -q
ruff check src tests
ruff format --check src tests
mypy src tests
python -m compileall -q src
python -m build
python -m tracefold --help
python -c "from tracefold.api import app; print(app.title)"
python -m tracefold.phase6_report
git diff --check
```

The canonical Phase 6 report is run twice and compared byte-for-byte after
latency fields are excluded.
