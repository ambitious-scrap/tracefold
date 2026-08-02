"""Deterministic CPRGC relation graph and protected closure."""

from __future__ import annotations

from collections import defaultdict

from tracefold.context_ir import node_source_spans, render_node, stable_id
from tracefold.hashing import sha256_domain
from tracefold.schemas.common import HashDomain
from tracefold.schemas.phase2 import ExtractionResult
from tracefold.schemas.phase6 import (
    ContextIR,
    ExactSpanNode,
    FactNode,
    GraphEdge,
    GraphEdgeType,
    ProtectedClosure,
    RelationGraph,
    RelationNode,
    StructureNode,
)
from tracefold.serialization import canonical_json_bytes
from tracefold.tokenizers.base import Tokenizer

COMPONENT_VERSION = "tracefold.cprgc-graph/1.0.0"


def _edge(
    edge_type: GraphEdgeType,
    from_node_id: str,
    to_node_id: str,
    source_id: str,
    relation_id: str | None = None,
) -> GraphEdge:
    payload = {
        "edge_type": edge_type.value,
        "from": from_node_id,
        "to": to_node_id,
        "source": source_id,
        "relation": relation_id,
    }
    return GraphEdge(
        edge_id=stable_id("edge", payload),
        edge_type=edge_type,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        source_ids=[source_id],
        relation_id=relation_id,
        explicit=True,
    )


def _span_node_id(span_id: str) -> str:
    return f"source-span:{span_id}"


def build_relation_graph(context_ir: ContextIR, extraction: ExtractionResult) -> RelationGraph:
    """Build graph edges from explicit obligations, relations, and structure."""

    nodes = {node.node_id: node for node in context_ir.nodes}
    obligation_to_node: dict[str, str] = {}
    for node in context_ir.nodes:
        for obligation_id in getattr(node, "obligation_ids", []):
            obligation_to_node[obligation_id] = node.node_id
    span_ids = {span.span_id for span in extraction.spans}
    graph_nodes = set(nodes)
    graph_nodes.update(_span_node_id(item) for item in span_ids)
    edges: list[GraphEdge] = []

    ordered_nodes = sorted(
        context_ir.nodes, key=lambda item: (getattr(item, "source_order", 0), item.node_id)
    )
    for left, right in zip(ordered_nodes, ordered_nodes[1:], strict=False):
        edges.append(
            _edge(
                GraphEdgeType.SOURCE_ORDER,
                left.node_id,
                right.node_id,
                extraction.sources[0].source_id,
            )
        )

    for node in context_ir.nodes:
        for span in node_source_spans(node):
            graph_nodes.add(_span_node_id(span.span_id))
        for obligation_id in getattr(node, "obligation_ids", []):
            span_ids_for_obligation = next(
                (
                    item.source_span_ids
                    for item in extraction.obligations
                    if item.obligation_id == obligation_id
                ),
                [],
            )
            for span_id in span_ids_for_obligation:
                graph_nodes.add(_span_node_id(span_id))
                edges.append(
                    _edge(
                        GraphEdgeType.OBLIGATION_EVIDENCE,
                        node.node_id,
                        _span_node_id(span_id),
                        extraction.sources[0].source_id,
                    )
                )
        if isinstance(node, StructureNode):
            for child in node.child_node_ids:
                if child in nodes:
                    edges.append(
                        _edge(
                            GraphEdgeType.STRUCTURAL_PARENT,
                            node.node_id,
                            child,
                            extraction.sources[0].source_id,
                        )
                    )

    relation_nodes = [node for node in context_ir.nodes if isinstance(node, RelationNode)]
    relation_by_id = {relation.relation_id: relation for relation in extraction.relations}
    edge_type_by_relation = {
        "relation.value_unit_owner": GraphEdgeType.OWNERSHIP,
        "relation.rule_exception": GraphEdgeType.EXCEPTION,
        "relation.condition_consequence": GraphEdgeType.CONDITION,
        "relation.statement_correction": GraphEdgeType.CORRECTION,
        "relation.instruction_scope": GraphEdgeType.SCOPE,
        "relation.definition_use": GraphEdgeType.DEFINITION_USE,
        "relation.caller_callee": GraphEdgeType.CALLER_CALLEE,
        "relation.import_symbol": GraphEdgeType.DEFINITION_USE,
        "relation.event_timestamp": GraphEdgeType.EVENT_TIME,
        "relation.event_trace": GraphEdgeType.EVENT_TRACE,
        "relation.error_causal_predecessor": GraphEdgeType.ERROR_PREDECESSOR,
    }
    for node in sorted(relation_nodes, key=lambda item: item.node_id):
        relation_id = node.relation_id
        relation = relation_by_id.get(relation_id)
        relation_edge_type = edge_type_by_relation.get(
            relation.relation_type if relation is not None else "", GraphEdgeType.RELATION_ENDPOINT
        )
        graph_nodes.add(node.node_id)
        for endpoint in node.endpoint_node_ids:
            edges.append(
                _edge(
                    GraphEdgeType.RELATION_ENDPOINT,
                    node.node_id,
                    endpoint,
                    extraction.sources[0].source_id,
                    relation_id,
                )
            )
        for span in node.evidence_spans:
            span_node = _span_node_id(span.span_id)
            graph_nodes.add(span_node)
            edges.append(
                _edge(
                    relation_edge_type,
                    node.node_id,
                    span_node,
                    extraction.sources[0].source_id,
                    relation_id,
                )
            )

    edges = sorted(
        {edge.edge_id: edge for edge in edges}.values(),
        key=lambda item: (item.edge_type.value, item.from_node_id, item.to_node_id, item.edge_id),
    )
    graph_payload = {
        "node_ids": sorted(graph_nodes),
        "edges": [item.model_dump(mode="json") for item in edges],
    }
    graph_hash = sha256_domain(HashDomain.CONTEXT_ARTIFACT, canonical_json_bytes(graph_payload))
    return RelationGraph(
        graph_hash=graph_hash,
        node_ids=sorted(graph_nodes),
        edges=edges,
        component_version=COMPONENT_VERSION,
    )


