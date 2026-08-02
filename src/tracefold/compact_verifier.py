"""Independent checks for synthesized CPRGC facts and relations."""

from __future__ import annotations

import ast

from tracefold.context_ir import render_fact
from tracefold.hashing import hash_query, sha256_domain
from tracefold.schemas.api import QueryEnvelope
from tracefold.schemas.common import ArtifactStage, HashDomain
from tracefold.schemas.phase2 import ExtractionResult, SourceArtifact
from tracefold.schemas.phase6 import CompactVerificationReport, ContextIR, FactNode, RelationNode
from tracefold.schemas.source_map import SourceMap
from tracefold.source_maps import validate_source_map
from tracefold.sources import normalize_source

COMPONENT_VERSION = "tracefold.compact-verifier/1.0.0"


def _artifact_bytes(
    source: SourceArtifact, source_map: SourceMap, output: bytes
) -> dict[str, bytes]:
    normalized = normalize_source(source)
    values: dict[str, bytes] = {}
    for artifact in source_map.artifacts:
        if artifact.stage == ArtifactStage.ORIGINAL and artifact.source_id == source.source_id:
            values[artifact.artifact_id] = source.raw_bytes
        elif artifact.stage == ArtifactStage.NORMALIZED and artifact.source_id == source.source_id:
            values[artifact.artifact_id] = normalized.normalized_bytes
        elif artifact.stage in {ArtifactStage.RAW_COMPRESSED, ArtifactStage.FINAL_COMPRESSED}:
            values[artifact.artifact_id] = output
    return values


def _output_fragments(
    source_map: SourceMap, source_span_id: str, output_ids: set[str], output: bytes
) -> list[bytes]:
    span_by_id = {span.span_id: span for span in source_map.spans}
    fragments: list[bytes] = []
    for mapping in source_map.mappings:
        if source_span_id not in mapping.from_span_ids:
            continue
        for output_id in mapping.to_span_ids:
            target = span_by_id.get(output_id)
            if target is not None and target.artifact_id in output_ids:
                fragments.append(output[target.byte_start : target.byte_end])
    return fragments


def _source_bytes(source: SourceArtifact, source_map: SourceMap, span_id: str) -> bytes | None:
    span_by_id = {span.span_id: span for span in source_map.spans}
    span = span_by_id.get(span_id)
    if span is None:
        return None
    if span.artifact_id not in {
        item.artifact_id
        for item in source_map.artifacts
        if item.stage == ArtifactStage.ORIGINAL and item.source_id == source.source_id
    }:
        return None
    return source.raw_bytes[span.byte_start : span.byte_end]


def _code_section(context: str, source_map: SourceMap | None = None) -> str:
    if source_map is not None:
        output = context.encode("utf-8", "strict")
        span_by_id = {span.span_id: span for span in source_map.spans}
        python_span_ids = {
            span_id
            for mapping in source_map.mappings
            if mapping.reason_code
            in {"python-ast-skeleton", "python-protected-skeleton", "python-protected-ast-node"}
            for span_id in mapping.to_span_ids
        }
        python_spans = sorted(
            (span_by_id[span_id] for span_id in python_span_ids if span_id in span_by_id),
            key=lambda span: (span.byte_start, span.byte_end, span.span_id),
        )
        if python_spans:
            return "\n".join(
                output[span.byte_start : span.byte_end].decode("utf-8", "strict")
                for span in python_spans
            )
    python_marker = "[PYTHON]\n"
    if python_marker in context:
        code = context.split(python_marker, 1)[1]
        for ending in ("\n[OMISSIONS]", "\n[/TRACEFOLD]"):
            if ending in code:
                code = code.split(ending, 1)[0]
        return code.strip()
    marker = "[SELECTED EVIDENCE]\n"
    if marker in context:
        code = context.split(marker, 1)[1]
        for ending in ("\n[OMISSIONS]", "\n[/TRACEFOLD]"):
            if ending in code:
                code = code.split(ending, 1)[0]
        return code.strip()
    return context


