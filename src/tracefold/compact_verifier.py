"""Independent verification of synthesized CPRGC facts and relations."""

from __future__ import annotations

import ast
import hashlib
import json
import re

from tracefold.hashing import hash_query, sha256_domain
from tracefold.schemas.api import QueryEnvelope
from tracefold.schemas.common import ArtifactStage, FailedInvariant, HashDomain
from tracefold.schemas.phase2 import ExtractionResult, Obligation, Relation, SourceArtifact
from tracefold.schemas.phase6 import (
    CompactVerificationReport,
    ContextIR,
    FactNode,
    RelationNode,
)
from tracefold.schemas.source_map import SourceMap, SourceSpan
from tracefold.serialization import canonical_json_bytes
from tracefold.source_maps import validate_source_map
from tracefold.sources import normalize_source

COMPONENT_VERSION = "tracefold.compact-verifier/2.0.0"
_UNIT_RE = re.compile(r"(?:^|\s)([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([A-Za-z%]+)\b")
_FACT_RULE = "compact-exact-fact"
_RELATION_RULE = "compact-exact-relation"
_PYTHON_RULES = {"python-ast-skeleton", "python-protected-ast-node"}
_RELATION_LABELS = {
    "relation.value_unit_owner": "value",
    "relation.rule_exception": "rule",
    "relation.condition_consequence": "condition",
    "relation.statement_correction": "old",
    "relation.instruction_scope": "instruction",
    "relation.definition_use": "definition",
    "relation.caller_callee": "caller",
    "relation.import_symbol": "import",
    "relation.event_timestamp": "event",
    "relation.event_trace": "event",
    "relation.error_causal_predecessor": "error",
}
_CODE_RELATION_TYPES = {
    "relation.definition_use",
    "relation.caller_callee",
    "relation.import_symbol",
}
_VERIFIER_HARD_CLASSES = {
    "instruction.system_developer",
    "role.boundary",
    "identifier.generic",
    "numeric.number",
    "numeric.currency",
    "numeric.percentage",
    "numeric.unit",
    "temporal.date",
    "identifier.version",
    "logic.negation",
    "logic.quantifier",
    "policy.permission",
    "policy.prohibition",
    "logic.condition",
    "logic.exception",
    "temporal.correction",
    "dialogue.commitment",
    "structured.anomalous_row",
    "log.severity_change",
    "identifier.trace_request",
    "code.definition",
    "code.branch_guard",
    "code.exception_path",
}


def verifier_obligation_is_mandatory(obligation: Obligation) -> bool:
    """Independent copy of the frozen mandatory policy."""

    if obligation.class_name in {"dialogue.commitment", "structured.anomalous_row"}:
        return True
    if obligation.class_name == "code.definition":
        return obligation.metadata.get("kind") not in {"module", "use", "import_binding"}
    if obligation.class_name == "log.severity_change":
        return "from" in obligation.metadata and "to" in obligation.metadata
    if obligation.class_name == "temporal.timestamp" and obligation.metadata.get("event_id"):
        return False
    if obligation.class_name == "identifier.generic" and obligation.metadata.get("event_id"):
        return obligation.metadata.get("field") in {"error_code", "code"} or (
            obligation.metadata.get("kind") == "exception"
        )
    if obligation.class_name == "entity.named" and obligation.confidence.value == "inferred":
        return False
    if obligation.discovery_status.value != "known":
        return False
    return obligation.class_name in _VERIFIER_HARD_CLASSES


def _span_text(source: SourceArtifact, span: SourceSpan) -> str:
    return source.raw_bytes[span.byte_start : span.byte_end].decode("utf-8", "strict")


def _obligation_value(obligation: Obligation) -> str:
    if obligation.class_name == "code.definition":
        value = obligation.metadata.get("qualified_name") or obligation.metadata.get("name")
        if value is not None:
            return str(value)
    if obligation.lexeme:
        return obligation.lexeme
    if isinstance(obligation.value, str):
        return obligation.value
    return json.dumps(obligation.value, ensure_ascii=False, separators=(",", ":"))


