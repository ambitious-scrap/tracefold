from __future__ import annotations

import ast
import hashlib
import importlib.util
from statistics import fmean
from typing import NamedTuple

import pytest
from pydantic import ValidationError

import tracefold.cprgc as cprgc
import tracefold.phase6_report as phase6_report
from tracefold.compact_verifier import verify_compact_context
from tracefold.context_ir import build_context_ir, stable_id
from tracefold.extractors import extract_obligations
from tracefold.graph import build_relation_graph, compute_protected_closure
from tracefold.phase6_fixtures import long_fixture_inputs
from tracefold.phase6_report import (
    COMPRESSIBLE_FIXTURES,
    FIXTURE_QUERIES,
    Phase6FixtureTokenizer,
    fixture_registry,
)
from tracefold.recovery import (
    build_recovery_history,
    recover_and_verify,
    verify_recovery_history,
)
from tracefold.schemas.common import FailedInvariant, FinalAction
from tracefold.schemas.phase2 import ContentType, ExtractionResult, SourceArtifact
from tracefold.schemas.phase4 import CertificateCandidate, VerificationReportStatus
from tracefold.schemas.phase5 import RecoveryRequest
from tracefold.schemas.phase6 import (
    AggregateNode,
    CPRGCMode,
    CPRGCResult,
    CPRGCStatus,
    FactNode,
    RelationNode,
)
from tracefold.serialization import canonical_json_bytes
from tracefold.sources import ingest_source
from tracefold.tokenizers import TiktokenTokenizer


class FixtureCase(NamedTuple):
    source: SourceArtifact
    extraction: ExtractionResult
    result: CPRGCResult


OPTIONAL_HEADERS = {
    "[INSTRUCTIONS]",
    "[FACTS]",
    "[RELATIONS]",
    "[STRUCTURE]",
    "[SELECTED EVIDENCE]",
    "[PYTHON]",
}


@pytest.fixture(scope="module")
def target_cases() -> dict[str, FixtureCase]:
    cases: dict[str, FixtureCase] = {}
    for name in COMPRESSIBLE_FIXTURES:
        source = ingest_source(long_fixture_inputs()[name])
        extraction = extract_obligations(source, ContentType(source.kind))
        result = cprgc.compress_with_cprgc(
            source,
            fixture_registry(),
            tokenizer_identity=Phase6FixtureTokenizer.identity,
            extraction=extraction,
        )
        cases[name] = FixtureCase(source, extraction, result)
    return cases


def test_empty_sections_are_elided_and_retained_output_stays_mapped(
    target_cases: dict[str, FixtureCase],
) -> None:
    expected = {
        "document": {"[FACTS]", "[RELATIONS]", "[STRUCTURE]", "[SELECTED EVIDENCE]"},
        "dialogue": {
            "[INSTRUCTIONS]",
            "[FACTS]",
            "[RELATIONS]",
            "[STRUCTURE]",
            "[SELECTED EVIDENCE]",
        },
        "json": {"[FACTS]", "[STRUCTURE]", "[SELECTED EVIDENCE]"},
        "logs": {"[FACTS]", "[RELATIONS]", "[STRUCTURE]", "[SELECTED EVIDENCE]"},
        "python": {"[FACTS]", "[RELATIONS]", "[STRUCTURE]", "[PYTHON]"},
    }
    for name, expected_headers in expected.items():
        result = target_cases[name].result
        assert OPTIONAL_HEADERS.intersection(result.context.splitlines()) == expected_headers
        assert result.verification_report is not None
        assert result.verification_report.status == VerificationReportStatus.VALID
        assert result.compact_verification_report is not None
        assert result.compact_verification_report.status == "valid"
        assert result.final_result is not None
        source_map = result.final_result.source_map
        assert source_map is not None
        assert source_map.coverage.lineage_coverage == "1.000000"

        compressed_artifact = next(
            artifact.artifact_id
            for artifact in source_map.artifacts
            if artifact.stage.value in {"raw_compressed", "repaired"}
        )
        mapped_span_ids = {
            span_id for mapping in source_map.mappings for span_id in mapping.to_span_ids
        }
        mapped_spans = [
            span
            for span in source_map.spans
            if span.artifact_id == compressed_artifact and span.span_id in mapped_span_ids
        ]
        offset = 0
        for line in result.context.splitlines(keepends=True):
            line_end = offset + len(line.rstrip("\n"))
            assert any(
                span.char_start <= offset and line_end <= span.char_end for span in mapped_spans
            )
            offset += len(line)

        for omitted_header in OPTIONAL_HEADERS - expected_headers:
            assert omitted_header not in result.context
            assert all(
                result.context[span.char_start : span.char_end] != omitted_header
                for span in mapped_spans
            )


