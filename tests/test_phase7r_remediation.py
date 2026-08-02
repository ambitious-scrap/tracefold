from __future__ import annotations

import ast
import importlib.util
from typing import Any

import pytest

import tracefold.cprgc as cprgc
from tracefold.compact_verifier import (
    verifier_obligation_is_mandatory,
)
from tracefold.compact_verifier import (
    verify_compact_context as independently_verify_compact,
)
from tracefold.context_ir import compressor_obligation_is_mandatory
from tracefold.extractors import extract_obligations
from tracefold.phase6_fixtures import long_fixture_inputs
from tracefold.phase6_report import Phase6FixtureTokenizer, fixture_registry
from tracefold.recovery import recover_and_verify as run_recovery
from tracefold.schemas.common import DiscoveryStatus, FailedInvariant
from tracefold.schemas.phase2 import (
    OBLIGATION_CLASSES,
    ContentType,
    ExtractionConfidence,
    Obligation,
)
from tracefold.schemas.phase6 import (
    CertificateDiagnosticStatus,
    CompactVerificationReport,
    CPRGCMode,
    CPRGCStatus,
)
from tracefold.schemas.source import SourceInput
from tracefold.serialization import canonical_json_bytes
from tracefold.sources import ingest_source
from tracefold.tokenizers import (
    FixtureByteTokenizer,
    TiktokenTokenizer,
    TokenizerIdentity,
    TokenizerRegistry,
    UnknownTokenizerError,
)


class OtherTokenizer(FixtureByteTokenizer):
    identity = TokenizerIdentity(
        implementation="test",
        identifier="other",
        revision="1",
        configuration_hash="sha256:" + "b" * 64,
    )


def _source(text: str, kind: str) -> Any:
    return ingest_source(
        SourceInput(
            input_ordinal=0,
            kind=kind,
            authority="phase7r-test",
            media_type="text/plain",
            text=text,
        )
    )


def test_registry_order_never_changes_explicit_selection() -> None:
    requested = FixtureByteTokenizer()
    first = TokenizerRegistry()
    first.register(requested)
    first.register(OtherTokenizer())
    second = TokenizerRegistry()
    second.register(OtherTokenizer())
    second.register(requested)
    assert first.resolve(requested.identity).identity == second.resolve(requested.identity).identity
    assert first.identities() == second.identities()
    with pytest.raises(UnknownTokenizerError):
        first.resolve(OtherTokenizer.identity.model_copy(update={"revision": "2"}))


def test_cprgc_requires_explicit_tokenizer() -> None:
    source = _source("same.same.", "document")
    with pytest.raises(cprgc.CPRGCExecutionError, match="exactly one"):
        cprgc.compress_with_cprgc(source, fixture_registry())


@pytest.mark.skipif(importlib.util.find_spec("tiktoken") is None, reason="optional tokenizer")
def test_tiktoken_identity_names_explicit_encoding() -> None:
    tokenizer = TiktokenTokenizer("cl100k_base")
    assert tokenizer.identity.implementation == "tiktoken"
    assert tokenizer.identity.identifier == "cl100k_base"
    assert tokenizer.count("TraceFold") > 0


@pytest.mark.parametrize(
    ("original", "expected"), [(1, 1), (3, 1), (10, 2), (999, 199), (1000, 200)]
)
def test_integer_aggressive_budget_boundaries(original: int, expected: int) -> None:
    allocation = cprgc.allocate_budget(original, mode=CPRGCMode.AGGRESSIVE)
    assert allocation.requested_token_budget == expected


def test_exact_duplicate_grouping_is_case_and_whitespace_sensitive() -> None:
    tokenizer = Phase6FixtureTokenizer()
    exact_source = _source("Alpha.Alpha.", "document")
    exact = cprgc._document_candidates(
        exact_source,
        extract_obligations(exact_source, ContentType.DOCUMENT),
        tokenizer,
        None,
    )
    assert any(item.compiler_rule == "exact-duplicate-group" for item in exact)
    changed_source = _source("Alpha.alpha.", "document")
    changed = cprgc._document_candidates(
        changed_source,
        extract_obligations(changed_source, ContentType.DOCUMENT),
        tokenizer,
        None,
    )
    assert not any(item.compiler_rule == "exact-duplicate-group" for item in changed)


def test_json_paths_escape_keys_and_groups_disjoint_indexes() -> None:
    text = (
        '{"users":[{"x":1},{"x":2},{"x":1}],'
        '"nested":{"events":[{"id":"a"},{"id":"b"}]},'
        '"a/b":[{"v":null},{"z":null}]}'
    )
    source = _source(text, "json")
    extraction = extract_obligations(source, ContentType.JSON)
    candidates = cprgc._json_candidates(source, extraction, Phase6FixtureTokenizer(), None)
    rendered = "\n".join(item.emitted_text for item in candidates)
    assert "path=/users" in rendered
    assert "path=/nested/events" in rendered
    assert "path=/a~1b" in rendered
    assert "rows=0,2 count=2" in rendered
    assert "rows=0-2 count=2" not in rendered
    assert any("~" in item.emitted_text for item in candidates if item.candidate_kind == "json_row")


def test_decorated_multiline_async_python_skeleton_is_parseable_and_synthesized() -> None:
    text = """@audit("π")
async def public_api(
    value: str,
) -> str:
    pass  # λ
"""
    source = _source(text, "python")
    candidates = cprgc._python_candidates(
        source,
        extract_obligations(source, ContentType.PYTHON),
        Phase6FixtureTokenizer(),
        None,
    )
    skeleton = next(item for item in candidates if item.candidate_kind == "python_skeleton")
    ast.parse(skeleton.emitted_text)
    assert skeleton.emitted_text.startswith('@audit("π")\nasync def public_api(')
    assert skeleton.metadata["synthesized"] is True