def _owner(
    source: SourceArtifact, spans: dict[str, SourceSpan], obligation: Obligation
) -> str | None:
    owner_spans = [spans[item] for item in obligation.owner_span_ids if item in spans]
    if owner_spans:
        owner_spans.sort(key=lambda item: (item.byte_start, item.byte_end, item.span_id))
        return " ".join(_span_text(source, item).strip() for item in owner_spans)
    value = obligation.metadata.get("owner")
    return value if isinstance(value, str) and value else None


def _scope(obligation: Obligation) -> str | None:
    if obligation.class_name == "code.definition":
        return None
    for key in ("scope", "json_path", "role", "qualified_name", "file_path"):
        value = obligation.metadata.get(key)
        if isinstance(value, str) and value:
            if key == "json_path":
                return re.sub(r"/\d+(?=/|$)", "/[]", value)
            return value
    return None


def _unit(
    source: SourceArtifact, spans: dict[str, SourceSpan], obligation: Obligation
) -> str | None:
    value = obligation.metadata.get("unit")
    if isinstance(value, str) and value:
        return value
    for span_id in obligation.source_span_ids:
        span = spans.get(span_id)
        if span is not None:
            match = _UNIT_RE.search(_span_text(source, span))
            if match:
                return match.group(2)
    return None


def _polarity(obligation: Obligation) -> str | None:
    value = obligation.metadata.get("polarity")
    if isinstance(value, str) and value:
        return value
    return {
        "logic.negation": "negative",
        "policy.prohibition": "prohibited",
        "policy.permission": "permitted",
    }.get(obligation.class_name)


def _temporal(obligation: Obligation) -> str | None:
    value = obligation.metadata.get("qualifier")
    return value if isinstance(value, str) and value else None


def _render_fact_independently(fields: dict[str, str | None]) -> str:
    fact_type = fields["fact_type"]
    exact_value = fields["exact_value"] or ""
    if fact_type == "code.definition":
        return f"- D={exact_value}"
    if fact_type == "code.exception_path":
        suffix = f"@{fields['scope']}" if fields["scope"] else ""
        return f"- P={exact_value}{suffix}"
    if fact_type == "code.call":
        return f"- C={exact_value}"
    if fact_type == "code.branch_guard":
        suffix = f"@{fields['scope']}" if fields["scope"] else ""
        return f"- G={exact_value}{suffix}"
    if fact_type == "code.import":
        return f"- I={exact_value}"
    parts = [f"{fact_type}={exact_value}"]
    for key, label in (
        ("owner", "owner"),
        ("unit", "unit"),
        ("scope", "scope"),
        ("polarity", "polarity"),
        ("temporal_qualifier", "time"),
    ):
        if fields[key]:
            parts.append(f"{label}={fields[key]}")
    prefix = "@row\t" if fact_type == "structured.anomalous_row" else ""
    return "- " + prefix + " ".join(parts)


