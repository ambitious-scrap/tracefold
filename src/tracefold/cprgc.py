"""Constraint-Protected Relation Graph Compiler.

This module deliberately stays training-free: extraction, fixed scoring,
compact rendering, and existing certificate/recovery infrastructure do work.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from tracefold.certificates import generate_certificate
from tracefold.compact_verifier import verify_compact_context
from tracefold.compression import build_compressed_source_map
from tracefold.context_ir import (
    _HARD_CLASSES,
    build_context_ir,
    node_source_spans,
    render_fact,
    render_node,
    stable_id,
)
from tracefold.extractors import extract_obligations
from tracefold.graph import build_relation_graph, compute_protected_closure
from tracefold.hashing import hash_query, sha256_domain
from tracefold.obligations import make_source_span
from tracefold.recovery import recover_and_verify
from tracefold.schemas.api import QueryEnvelope
from tracefold.schemas.common import ArtifactStage, FinalAction, HashDomain
from tracefold.schemas.phase2 import (
    ContentType,
    ExtractionResult,
    SourceArtifact,
)
from tracefold.schemas.phase3 import (
    CandidatePriority,
    CompilerStrategy,
    CompressionCandidate,
    CompressionStatus,
    CoverageCount,
    OmittedSpan,
    RawCompressionRequest,
    RawCompressionResult,
)
from tracefold.schemas.phase4 import VerificationReportStatus
from tracefold.schemas.phase5 import RecoveryRequest
from tracefold.schemas.phase6 import (
    BudgetAllocation,
    CertificateDiagnosticStatus,
    CompactVerificationReport,
    ContextIR,
    CPRGCDiagnostics,
    CPRGCMode,
    CPRGCResult,
    CPRGCStatus,
    ExactSpanNode,
    FactNode,
    ProtectedClosure,
    RelationNode,
    RepresentationChoice,
    RepresentationKind,
    StructureNode,
)
from tracefold.schemas.source_map import SourceMap, SourceSpan
from tracefold.serialization import canonical_json_bytes
from tracefold.source_maps import SourceMapValidationError, validate_source_map
from tracefold.sources import normalize_source
from tracefold.tokenizers import (
    Tokenizer,
    TokenizerIdentity,
    TokenizerRegistry,
    UnknownTokenizerError,
)
from tracefold.verifier import VerificationEvidence, verify_certificate

COMPONENT_VERSION = "tracefold.cprgc/1.0.0"
DEFAULT_RUN_ID = "123e4567-e89b-42d3-a456-426614174000"
MODE_REDUCTION_BASIS_POINTS: dict[CPRGCMode, int] = {
    CPRGCMode.CONSERVATIVE: 5_000,
    CPRGCMode.TARGET: 7_000,
    CPRGCMode.AGGRESSIVE: 8_000,
}
MODE_REDUCTIONS: dict[CPRGCMode, Decimal] = {
    mode: Decimal(basis_points) / Decimal(10_000)
    for mode, basis_points in MODE_REDUCTION_BASIS_POINTS.items()
}


def _mode_budget(original_token_count: int, mode: CPRGCMode) -> int:
    remaining_basis_points = 10_000 - MODE_REDUCTION_BASIS_POINTS[mode]
    return max(1, original_token_count * remaining_basis_points // 10_000)


BM25_K1 = 1.2
BM25_B = 0.75
_TERM_RE = re.compile(r"[\w./:@%+-]+", re.UNICODE)
_SENTENCE_RE = re.compile(r"[^\n.!?]+(?:[.!?]+|$)", re.MULTILINE)
_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.\d+)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?\b"
)
_TRACE_RE = re.compile(r"\b(?:trace|trace_id|request|request_id|event_id)=[^\s]+")


class CPRGCExecutionError(ValueError):
    """CPRGC could not produce typed evidence."""


def _ratio(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return f"{max(0.0, min(1.0, 1 - numerator / denominator)):.6f}"


def _plain_ratio(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{max(0.0, min(1.0, value)):.6f}"


def _terms(value: str) -> list[str]:
    return [item.lower() for item in _TERM_RE.findall(value)]


def _query_hash(query: str | None) -> str:
    return hash_query(QueryEnvelope(query=query))


def bm25_query_score(query: str | None, documents: Sequence[str]) -> list[float]:
    """Frozen dependency-free BM25-like scores, in input order."""

    query_terms = _terms(query or "")
    if not query_terms or not documents:
        return [0.0 for _ in documents]
    document_terms = [_terms(item) for item in documents]
    document_frequency = Counter(term for terms in document_terms for term in set(terms))
    average_length = sum(len(item) for item in document_terms) / len(document_terms) or 1.0
    scores: list[float] = []
    for terms in document_terms:
        frequencies = Counter(terms)
        length = len(terms) or 1
        score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            df = document_frequency[term]
            idf = math.log(1.0 + (len(documents) - df + 0.5) / (df + 0.5))
            denominator = frequency + BM25_K1 * (1 - BM25_B + BM25_B * length / average_length)
            score += idf * (frequency * (BM25_K1 + 1) / denominator)
        scores.append(score)
    return scores


def _query_match(
    query: str | None, text: str, *, relation_bonus: bool = False
) -> tuple[int, int, int, int, float]:
    query_terms = set(_terms(query or ""))
    text_terms = set(_terms(text))
    overlap = len(query_terms & text_terms)
    exact_identifier = sum(
        1
        for term in query_terms
        if ("-" in term or "/" in term or ":" in term) and term in text_terms
    )
    exact_numeric = sum(
        1 for term in query_terms if any(char.isdigit() for char in term) and term in text_terms
    )
    exact_path = sum(
        1 for term in query_terms if ("." in term or "_" in term) and term in text_terms
    )
    bm25 = bm25_query_score(query, [text])[0] if query_terms else 0.0
    return (
        exact_identifier,
        exact_numeric,
        exact_path,
        overlap,
        bm25 + (12.0 if relation_bonus and overlap else 0.0),
    )


def utility_score(
    *,
    hard_requirement: int = 0,
    query_relevance: float = 0.0,
    relation_bridge_value: int = 0,
    structural_value: int = 0,
    anomaly_value: int = 0,
    uniqueness_value: int = 0,
    recency_value: int = 0,
    severity_value: int = 0,
    redundancy_penalty: int = 0,
    token_cost: int = 0,
    ambiguity_penalty: int = 0,
) -> int:
    """Return frozen hundredth-free integer utility score."""

    return int(
        10000 * hard_requirement
        + 100 * query_relevance
        + 80 * relation_bridge_value
        + 60 * structural_value
        + 60 * anomaly_value
        + 40 * uniqueness_value
        + 20 * recency_value
        + 40 * severity_value
        - 30 * redundancy_penalty
        - 10 * token_cost
        - 80 * ambiguity_penalty
    )


def allocate_budget(
    original_token_count: int,
    *,
    mode: CPRGCMode = CPRGCMode.TARGET,
    target_token_budget: int | None = None,
    mandatory_token_cost: int = 0,
    envelope_tokens: int = 0,
    anomaly_tokens: int = 0,
    structure_tokens: int = 0,
    query_neighborhood_tokens: int = 0,
    recovery_reserve_tokens: int = 8,
) -> BudgetAllocation:
    if original_token_count < 0:
        raise ValueError("original_token_count must be non-negative")
    if target_token_budget is not None and target_token_budget <= 0:
        raise ValueError("target_token_budget must be positive")
    budget = target_token_budget or max(1, _mode_budget(original_token_count, mode))
    remaining = max(0, budget - envelope_tokens - mandatory_token_cost - recovery_reserve_tokens)
    query_budget = min(remaining, query_neighborhood_tokens)
    remaining -= query_budget
    anomaly_budget = min(remaining, anomaly_tokens)
    remaining -= anomaly_budget
    structure_budget = min(remaining, structure_tokens)
    remaining -= structure_budget
    return BudgetAllocation(
        mode=mode,
        original_token_count=original_token_count,
        requested_token_budget=budget,
        envelope_tokens=envelope_tokens,
        mandatory_token_cost=mandatory_token_cost,
        query_neighborhood_tokens=query_budget,
        anomaly_tokens=anomaly_budget,
        structure_tokens=structure_budget,
        optional_tokens=remaining,
        recovery_reserve_tokens=recovery_reserve_tokens,
        incompressible=mandatory_token_cost + envelope_tokens + recovery_reserve_tokens > budget,
    )


def _text(source: SourceArtifact) -> str:
    return source.raw_bytes.decode("utf-8", "strict")


def _full_span(source: SourceArtifact) -> SourceSpan:
    return make_source_span(source, 0, len(_text(source)), kind="text")


def _candidate(
    source: SourceArtifact,
    tokenizer: Tokenizer,
    text: str,
    spans: Sequence[SourceSpan],
    *,
    kind: str,
    order: int,
    mandatory: bool = False,
    obligation_ids: Sequence[str] = (),
    relation_ids: Sequence[str] = (),
    metadata: dict[str, Any] | None = None,
    compiler_rule: str = "cprgc",
) -> CompressionCandidate:
    original_spans = sorted(
        list(spans), key=lambda item: (item.char_start, item.char_end, item.span_id)
    )
    if not original_spans:
        raise CPRGCExecutionError(f"candidate {kind} has no source lineage")
    candidate_payload = {
        "source": source.source_id,
        "kind": kind,
        "order": order,
        "text": text,
        "spans": [item.span_id for item in original_spans],
        "obligations": sorted(set(obligation_ids)),
        "relations": sorted(set(relation_ids)),
        "metadata": metadata or {},
    }
    candidate_id = stable_id("cand", candidate_payload)
    priority = CandidatePriority.MANDATORY if mandatory else CandidatePriority.OPTIONAL
    if kind in {"structure", "header", "omission", "anchor"} and not mandatory:
        priority = CandidatePriority.STRUCTURAL
    return CompressionCandidate(
        candidate_id=candidate_id,
        source_id=source.source_id,
        candidate_kind=kind,
        emitted_text=text,
        token_cost=tokenizer.count(text),
        priority_class=priority,
        original_source_spans=original_spans,
        normalized_source_spans=[],
        obligation_ids=sorted(set(obligation_ids)),
        relation_ids=sorted(set(relation_ids)),
        mandatory=mandatory,
        source_map_mapping_ids=[],
        compiler_rule=compiler_rule,
        tie_break_key=f"{order:06d}:{original_spans[0].char_start:012d}:{candidate_id}",
        metadata={"synthesized": True, "structurally_equivalent": True, **(metadata or {})},
    )


def _node_candidate(
    source: SourceArtifact,
    tokenizer: Tokenizer,
    node: Any,
    *,
    order: int,
    mandatory: bool,
) -> CompressionCandidate:
    if isinstance(node, FactNode):
        return _candidate(
            source,
            tokenizer,
            render_fact(node),
            node.source_spans,
            kind="compact_fact",
            order=order,
            mandatory=mandatory,
            obligation_ids=node.obligation_ids,
            relation_ids=node.relation_ids,
            metadata={"fact_type": node.fact_type},
            compiler_rule="compact-exact-fact",
        )
    if isinstance(node, RelationNode):
        return _candidate(
            source,
            tokenizer,
            f"- {node.compact_rendering}",
            node.evidence_spans,
            kind="compact_relation",
            order=order,
            mandatory=mandatory,
            obligation_ids=[],
            relation_ids=[node.relation_id, *node.represented_relation_ids],
            metadata={"relation_type": node.relation_type},
            compiler_rule="compact-exact-relation",
        )
    if isinstance(node, ExactSpanNode):
        return _candidate(
            source,
            tokenizer,
            node.exact_text.strip(),
            node.original_spans,
            kind="exact_span",
            order=order,
            mandatory=mandatory,
            obligation_ids=node.obligation_ids,
            relation_ids=node.relation_ids,
            metadata={"exact": True, "synthesized": False},
            compiler_rule="exact-protected-span",
        )
    if isinstance(node, StructureNode):
        return _candidate(
            source,
            tokenizer,
            f"- structure={node.structure_type}",
            node.source_spans,
            kind="structure",
            order=order,
            mandatory=mandatory,
            obligation_ids=node.obligation_ids,
            compiler_rule="structure-record",
        )
    raise CPRGCExecutionError(f"unsupported node type {type(node).__name__}")


def _span_groups(extraction: ExtractionResult) -> dict[str, list[SourceSpan]]:
    groups: defaultdict[str, list[SourceSpan]] = defaultdict(list)
    for span in extraction.spans:
        if span.kind in {"text", "dialogue_turn", "log_event", "code_node", "json_container"}:
            groups[span.kind].append(span)
    for values in groups.values():
        values.sort(key=lambda item: (item.char_start, item.char_end, item.span_id))
    return groups


def _document_candidates(
    source: SourceArtifact, extraction: ExtractionResult, tokenizer: Tokenizer, query: str | None
) -> list[CompressionCandidate]:
    text = _text(source)
    spans: list[SourceSpan] = []
    for match in _SENTENCE_RE.finditer(text):
        start, end = match.span()
        if text[start:end].strip():
            spans.append(make_source_span(source, start, end, kind="text"))
    by_exact: dict[str, list[SourceSpan]] = defaultdict(list)
    for span in spans:
        exact = text[span.char_start : span.char_end].replace("\r\n", "\n").replace("\r", "\n")
        by_exact[exact].append(span)
    result: list[CompressionCandidate] = []
    for index, (_exact, group) in enumerate(
        sorted(by_exact.items(), key=lambda item: item[1][0].char_start)
    ):
        sample = text[group[0].char_start : group[0].char_end].strip()
        if len(group) > 1:
            rendered = f"- repeated_exact count={len(group)} text={sample}"
            result.append(
                _candidate(
                    source,
                    tokenizer,
                    rendered,
                    group,
                    kind="document_aggregate",
                    order=5000 + index,
                    metadata={"aggregate": True, "count": len(group)},
                    compiler_rule="exact-duplicate-group",
                )
            )
        else:
            result.append(
                _candidate(
                    source,
                    tokenizer,
                    sample,
                    group,
                    kind="document_sentence",
                    order=5000 + index,
                    metadata={
                        "query_match": bool(_query_match(query, sample)[3]),
                        "synthesized": False,
                    },
                    compiler_rule="sentence-candidate",
                )
            )
    return result


def _dialogue_candidates(
    source: SourceArtifact, extraction: ExtractionResult, tokenizer: Tokenizer, query: str | None
) -> list[CompressionCandidate]:
    result: list[CompressionCandidate] = []
    turns = [span for span in extraction.spans if span.kind == "dialogue_turn"]
    if not turns:
        text = _text(source)
        records: list[tuple[int, str, str, list[SourceSpan]]] = []
        cursor = 0
        for line in text.splitlines(keepends=True):
            value = line.rstrip("\r\n")
            match = re.match(r"^(system|developer|user|assistant|tool):", value, re.IGNORECASE)
            line_end = cursor + len(value)
            if match:
                lineage = [
                    span
                    for span in extraction.spans
                    if span.char_start < line_end and span.char_end > cursor
                ]
                if lineage:
                    records.append((cursor, match.group(1).lower(), value, lineage))
            cursor += len(line)
        latest_user_start = max(
            (start for start, role, _, _ in records if role == "user"),
            default=-1,
        )
        for index, (start, role, value, lineage) in enumerate(records):
            lower = value.lower()
            lineage_ids = {span.span_id for span in lineage}
            obligation_ids = [
                obligation.obligation_id
                for obligation in extraction.obligations
                if lineage_ids.intersection(obligation.source_span_ids)
            ]
            relation_ids = [
                relation.relation_id
                for relation in extraction.relations
                if lineage_ids.intersection(relation.evidence_span_ids)
            ]
            required = (
                role in {"system", "developer"}
                or start == latest_user_start
                or any(
                    marker in lower
                    for marker in (
                        "correction",
                        "actually",
                        "instead",
                        "must",
                        "prohibited",
                        "commit",
                    )
                )
            )
            result.append(
                _candidate(
                    source,
                    tokenizer,
                    value,
                    lineage,
                    kind="dialogue_turn",
                    order=5000 + index,
                    mandatory=required,
                    obligation_ids=obligation_ids,
                    relation_ids=relation_ids,
                    metadata={
                        "role": role,
                        "query_match": bool(_query_match(query, value)[3]),
                        "synthesized": False,
                    },
                    compiler_rule="dialogue-ledger-turn",
                )
            )
        return result
    turns.sort(key=lambda item: item.char_start)
    text = _text(source)
    latest_user = max(
        (span for span in turns if (span.role or "").lower() == "user"),
        key=lambda item: item.char_start,
        default=None,
    )
    seen_line_starts: set[int] = set()
    for index, span in enumerate(turns):
        line_start = text.rfind("\n", 0, span.char_start) + 1
        line_end = text.find("\n", span.char_end)
        if line_end < 0:
            line_end = len(text)
        if line_start in seen_line_starts:
            continue
        seen_line_starts.add(line_start)
        value = text[line_start:line_end].strip()
        lineage = [
            item
            for item in extraction.spans
            if item.char_start < line_end and item.char_end > line_start
        ] or [span]
        lineage_ids = {item.span_id for item in lineage}
        obligation_ids = [
            obligation.obligation_id
            for obligation in extraction.obligations
            if lineage_ids.intersection(obligation.source_span_ids)
        ]
        relation_ids = [
            relation.relation_id
            for relation in extraction.relations
            if lineage_ids.intersection(relation.evidence_span_ids)
        ]
        lower = value.lower()
        required = span is latest_user or any(
            marker in lower
            for marker in ("correction", "actually", "instead", "must", "prohibited", "commit")
        )
        result.append(
            _candidate(
                source,
                tokenizer,
                value,
                lineage,
                kind="dialogue_turn",
                order=5000 + index,
                mandatory=required,
                obligation_ids=obligation_ids,
                relation_ids=relation_ids,
                metadata={
                    "role": span.role,
                    "query_match": bool(_query_match(query, value)[3]),
                    "synthesized": False,
                },
                compiler_rule="dialogue-ledger-turn",
            )
        )
    return result


def _json_row_span(source: SourceArtifact, extraction: ExtractionResult, index: int) -> SourceSpan:
    values = [
        span
        for span in extraction.spans
        if span.json_path
        and (
            span.json_path == f"/records/{index}" or span.json_path.startswith(f"/records/{index}/")
        )
    ]
    if not values:
        values = [
            span
            for span in extraction.spans
            if span.json_path and span.json_path.startswith(f"/{index}")
        ]
    if values:
        return make_source_span(
            source,
            min(item.char_start for item in values),
            max(item.char_end for item in values),
            kind="json_container",
        )
    return _full_span(source)


def _json_row_span_from_values(source: SourceArtifact, values: Sequence[SourceSpan]) -> SourceSpan:
    if values:
        return make_source_span(
            source,
            min(item.char_start for item in values),
            max(item.char_end for item in values),
            kind="json_container",
        )
    return _full_span(source)


def _json_pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _json_object_arrays(value: Any, path: str = "") -> list[tuple[str, list[dict[str, Any]]]]:
    result: list[tuple[str, list[dict[str, Any]]]] = []
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            result.append((path, value))
        for index, item in enumerate(value):
            result.extend(_json_object_arrays(item, f"{path}/{index}"))
    elif isinstance(value, dict):
        for key, item in value.items():
            result.extend(_json_object_arrays(item, f"{path}/{_json_pointer_escape(key)}"))
    return result


def _json_row_spans(extraction: ExtractionResult, array_path: str, index: int) -> list[SourceSpan]:
    prefix = f"{array_path}/{index}" if array_path else f"/{index}"
    return [
        span
        for span in extraction.spans
        if span.json_path and (span.json_path == prefix or span.json_path.startswith(prefix + "/"))
    ]


def _render_indexes(indexes: Sequence[int]) -> str:
    return ",".join(str(index) for index in indexes)


def _json_candidates(
    source: SourceArtifact, extraction: ExtractionResult, tokenizer: Tokenizer, query: str | None
) -> list[CompressionCandidate]:
    text = _text(source).lstrip("\ufeff")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return []
    result: list[CompressionCandidate] = []
    arrays = _json_object_arrays(value)
    if not arrays:
        compact = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return [
            _candidate(
                source,
                tokenizer,
                compact,
                [_full_span(source)],
                kind="json_compact",
                order=5000,
                mandatory=True,
                compiler_rule="json-compact",
            )
        ]
    for array_path, rows in arrays:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        rendered_path = array_path or "/"
        header = f"@json path={rendered_path} rows={len(rows)} keys={','.join(keys)}"
        result.append(
            _candidate(
                source,
                tokenizer,
                header,
                [_full_span(source)],
                kind="json_schema",
                order=5000,
                mandatory=True,
                metadata={"json_path": rendered_path, "row_count": len(rows)},
                compiler_rule="json-schema-factored",
            )
        )
        for index, row in enumerate(rows):
            rendered = "|".join(
                json.dumps(row.get(key), ensure_ascii=False, separators=(",", ":"))
                if key in row
                else "~"
                for key in keys
            )
            lower = rendered.lower()
            query_match = bool(_query_match(query, rendered)[3])
            anomaly = any(token in lower for token in ("error", "failed", "critical", "anomaly"))
            required = anomaly or query_match or index in {0, len(rows) - 1}
            result.append(
                _candidate(
                    source,
                    tokenizer,
                    f"@row {index}|{rendered}",
                    [
                        _json_row_span_from_values(
                            source, _json_row_spans(extraction, array_path, index)
                        )
                    ],
                    kind="json_row",
                    order=5100 + index,
                    mandatory=required,
                    metadata={
                        "json_path": f"{array_path}/{index}" if array_path else f"/{index}",
                        "row_index": index,
                        "anomaly": anomaly,
                    },
                    compiler_rule="json-schema-row",
                )
            )
        groups: dict[str, list[int]] = defaultdict(list)
        for index, row in enumerate(rows):
            groups[
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            ].append(index)
        for group_index, (fingerprint, indexes) in enumerate(
            sorted(groups.items(), key=lambda item: item[1][0])
        ):
            if len(indexes) < 2:
                continue
            sample = json.loads(fingerprint)
            rendered = "|".join(
                json.dumps(sample.get(key), ensure_ascii=False, separators=(",", ":"))
                if key in sample
                else "~"
                for key in keys
            )
            result.append(
                _candidate(
                    source,
                    tokenizer,
                    f"@group rows={_render_indexes(indexes)} count={len(indexes)}|{rendered}",
                    [
                        _json_row_span_from_values(
                            source, _json_row_spans(extraction, array_path, index)
                        )
                        for index in indexes
                    ],
                    kind="json_aggregate",
                    order=6000 + group_index,
                    metadata={
                        "aggregate": True,
                        "count": len(indexes),
                        "json_path": rendered_path,
                    },
                    compiler_rule="json-exact-duplicate-group",
                )
            )
    return result


def _log_candidates(
    source: SourceArtifact, extraction: ExtractionResult, tokenizer: Tokenizer, query: str | None
) -> list[CompressionCandidate]:
    text = _text(source)
    events = [span for span in extraction.spans if span.kind == "log_event"]
    events.sort(key=lambda item: item.char_start)
    groups: dict[str, list[SourceSpan]] = defaultdict(list)
    first_values: dict[str, str] = {}
    result: list[CompressionCandidate] = []
    relation_by_span: defaultdict[str, list[str]] = defaultdict(list)
    for relation in extraction.relations:
        for span_id in relation.evidence_span_ids:
            relation_by_span[span_id].append(relation.relation_id)
    for span in events:
        event = text[span.char_start : span.char_end].strip()
        template = _TRACE_RE.sub("trace=<id>", _TIMESTAMP_RE.sub("<timestamp>", event))
        relation_ids = sorted(set(relation_by_span.get(span.span_id, [])))
        lineage_ids = {span.span_id}
        for relation_id in relation_ids:
            for relation in extraction.relations:
                if relation.relation_id == relation_id:
                    lineage_ids.update(relation.evidence_span_ids)
        lineage = [item for item in extraction.spans if item.span_id in lineage_ids]
        if (
            any(
                level in event.upper()
                for level in ("ERROR", "WARN", "WARNING", "CRITICAL", "FATAL")
            )
            or _query_match(query, event)[3]
        ):
            result.append(
                _candidate(
                    source,
                    tokenizer,
                    event,
                    lineage,
                    kind="log_event",
                    order=5500 + len(result),
                    mandatory=True,
                    relation_ids=relation_ids,
                    metadata={
                        "severity": "error" if "ERROR" in event.upper() else "warning",
                        "synthesized": False,
                    },
                    compiler_rule="log-protected-event",
                )
            )
        else:
            groups[template].append(span)
            first_values.setdefault(template, event)
    for index, (template, group) in enumerate(
        sorted(groups.items(), key=lambda item: item[1][0].char_start)
    ):
        first = _TIMESTAMP_RE.search(first_values[template])
        last_text = text[group[-1].char_start : group[-1].char_end]
        last = _TIMESTAMP_RE.search(last_text)
        first_value = first.group(0) if first else "-"
        last_value = last.group(0) if last else "-"
        rendered = f"- template={template} count={len(group)} first={first_value} last={last_value}"
        group_ids = {span.span_id for span in group}
        relation_ids = sorted(
            {
                relation_id
                for span_id, relation_values in relation_by_span.items()
                if span_id in group_ids
                for relation_id in relation_values
            }
        )
        lineage_ids = set(group_ids)
        for relation in extraction.relations:
            if relation.relation_id in relation_ids:
                lineage_ids.update(relation.evidence_span_ids)
        lineage = [item for item in extraction.spans if item.span_id in lineage_ids]
        result.append(
            _candidate(
                source,
                tokenizer,
                rendered,
                lineage,
                kind="log_template",
                order=5000 + index,
                mandatory=bool(relation_ids),
                relation_ids=relation_ids,
                metadata={"aggregate": True, "template": template, "count": len(group)},
                compiler_rule="log-template-factor",
            )
        )
    return result


def _python_candidates(
    source: SourceArtifact, extraction: ExtractionResult, tokenizer: Tokenizer, query: str | None
) -> list[CompressionCandidate]:
    text = _text(source)
    try:
        tree = ast.parse(text, filename=source.file_path or source.source_id)
    except SyntaxError:
        return []
    result: list[CompressionCandidate] = []
    protected_ranges = [
        (span.char_start, span.char_end)
        for span in extraction.spans
        if span.kind == "code_node"
        and any(
            obligation.class_name in {"code.branch_guard", "code.exception_path"}
            and span.span_id in obligation.source_span_ids
            for obligation in extraction.obligations
        )
    ]
    for index, node in enumerate(tree.body):
        if not hasattr(node, "lineno"):
            continue
        decorator_lines = [item.lineno for item in getattr(node, "decorator_list", [])]
        start_line = min([node.lineno, *decorator_lines])
        start = _line_start(text, start_line)
        end = _line_end(text, getattr(node, "end_lineno", node.lineno))
        source_span = make_source_span(source, start, end, kind="code_node")
        segment = text[start:end]
        name = getattr(node, "name", "")
        matched = bool(_query_match(query, segment)[3])
        protected = any(
            start <= left < end or start < right <= end for left, right in protected_ranges
        )
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not (matched or protected)
            and node.body
            and node.body[0].lineno > node.lineno
        ):
            body_line = (
                node.body[0].lineno if node.body else getattr(node, "end_lineno", node.lineno)
            )
            header = text[start : _line_start(text, body_line)].rstrip()
            rendered = f"{header}\n{' ' * (node.col_offset + 4)}..."
            result.append(
                _candidate(
                    source,
                    tokenizer,
                    rendered,
                    [source_span],
                    kind="python_skeleton",
                    order=5000 + index,
                    metadata={"symbol": name, "parseable": True, "synthesized": True},
                    compiler_rule="python-ast-skeleton",
                )
            )
        else:
            result.append(
                _candidate(
                    source,
                    tokenizer,
                    segment.rstrip(),
                    [source_span],
                    kind="python_exact_node",
                    order=5000 + index,
                    mandatory=protected or matched,
                    metadata={"symbol": name, "parseable": True, "synthesized": False},
                    compiler_rule="python-protected-ast-node",
                )
            )
    return result


def _line_start(text: str, line: int) -> int:
    return sum(len(item) for item in text.splitlines(keepends=True)[: max(0, line - 1)])


def _line_end(text: str, line: int) -> int:
    return _line_start(text, line) + len(text.splitlines(keepends=True)[line - 1])


def _content_candidates(
    source: SourceArtifact, extraction: ExtractionResult, tokenizer: Tokenizer, query: str | None
) -> list[CompressionCandidate]:
    if extraction.content_type == ContentType.DOCUMENT:
        return _document_candidates(source, extraction, tokenizer, query)
    if extraction.content_type == ContentType.DIALOGUE:
        return _dialogue_candidates(source, extraction, tokenizer, query)
    if extraction.content_type == ContentType.JSON:
        return _json_candidates(source, extraction, tokenizer, query)
    if extraction.content_type == ContentType.LOG:
        return _log_candidates(source, extraction, tokenizer, query)
    if extraction.content_type == ContentType.PYTHON:
        return _python_candidates(source, extraction, tokenizer, query)
    return []


def _node_texts(context_ir: ContextIR) -> list[str]:
    return [render_node(node) for node in context_ir.nodes]


def _node_utility(node: Any, query: str | None, tokenizer: Tokenizer) -> int:
    text = render_node(node)
    exact_id, exact_num, exact_path, overlap, bm25 = _query_match(
        query,
        text,
        relation_bonus=isinstance(node, RelationNode),
    )
    hard = int(isinstance(node, RelationNode) or getattr(node, "protection", "optional") == "hard")
    return utility_score(
        hard_requirement=hard,
        query_relevance=exact_id * 40 + exact_num * 32 + exact_path * 32 + overlap * 8 + bm25,
        relation_bridge_value=int(isinstance(node, RelationNode)),
        structural_value=int(isinstance(node, StructureNode)),
        anomaly_value=int("anomal" in text.lower() or "error" in text.lower()),
        uniqueness_value=1,
        token_cost=tokenizer.count(text),
    )


def _omitted_spans(
    source: SourceArtifact, extraction: ExtractionResult, selected: Sequence[CompressionCandidate]
) -> list[OmittedSpan]:
    def hard(obligation: Any) -> bool:
        if obligation.class_name in {"dialogue.commitment", "structured.anomalous_row"}:
            return True
        if obligation.class_name == "code.definition":
            return obligation.metadata.get("kind") not in {
                "module",
                "use",
                "import_binding",
            }
        if obligation.class_name == "log.severity_change":
            return "from" in obligation.metadata and "to" in obligation.metadata
        if obligation.class_name == "identifier.generic" and obligation.metadata.get("event_id"):
            return obligation.metadata.get("field") in {"error_code", "code"} or (
                obligation.metadata.get("kind") == "exception"
            )
        if obligation.class_name == "temporal.timestamp" and obligation.metadata.get("event_id"):
            return False
        if obligation.class_name == "entity.named" and obligation.confidence.value == "inferred":
            return False
        return (
            obligation.discovery_status.value == "known" and obligation.class_name in _HARD_CLASSES
        )

    selected_ids = {
        span.span_id for candidate in selected for span in candidate.original_source_spans
    }
    # A span carried inside a larger verbatim emission is present in the output
    # even though the emitting candidate references a different span id.
    emitted_ranges = _verbatim_ranges(selected, mandatory_only=False)
    obligation_by_span: defaultdict[str, list[str]] = defaultdict(list)
    relation_by_span: defaultdict[str, list[str]] = defaultdict(list)
    for obligation in extraction.obligations:
        if not hard(obligation):
            continue
        for span_id in obligation.source_span_ids:
            obligation_by_span[span_id].append(obligation.obligation_id)
    for relation in extraction.relations:
        for span_id in relation.evidence_span_ids:
            relation_by_span[span_id].append(relation.relation_id)
    result: list[OmittedSpan] = []
    for span in sorted(
        extraction.spans, key=lambda item: (item.char_start, item.char_end, item.span_id)
    ):
        if span.span_id in selected_ids:
            continue
        if any(start <= span.char_start and span.char_end <= end for start, end in emitted_ranges):
            continue
        if not obligation_by_span[span.span_id] and not relation_by_span[span.span_id]:
            continue
        result.append(
            OmittedSpan(
                source_id=source.source_id,
                original_span_id=span.span_id,
                omission_reason="cprgc_optional_selection",
                obligation_ids=sorted(set(obligation_by_span[span.span_id])),
                relation_ids=sorted(set(relation_by_span[span.span_id])),
                reversible_from_source_map=True,
                omission_group_id=stable_id("omit", {"span": span.span_id}),
            )
        )
    return result


def _coverage_counts(
    extraction: ExtractionResult, selected: Sequence[CompressionCandidate]
) -> tuple[dict[str, CoverageCount], dict[str, CoverageCount]]:
    selected_obligations = {item for candidate in selected for item in candidate.obligation_ids}
    selected_relations = {item for candidate in selected for item in candidate.relation_ids}
    obligation_counts: dict[str, CoverageCount] = {}
    for class_name in sorted({item.class_name for item in extraction.obligations}):
        values = [item for item in extraction.obligations if item.class_name == class_name]
        obligation_counts[class_name] = CoverageCount(
            discovered=len(values),
            mandatory=sum(item.class_name in _HARD_CLASSES for item in values),
            represented=sum(item.obligation_id in selected_obligations for item in values),
        )
    relation_counts: dict[str, CoverageCount] = {}
    for relation_type in sorted({item.relation_type for item in extraction.relations}):
        relation_values = [
            item for item in extraction.relations if item.relation_type == relation_type
        ]
        relation_counts[relation_type] = CoverageCount(
            discovered=len(relation_values),
            mandatory=len(relation_values),
            represented=sum(item.relation_id in selected_relations for item in relation_values),
        )
    return obligation_counts, relation_counts


def _bind_query(source_map: SourceMap, query: str | None) -> SourceMap:
    updated = source_map.model_copy(update={"query_hash": _query_hash(query), "map_id": "pending"})
    identity = updated.model_dump(mode="json", exclude={"map_id", "created_at"})
    map_hash = sha256_domain(HashDomain.SOURCE_MAP, canonical_json_bytes(identity))
    return updated.model_copy(update={"map_id": f"map:source-map:{map_hash[7:23]}"})


def _request(
    source: SourceArtifact,
    tokenizer: Tokenizer,
    mode: CPRGCMode,
    target_budget: int | None,
    run_id: str,
    query: str | None,
) -> RawCompressionRequest:
    options: dict[str, str | bool | int] = {
        "algorithm": "cprgc",
        "mode": mode.value,
        "query_bound": query is not None,
    }
    return RawCompressionRequest(
        run_id=run_id,
        source_id=source.source_id,
        source_kind=ContentType(source.kind)
        if source.kind in {item.value for item in ContentType}
        else ContentType.UNKNOWN,
        tokenizer_id=tokenizer.identity,
        target_token_budget=target_budget,
        requested_reduction=(None if target_budget is not None else float(MODE_REDUCTIONS[mode])),
        compiler_strategy=CompilerStrategy.DETERMINISTIC_EXTRACTIVE,
        deterministic_options=options,
    )


def _raw_result(
    request: RawCompressionRequest,
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
    selected: Sequence[CompressionCandidate],
    all_candidates: Sequence[CompressionCandidate],
    output: str,
    budget: int,
    omitted: list[OmittedSpan],
    source_map: SourceMap,
    minimum_mandatory: int,
) -> RawCompressionResult:
    original_tokens = tokenizer.count(_text(source))
    output_tokens = tokenizer.count(output)
    obligation_counts, relation_counts = _coverage_counts(extraction, selected)
    return RawCompressionResult(
        run_id=request.run_id,
        attempt_id=f"attempt:cprgc:{hashlib.sha256(canonical_json_bytes(request.model_dump(mode='json'))).hexdigest()[:16]}",
        source_id=source.source_id,
        source_hash=sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes),
        normalized_source_hash=normalize_source(source).normalized_hash,
        tokenizer_id=tokenizer.identity,
        original_token_count=original_tokens,
        requested_token_budget=budget,
        requested_reduction=request.requested_reduction,
        compressed_token_count=output_tokens,
        achieved_reduction=round(1 - output_tokens / original_tokens, 6)
        if original_tokens
        else 0.0,
        status=CompressionStatus.COMPRESSED
        if output_tokens < original_tokens
        else CompressionStatus.UNCHANGED,
        compiler_strategy=CompilerStrategy.DETERMINISTIC_EXTRACTIVE,
        compressed_text=output,
        selected_candidate_ids=[item.candidate_id for item in selected],
        omitted_spans=omitted,
        obligation_coverage=obligation_counts,
        relation_coverage=relation_counts,
        minimum_mandatory_token_count=minimum_mandatory,
        compressed_hash=sha256_domain(HashDomain.CONTEXT_ARTIFACT, output.encode("utf-8")),
        source_map=source_map,
        component_version=COMPONENT_VERSION,
    )


def _failed_raw(
    request: RawCompressionRequest, source: SourceArtifact, tokenizer: Tokenizer, code: str
) -> RawCompressionResult:
    from tracefold.schemas.phase3 import CompressionFailure

    return RawCompressionResult(
        run_id=request.run_id,
        attempt_id=f"attempt:cprgc:{hashlib.sha256(canonical_json_bytes(request.model_dump(mode='json'))).hexdigest()[:16]}",
        source_id=source.source_id,
        source_hash=sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes),
        tokenizer_id=tokenizer.identity,
        original_token_count=tokenizer.count(_text(source)),
        status=CompressionStatus.FAILED,
        compiler_strategy=CompilerStrategy.DETERMINISTIC_EXTRACTIVE,
        minimum_mandatory_token_count=0,
        failure=CompressionFailure(code=code, message=code, source_ids=[source.source_id]),
        component_version=COMPONENT_VERSION,
    )


def _section_headers(
    source: SourceArtifact, extraction: ExtractionResult, tokenizer: Tokenizer
) -> list[CompressionCandidate]:
    full = _full_span(source)
    kind = extraction.content_type.value
    values = [
        "[TRACEFOLD CONTEXT v1]",
        f"[SOURCE {source.source_id.split(':')[-1]} kind={kind}]",
        "[INSTRUCTIONS]",
        "[FACTS]",
        "[RELATIONS]",
        "[STRUCTURE]",
        "[SELECTED EVIDENCE]",
    ]
    if extraction.content_type == ContentType.PYTHON:
        values.append("[PYTHON]")
    return [
        _candidate(
            source,
            tokenizer,
            value,
            [full],
            kind="header",
            order=index,
            mandatory=True,
            compiler_rule="compact-envelope",
        )
        for index, value in enumerate(values)
    ]


_OPTIONAL_SECTION_HEADERS = {
    "[INSTRUCTIONS]",
    "[FACTS]",
    "[RELATIONS]",
    "[STRUCTURE]",
    "[SELECTED EVIDENCE]",
    "[PYTHON]",
}


def _record_section(candidate: CompressionCandidate, extraction: ExtractionResult) -> str | None:
    instruction_ids = {
        obligation.obligation_id
        for obligation in extraction.obligations
        if obligation.class_name == "instruction.system_developer"
    }
    if candidate.candidate_kind == "compact_fact":
        return "[FACTS]"
    if candidate.candidate_kind == "compact_relation":
        return "[RELATIONS]"
    if candidate.candidate_kind == "structure":
        return "[STRUCTURE]"
    if candidate.candidate_kind in {"python_skeleton", "python_exact_node"}:
        return "[PYTHON]"
    if instruction_ids.intersection(candidate.obligation_ids):
        return "[INSTRUCTIONS]"
    if candidate.candidate_kind not in {"header", "omission", "footer"}:
        return "[SELECTED EVIDENCE]"
    return None


def _elide_empty_section_headers(
    candidates: Sequence[CompressionCandidate], extraction: ExtractionResult
) -> list[CompressionCandidate]:
    occupied = {
        section
        for candidate in candidates
        if (section := _record_section(candidate, extraction)) is not None
    }
    return [
        candidate
        for candidate in candidates
        if candidate.emitted_text not in _OPTIONAL_SECTION_HEADERS
        or candidate.emitted_text in occupied
    ]


def _footer(
    source: SourceArtifact, tokenizer: Tokenizer, omitted_count: int
) -> list[CompressionCandidate]:
    full = _full_span(source)
    return [
        _candidate(
            source,
            tokenizer,
            "[OMISSIONS]",
            [full],
            kind="omission",
            order=8000,
            mandatory=True,
            compiler_rule="omission-ledger",
        ),
        _candidate(
            source,
            tokenizer,
            f"- omitted_source_spans={omitted_count} reason=optional_redundancy",
            [full],
            kind="omission",
            order=8001,
            mandatory=True,
            compiler_rule="omission-ledger",
        ),
        _candidate(
            source,
            tokenizer,
            "[/TRACEFOLD]",
            [full],
            kind="footer",
            order=9000,
            mandatory=True,
            compiler_rule="compact-envelope",
        ),
    ]


def _render(candidates: Sequence[CompressionCandidate]) -> str:
    return "\n".join(
        item.emitted_text for item in sorted(candidates, key=lambda item: item.tie_break_key)
    )


def _verbatim_ranges(
    candidates: Sequence[CompressionCandidate],
    *,
    mandatory_only: bool = True,
) -> list[tuple[int, int]]:
    """Return source ranges a candidate already emits byte-for-byte."""

    ranges = [
        (span.char_start, span.char_end)
        for candidate in candidates
        if candidate.metadata.get("synthesized") is False
        and (candidate.mandatory or not mandatory_only)
        for span in candidate.original_source_spans
    ]
    return sorted(ranges)


def _covered_verbatim(node: Any, ranges: Sequence[tuple[int, int]]) -> bool:
    """Report whether verbatim output already carries every span of a compact node.

    A synthesized fact or relation line restates evidence that is present exactly,
    so it is redundant rather than protected and must not consume mandatory budget.
    """

    if not ranges or not isinstance(node, (FactNode, RelationNode)):
        return False
    spans = node_source_spans(node)
    if not spans:
        return False
    return all(
        any(start <= span.char_start and span.char_end <= end for start, end in ranges)
        for span in spans
    )


def _select(
    candidates: Sequence[CompressionCandidate],
    mandatory: Sequence[CompressionCandidate],
    budget: int,
    tokenizer: Tokenizer,
    query: str | None,
) -> tuple[list[CompressionCandidate], bool]:
    selected = list(mandatory)
    if tokenizer.count(_render(selected)) > budget:
        return selected, False
    optional = [item for item in candidates if not item.mandatory and item not in selected]
    optional.sort(
        key=lambda item: (
            -utility_score(
                query_relevance=_query_match(query, item.emitted_text)[3] * 8
                + _query_match(query, item.emitted_text)[4],
                anomaly_value=int(item.metadata.get("anomaly", False)),
                uniqueness_value=1,
                token_cost=item.token_cost,
            ),
            item.tie_break_key,
        )
    )
    for item in optional:
        candidate = [*selected, item]
        if tokenizer.count(_render(candidate)) <= budget:
            selected.append(item)
    return selected, True


def _finalize_selection(
    source: SourceArtifact,
    extraction: ExtractionResult,
    selected: Sequence[CompressionCandidate],
    tokenizer: Tokenizer,
    budget: int,
) -> tuple[list[CompressionCandidate], list[OmittedSpan], bool]:
    """Rebuild final markers and enforce budget against final rendered bytes."""

    current = _elide_empty_section_headers(
        [item for item in selected if item.candidate_kind not in {"omission", "footer"}],
        extraction,
    )
    for _ in range(len(current) + 2):
        current = _elide_empty_section_headers(current, extraction)
        omitted = _omitted_spans(source, extraction, current)
        final = [*current, *_footer(source, tokenizer, len(omitted))]
        if tokenizer.count(_render(final)) <= budget:
            return final, omitted, True
        optional = [item for item in current if not item.mandatory]
        if not optional:
            return final, omitted, False
        current.remove(optional[-1])
    raise AssertionError("bounded final-budget loop exhausted")


def _diagnostics(
    raw: RawCompressionResult,
    final: RawCompressionResult | None,
    allocation: BudgetAllocation,
    selected: Sequence[CompressionCandidate],
    headers: Sequence[CompressionCandidate],
    closure: ProtectedClosure,
    action: FinalAction,
    certificate_status: CertificateDiagnosticStatus,
    verification_status: str,
    tokenizer: Tokenizer,
    source: SourceArtifact,
) -> CPRGCDiagnostics:
    final_tokens = final.compressed_token_count if final is not None else None
    final_reduction = None
    if final is not None and final.achieved_reduction is not None:
        final_reduction = _plain_ratio(final.achieved_reduction)
    if action == FinalAction.FULL_FALLBACK:
        final_tokens = raw.original_token_count
        final_reduction = "0.000000"
    raw_reduction = _plain_ratio(raw.achieved_reduction)
    omitted_tokens = max(
        0, tokenizer.count(_text(source)) - (final_tokens or raw.compressed_token_count or 0)
    )
    choices = [
        RepresentationChoice(
            source_id=source.source_id,
            kind=(
                RepresentationKind.FACT_LEDGER
                if item.candidate_kind == "compact_fact"
                else RepresentationKind.RELATION_LEDGER
                if item.candidate_kind == "compact_relation"
                else RepresentationKind.EXACT
            ),
            token_count=item.token_cost,
            mandatory_coverage="1.000000" if item.mandatory else None,
            relation_coverage="1.000000" if item.relation_ids else None,
            verifier_compatible=True,
            source_map_valid=True,
            parseable=True if source.kind == ContentType.PYTHON.value else None,
            selected=True,
            reason=item.compiler_rule,
        )
        for item in selected
        if item not in headers and item.candidate_kind not in {"header", "footer", "omission"}
    ]
    return CPRGCDiagnostics(
        original_tokens=raw.original_token_count,
        raw_compressed_tokens=raw.compressed_token_count,
        final_tokens=final_tokens,
        requested_reduction=_plain_ratio(raw.requested_reduction),
        raw_reduction=raw_reduction,
        final_reduction=final_reduction,
        mandatory_closure_tokens=closure.mandatory_token_cost,
        compact_fact_tokens=sum(
            item.token_cost for item in selected if item.candidate_kind == "compact_fact"
        ),
        relation_tokens=sum(
            item.token_cost for item in selected if item.candidate_kind == "compact_relation"
        ),
        structure_tokens=sum(
            item.token_cost
            for item in selected
            if item.candidate_kind in {"structure", "python_skeleton"}
        ),
        optional_evidence_tokens=sum(item.token_cost for item in selected if not item.mandatory),
        envelope_tokens=sum(item.token_cost for item in headers),
        omitted_tokens=omitted_tokens,
        certificate_status=certificate_status,
        verification_status=verification_status,
        recovery_action=action,
        restored_tokens=max(0, (final_tokens or 0) - (raw.compressed_token_count or 0)),
        representation_choices=choices,
        budget_allocation=allocation,
    )


def _certificate_diagnostic_status(
    candidate: object | None, report: object | None
) -> CertificateDiagnosticStatus:
    if candidate is None:
        return CertificateDiagnosticStatus.UNAVAILABLE
    if report is None:
        return CertificateDiagnosticStatus.GENERATED_UNVERIFIED
    status = getattr(report, "status", None)
    if status == VerificationReportStatus.VALID:
        return CertificateDiagnosticStatus.VERIFIED_VALID
    if status == VerificationReportStatus.INVALID:
        return CertificateDiagnosticStatus.VERIFIED_INVALID
    if status == VerificationReportStatus.UNVERIFIABLE:
        return CertificateDiagnosticStatus.UNVERIFIABLE
    return CertificateDiagnosticStatus.VERIFIED_INVALID


def _merge_compact_failures(report: Any, compact_report: CompactVerificationReport | None) -> Any:
    if report is None or compact_report is None or compact_report.status == "valid":
        return report
    failures = {item.invariant_id: item for item in report.failed_checks}
    failures.update({item.invariant_id: item for item in compact_report.failed_invariants})
    return report.model_copy(
        update={
            "status": VerificationReportStatus.INVALID,
            "failed_checks": [failures[key] for key in sorted(failures)],
            "recommended_action": FinalAction.RESTORE_SPANS,
        }
    )


def compress_with_cprgc(
    source: SourceArtifact,
    registry: TokenizerRegistry,
    *,
    tokenizer_identity: TokenizerIdentity | None = None,
    tokenizer: Tokenizer | None = None,
    query: str | None = None,
    mode: CPRGCMode = CPRGCMode.TARGET,
    target_token_budget: int | None = None,
    extraction: ExtractionResult | None = None,
    run_id: str = DEFAULT_RUN_ID,
    maximum_attempts: int = 3,
    maximum_final_token_budget: int | None = None,
) -> CPRGCResult:
    """Compile one source with CPRGC and reuse Phase 5 recovery on failure."""

    if isinstance(mode, str):
        mode = CPRGCMode(mode)
    if (tokenizer_identity is None) == (tokenizer is None):
        raise CPRGCExecutionError("CPRGC requires exactly one of tokenizer_identity or tokenizer")
    if tokenizer is None:
        assert tokenizer_identity is not None
        try:
            tokenizer = registry.resolve(tokenizer_identity)
        except UnknownTokenizerError as exc:
            raise CPRGCExecutionError("unknown CPRGC tokenizer identity") from exc
    else:
        tokenizer_identity = tokenizer.identity
        try:
            registry.resolve(tokenizer_identity)
        except UnknownTokenizerError:
            registry.register(tokenizer)
    extraction = extraction or extract_obligations(source, ContentType(source.kind))
    if extraction.coverage.value == "failed":
        raw = _failed_raw(
            _request(source, tokenizer, mode, target_token_budget, run_id, query),
            source,
            tokenizer,
            "EXTRACTION_FAILURE",
        )
        raise CPRGCExecutionError("extraction failed")
    request = _request(source, tokenizer, mode, target_token_budget, run_id, query)
    context_ir = build_context_ir(source, extraction, tokenizer, query=query)
    graph = build_relation_graph(context_ir, extraction)
    closure = compute_protected_closure(context_ir, graph, extraction, tokenizer)
    headers = _section_headers(source, extraction, tokenizer)
    content_candidates = _content_candidates(source, extraction, tokenizer, query)
    closure_ids = set(closure.node_ids)
    covered_obligation_ids = {
        obligation_id
        for candidate in content_candidates
        if source.kind == "dialogue" and candidate.mandatory
        for obligation_id in candidate.obligation_ids
    }
    covered_relation_ids = {
        relation_id
        for candidate in content_candidates
        if source.kind == "dialogue" and candidate.mandatory
        for relation_id in candidate.relation_ids
    }
    verbatim_ranges = _verbatim_ranges(content_candidates)
    node_candidates = [
        _node_candidate(
            source,
            tokenizer,
            node,
            order=1000 + index,
            mandatory=(
                (
                    (
                        node.node_id in closure_ids
                        and not (
                            getattr(node, "obligation_ids", [])
                            and set(getattr(node, "obligation_ids", [])) <= covered_obligation_ids
                        )
                        and not (
                            isinstance(node, RelationNode)
                            and node.relation_id in covered_relation_ids
                        )
                    )
                    or (
                        source.kind == "python"
                        and isinstance(node, RelationNode)
                        and not node.mandatory
                    )
                )
                and not _covered_verbatim(node, verbatim_ranges)
            ),
        )
        for index, node in enumerate(context_ir.nodes)
        if isinstance(node, (FactNode, RelationNode, ExactSpanNode, StructureNode))
        and not (isinstance(node, RelationNode) and not node.mandatory and source.kind != "python")
    ]
    footer = _footer(source, tokenizer, len(extraction.spans))
    all_candidates = _elide_empty_section_headers(
        [*headers, *node_candidates, *content_candidates, *footer], extraction
    )
    headers = [item for item in all_candidates if item.candidate_kind == "header"]
    mandatory = [item for item in all_candidates if item.mandatory]
    original_tokens = tokenizer.count(_text(source))
    requested_budget = target_token_budget or max(1, _mode_budget(original_tokens, mode))
    allocation = allocate_budget(
        original_tokens,
        mode=mode,
        target_token_budget=requested_budget,
        mandatory_token_cost=closure.mandatory_token_cost,
        envelope_tokens=tokenizer.count(_render(headers)),
        anomaly_tokens=sum(
            item.token_cost for item in content_candidates if item.metadata.get("anomaly")
        ),
        structure_tokens=sum(
            item.token_cost
            for item in content_candidates
            if item.candidate_kind == "python_skeleton"
        ),
        query_neighborhood_tokens=sum(
            item.token_cost for item in content_candidates if item.metadata.get("query_match")
        ),
    )
    selected, fits = _select(all_candidates, mandatory, requested_budget, tokenizer, query)
    omitted: list[OmittedSpan] = []
    if fits:
        selected, omitted, fits = _finalize_selection(
            source, extraction, selected, tokenizer, requested_budget
        )
    if not fits:
        raw = RawCompressionResult(
            run_id=request.run_id,
            attempt_id=f"attempt:cprgc:{hashlib.sha256(canonical_json_bytes(request.model_dump(mode='json'))).hexdigest()[:16]}",
            source_id=source.source_id,
            source_hash=sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes),
            normalized_source_hash=normalize_source(source).normalized_hash,
            tokenizer_id=tokenizer.identity,
            original_token_count=original_tokens,
            requested_token_budget=requested_budget,
            requested_reduction=request.requested_reduction,
            status=CompressionStatus.INCOMPRESSIBLE,
            compiler_strategy=CompilerStrategy.DETERMINISTIC_EXTRACTIVE,
            minimum_mandatory_token_count=tokenizer.count(_render(mandatory)),
            component_version=COMPONENT_VERSION,
        )
        diagnostics = CPRGCDiagnostics(
            original_tokens=original_tokens,
            raw_compressed_tokens=None,
            final_tokens=None,
            requested_reduction=_plain_ratio(request.requested_reduction),
            raw_reduction=None,
            final_reduction=None,
            mandatory_closure_tokens=closure.mandatory_token_cost,
            compact_fact_tokens=0,
            relation_tokens=0,
            structure_tokens=0,
            optional_evidence_tokens=0,
            envelope_tokens=tokenizer.count(_render(headers)),
            omitted_tokens=0,
            certificate_status=CertificateDiagnosticStatus.UNAVAILABLE,
            verification_status="incompressible",
            recovery_action=FinalAction.EXPAND_BUDGET,
            restored_tokens=0,
            budget_allocation=allocation,
        )
        return CPRGCResult(
            status=CPRGCStatus.INCOMPRESSIBLE,
            final_action=FinalAction.EXPAND_BUDGET,
            context="",
            tokenizer_identity=tokenizer.identity,
            context_ir=context_ir,
            graph=graph,
            protected_closure=closure,
            raw_result=raw,
            final_result=None,
            certificate=None,
            verification_report=None,
            recovery_result=None,
            diagnostics=diagnostics,
            warnings=["mandatory closure exceeds requested budget"],
        )
    # _finalize_selection already rebuilt and counted final omission/footer markers.
    all_candidates = [
        item for item in all_candidates if item.candidate_kind not in {"omission", "footer"}
    ]
    all_candidates.extend(selected)
    output = _render(selected)
    request_digest = hashlib.sha256(
        canonical_json_bytes(request.model_dump(mode="json"))
    ).hexdigest()[:16]
    attempt_id = f"attempt:cprgc:{request_digest}"
    try:
        source_map = build_compressed_source_map(
            extraction,
            all_candidates,
            selected,
            omitted,
            output_text=output,
            run_id=request.run_id,
            attempt_id=attempt_id,
        )
        source_map = _bind_query(source_map, query)
        artifacts = {
            item.artifact_id: (
                source.raw_bytes
                if item.stage == ArtifactStage.ORIGINAL
                else normalize_source(source).normalized_bytes
                if item.stage == ArtifactStage.NORMALIZED
                else output.encode("utf-8")
            )
            for item in source_map.artifacts
        }
        source_map_validation = validate_source_map(source_map, artifacts=artifacts)
        if not source_map_validation.valid:
            raise SourceMapValidationError("; ".join(source_map_validation.errors))
        raw = _raw_result(
            request,
            source,
            extraction,
            tokenizer,
            selected,
            all_candidates,
            output,
            requested_budget,
            omitted,
            source_map,
            tokenizer.count(_render(mandatory)),
        )
        candidate = generate_certificate(request, source, extraction, raw, query=query)
        report = verify_certificate(
            candidate,
            VerificationEvidence(
                source=source,
                raw_result=raw,
                registry=registry,
                request=request,
                extraction=extraction,
                normalized_source=normalize_source(source),
                source_map=source_map,
                compressed_text=output,
                query=query,
            ),
        )
        compact_report = verify_compact_context(
            source, extraction, context_ir, output, source_map, query=query
        )
        report = _merge_compact_failures(report, compact_report)
    except (ValueError, SourceMapValidationError, UnknownTokenizerError) as exc:
        raw = _failed_raw(request, source, tokenizer, type(exc).__name__)
        candidate = None
        report = None
        compact_report = None
    recovery_result = None
    final_result = raw
    final_candidate: Any = candidate
    final_report = report
    final_action = FinalAction.EMIT
    status = CPRGCStatus.VERIFIED_COMPRESSED
    warnings: list[str] = []
    if (
        report is None
        or report.status != VerificationReportStatus.VALID
        or compact_report is None
        or compact_report.status != "valid"
    ):
        warnings.extend(
            [item.code for item in report.failed_checks]
            if report is not None
            else ["certificate_generation_failed"]
        )
        if (
            candidate is not None
            and report is not None
            and raw.status in {CompressionStatus.COMPRESSED, CompressionStatus.UNCHANGED}
        ):
            maximum_budget = maximum_final_token_budget or max(original_tokens, requested_budget)
            recovery_request = RecoveryRequest(
                source=source,
                request=request,
                extraction=extraction,
                raw_result=raw,
                certificate=candidate,
                verification_report=report,
                maximum_attempts=maximum_attempts,
                maximum_final_token_budget=maximum_budget,
                deterministic_options={"restore_span_limit": 8},
            )
            try:
                recovery_result = recover_and_verify(recovery_request, registry)
                final_result = recovery_result.final_raw_result or raw
                final_candidate = recovery_result.final_certificate
                final_report = recovery_result.final_verification_report
                final_action = recovery_result.final_action
                if final_action == FinalAction.FULL_FALLBACK:
                    status = CPRGCStatus.VERIFIED_FALLBACK
                elif recovery_result.final_status == "valid":
                    status = CPRGCStatus.VERIFIED_REPAIRED
                else:
                    status = CPRGCStatus.FAILED
            except ValueError as exc:
                warnings.append(type(exc).__name__)
                status = CPRGCStatus.FAILED
                final_action = FinalAction.FULL_FALLBACK
    else:
        status = CPRGCStatus.VERIFIED_COMPRESSED
        final_action = FinalAction.EMIT

    final_compact_report = compact_report
    if (
        recovery_result is not None
        and final_result is not None
        and final_result.source_map is not None
        and final_result.compressed_text is not None
    ):
        # Recovery recompiles through the query-independent Phase 3 compressor, so its
        # artifact and source map are bound to the empty query. The compact verifier must
        # check the artifact that is actually emitted against the binding it carries,
        # otherwise every query-driven recovery reports a spurious query mismatch.
        recovered_query = query if final_result.component_version == COMPONENT_VERSION else None
        recovered_ir = (
            context_ir
            if recovered_query == query
            else build_context_ir(source, extraction, tokenizer)
        )
        final_compact_report = verify_compact_context(
            source,
            extraction,
            recovered_ir,
            final_result.compressed_text,
            final_result.source_map,
            query=recovered_query,
        )
        final_report = _merge_compact_failures(final_report, final_compact_report)
        if final_compact_report.status != "valid" and final_action != FinalAction.FULL_FALLBACK:
            warnings.extend(item.code for item in final_compact_report.failed_invariants)
            status = CPRGCStatus.FAILED
            final_action = FinalAction.FULL_FALLBACK
    diagnostics = _diagnostics(
        raw,
        final_result,
        allocation,
        selected,
        headers,
        closure,
        final_action,
        _certificate_diagnostic_status(final_candidate, final_report),
        final_report.status.value if final_report is not None else "failed",
        tokenizer,
        source,
    )
    return CPRGCResult(
        status=status,
        final_action=final_action,
        context=(
            _text(source)
            if final_action == FinalAction.FULL_FALLBACK
            else final_result.compressed_text or _text(source)
            if final_result is not None
            else ""
        ),
        tokenizer_identity=tokenizer.identity,
        context_ir=context_ir,
        graph=graph,
        protected_closure=closure,
        raw_result=raw,
        final_result=final_result,
        certificate=final_candidate,
        verification_report=final_report,
        compact_verification_report=final_compact_report,
        failed_invariants=(final_report.failed_checks if final_report is not None else []),
        recovery_result=recovery_result,
        diagnostics=diagnostics,
        warnings=sorted(set(warnings)),
    )


def compress_context(*args: Any, **kwargs: Any) -> CPRGCResult:
    return compress_with_cprgc(*args, **kwargs)


__all__ = [
    "BM25_B",
    "BM25_K1",
    "COMPONENT_VERSION",
    "CPRGCExecutionError",
    "MODE_REDUCTIONS",
    "allocate_budget",
    "bm25_query_score",
    "compress_context",
    "compress_with_cprgc",
    "utility_score",
]