def test_section_elision_remains_byte_deterministic(
    target_cases: dict[str, FixtureCase],
) -> None:
    case = target_cases["document"]
    second = cprgc.compress_with_cprgc(
        case.source,
        fixture_registry(),
        tokenizer_identity=Phase6FixtureTokenizer.identity,
        extraction=case.extraction,
    )
    assert second.context.encode("utf-8") == case.result.context.encode("utf-8")
    assert canonical_json_bytes(second.final_result) == canonical_json_bytes(
        case.result.final_result
    )


def test_phase6_fixtures_and_mode_thresholds_are_frozen() -> None:
    expected_hashes = {
        "dense": "769f6b2f38c3a395fff1bce42abf7b24b0d999b66c9fc0ec3157236e0604d289",
        "dialogue": "5f86b8fcc97a35acf58e55437aeca9b56ad9bc1b4bec92267dd2b8617d85645b",
        "document": "19848077124ae7b6f2a6772b64d4962d1c8633cdaab40e9bb3590ceda1993873",
        "json": "89f5e56dc162a31bd6d52854e0bcf42f056b9d8a57dbba907f02c2f1c29b342c",
        "logs": "0210a759f224905d87a1cf02109a7dc677f19490c674873ab9ea7f2ed791ca89",
        "python": "0b852b760a42f800094bf92896ce2823b48e2c85385bff7864f77c5b80ce6241",
    }
    assert {
        name: hashlib.sha256((fixture.text or "").encode("utf-8")).hexdigest()
        for name, fixture in long_fixture_inputs().items()
    } == expected_hashes
    assert cprgc.MODE_REDUCTION_BASIS_POINTS == {
        CPRGCMode.CONSERVATIVE: 5000,
        CPRGCMode.TARGET: 7000,
        CPRGCMode.AGGRESSIVE: 8000,
    }


@pytest.mark.skipif(importlib.util.find_spec("tiktoken") is None, reason="optional tiktoken")
def test_phase6_report_keeps_tokenizer_metrics_separate_and_recalculates_cl100k() -> None:
    fixture_record = phase6_report._fixture_record("python", CPRGCMode.TARGET)
    assert fixture_record["reduction_metric"] == "fixture_byte_reduction"

    tokenizer = TiktokenTokenizer("cl100k_base")
    configured_record = phase6_report._fixture_record(
        "python",
        CPRGCMode.TARGET,
        tokenizer=tokenizer,
        reduction_label="configured_tokenizer_reduction",
    )
    assert configured_record["reduction_metric"] == "configured_tokenizer_reduction"
    assert configured_record["tokenizer_identity"] == tokenizer.identity.model_dump(mode="json")
    assert configured_record["original_tokens"] == tokenizer.count(
        long_fixture_inputs()["python"].text or ""
    )
    final_tokens = configured_record["final_tokens"]
    if final_tokens is None:
        assert configured_record["final_reduction"] is None
    else:
        original_tokens = configured_record["original_tokens"]
        assert isinstance(final_tokens, int)
        assert isinstance(original_tokens, int)
        expected_reduction = 1 - final_tokens / original_tokens
        assert configured_record["final_reduction"] == f"{expected_reduction:.6f}"