def _render_relation_independently(
    relation: Relation,
    obligations: dict[str, Obligation],
    source: SourceArtifact,
    spans: dict[str, SourceSpan],
) -> str:
    """Independent copy of the frozen relation rendering contract."""

    if relation.relation_type == "relation.event_trace" and source.kind == "json":
        path = "?"
        trace = "null"
        for obligation_id in relation.obligation_ids:
            obligation = obligations.get(obligation_id)
            if obligation is None:
                continue
            if obligation.class_name == "structured.json_schema_path":
                candidate_path = obligation.metadata.get("json_path")
                if isinstance(candidate_path, str):
                    path = candidate_path
            elif obligation.class_name == "identifier.trace_request":
                trace = _obligation_value(obligation)
        return f"event_trace path={path} trace_id={trace}"

    if relation.relation_type in _CODE_RELATION_TYPES:
        code_values: list[str] = []
        for obligation_id in relation.obligation_ids:
            obligation = obligations.get(obligation_id)
            if obligation is None:
                continue
            metadata = obligation.metadata
            value = metadata.get("qualified_name") or metadata.get("name")
            if obligation.class_name == "code.call":
                value = obligation.value
            if obligation.class_name == "code.import":
                value = metadata.get("module") or metadata.get("name") or obligation.value
            if value is not None:
                code_values.append(str(value))
        left = code_values[0] if code_values else relation.relation_type
        right = code_values[1] if len(code_values) > 1 else "evidence"
        label = _RELATION_LABELS[relation.relation_type]
        return f"{label}: {left} -> {right}"

    values: list[str] = []
    for obligation_id in relation.obligation_ids:
        obligation = obligations.get(obligation_id)
        if obligation is None:
            continue
        value = _obligation_value(obligation)
        owner = _owner(source, spans, obligation)
        values.append(f"{value} [owner={owner}]" if owner else value)
    left = values[0] if values else relation.relation_type
    right = values[1] if len(values) > 1 else "evidence"
    if relation.relation_type == "relation.condition_consequence":
        return f"if {left} then {right}"
    label = _RELATION_LABELS.get(relation.relation_type, "relation")
    return f"{label}: {left} -> {right}"


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


def _mapped_output(
    source_map: SourceMap,
    output: bytes,
    *,
    reason_code: str,
    from_span_ids: set[str],
    obligation_ids: set[str] | None = None,
    relation_ids: set[str] | None = None,
) -> bytes:
    """Return the output bytes a specific compiler rule emitted for this lineage.

    Lineage that reaches the output through some other rule is not evidence that
    this node was rendered, so the rule and the originating spans both gate the
    lookup.
    """

    span_by_id = {span.span_id: span for span in source_map.spans}
    output_artifacts = {
        item.artifact_id
        for item in source_map.artifacts
        if item.stage in {ArtifactStage.RAW_COMPRESSED, ArtifactStage.FINAL_COMPRESSED}
    }
    fragments: list[bytes] = []
    for mapping in source_map.mappings:
        if mapping.reason_code != reason_code:
            continue
        if not from_span_ids.intersection(mapping.from_span_ids):
            continue
        if obligation_ids is not None and not obligation_ids.intersection(mapping.obligation_ids):
            continue
        if relation_ids is not None and not relation_ids.intersection(mapping.relation_ids):
            continue
        for span_id in mapping.to_span_ids:
            span = span_by_id.get(span_id)
            if span is not None and span.artifact_id in output_artifacts:
                fragments.append(output[span.byte_start : span.byte_end])
    return b"\n".join(fragments)


def _failure(
    code: str,
    source: SourceArtifact,
    *,
    kind: str,
    obligation_ids: list[str] | None = None,
    relation_ids: list[str] | None = None,
    source_span_ids: list[str] | None = None,
    candidate_span_ids: list[str] | None = None,
    expected: str | None = None,
    observed: str | None = None,
) -> FailedInvariant:
    payload = {
        "code": code,
        "source_id": source.source_id,
        "obligation_ids": sorted(obligation_ids or []),
        "relation_ids": sorted(relation_ids or []),
        "source_span_ids": sorted(source_span_ids or []),
        "candidate_span_ids": sorted(candidate_span_ids or []),
        "expected": expected,
        "observed": observed,
        "version": COMPONENT_VERSION,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:24]
    return FailedInvariant(
        invariant_id=f"compact:{digest}",
        class_name="compact.semantic_integrity",
        kind=kind,  # type: ignore[arg-type]
        severity="hard",
        code=code,
        message=f"compact semantic verification failed: {code}",
        source_span_ids=sorted(source_span_ids or []),
        candidate_span_ids=sorted(candidate_span_ids or []),
        recovery_hint="restore exact primary evidence and independently re-verify",
        source_id=source.source_id,
        obligation_ids=sorted(obligation_ids or []),
        relation_ids=sorted(relation_ids or []),
        expected_condition=expected,
        observed_condition=observed,
        verifier_rule_version=COMPONENT_VERSION,
    )