def verify_compact_context(
    source: SourceArtifact,
    extraction: ExtractionResult,
    context_ir: ContextIR,
    compact_text: str,
    source_map: SourceMap,
    *,
    query: str | None = None,
) -> CompactVerificationReport:
    """Recompute compact fact and relation claims from source evidence.

    This function intentionally does not read compressor diagnostics or node
    metadata as proof. It uses source bytes, source-map lineage, and rendered
    fields only.
    """

    output = compact_text.encode("utf-8", "strict")
    artifacts = _artifact_bytes(source, source_map, output)
    source_map_report = validate_source_map(source_map, artifacts=artifacts)
    failures: list[str] = []
    expected_query_hash = hash_query(QueryEnvelope(query=query))
    expected_source_hash = sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes)
    if source_map.query_hash != expected_query_hash:
        failures.append("QUERY_HASH_MISMATCH")
    if context_ir.query_hash != expected_query_hash:
        failures.append("IR_QUERY_HASH_MISMATCH")
    if context_ir.source_hash != expected_source_hash:
        failures.append("IR_SOURCE_HASH_MISMATCH")
    if not source_map_report.valid:
        failures.extend(f"SOURCE_MAP:{item}" for item in source_map_report.errors)

    output_ids = {
        item.artifact_id
        for item in source_map.artifacts
        if item.stage in {ArtifactStage.RAW_COMPRESSED, ArtifactStage.FINAL_COMPRESSED}
    }
    verified_facts = 0
    verified_relations = 0
    for node in context_ir.nodes:
        if isinstance(node, FactNode):
            source_span_ids = {span.span_id for span in node.source_spans}
            selected = any(
                mapping.reason_code == "compact-exact-fact"
                and source_span_ids.intersection(mapping.from_span_ids)
                and set(node.obligation_ids).intersection(mapping.obligation_ids)
                for mapping in source_map.mappings
            )
            if not selected:
                continue
            rendered = render_fact(node).encode("utf-8")
            fragments: list[bytes] = []
            source_values: list[str] = []
            for span in node.source_spans:
                if span.artifact_id not in {
                    item.artifact_id
                    for item in source_map.artifacts
                    if item.stage == ArtifactStage.ORIGINAL and item.source_id == source.source_id
                }:
                    failures.append(f"FOREIGN_FACT_SOURCE:{node.node_id}")
                    continue
                raw = _source_bytes(source, source_map, span.span_id)
                if raw is None:
                    failures.append(f"FACT_SOURCE_SPAN_MISSING:{node.node_id}")
                else:
                    source_values.append(raw.decode("utf-8", "strict"))
                fragments.extend(_output_fragments(source_map, span.span_id, output_ids, output))
            if (
                node.fact_type == "log.severity_change"
                and node.exact_value.startswith('{"from":')
                and len(source_values) == 2
            ):
                first, second = (value.strip().lower() for value in source_values)
                source_value_matches = node.exact_value == f'{{"from":"{first}","to":"{second}"}}'
            elif node.fact_type == "role.boundary" and source_values:
                source_value_matches = len(set(source_values)) == 1 and (
                    node.exact_value == f"{source_values[0]}:"
                )
            else:
                source_value_matches = node.exact_value in "\n".join(source_values)
            if not source_value_matches:
                failures.append(f"FACT_VALUE_SOURCE_MISMATCH:{node.node_id}")
            if not fragments or not any(rendered in fragment for fragment in fragments):
                failures.append(f"FACT_RENDERING_MISSING:{node.node_id}")
                continue
            fields = [node.exact_value, node.owner, node.unit, node.scope, node.polarity]
            if not all(
                value is None or value.encode("utf-8") in b"\n".join(fragments) for value in fields
            ):
                failures.append(f"FACT_FIELD_TAMPER:{node.node_id}")
                continue
            verified_facts += 1
        elif isinstance(node, RelationNode):
            if not any(
                mapping.reason_code == "compact-exact-relation"
                and node.relation_id in mapping.relation_ids
                for mapping in source_map.mappings
            ):
                continue
            evidence_fragments: list[bytes] = []
            for span in node.evidence_spans:
                evidence_fragments.extend(
                    _output_fragments(source_map, span.span_id, output_ids, output)
                )
            rendered = node.compact_rendering.encode("utf-8")
            if not evidence_fragments or not any(
                rendered in fragment for fragment in evidence_fragments
            ):
                failures.append(f"RELATION_RENDERING_MISSING:{node.relation_id}")
                continue
            if len(node.endpoint_node_ids) < 2:
                failures.append(f"RELATION_ENDPOINT_COUNT:{node.relation_id}")
                continue
            verified_relations += 1

    parseable: bool | None = None
    if context_ir.source_kind.value == "python":
        try:
            ast.parse(_code_section(compact_text, source_map))
            parseable = True
        except SyntaxError:
            parseable = False
            failures.append("PYTHON_NOT_PARSEABLE")

    return CompactVerificationReport(
        status="valid" if not failures else "invalid",
        source_hash=expected_source_hash,
        query_hash=expected_query_hash,
        verified_fact_count=verified_facts,
        verified_relation_count=verified_relations,
        source_map_valid=source_map_report.valid,
        parseable=parseable,
        failed_checks=sorted(set(failures)),
        component_version=COMPONENT_VERSION,
    )


__all__ = ["COMPONENT_VERSION", "verify_compact_context"]