def test_context_ir_ids_facts_and_rendering_are_deterministic(
    target_cases: dict[str, FixtureCase],
) -> None:
    case = target_cases["document"]
    tokenizer = Phase6FixtureTokenizer()
    first = build_context_ir(case.source, case.extraction, tokenizer)
    second = build_context_ir(case.source, case.extraction, tokenizer)
    assert canonical_json_bytes(first.model_dump(mode="json")) == canonical_json_bytes(
        second.model_dump(mode="json")
    )
    assert len({node.node_id for node in first.nodes}) == len(first.nodes)
    facts = [node for node in first.nodes if isinstance(node, FactNode)]
    assert facts
    assert all(node.exactness == "exact" and node.source_spans for node in facts)
    assert stable_id("node", {"value": 1}) == stable_id("node", {"value": 1})
    assert stable_id("node", {"value": 1}) != stable_id("node", {"value": 2})


def test_ir_models_reject_ambiguity_bad_endpoints_and_bad_aggregate_counts(
    target_cases: dict[str, FixtureCase],
) -> None:
    document = target_cases["document"].result.context_ir
    fact = next(node for node in document.nodes if isinstance(node, FactNode))
    with pytest.raises(ValidationError):
        FactNode.model_validate({**fact.model_dump(mode="json"), "ambiguity": "owner unknown"})

    relation = next(node for node in document.nodes if isinstance(node, RelationNode))
    with pytest.raises(ValidationError):
        RelationNode.model_validate(
            {**relation.model_dump(mode="json"), "endpoint_node_ids": ["only-one"]}
        )

    span = fact.source_spans[0]
    with pytest.raises(ValidationError):
        AggregateNode(
            node_id="aggregate:test",
            source_id=fact.source_id,
            aggregation_rule="exact-duplicate",
            exact_count=0,
            first_source_span=span,
            last_source_span=span,
            represented_source_ids=[fact.source_id],
            token_cost=1,
        )


@pytest.mark.parametrize("name", COMPRESSIBLE_FIXTURES)
def test_graph_edges_and_protected_relation_closure_are_stable(
    name: str, target_cases: dict[str, FixtureCase]
) -> None:
    case = target_cases[name]
    first = build_relation_graph(case.result.context_ir, case.extraction)
    second = build_relation_graph(case.result.context_ir, case.extraction)
    assert first == second
    assert len({edge.edge_id for edge in first.edges}) == len(first.edges)
    assert all(edge.explicit for edge in first.edges)
    closure = compute_protected_closure(
        case.result.context_ir,
        first,
        case.extraction,
        Phase6FixtureTokenizer(),
    )
    selected = set(closure.node_ids)
    for node in case.result.context_ir.nodes:
        if isinstance(node, RelationNode) and node.mandatory:
            assert node.node_id in selected
            assert set(node.endpoint_node_ids) <= selected


def test_query_scoring_recognizes_exact_tokens_and_binds_hash(
    target_cases: dict[str, FixtureCase],
) -> None:
    scores = cprgc.bm25_query_score(
        "REQ-8842 timeout 5000",
        ["ticket REQ-8842 timeout 5000 ms", "routine checklist"],
    )
    assert scores[0] > scores[1]
    match = cprgc._query_match(
        "records/53 latency_ms 9000 transfer",
        "records/53 latency_ms=9000 transfer owner_approval",
    )
    assert match[0] >= 1
    assert match[1] >= 1
    assert match[2] >= 1
    assert match[3] >= 4

    case = target_cases["document"]
    result = cprgc.compress_with_cprgc(
        case.source,
        fixture_registry(),
        tokenizer_identity=Phase6FixtureTokenizer.identity,
        query=FIXTURE_QUERIES["document"],
        extraction=case.extraction,
    )
    assert result.status == CPRGCStatus.VERIFIED_COMPRESSED
    assert result.raw_result.source_map is not None
    assert result.raw_result.source_map.query_hash == result.context_ir.query_hash
    assert "REQ-8842" in result.context
    assert "external transfer is prohibited" in result.context


