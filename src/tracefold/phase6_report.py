"""Deterministic structural compression report for Phase 6 fixtures."""

from __future__ import annotations

import hashlib
import json
import os
from statistics import fmean

from tracefold.cprgc import compress_with_cprgc
from tracefold.phase6_fixtures import long_fixture_inputs
from tracefold.schemas.phase6 import CPRGCMode, CPRGCResult, RelationNode
from tracefold.serialization import canonical_json_bytes
from tracefold.sources import ingest_source
from tracefold.tokenizers import (
    FixtureByteTokenizer,
    Tokenizer,
    TokenizerRegistry,
    resolve_tokenizer,
)

COMPRESSIBLE_FIXTURES = ("document", "dialogue", "json", "logs", "python")
FIXTURE_QUERIES = {
    "document": "ticket=REQ-8842 signed maintenance package",
    "dialogue": "why does ticket=REQ-8842 permit the signed maintenance package",
    "json": "trace-json-053 anomaly latency_ms",
    "logs": "trace-rare request_id=REQ-77 error_code=E43",
    "python": "transfer owner_approval MAX_RETRIES circuit breaker",
}


class Phase6FixtureTokenizer(FixtureByteTokenizer):
    """Byte tokenizer frozen for local structural gates, never production use."""


def fixture_registry() -> TokenizerRegistry:
    registry = TokenizerRegistry()
    registry.register(Phase6FixtureTokenizer())
    return registry


def _coverage(result: CPRGCResult) -> tuple[str | None, str | None]:
    raw = result.final_result or result.raw_result
    report = result.verification_report
    if report is None:
        return None, None
    mandatory = sum(item.mandatory for item in raw.obligation_coverage.values())
    verified_mandatory = sum(
        min(item.mandatory, report.obligation_results[class_name].verified)
        for class_name, item in raw.obligation_coverage.items()
        if class_name in report.obligation_results
    )
    relation_discovered = sum(item.discovered for item in report.relation_results)
    relation_verified = sum(item.verified for item in report.relation_results)
    hard = 1.0 if mandatory == 0 else verified_mandatory / mandatory
    relations = None if relation_discovered == 0 else relation_verified / relation_discovered
    return f"{hard:.6f}", None if relations is None else f"{relations:.6f}"


def _fixture_record(
    name: str,
    mode: CPRGCMode,
    *,
    tokenizer: Tokenizer | None = None,
    reduction_label: str = "fixture_byte_reduction",
) -> dict[str, object]:
    source = ingest_source(long_fixture_inputs()[name])
    selected_tokenizer = tokenizer or Phase6FixtureTokenizer()
    registry = TokenizerRegistry()
    registry.register(selected_tokenizer)
    result = compress_with_cprgc(
        source,
        registry,
        tokenizer_identity=selected_tokenizer.identity,
        mode=mode,
    )
    diagnostics = result.diagnostics
    hard_coverage, relation_coverage = _coverage(result)
    report = result.verification_report
    recovery = result.recovery_result
    relation_discovered = (
        sum(item.discovered for item in report.relation_results) if report is not None else 0
    )
    relation_verified = (
        sum(item.verified for item in report.relation_results) if report is not None else 0
    )
    relation_classes = (
        len({item.class_name for item in report.relation_results if item.discovered})
        if report is not None
        else 0
    )
    relation_nodes = [item for item in result.context_ir.nodes if isinstance(item, RelationNode)]
    source_map_value = (
        report.source_map_coverage.value
        if report is not None and report.source_map_coverage is not None
        else None
    )
    return {
        "fixture": name,
        "source_kind": source.kind,
        "mode": mode.value,
        "tokenizer_identity": selected_tokenizer.identity.model_dump(mode="json"),
        "reduction_metric": reduction_label,
        "query_conditioned": False,
        "status": result.status.value,
        "original_tokens": diagnostics.original_tokens,
        "raw_compressed_tokens": diagnostics.raw_compressed_tokens,
        "final_tokens": diagnostics.final_tokens,
        "requested_reduction": diagnostics.requested_reduction,
        "raw_reduction": diagnostics.raw_reduction,
        "final_reduction": diagnostics.final_reduction,
        "mandatory_closure_tokens": diagnostics.mandatory_closure_tokens,
        "compact_fact_tokens": diagnostics.compact_fact_tokens,
        "relation_tokens": diagnostics.relation_tokens,
        "structure_tokens": diagnostics.structure_tokens,
        "optional_evidence_tokens": diagnostics.optional_evidence_tokens,
        "envelope_tokens": diagnostics.envelope_tokens,
        "omitted_tokens": diagnostics.omitted_tokens,
        "certificate_status": diagnostics.certificate_status,
        "raw_verification_status": (
            "valid" if result.status.value == "verified_compressed" else "not_valid"
        ),
        "final_verification_status": report.status.value if report is not None else "not_run",
        "hard_obligation_coverage": hard_coverage,
        "required_relation_coverage": relation_coverage,
        "required_relation_coverage_status": (
            "not_applicable" if relation_discovered == 0 else "applicable"
        ),
        "discovered_relation_count": relation_discovered,
        "verified_relation_count": relation_verified,
        "relation_class_diversity": relation_classes,
        "exact_relation_count": sum(item.exactness.value == "exact" for item in relation_nodes),
        "inferred_relation_count": sum(
            item.exactness.value == "inferred" for item in relation_nodes
        ),
        "source_map_coverage": source_map_value,
        "recovery_action": result.final_action.value,
        "recovery_attempts": len(recovery.attempts) if recovery is not None else 0,
        "restored_tokens": diagnostics.restored_tokens,
        "raw_verification_failures": result.warnings,
    }