def _fact_failures(
    source: SourceArtifact,
    extraction: ExtractionResult,
    context_ir: ContextIR,
    compact_text: str,
    source_map: SourceMap,
) -> tuple[int, list[FailedInvariant]]:
    spans = {item.span_id: item for item in extraction.spans}
    obligations = {item.obligation_id: item for item in extraction.obligations}
    failures: list[FailedInvariant] = []
    verified = 0
    for node in context_ir.nodes:
        if not isinstance(node, FactNode):
            continue
        node_spans = [item.span_id for item in node.source_spans]
        mapped = _mapped_output(
            source_map,
            compact_text.encode(),
            reason_code=_FACT_RULE,
            from_span_ids=set(node_spans),
            obligation_ids=set(node.obligation_ids),
        )
        if not mapped:
            continue
        relevant = [obligations.get(item) for item in node.obligation_ids]
        if not relevant or any(item is None for item in relevant):
            failures.append(
                _failure(
                    "FACT_OBLIGATION_MISSING",
                    source,
                    kind="obligation",
                    obligation_ids=node.obligation_ids,
                    source_span_ids=node_spans,
                )
            )
            continue
        typed = [item for item in relevant if item is not None]
        expected_rows = [
            {
                "fact_type": item.class_name,
                "exact_value": _obligation_value(item),
                "owner": _owner(source, spans, item),
                "unit": _unit(source, spans, item),
                "scope": _scope(item),
                "polarity": _polarity(item),
                "temporal_qualifier": _temporal(item),
            }
            for item in typed
        ]
        expected = expected_rows[0]
        if any(item != expected for item in expected_rows[1:]):
            failures.append(
                _failure(
                    "FACT_AMBIGUOUS_PRIMARY_EVIDENCE",
                    source,
                    kind="obligation",
                    obligation_ids=node.obligation_ids,
                    source_span_ids=node_spans,
                )
            )
            continue
        observed = {
            "fact_type": node.fact_type,
            "exact_value": node.exact_value,
            "owner": node.owner,
            "unit": node.unit,
            "scope": node.scope,
            "polarity": node.polarity,
            "temporal_qualifier": node.temporal_qualifier,
        }
        expected_span_ids = sorted({span_id for item in typed for span_id in item.source_span_ids})
        if node.source_id != source.source_id or not set(expected_span_ids).issubset(node_spans):
            failures.append(
                _failure(
                    "FACT_SOURCE_OWNERSHIP_MISMATCH",
                    source,
                    kind="source_map",
                    obligation_ids=node.obligation_ids,
                    source_span_ids=expected_span_ids,
                    candidate_span_ids=node_spans,
                )
            )
        if observed != expected:
            failures.append(
                _failure(
                    "FACT_PRIMARY_EVIDENCE_MISMATCH",
                    source,
                    kind="obligation",
                    obligation_ids=node.obligation_ids,
                    source_span_ids=expected_span_ids,
                    candidate_span_ids=node_spans,
                    expected=json.dumps(expected, sort_keys=True),
                    observed=json.dumps(observed, sort_keys=True),
                )
            )
            continue
        rendering = _render_fact_independently(expected)
        if rendering not in compact_text or rendering.encode() not in mapped:
            failures.append(
                _failure(
                    "FACT_RENDERING_MISMATCH",
                    source,
                    kind="obligation",
                    obligation_ids=node.obligation_ids,
                    source_span_ids=expected_span_ids,
                    candidate_span_ids=node_spans,
                    expected=rendering,
                    observed=mapped.decode("utf-8", "replace"),
                )
            )
            continue
        verified += 1
    return verified, failures


