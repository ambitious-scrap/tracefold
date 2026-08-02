"""Deterministic ContextIR construction for CPRGC."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from tracefold.hashing import hash_query, sha256_domain
from tracefold.schemas.api import QueryEnvelope
from tracefold.schemas.common import HashDomain
from tracefold.schemas.phase2 import ExtractionResult, Obligation, Relation, SourceArtifact
from tracefold.schemas.phase6 import (
    AggregateNode,
    ContextIR,
    ExactSpanNode,
    FactNode,
    OmissionNode,
    RelationNode,
    StructureNode,
)
from tracefold.schemas.source_map import SourceSpan
from tracefold.serialization import canonical_json_bytes
from tracefold.tokenizers.base import Tokenizer

COMPONENT_VERSION = "tracefold.context-ir/1.0.0"
_UNIT_RE = re.compile(r"(?:^|\s)([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([A-Za-z%]+)\b")
_FACT_CLASSES = {
    "identifier.generic",
    "identifier.version",
    "numeric.number",
    "numeric.currency",
    "numeric.percentage",
    "numeric.unit",
    "temporal.date",
    "temporal.timestamp",
    "identifier.trace_request",
    "dialogue.commitment",
    "role.boundary",
    "logic.negation",
    "logic.quantifier",
    "policy.permission",
    "policy.prohibition",
    "structured.json_schema_path",
    "structured.anomalous_row",
    "log.severity_change",
    "code.definition",
    "code.import",
    "code.call",
    "code.constant",
    "code.branch_guard",
    "code.exception_path",
}
_HARD_CLASSES = {
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


def stable_id(prefix: str, payload: object) -> str:
    """Return short deterministic ID; full evidence remains in source maps."""

    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _span_text(source: SourceArtifact, span: SourceSpan) -> str:
    return source.raw_bytes[span.byte_start : span.byte_end].decode("utf-8", "strict")


def _span_order(span: SourceSpan) -> tuple[int, int, str]:
    return span.byte_start, span.byte_end, span.span_id


def _value_text(obligation: Obligation) -> str:
    if obligation.class_name == "code.definition":
        name = obligation.metadata.get("qualified_name") or obligation.metadata.get("name")
        if isinstance(name, str) and name:
            return name
    if obligation.lexeme:
        return obligation.lexeme
    if isinstance(obligation.value, str):
        return obligation.value
    return json.dumps(obligation.value, ensure_ascii=False, separators=(",", ":"))


def _owner_text(
    source: SourceArtifact,
    spans: dict[str, SourceSpan],
    obligation: Obligation,
) -> str | None:
    owner_spans = [spans[item] for item in obligation.owner_span_ids if item in spans]
    if owner_spans:
        return " ".join(
            _span_text(source, item).strip() for item in sorted(owner_spans, key=_span_order)
        )
    owner = obligation.metadata.get("owner")
    return owner if isinstance(owner, str) and owner else None


def _scope_text(obligation: Obligation) -> str | None:
    if obligation.class_name == "code.definition":
        return None
    for key in ("scope", "json_path", "role", "qualified_name", "file_path"):
        value = obligation.metadata.get(key)
        if isinstance(value, str) and value:
            if key == "json_path":
                value = re.sub(r"/\d+(?=/|$)", "/[]", value)
            return value
    return None


def _unit_text(
    source: SourceArtifact,
    spans: dict[str, SourceSpan],
    obligation: Obligation,
) -> str | None:
    value = obligation.metadata.get("unit")
    if isinstance(value, str) and value:
        return value
    for span_id in obligation.source_span_ids:
        span = spans.get(span_id)
        if span is None:
            continue
        match = _UNIT_RE.search(_span_text(source, span))
        if match:
            return match.group(2)
    return None


def _polarity(obligation: Obligation) -> str | None:
    value = obligation.metadata.get("polarity")
    if isinstance(value, str) and value:
        return value
    if obligation.class_name == "logic.negation":
        return "negative"
    if obligation.class_name == "policy.prohibition":
        return "prohibited"
    if obligation.class_name == "policy.permission":
        return "permitted"
    return None


def _source_spans(extraction: ExtractionResult) -> dict[str, SourceSpan]:
    return {span.span_id: span for span in extraction.spans}


def _hard(obligation: Obligation) -> bool:
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
    return obligation.class_name in _HARD_CLASSES


def _compact_fact_allowed(
    source: SourceArtifact, spans: dict[str, SourceSpan], obligation: Obligation
) -> bool:
    if obligation.class_name not in _FACT_CLASSES:
        return False
    if obligation.confidence.value == "unknown":
        return False
    if not obligation.source_span_ids:
        return False
    # A value with a declared owner must carry that owner into the ledger.
    if obligation.class_name in {
        "numeric.number",
        "numeric.unit",
        "numeric.currency",
        "numeric.percentage",
    }:
        if obligation.owner_span_ids and _owner_text(source, spans, obligation) is None:
            return False
    return True


def _relation_rendering(
    relation: Relation,
    obligations: dict[str, Obligation],
    source: SourceArtifact,
    spans: dict[str, SourceSpan],
) -> str:
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
                trace = _value_text(obligation)
        return f"event_trace path={path} trace_id={trace}"

    if relation.relation_type in {
        "relation.definition_use",
        "relation.caller_callee",
        "relation.import_symbol",
    }:
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
        label = {
            "relation.definition_use": "definition",
            "relation.caller_callee": "caller",
            "relation.import_symbol": "import",
        }[relation.relation_type]
        return f"{label}: {left} -> {right}"

    values: list[str] = []
    for obligation_id in relation.obligation_ids:
        obligation = obligations.get(obligation_id)
        if obligation is None:
            continue
        value = _value_text(obligation)
        owner = _owner_text(source, spans, obligation)
        values.append(f"{value} [owner={owner}]" if owner else value)
    left = values[0] if values else relation.relation_type
    right = values[1] if len(values) > 1 else "evidence"
    labels = {
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
    label = labels.get(relation.relation_type, "relation")
    if relation.relation_type == "relation.condition_consequence":
        return f"if {left} then {right}"
    return f"{label}: {left} -> {right}"


def build_context_ir(
    source: SourceArtifact,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
    *,
    query: str | None = None,
) -> ContextIR:
    """Build typed nodes from primary extraction evidence only."""

    if not extraction.sources or extraction.sources[0].source_id != source.source_id:
        raise ValueError("ContextIR source and extraction differ")
    spans = _source_spans(extraction)
    obligations = {item.obligation_id: item for item in extraction.obligations}
    source_text = source.raw_bytes.decode("utf-8", "strict")
    nodes: list[Any] = []
    obligation_node: dict[str, str] = {}
    span_node: dict[str, str] = {}
    fact_by_key: dict[
        tuple[str, str, str | None, str | None, str | None, str | None], FactNode
    ] = {}

    for obligation in sorted(extraction.obligations, key=lambda item: item.obligation_id):
        source_spans = [spans[item] for item in obligation.source_span_ids if item in spans]
        source_spans.sort(key=_span_order)
        if not source_spans:
            continue
        if _compact_fact_allowed(source, spans, obligation):
            fact_value = _value_text(obligation)
            owner = _owner_text(source, spans, obligation)
            scope = _scope_text(obligation)
            fact_payload = {
                "source_id": source.source_id,
                "class": obligation.class_name,
                "value": fact_value,
                "owner": owner,
                "scope": scope,
                "spans": [item.span_id for item in source_spans],
            }
            node_id = stable_id("fact", fact_payload)
            unit = _unit_text(source, spans, obligation)
            fact = FactNode(
                node_id=node_id,
                source_id=source.source_id,
                source_kind=extraction.content_type,
                fact_type=obligation.class_name,
                exact_value=fact_value,
                owner=owner,
                unit=unit,
                scope=scope,
                polarity=_polarity(obligation),
                temporal_qualifier=(
                    obligation.metadata.get("qualifier")
                    if isinstance(obligation.metadata.get("qualifier"), str)
                    else None
                ),
                source_spans=source_spans,
                obligation_ids=[obligation.obligation_id],
                token_cost=tokenizer.count(fact_value),
                exactness="exact" if obligation.confidence.value == "exact" else "inferred",
            )
            fact_key = (
                fact.fact_type,
                fact.exact_value,
                fact.owner,
                fact.unit,
                fact.scope,
                fact.polarity,
            )
            previous = fact_by_key.get(fact_key)
            if previous is not None:
                fact = previous.model_copy(
                    update={
                        "source_spans": [*previous.source_spans, *source_spans],
                        "obligation_ids": [*previous.obligation_ids, obligation.obligation_id],
                    }
                )
                nodes[nodes.index(previous)] = fact
                fact_by_key[fact_key] = fact
            else:
                fact_by_key[fact_key] = fact
                nodes.append(fact)
            obligation_node[obligation.obligation_id] = fact.node_id
            for span in source_spans:
                span_node.setdefault(span.span_id, fact.node_id)
            continue

        related = [item for item in nodes if isinstance(item, ExactSpanNode)]
        existing = next(
            (
                item
                for item in related
                if {span.span_id for span in item.original_spans}
                == {span.span_id for span in source_spans}
            ),
            None,
        )
        if existing is not None:
            node = existing.model_copy(
                update={
                    "obligation_ids": [*existing.obligation_ids, obligation.obligation_id],
                }
            )
            nodes[nodes.index(existing)] = node
            obligation_node[obligation.obligation_id] = node.node_id
            continue
        exact_text = " ".join(_span_text(source, item).strip() for item in source_spans)
        node_id = stable_id(
            "span",
            {
                "source_id": source.source_id,
                "spans": [item.span_id for item in source_spans],
                "text": exact_text,
            },
        )
        node = ExactSpanNode(
            node_id=node_id,
            source_id=source.source_id,
            source_kind=extraction.content_type,
            original_spans=source_spans,
            exact_text=exact_text,
            obligation_ids=[obligation.obligation_id],
            relation_ids=[],
            token_cost=tokenizer.count(exact_text),
            protection="hard" if _hard(obligation) else "optional",
            source_order=source_spans[0].char_start,
            extraction_method=obligation.extraction_method,
        )
        nodes.append(node)
        obligation_node[obligation.obligation_id] = node_id
        for span in source_spans:
            span_node.setdefault(span.span_id, node_id)

    full_span = min(extraction.spans, key=_span_order) if extraction.spans else None
    if full_span is not None:
        structure_id = stable_id("structure", {"source": source.source_id, "kind": "source"})
        nodes.append(
            StructureNode(
                node_id=structure_id,
                source_id=source.source_id,
                source_kind=extraction.content_type,
                structure_type="source_boundary",
                exact_text=source_text[:0],
                source_spans=[full_span],
                child_node_ids=[],
                token_cost=0,
                source_order=0,
            )
        )

    relation_by_key: dict[tuple[str, tuple[str, ...], str], RelationNode] = {}
    for relation in sorted(extraction.relations, key=lambda item: item.relation_id):
        endpoint_ids = list(
            dict.fromkeys(
                obligation_node[item] for item in relation.obligation_ids if item in obligation_node
            )
        )
        evidence = [spans[item] for item in relation.evidence_span_ids if item in spans]
        if len(endpoint_ids) < 2 or not evidence:
            continue
        rendering = _relation_rendering(relation, obligations, source, spans)
        relation_key = (relation.relation_type, tuple(endpoint_ids), rendering)
        previous_relation = relation_by_key.get(relation_key)
        if previous_relation is not None:
            merged = previous_relation.model_copy(
                update={
                    "evidence_spans": [*previous_relation.evidence_spans, *evidence],
                    "represented_relation_ids": [
                        *previous_relation.represented_relation_ids,
                        relation.relation_id,
                    ],
                }
            )
            nodes[nodes.index(previous_relation)] = merged
            relation_by_key[relation_key] = merged
            continue
        node_id = stable_id(
            "relation",
            {
                "relation_id": relation.relation_id,
                "endpoints": endpoint_ids,
                "evidence": [item.span_id for item in evidence],
                "rendering": rendering,
            },
        )
        nodes.append(
            RelationNode(
                node_id=node_id,
                source_id=source.source_id,
                relation_id=relation.relation_id,
                represented_relation_ids=[],
                relation_type=relation.relation_type,
                endpoint_node_ids=endpoint_ids,
                evidence_spans=evidence,
                compact_rendering=rendering,
                exactness=relation.exactness,
                mandatory=not (
                    (source.kind == "log" and relation.relation_type == "relation.event_timestamp")
                    or (source.kind == "json" and relation.relation_type == "relation.event_trace")
                    or (
                        source.kind == "python"
                        and relation.relation_type
                        in {"relation.definition_use", "relation.caller_callee"}
                    )
                ),
                token_cost=tokenizer.count(rendering),
            )
        )
        relation_by_key[relation_key] = nodes[-1]
        for endpoint in endpoint_ids:
            for item in nodes:
                if getattr(item, "node_id", None) != endpoint or not isinstance(
                    item, (ExactSpanNode, FactNode)
                ):
                    continue
                item_index = nodes.index(item)
                nodes[item_index] = item.model_copy(
                    update={"relation_ids": [*item.relation_ids, relation.relation_id]}
                )

    for relation_node in [item for item in nodes if isinstance(item, RelationNode)]:
        relation_ids = [relation_node.relation_id, *relation_node.represented_relation_ids]
        for endpoint in relation_node.endpoint_node_ids:
            for item in nodes:
                if getattr(item, "node_id", None) != endpoint or not isinstance(
                    item, (ExactSpanNode, FactNode)
                ):
                    continue
                index = nodes.index(item)
                nodes[index] = item.model_copy(
                    update={"relation_ids": sorted(set([*item.relation_ids, *relation_ids]))}
                )
    nodes.sort(key=lambda item: (getattr(item, "source_order", 0), item.node_id))
    return ContextIR(
        source_ids=[source.source_id],
        source_kind=extraction.content_type,
        source_hash=sha256_domain(HashDomain.SOURCE_ARTIFACT, source.raw_bytes),
        query_hash=hash_query(QueryEnvelope(query=query)),
        nodes=nodes,
        obligation_count=len(extraction.obligations),
        relation_count=len(extraction.relations),
        component_version=COMPONENT_VERSION,
    )


def node_source_spans(node: Any) -> list[SourceSpan]:
    if isinstance(node, ExactSpanNode):
        return node.original_spans
    if isinstance(node, FactNode):
        return node.source_spans
    if isinstance(node, RelationNode):
        return node.evidence_spans
    if isinstance(node, StructureNode):
        return node.source_spans
    if isinstance(node, AggregateNode):
        return [node.first_source_span, node.last_source_span]
    return []


def render_fact(node: FactNode) -> str:
    if node.fact_type == "code.definition":
        return f"- D={node.exact_value}"
    if node.fact_type == "code.exception_path":
        scope = f"@{node.scope}" if node.scope else ""
        return f"- P={node.exact_value}{scope}"
    if node.fact_type == "code.call":
        return f"- C={node.exact_value}"
    if node.fact_type == "code.branch_guard":
        scope = f"@{node.scope}" if node.scope else ""
        return f"- G={node.exact_value}{scope}"
    if node.fact_type == "code.import":
        return f"- I={node.exact_value}"
    parts = [f"{node.fact_type}={node.exact_value}"]
    if node.owner:
        parts.append(f"owner={node.owner}")
    if node.unit:
        parts.append(f"unit={node.unit}")
    if node.scope:
        parts.append(f"scope={node.scope}")
    if node.polarity:
        parts.append(f"polarity={node.polarity}")
    if node.temporal_qualifier:
        parts.append(f"time={node.temporal_qualifier}")
    prefix = "@row\t" if node.fact_type == "structured.anomalous_row" else ""
    return "- " + prefix + " ".join(parts)


def render_node(node: Any) -> str:
    if isinstance(node, FactNode):
        return render_fact(node)
    if isinstance(node, RelationNode):
        return f"- {node.compact_rendering}"
    if isinstance(node, ExactSpanNode):
        return node.exact_text
    if isinstance(node, StructureNode):
        return node.structure_type
    if isinstance(node, AggregateNode):
        return f"- {node.aggregation_rule} count={node.exact_count}"
    if isinstance(node, OmissionNode):
        return f"- omitted={len(node.omitted_span_ids)} reason={node.reason}"
    raise TypeError(f"unsupported ContextIR node: {type(node).__name__}")


__all__ = [
    "COMPONENT_VERSION",
    "build_context_ir",
    "node_source_spans",
    "render_fact",
    "render_node",
    "stable_id",
]
