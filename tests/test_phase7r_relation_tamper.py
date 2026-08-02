"""Phase 7R: combined tamper coverage for every frozen relation class.

Each case compiles a real artifact with CPRGC, checks that the independent compact
verifier reconstructs the relation from primary evidence, and then attacks the same
artifact from both sides of the trust boundary: the emitted compact text and the
primary extraction the verifier reconstructs from.
"""

from __future__ import annotations

import json
from typing import NamedTuple

import pytest

import tracefold.cprgc as cprgc
from tracefold.compact_verifier import verify_compact_context
from tracefold.extractors import extract_obligations
from tracefold.phase6_fixtures import long_fixture_inputs
from tracefold.phase6_report import Phase6FixtureTokenizer, fixture_registry
from tracefold.schemas.phase2 import ContentType, ExtractionResult, SourceArtifact
from tracefold.schemas.phase6 import (
    CompactVerificationReport,
    ContextIR,
    CPRGCMode,
    RelationNode,
)
from tracefold.schemas.source import SourceInput
from tracefold.schemas.source_map import SourceMap
from tracefold.sources import ingest_source

RELATION_CLASSES = (
    "relation.value_unit_owner",
    "relation.rule_exception",
    "relation.condition_consequence",
    "relation.statement_correction",
    "relation.instruction_scope",
    "relation.definition_use",
    "relation.caller_callee",
    "relation.import_symbol",
    "relation.event_timestamp",
    "relation.event_trace",
    "relation.error_causal_predecessor",
)


def _padded_document() -> str:
    filler = "".join(
        f"Section {index:03d}: routine operational notice with no recorded obligation.\n"
        for index in range(120)
    )
    return "If the queue depth exceeds 100, the gateway must shed load.\n" + filler


def _event_json() -> str:
    rows: list[dict[str, object]] = [
        {
            "service": "gateway-api",
            "status": "ok",
            "latency_ms": 42,
            "timestamp": "2026-08-01T00:00:00",
            "trace_id": None,
        }
        for _ in range(72)
    ]
    rows[53] = {
        "service": "gateway-api",
        "status": "error",
        "latency_ms": 9000,
        "timestamp": "2026-08-01T09:00:53",
        "trace_id": "trace-json-053",
    }
    return json.dumps({"records": rows, "total": len(rows)}, separators=(",", ":"))


def _causal_logs() -> str:
    filler = "\n".join(
        f"2026-08-01T00:{index // 60:02d}:{index % 60:02d} INFO service=auth health-check status=ok"
        for index in range(120)
    )
    pair = (
        "2026-08-01T09:00:00 WARN service=auth event_id=E41 status=degraded "
        "trace_id=trace-rare request_id=REQ-77\n"
        "2026-08-01T09:00:01 ERROR service=auth event_id=E42 caused_by=E41 status=failed "
        "trace_id=trace-rare request_id=REQ-77\n"
    )
    return filler + "\n" + pair


class FixtureSpec(NamedTuple):
    source: SourceInput
    query: str | None
    mode: CPRGCMode
    # Redundant compact lines are suppressed when the same evidence is emitted verbatim.
    # Log causal evidence is always carried verbatim, so the compact relation line only
    # exists with that one optimisation disabled; everything else stays production code.
    keep_redundant_lines: bool = False