def _relation_failures(
    source: SourceArtifact,
    extraction: ExtractionResult,
    context_ir: ContextIR,
    compact_text: str,
    source_map: SourceMap,
) -> tuple[int, list[FailedInvariant]]:
    relations = {item.relation_id: item for item in extraction.relations}
    obligations = {item.obligation_id: item for item in extraction.obligations}
    extraction_spans = {item.span_id: item for item in extraction.spans}
    nodes = {item.node_id: item for item in context_ir.nodes}
    failures: list[FailedInvariant] = []
    verified = 0
    for node in context_ir.nodes:
        if not isinstance(node, RelationNode):
            continue
        relation_ids = [node.relation_id, *node.represented_relation_ids]
        evidence_ids = [item.span_id for item in node.evidence_spans]
        mapped = _mapped_output(
            source_map,
            compact_text.encode(),
            reason_code=_RELATION_RULE,
            from_span_ids=set(evidence_ids),
            relation_ids=set(relation_ids),
        )
        if not mapped:
            continue
        relation = relations.get(node.relation_id)
        if relation is None:
            failures.append(
                _failure(
                    "RELATION_NOT_IN_PRIMARY_EXTRACTION",
                    source,
                    kind="relation",
                    relation_ids=relation_ids,
                    source_span_ids=evidence_ids,
                )
            )
            continue
        if (
            relation.relation_type != node.relation_type
            or relation.exactness != node.exactness
            or source.source_id not in relation.source_ids
            or not set(relation.evidence_span_ids).issubset(evidence_ids)
        ):
            failures.append(
                _failure(
                    "RELATION_PRIMARY_EVIDENCE_MISMATCH",
                    source,
                    kind="relation",
                    relation_ids=relation_ids,
                    source_span_ids=relation.evidence_span_ids,
                    candidate_span_ids=evidence_ids,
                )
            )
            continue
        if not 2 <= len(node.endpoint_node_ids) <= len(relation.obligation_ids):
            failures.append(
                _failure(
                    "RELATION_ENDPOINT_COUNT_MISMATCH",
                    source,
                    kind="relation",
                    relation_ids=relation_ids,
                    obligation_ids=relation.obligation_ids,
                    source_span_ids=relation.evidence_span_ids,
                )
            )
            continue
        # Endpoints may collapse when two obligations resolve to one node, so the
        # check is that every endpoint owns relation evidence and that endpoint
        # order still follows the relation's declared obligation order.
        direction_valid = True
        ordinals: list[int] = []
        for endpoint_id in node.endpoint_node_ids:
            endpoint = nodes.get(endpoint_id)
            owned = [
                relation.obligation_ids.index(item)
                for item in getattr(endpoint, "obligation_ids", [])
                if item in relation.obligation_ids
            ]
            if endpoint is None or not owned:
                direction_valid = False
                break
            ordinals.append(min(owned))
        if direction_valid and ordinals != sorted(ordinals):
            direction_valid = False
        if not direction_valid:
            failures.append(
                _failure(
                    "RELATION_ENDPOINT_DIRECTION_MISMATCH",
                    source,
                    kind="relation",
                    relation_ids=relation_ids,
                    obligation_ids=relation.obligation_ids,
                    source_span_ids=relation.evidence_span_ids,
                )
            )
            continue
        expected_rendering = _render_relation_independently(
            relation, obligations, source, extraction_spans
        )
        rendered = node.compact_rendering
        if (
            rendered != expected_rendering
            or f"- {rendered}" not in compact_text
            or rendered.encode() not in mapped
        ):
            failures.append(
                _failure(
                    "RELATION_RENDERING_SEMANTICS_MISMATCH",
                    source,
                    kind="relation",
                    relation_ids=relation_ids,
                    obligation_ids=relation.obligation_ids,
                    source_span_ids=relation.evidence_span_ids,
                    candidate_span_ids=evidence_ids,
                    expected=expected_rendering,
                    observed=rendered,
                )
            )
            continue
        verified += 1
    return verified, failures


