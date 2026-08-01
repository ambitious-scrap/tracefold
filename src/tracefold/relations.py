import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from tracefold.schemas.common import DiscoveryStatus
from tracefold.schemas.phase2 import Obligation, Relation, RelationExactness
from tracefold.serialization import canonical_json_bytes


def relation_id(
    relation_type: str,
    obligation_ids: list[str],
    evidence_span_ids: list[str],
    source_ids: list[str],
) -> str:
    payload = {
        "relation_type": relation_type,
        "obligation_ids": obligation_ids,
        "evidence_span_ids": evidence_span_ids,
        "source_ids": source_ids,
    }
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()[:16]
    return f"rel:{relation_type}:{digest}"


def make_relation(
    *,
    relation_type: str,
    obligations: Iterable[Obligation],
    evidence_span_ids: list[str],
    extraction_method: str,
    discovery_status: DiscoveryStatus,
    exactness: RelationExactness,
    metadata: Mapping[str, Any] | None = None,
) -> Relation:
    endpoints = list(obligations)
    obligation_ids = [item.obligation_id for item in endpoints]
    source_ids = list(dict.fromkeys(item.source_id for item in endpoints))
    return Relation(
        relation_id=relation_id(relation_type, obligation_ids, evidence_span_ids, source_ids),
        relation_type=relation_type,
        obligation_ids=obligation_ids,
        evidence_span_ids=evidence_span_ids,
        source_ids=source_ids,
        extraction_method=extraction_method,
        discovery_status=discovery_status,
        exactness=exactness,
        metadata=dict(metadata or {}),
    )


def validate_relations(
    relations: Iterable[Relation],
    obligations: Iterable[Obligation],
    span_ids: set[str],
) -> None:
    obligation_ids = {item.obligation_id for item in obligations}
    relation_ids: set[str] = set()
    for relation in relations:
        if relation.relation_id in relation_ids:
            raise ValueError("duplicate relation ID")
        relation_ids.add(relation.relation_id)
        if not set(relation.obligation_ids).issubset(obligation_ids):
            raise ValueError("relation references missing obligation")
        if not set(relation.evidence_span_ids).issubset(span_ids):
            raise ValueError("relation references missing evidence span")


__all__ = ["make_relation", "relation_id", "validate_relations"]