FIXTURE_SPECS: dict[str, FixtureSpec] = {
    "document": FixtureSpec(long_fixture_inputs()["document"], None, CPRGCMode.TARGET),
    "condition": FixtureSpec(
        SourceInput(
            input_ordinal=0,
            kind="document",
            authority="phase7r-fixture",
            media_type="text/plain",
            text=_padded_document(),
        ),
        None,
        CPRGCMode.CONSERVATIVE,
    ),
    "dialogue": FixtureSpec(
        long_fixture_inputs()["dialogue"],
        "system instruction change-control correction gateway-api worker-api timeout owner",
        CPRGCMode.TARGET,
    ),
    "python": FixtureSpec(long_fixture_inputs()["python"], None, CPRGCMode.TARGET),
    "logs": FixtureSpec(long_fixture_inputs()["logs"], None, CPRGCMode.TARGET),
    "json_events": FixtureSpec(
        SourceInput(
            input_ordinal=0,
            kind="json",
            authority="phase7r-fixture",
            media_type="application/json",
            text=_event_json(),
        ),
        "trace-json-053 anomaly timestamp latency_ms",
        CPRGCMode.TARGET,
    ),
    "logs_causal": FixtureSpec(
        SourceInput(
            input_ordinal=0,
            kind="log",
            authority="phase7r-fixture",
            media_type="text/plain",
            text=_causal_logs(),
        ),
        "which event caused E42",
        CPRGCMode.TARGET,
        keep_redundant_lines=True,
    ),
}

FIXTURE_BY_CLASS = {
    "relation.value_unit_owner": "document",
    "relation.rule_exception": "document",
    "relation.condition_consequence": "condition",
    "relation.statement_correction": "dialogue",
    "relation.instruction_scope": "dialogue",
    "relation.definition_use": "python",
    "relation.caller_callee": "python",
    "relation.import_symbol": "python",
    "relation.event_timestamp": "json_events",
    "relation.event_trace": "logs",
    "relation.error_causal_predecessor": "logs_causal",
}


class CompiledCase(NamedTuple):
    source: SourceArtifact
    extraction: ExtractionResult
    context_ir: ContextIR
    compact_text: str
    source_map: SourceMap
    query: str | None
    relations: dict[str, RelationNode]


def _compile(spec: FixtureSpec) -> CompiledCase:
    source = ingest_source(spec.source)
    extraction = extract_obligations(source, ContentType(source.kind))
    original = cprgc._covered_verbatim
    if spec.keep_redundant_lines:
        cprgc._covered_verbatim = lambda node, ranges: False
    try:
        result = cprgc.compress_with_cprgc(
            source,
            fixture_registry(),
            tokenizer_identity=Phase6FixtureTokenizer.identity,
            extraction=extraction,
            mode=spec.mode,
            query=spec.query,
        )
    finally:
        cprgc._covered_verbatim = original
    source_map = result.raw_result.source_map
    assert source_map is not None
    mapped = {
        relation_id
        for mapping in source_map.mappings
        if mapping.reason_code == "compact-exact-relation"
        for relation_id in mapping.relation_ids
    }
    relations: dict[str, RelationNode] = {}
    for node in sorted(result.context_ir.nodes, key=lambda item: item.node_id):
        if not isinstance(node, RelationNode) or node.relation_id not in mapped:
            continue
        left, right = _endpoints(node.compact_rendering)[1:]
        if left == right or node.relation_type in relations:
            continue
        relations[node.relation_type] = node
    return CompiledCase(
        source, extraction, result.context_ir, result.context, source_map, spec.query, relations
    )


@pytest.fixture(scope="module")
def compiled_cases() -> dict[str, CompiledCase]:
    return {name: _compile(spec) for name, spec in FIXTURE_SPECS.items()}


@pytest.fixture(scope="module")
def relation_cases(
    compiled_cases: dict[str, CompiledCase],
) -> dict[str, tuple[CompiledCase, RelationNode]]:
    cases: dict[str, tuple[CompiledCase, RelationNode]] = {}
    for relation_type, fixture_name in FIXTURE_BY_CLASS.items():
        case = compiled_cases[fixture_name]
        node = case.relations.get(relation_type)
        assert node is not None, f"{relation_type} is not rendered by fixture {fixture_name}"
        cases[relation_type] = (case, node)
    return cases


def _endpoints(rendering: str) -> tuple[str, str, str]:
    """Split a frozen relation rendering into its prefix and two endpoint texts."""

    if rendering.startswith("if "):
        left, _, right = rendering[3:].partition(" then ")
        return "if ", left, right
    label, _, rest = rendering.partition(": ")
    left, _, right = rest.partition(" -> ")
    return f"{label}: ", left, right