def _obligation(class_name: str, **metadata: Any) -> Obligation:
    return Obligation(
        obligation_id=f"obl:{class_name}:{len(metadata)}",
        class_name=class_name,
        value="x",
        lexeme="x",
        source_id="source",
        source_span_ids=["span"],
        extraction_method="phase7r-test",
        confidence=ExtractionConfidence.EXACT,
        discovery_status=DiscoveryStatus.KNOWN,
        metadata=metadata,
    )


def test_mandatory_policy_matches_across_trust_domains() -> None:
    cases = [_obligation(class_name) for class_name in OBLIGATION_CLASSES]
    cases.extend(
        [
            _obligation("code.definition", kind="module"),
            _obligation("code.definition", kind="function"),
            _obligation("temporal.timestamp", event_id="e1"),
            _obligation("identifier.generic", event_id="e1", field="error_code"),
            _obligation("identifier.generic", event_id="e1", field="message"),
            _obligation("log.severity_change", **{"from": "INFO", "to": "WARN"}),
        ]
    )
    assert [compressor_obligation_is_mandatory(item) for item in cases] == [
        verifier_obligation_is_mandatory(item) for item in cases
    ]


def test_compact_failure_enters_recovery_and_blocks_emit(monkeypatch: pytest.MonkeyPatch) -> None:
    source = ingest_source(long_fixture_inputs()["document"])
    real_compact = independently_verify_compact
    real_recovery = run_recovery
    observed: dict[str, Any] = {}
    calls = 0

    def fail_once(*args: Any, **kwargs: Any) -> CompactVerificationReport:
        nonlocal calls
        calls += 1
        report = real_compact(*args, **kwargs)
        if calls != 1:
            return report
        extraction = args[1]
        span_id = extraction.spans[0].span_id
        failure = FailedInvariant(
            invariant_id="compact:test-failure",
            class_name="compact.semantic_integrity",
            kind="obligation",
            severity="hard",
            code="FACT_PRIMARY_EVIDENCE_MISMATCH",
            message="injected compact failure",
            source_span_ids=[span_id],
            candidate_span_ids=[],
            recovery_hint="restore exact evidence",
            source_id=source.source_id,
            expected_condition="primary evidence",
            observed_condition="tampered fact",
            verifier_rule_version="test/1",
        )
        return report.model_copy(
            update={
                "status": "invalid",
                "failed_checks": [failure.code],
                "failed_invariants": [failure],
            }
        )

    def capture_recovery(request: Any, registry: Any) -> Any:
        observed["codes"] = [item.code for item in request.verification_report.failed_checks]
        return real_recovery(request, registry)

    monkeypatch.setattr(cprgc, "verify_compact_context", fail_once)
    monkeypatch.setattr(cprgc, "recover_and_verify", capture_recovery)
    result = cprgc.compress_with_cprgc(
        source,
        fixture_registry(),
        tokenizer_identity=Phase6FixtureTokenizer.identity,
    )
    assert "FACT_PRIMARY_EVIDENCE_MISMATCH" in observed["codes"]
    assert result.final_action.value != "emit"
    assert result.status in {
        CPRGCStatus.VERIFIED_REPAIRED,
        CPRGCStatus.VERIFIED_FALLBACK,
        CPRGCStatus.FAILED,
    }
    assert calls >= 2


def test_query_driven_recovery_is_verified_against_its_own_binding() -> None:
    # Recovery recompiles through the query-independent Phase 3 compressor, so its artifact
    # and source map carry the empty-query binding. Re-verifying that artifact against the
    # request query would report a query mismatch that no compressor could ever repair.
    base_logs = long_fixture_inputs()["logs"].text
    assert base_logs is not None
    causal_logs = base_logs + (
        "2026-08-01T09:30:00 INFO service=auth event_id=E41 status=ok "
        "trace_id=trace-cause request_id=REQ-91\n"
        "2026-08-01T09:30:05 ERROR service=auth event_id=E42 caused_by=E41 status=failed "
        "trace_id=trace-cause request_id=REQ-92\n"
    )
    source = _source(causal_logs, "log")
    result = cprgc.compress_with_cprgc(
        source,
        fixture_registry(),
        tokenizer_identity=Phase6FixtureTokenizer.identity,
        query="which event caused E42",
    )
    assert result.recovery_result is not None
    assert result.final_result is not None
    assert result.final_result.component_version != cprgc.COMPONENT_VERSION
    final_report = result.compact_verification_report
    assert final_report is not None
    assert "QUERY_HASH_MISMATCH" not in final_report.failed_checks
    assert "IR_BINDING_MISMATCH" not in final_report.failed_checks
    assert "QUERY_HASH_MISMATCH" not in result.warnings


def test_diagnostic_status_rejects_false_validity() -> None:
    source = ingest_source(long_fixture_inputs()["dense"])
    result = cprgc.compress_with_cprgc(
        source,
        fixture_registry(),
        tokenizer_identity=Phase6FixtureTokenizer.identity,
        mode=CPRGCMode.AGGRESSIVE,
    )
    assert result.diagnostics.certificate_status == CertificateDiagnosticStatus.UNAVAILABLE
    assert canonical_json_bytes(result.model_dump(mode="json"))