def compute_protected_closure(
    context_ir: ContextIR,
    graph: RelationGraph,
    extraction: ExtractionResult,
    tokenizer: Tokenizer,
) -> ProtectedClosure:
    """Compute smallest deterministic closure before optional ranking."""

    nodes = {node.node_id: node for node in context_ir.nodes}
    selected: set[str] = set()
    relation_ids: set[str] = set()
    reasons: defaultdict[str, list[str]] = defaultdict(list)
    hard_obligation_ids = {
        item.obligation_id
        for item in extraction.obligations
        if item.class_name
        in {
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
        and not (
            (
                item.class_name == "log.severity_change"
                and not ("from" in item.metadata and "to" in item.metadata)
            )
            or (
                item.class_name == "identifier.generic"
                and item.metadata.get("event_id")
                and item.metadata.get("field") not in {"error_code", "code"}
                and item.metadata.get("kind") != "exception"
            )
            or (
                item.class_name == "code.definition"
                and item.metadata.get("kind") in {"module", "use", "import_binding"}
            )
        )
    }
    for node in context_ir.nodes:
        node_obligations = set(getattr(node, "obligation_ids", []))
        if isinstance(node, ExactSpanNode) and node.protection == "hard":
            selected.add(node.node_id)
            reasons["hard_obligation"].extend(sorted(node_obligations))
        elif isinstance(node, FactNode) and node_obligations & hard_obligation_ids:
            selected.add(node.node_id)
            reasons["hard_obligation"].extend(sorted(node_obligations & hard_obligation_ids))
        if isinstance(node, RelationNode) and node.mandatory:
            selected.add(node.node_id)
            relation_ids.update([node.relation_id, *node.represented_relation_ids])
            reasons["relation"].extend([node.relation_id, *node.represented_relation_ids])

    # Include every endpoint of a protected relation. This is relation closure,
    # not a semantic guess: endpoints come directly from the frozen extractor.
    for node in context_ir.nodes:
        if isinstance(node, RelationNode) and node.node_id in selected:
            for endpoint in node.endpoint_node_ids:
                selected.add(endpoint)
                reasons["bridge"].append(endpoint)

    # Preserve structural boundary needed to interpret instructions, turns,
    # files, JSON paths, and code nodes.
    for node in context_ir.nodes:
        if isinstance(node, StructureNode) and node.source_kind in {
            context_ir.source_kind,
        }:
            selected.add(node.node_id)
            reasons["structure"].append(node.node_id)

    # Deduplicate reasons and compute token cost from rendered compact nodes.
    ordered = sorted(selected)
    cost = tokenizer.count("\n".join(render_node(nodes[item]) for item in ordered if item in nodes))
    return ProtectedClosure(
        node_ids=ordered,
        relation_ids=sorted(relation_ids),
        bridge_node_ids=sorted(set(reasons.get("bridge", []))),
        mandatory_token_cost=cost,
        reasons={key: sorted(set(value)) for key, value in sorted(reasons.items())},
    )


__all__ = ["COMPONENT_VERSION", "build_relation_graph", "compute_protected_closure"]