def test_budget_modes_precedence_redistribution_and_incompressibility() -> None:
    conservative = cprgc.allocate_budget(1000, mode=CPRGCMode.CONSERVATIVE)
    target = cprgc.allocate_budget(1000, mode=CPRGCMode.TARGET)
    aggressive = cprgc.allocate_budget(1000, mode=CPRGCMode.AGGRESSIVE)
    explicit = cprgc.allocate_budget(
        1000,
        mode=CPRGCMode.AGGRESSIVE,
        target_token_budget=333,
        mandatory_token_cost=100,
        envelope_tokens=20,
        query_neighborhood_tokens=30,
        anomaly_tokens=40,
        structure_tokens=50,
    )
    impossible = cprgc.allocate_budget(
        1000,
        mode=CPRGCMode.TARGET,
        mandatory_token_cost=400,
        envelope_tokens=20,
    )
    assert conservative.requested_token_budget == 500
    assert target.requested_token_budget == 300
    assert aggressive.requested_token_budget == 200
    assert explicit.requested_token_budget == 333
    assert explicit.query_neighborhood_tokens == 30
    assert explicit.anomaly_tokens == 40
    assert explicit.structure_tokens == 50
    assert impossible.incompressible


def test_target_fixture_gate_and_content_compilers(
    target_cases: dict[str, FixtureCase],
) -> None:
    reductions: list[float] = []
    for name in COMPRESSIBLE_FIXTURES:
        case = target_cases[name]
        result = case.result
        assert result.status == CPRGCStatus.VERIFIED_COMPRESSED
        assert result.final_action == FinalAction.EMIT
        assert result.verification_report is not None
        assert result.verification_report.status == VerificationReportStatus.VALID
        assert result.verification_report.source_map_coverage is not None
        assert result.verification_report.source_map_coverage.value == "1.000000"
        assert result.diagnostics.final_reduction is not None
        reductions.append(float(result.diagnostics.final_reduction))

        source_map = result.raw_result.source_map
        assert source_map is not None
        compact = verify_compact_context(
            case.source,
            case.extraction,
            result.context_ir,
            result.context,
            source_map,
        )
        assert compact.status == "valid"

    assert fmean(reductions) >= 0.70
    assert sum(value >= 0.70 for value in reductions) >= 4
    assert min(reductions) >= 0.60

    assert "repeated_exact count=52" in target_cases["document"].result.context
    assert "REQ-8842" in target_cases["document"].result.context
    assert "role.boundary=system:" in target_cases["dialogue"].result.context
    assert "Active request:" in target_cases["dialogue"].result.context
    assert "path=/records rows=72" in target_cases["json"].result.context
    assert '"trace-json-053"' in target_cases["json"].result.context
    assert "count=120" in target_cases["logs"].result.context
    assert "first=2026-08-01T00:00:00" in target_cases["logs"].result.context
    assert "predecessor=E41" in target_cases["logs"].result.context
    # Protected code is carried verbatim, so the guard and exception path appear as
    # source rather than as a redundant compact-fact restatement.
    python_context = target_cases["python"].result.context
    assert "if attempts >= MAX_RETRIES:" in python_context
    assert "raise PermissionError('external transfer prohibited')" in python_context

    python_case = target_cases["python"]
    python_map = python_case.result.raw_result.source_map
    assert python_map is not None
    python_report = verify_compact_context(
        python_case.source,
        python_case.extraction,
        python_case.result.context_ir,
        python_case.result.context,
        python_map,
    )
    assert python_report.parseable is True


@pytest.mark.parametrize(
    ("fixture", "old", "new"),
    [
        ("document", "v2.7.4", "v2.7.5"),
        ("document", "5000", "6000"),
        ("document", "external transfer is prohibited", "external transfer is permitted"),
        ("document", "unless", "always"),
        ("json", "trace-json-053", "trace-json-999"),
        ("json", "9000", "9"),
        ("logs", "2026-08-01T00:01:59", "2026-08-01T00:01:58"),
        ("logs", "trace-rare", "trace-fake"),
        ("python", "MAX_RETRIES", "MAX_TRIES"),
    ],
)
def test_compact_fact_relation_and_source_map_tampering_is_detected(
    fixture: str,
    old: str,
    new: str,
    target_cases: dict[str, FixtureCase],
) -> None:
    case = target_cases[fixture]
    source_map = case.result.raw_result.source_map
    assert source_map is not None
    assert old in case.result.context
    tampered = case.result.context.replace(old, new, 1)
    report = verify_compact_context(
        case.source,
        case.extraction,
        case.result.context_ir,
        tampered,
        source_map,
    )
    assert report.status == "invalid"
    assert report.failed_checks