def _compose(prefix: str, left: str, right: str) -> str:
    if prefix == "if ":
        return f"if {left} then {right}"
    return f"{prefix}{left} -> {right}"


def _verify(
    case: CompiledCase, *, compact_text: str, extraction: ExtractionResult
) -> CompactVerificationReport:
    return verify_compact_context(
        case.source,
        extraction,
        case.context_ir,
        compact_text,
        case.source_map,
        query=case.query,
    )


def _replace_line(compact_text: str, rendering: str, replacement: str) -> str:
    line = f"- {rendering}"
    assert line in compact_text
    return compact_text.replace(line, f"- {replacement}", 1)


def _relations_without(extraction: ExtractionResult, relation_id: str) -> ExtractionResult:
    kept = [item for item in extraction.relations if item.relation_id != relation_id]
    return extraction.model_copy(update={"relations": kept})


def _replace_relation(
    extraction: ExtractionResult, relation_id: str, **changes: object
) -> ExtractionResult:
    updated = [
        item.model_copy(update=changes) if item.relation_id == relation_id else item
        for item in extraction.relations
    ]
    return extraction.model_copy(update={"relations": updated})


def _substitute_endpoint(text: str) -> str:
    """Alter one endpoint character in place, keeping every offset in the artifact stable."""

    index = max(position for position, character in enumerate(text) if character.isalnum())
    character = text[index]
    if character.isdigit():
        replacement = "0" if character != "0" else "1"
    elif character.islower():
        replacement = "a" if character != "a" else "b"
    else:
        replacement = "A" if character != "A" else "B"
    return f"{text[:index]}{replacement}{text[index + 1 :]}"


@pytest.mark.parametrize("relation_type", RELATION_CLASSES)
def test_every_frozen_relation_class_is_reconstructed_from_primary_evidence(
    relation_type: str,
    relation_cases: dict[str, tuple[CompiledCase, RelationNode]],
) -> None:
    case, node = relation_cases[relation_type]
    assert f"- {node.compact_rendering}" in case.compact_text
    report = _verify(case, compact_text=case.compact_text, extraction=case.extraction)
    assert report.status == "valid"
    assert report.failed_checks == []
    assert report.verified_relation_count >= 1


@pytest.mark.parametrize("relation_type", RELATION_CLASSES)
def test_reversed_endpoints_in_compact_output_are_rejected(
    relation_type: str,
    relation_cases: dict[str, tuple[CompiledCase, RelationNode]],
) -> None:
    case, node = relation_cases[relation_type]
    prefix, left, right = _endpoints(node.compact_rendering)
    reversed_rendering = _compose(prefix, right, left)
    assert reversed_rendering != node.compact_rendering
    # A direction attack keeps every byte of the line, so only the claim changes.
    assert len(reversed_rendering) == len(node.compact_rendering)
    tampered = _replace_line(case.compact_text, node.compact_rendering, reversed_rendering)
    report = _verify(case, compact_text=tampered, extraction=case.extraction)
    assert report.status == "invalid"
    assert "RELATION_RENDERING_SEMANTICS_MISMATCH" in report.failed_checks


@pytest.mark.parametrize("relation_type", RELATION_CLASSES)
def test_substituted_endpoint_in_compact_output_is_rejected(
    relation_type: str,
    relation_cases: dict[str, tuple[CompiledCase, RelationNode]],
) -> None:
    case, node = relation_cases[relation_type]
    prefix, left, right = _endpoints(node.compact_rendering)
    tampered_rendering = _compose(prefix, left, _substitute_endpoint(right))
    assert tampered_rendering != node.compact_rendering
    assert len(tampered_rendering) == len(node.compact_rendering)
    tampered = _replace_line(case.compact_text, node.compact_rendering, tampered_rendering)
    report = _verify(case, compact_text=tampered, extraction=case.extraction)
    assert report.status == "invalid"
    assert "RELATION_RENDERING_SEMANTICS_MISMATCH" in report.failed_checks