def _dense_record() -> dict[str, object]:
    source = ingest_source(long_fixture_inputs()["dense"])
    result = compress_with_cprgc(
        source,
        fixture_registry(),
        tokenizer_identity=Phase6FixtureTokenizer.identity,
        mode=CPRGCMode.AGGRESSIVE,
    )
    return {
        "fixture": "dense",
        "source_kind": source.kind,
        "mode": CPRGCMode.AGGRESSIVE.value,
        "status": result.status.value,
        "action": result.final_action.value,
        "original_tokens": result.diagnostics.original_tokens,
        "raw_compressed_tokens": result.diagnostics.raw_compressed_tokens,
        "final_tokens": result.diagnostics.final_tokens,
        "final_reduction": result.diagnostics.final_reduction,
        "verification_status": (
            result.verification_report.status.value
            if result.verification_report is not None
            else "not_run"
        ),
        "warnings": result.warnings,
    }


def _target_gate(target: list[dict[str, object]]) -> tuple[dict[str, bool], list[float]]:
    reductions = [
        float(value) for item in target if isinstance((value := item["final_reduction"]), str)
    ]
    target_gate = {
        "mean_reduction_at_least_70_percent": fmean(reductions) >= 0.70,
        "four_of_five_at_least_70_percent": sum(value >= 0.70 for value in reductions) >= 4,
        "no_fixture_below_60_percent": len(reductions) == 5
        and all(value >= 0.60 for value in reductions),
        "all_final_verification_valid": all(
            item["final_verification_status"] == "valid" for item in target
        ),
        "hard_obligation_coverage_complete": all(
            item["hard_obligation_coverage"] == "1.000000" for item in target
        ),
        "required_relation_coverage_complete": all(
            item["required_relation_coverage"] == "1.000000" for item in target
        ),
        "nonzero_relation_instances": sum(
            int(str(item["discovered_relation_count"])) for item in target
        )
        > 0,
        "multiple_relation_classes": sum(
            int(str(item["relation_class_diversity"])) for item in target
        )
        >= 2,
        "source_maps_complete": all(item["source_map_coverage"] == "1.000000" for item in target),
    }
    target_gate["passed"] = all(target_gate.values())
    return target_gate, reductions


def build_report() -> dict[str, object]:
    target = [_fixture_record(name, CPRGCMode.TARGET) for name in COMPRESSIBLE_FIXTURES]
    aggressive = [_fixture_record(name, CPRGCMode.AGGRESSIVE) for name in COMPRESSIBLE_FIXTURES]
    target_gate, reductions = _target_gate(target)
    backend = os.getenv("TRACEFOLD_TOKENIZER_BACKEND")
    encoding = os.getenv("TRACEFOLD_TOKENIZER_ENCODING")
    configured_target: list[dict[str, object]] | None = None
    configured_gate: dict[str, bool] | None = None
    configured_mean: str | None = None
    configured_identity: dict[str, str] | None = None
    if backend and encoding and backend != "fixture-only":
        configured_tokenizer = resolve_tokenizer(backend, encoding)
        configured_target = [
            _fixture_record(
                name,
                CPRGCMode.TARGET,
                tokenizer=configured_tokenizer,
                reduction_label="configured_tokenizer_reduction",
            )
            for name in COMPRESSIBLE_FIXTURES
        ]
        configured_gate, configured_reductions = _target_gate(configured_target)
        configured_mean = f"{fmean(configured_reductions):.6f}"
        configured_identity = configured_tokenizer.identity.model_dump(mode="json")
    payload: dict[str, object] = {
        "report_version": "1.0.0",
        "algorithm": "CPRGC",
        "tokenizer": Phase6FixtureTokenizer.identity.model_dump(mode="json"),
        "metrics_scope": "local structural fixture metrics; not downstream accuracy",
        "target": target,
        "target_mean_final_reduction": f"{fmean(reductions):.6f}",
        "target_gate": target_gate,
        "fixture_byte_reduction": target,
        "configured_tokenizer": configured_identity,
        "configured_tokenizer_reduction": configured_target,
        "configured_tokenizer_mean_final_reduction": configured_mean,
        "configured_tokenizer_gate": configured_gate,
        "official_token_gate_measured": configured_target is not None,
        "aggressive": aggressive,
        "incompressible": _dense_record(),
    }
    payload["canonical_payload_sha256"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    return payload


def canonical_report_json() -> str:
    return json.dumps(build_report(), sort_keys=True, separators=(",", ":"))


def main() -> None:
    print(canonical_report_json())


if __name__ == "__main__":
    main()


__all__ = [
    "COMPRESSIBLE_FIXTURES",
    "FIXTURE_QUERIES",
    "Phase6FixtureTokenizer",
    "build_report",
    "canonical_report_json",
    "fixture_registry",
]