def test_compact_fact_copied_to_another_source_is_detected(
    target_cases: dict[str, FixtureCase],
) -> None:
    document = target_cases["document"]
    dialogue = target_cases["dialogue"]
    source_map = document.result.raw_result.source_map
    assert source_map is not None
    report = verify_compact_context(
        dialogue.source,
        document.extraction,
        document.result.context_ir,
        document.result.context,
        source_map,
    )
    assert report.status == "invalid"


def test_phase5_recovery_reverifies_cprgc_and_chains_attempts(
    target_cases: dict[str, FixtureCase],
) -> None:
    case = target_cases["document"]
    result = case.result
    assert isinstance(result.certificate, CertificateCandidate)
    assert result.verification_report is not None
    failure = FailedInvariant(
        invariant_id="inv:phase6:fallback",
        class_name="source_map",
        kind="source_map",
        severity="hard",
        code="STALE_SOURCE_MAP",
        message="controlled Phase 6 recovery trigger",
        source_span_ids=[],
        candidate_span_ids=[],
        recovery_hint=FinalAction.FULL_FALLBACK.value,
    )
    invalid_report = result.verification_report.model_copy(
        update={
            "status": VerificationReportStatus.INVALID,
            "failed_checks": [failure],
            "recommended_action": FinalAction.FULL_FALLBACK,
        }
    )
    tokenizer = Phase6FixtureTokenizer()
    request = cprgc._request(
        case.source,
        tokenizer,
        CPRGCMode.TARGET,
        None,
        cprgc.DEFAULT_RUN_ID,
        None,
    )
    recovery = recover_and_verify(
        RecoveryRequest(
            source=case.source,
            request=request,
            extraction=case.extraction,
            raw_result=result.raw_result,
            certificate=result.certificate,
            verification_report=invalid_report,
            maximum_attempts=3,
            maximum_final_token_budget=result.raw_result.original_token_count,
        ),
        fixture_registry(),
    )
    assert recovery.final_status == "valid"
    assert recovery.final_action == FinalAction.FULL_FALLBACK
    assert recovery.final_reduction == "0.000000"
    assert recovery.final_verification_report is not None
    assert recovery.final_verification_report.status == VerificationReportStatus.VALID
    assert recovery.attempts
    history = build_recovery_history(recovery.attempts)
    assert history.history_hash == recovery.recovery_history_hash
    assert verify_recovery_history(history)


def test_dense_input_and_fallback_schema_never_claim_false_savings(
    target_cases: dict[str, FixtureCase],
) -> None:
    dense = ingest_source(long_fixture_inputs()["dense"])
    result = cprgc.compress_with_cprgc(
        dense,
        fixture_registry(),
        tokenizer_identity=Phase6FixtureTokenizer.identity,
        mode=CPRGCMode.AGGRESSIVE,
    )
    assert result.status == CPRGCStatus.INCOMPRESSIBLE
    assert result.final_action == FinalAction.EXPAND_BUDGET
    assert result.diagnostics.final_reduction is None

    document = target_cases["document"].result.model_dump(mode="json")
    diagnostics = dict(document["diagnostics"])
    diagnostics["final_reduction"] = "0.100000"
    with pytest.raises(ValidationError):
        CPRGCResult.model_validate(
            {
                **document,
                "status": CPRGCStatus.VERIFIED_FALLBACK.value,
                "final_action": FinalAction.FULL_FALLBACK.value,
                "diagnostics": diagnostics,
            }
        )


@pytest.mark.parametrize("name", COMPRESSIBLE_FIXTURES)
def test_cprgc_outputs_are_byte_deterministic(
    name: str, target_cases: dict[str, FixtureCase]
) -> None:
    first = target_cases[name]
    second = cprgc.compress_with_cprgc(
        first.source,
        fixture_registry(),
        tokenizer_identity=Phase6FixtureTokenizer.identity,
        extraction=first.extraction,
    )
    assert canonical_json_bytes(first.result.model_dump(mode="json")) == canonical_json_bytes(
        second.model_dump(mode="json")
    )


def test_python_source_fixture_remains_parseable() -> None:
    source = long_fixture_inputs()["python"].text
    assert source is not None
    ast.parse(source)