def _code_section(compact_text: str, source_map: SourceMap) -> str:
    output = compact_text.encode("utf-8", "strict")
    span_by_id = {span.span_id: span for span in source_map.spans}
    code_span_ids = {
        span_id
        for mapping in source_map.mappings
        if mapping.reason_code in _PYTHON_RULES
        for span_id in mapping.to_span_ids
    }
    code_spans = sorted(
        (span_by_id[span_id] for span_id in code_span_ids if span_id in span_by_id),
        key=lambda span: (span.byte_start, span.byte_end, span.span_id),
    )
    if code_spans:
        return "\n".join(
            output[span.byte_start : span.byte_end].decode("utf-8", "strict") for span in code_spans
        )
    marker = "[PYTHON]\n"
    if marker not in compact_text:
        return compact_text
    code = compact_text.split(marker, 1)[1]
    for ending in ("\n[OMISSIONS]", "\n[/TRACEFOLD]"):
        if ending in code:
            code = code.split(ending, 1)[0]
    return code.strip()


def verify_compact_context(
    source: SourceArtifact,
    extraction: ExtractionResult,
    context_ir: ContextIR,
    compact_text: str,
    source_map: SourceMap,
    *,
    query: str | None = None,
) -> CompactVerificationReport:
    """Reconstruct compact claims from primary evidence in an independent trust domain."""

    output = compact_text.encode("utf-8", "strict")
    source_map_report = validate_source_map(
        source_map, artifacts=_artifact_bytes(source, source_map, output)
    )
    source_hash = sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes)
    query_hash = hash_query(QueryEnvelope(query=query))
    failures: list[FailedInvariant] = []
    if source_map.query_hash != query_hash:
        failures.append(
            _failure(
                "QUERY_HASH_MISMATCH",
                source,
                kind="hash",
                expected=query_hash,
                observed=source_map.query_hash,
            )
        )
    if context_ir.query_hash != query_hash or context_ir.source_hash != source_hash:
        failures.append(
            _failure(
                "IR_BINDING_MISMATCH",
                source,
                kind="hash",
                expected=f"{source_hash}:{query_hash}",
                observed=f"{context_ir.source_hash}:{context_ir.query_hash}",
            )
        )
    for error in source_map_report.errors:
        failures.append(
            _failure(
                "SOURCE_MAP_INVALID",
                source,
                kind="source_map",
                expected="valid source map",
                observed=error,
            )
        )
    fact_count, fact_failures = _fact_failures(
        source, extraction, context_ir, compact_text, source_map
    )
    relation_count, relation_failures = _relation_failures(
        source, extraction, context_ir, compact_text, source_map
    )
    failures.extend(fact_failures)
    failures.extend(relation_failures)
    parseable: bool | None = None
    if context_ir.source_kind.value == "python":
        try:
            ast.parse(_code_section(compact_text, source_map))
            parseable = True
        except SyntaxError:
            parseable = False
            failures.append(_failure("PYTHON_NOT_PARSEABLE", source, kind="parser"))
    unique = {item.invariant_id: item for item in failures}
    ordered = [unique[key] for key in sorted(unique)]
    return CompactVerificationReport(
        status="invalid" if ordered else "valid",
        source_hash=source_hash,
        query_hash=query_hash,
        verified_fact_count=fact_count,
        verified_relation_count=relation_count,
        source_map_valid=source_map_report.valid,
        parseable=parseable,
        failed_checks=sorted({item.code for item in ordered}),
        failed_invariants=ordered,
        component_version=COMPONENT_VERSION,
    )


__all__ = [
    "COMPONENT_VERSION",
    "verifier_obligation_is_mandatory",
    "verify_compact_context",
]