@pytest.mark.parametrize("relation_type", RELATION_CLASSES)
def test_relabelled_relation_class_in_compact_output_is_rejected(
    relation_type: str,
    relation_cases: dict[str, tuple[CompiledCase, RelationNode]],
) -> None:
    case, node = relation_cases[relation_type]
    prefix, left, right = _endpoints(node.compact_rendering)
    relabelled = (
        f"caller: {left} -> {right}" if prefix != "caller: " else f"import: {left} -> {right}"
    )
    assert relabelled != node.compact_rendering
    tampered = _replace_line(case.compact_text, node.compact_rendering, relabelled)
    report = _verify(case, compact_text=tampered, extraction=case.extraction)
    assert report.status == "invalid"
    assert "RELATION_RENDERING_SEMANTICS_MISMATCH" in report.failed_checks


@pytest.mark.parametrize("relation_type", RELATION_CLASSES)
def test_reversed_primary_relation_direction_is_rejected(
    relation_type: str,
    relation_cases: dict[str, tuple[CompiledCase, RelationNode]],
) -> None:
    case, node = relation_cases[relation_type]
    relation = next(
        item for item in case.extraction.relations if item.relation_id == node.relation_id
    )
    extraction = _replace_relation(
        case.extraction,
        node.relation_id,
        obligation_ids=list(reversed(relation.obligation_ids)),
    )
    report = _verify(case, compact_text=case.compact_text, extraction=extraction)
    assert report.status == "invalid"
    assert {
        "RELATION_ENDPOINT_DIRECTION_MISMATCH",
        "RELATION_RENDERING_SEMANTICS_MISMATCH",
    } & set(report.failed_checks)


@pytest.mark.parametrize("relation_type", RELATION_CLASSES)
def test_relation_absent_from_primary_extraction_is_rejected(
    relation_type: str,
    relation_cases: dict[str, tuple[CompiledCase, RelationNode]],
) -> None:
    case, node = relation_cases[relation_type]
    extraction = _relations_without(case.extraction, node.relation_id)
    report = _verify(case, compact_text=case.compact_text, extraction=extraction)
    assert report.status == "invalid"
    assert "RELATION_NOT_IN_PRIMARY_EXTRACTION" in report.failed_checks


@pytest.mark.parametrize("relation_type", RELATION_CLASSES)
def test_internally_consistent_fabricated_relation_class_is_rejected(
    relation_type: str,
    relation_cases: dict[str, tuple[CompiledCase, RelationNode]],
) -> None:
    # Real endpoints, real evidence spans, real source: only the claimed class is invented.
    fabricated_type = next(item for item in RELATION_CLASSES if item != relation_type)
    case, node = relation_cases[relation_type]
    extraction = _replace_relation(case.extraction, node.relation_id, relation_type=fabricated_type)
    report = _verify(case, compact_text=case.compact_text, extraction=extraction)
    assert report.status == "invalid"
    assert "RELATION_PRIMARY_EVIDENCE_MISMATCH" in report.failed_checks


@pytest.mark.parametrize("relation_type", RELATION_CLASSES)
def test_relation_evidence_moved_to_another_span_is_rejected(
    relation_type: str,
    relation_cases: dict[str, tuple[CompiledCase, RelationNode]],
) -> None:
    case, node = relation_cases[relation_type]
    foreign = next(
        span.span_id
        for span in case.extraction.spans
        if span.span_id not in {item.span_id for item in node.evidence_spans}
    )
    extraction = _replace_relation(case.extraction, node.relation_id, evidence_span_ids=[foreign])
    report = _verify(case, compact_text=case.compact_text, extraction=extraction)
    assert report.status == "invalid"
    assert "RELATION_PRIMARY_EVIDENCE_MISMATCH" in report.failed_checks
