from tracefold.extractors import extract_dialogue, extract_obligations
from tracefold.schemas.phase2 import (
    ContentType,
    DialogueMessage,
    ExtractionConfidence,
    SourceArtifact,
)
from tracefold.schemas.source import SourceInput
from tracefold.sources import ingest_source


def source(text: str, *, authority: str = "user", role: str | None = None) -> SourceArtifact:
    return ingest_source(
        SourceInput(
            input_ordinal=0,
            kind="text",
            authority=authority,
            media_type="text/plain",
            text=text,
            role=role,
        )
    )


def test_document_obligations_and_relations_are_source_exact() -> None:
    text = (
        "System: Return exact values.\nLimit: 15 ms for API.\n"
        "If enabled, use it except maintenance."
    )
    result = extract_obligations(source(text, authority="system"))
    classes = {item.class_name for item in result.obligations}
    assert result.content_type == ContentType.DOCUMENT
    assert result.coverage.value == "partial"
    assert {"instruction.system_developer", "role.boundary", "numeric.number"}.issubset(classes)
    assert {"numeric.unit", "logic.condition", "logic.exception"}.issubset(classes)
    assert "relation.value_unit_owner" in {item.relation_type for item in result.relations}
    assert "relation.condition_consequence" in {item.relation_type for item in result.relations}
    assert "relation.rule_exception" in {item.relation_type for item in result.relations}
    for obligation in result.obligations:
        for span_id in obligation.source_span_ids:
            span = next(span for span in result.spans if span.span_id == span_id)
            assert (
                source(text).raw_bytes[span.byte_start : span.byte_end]
                == text[span.char_start : span.char_end].encode()
            )


def test_document_correction_keeps_old_and_new_statements() -> None:
    result = extract_obligations(source("Use port 80. Correction: use port 8080."))
    corrections = [item for item in result.obligations if item.class_name == "temporal.correction"]
    assert len(corrections) >= 2
    relation = next(
        item for item in result.relations if item.relation_type == "relation.statement_correction"
    )
    assert relation.exactness.value == "inferred"
    assert relation.discovery_status.value == "partial"


def test_dialogue_preserves_roles_message_ids_and_commitment() -> None:
    result = extract_dialogue(
        [
            DialogueMessage(message_id="m1", role="user", ordinal=0, text="Use port 80."),
            DialogueMessage(
                message_id="m2",
                role="user",
                ordinal=1,
                text="Correction: use port 8080. I will deploy it.",
            ),
        ]
    )
    assert result.content_type == ContentType.DIALOGUE
    assert {source.message_id for source in result.sources} == {"m1", "m2"}
    assert any(item.class_name == "dialogue.commitment" for item in result.obligations)
    assert any(item.relation_type == "relation.statement_correction" for item in result.relations)
    assert all(
        span.conversation_message_id in {"m1", "m2"}
        for span in result.spans
        if span.conversation_message_id is not None
    )


def test_dialogue_missing_message_id_uses_source_map_id_format() -> None:
    result = extract_dialogue(
        [DialogueMessage(message_id=None, role="user", ordinal=3, text="Keep this.")]
    )
    assert result.sources[0].message_id == "msg:3:user:7d1369f8c9015818"


def test_general_named_entity_signal_is_not_complete() -> None:
    result = extract_obligations(source("Alice sent an update to Bob."))
    entities = [item for item in result.obligations if item.class_name == "entity.named"]
    assert entities
    assert all(item.confidence == ExtractionConfidence.INFERRED for item in entities)
    assert result.coverage.value != "known"


def test_cross_format_lexical_classes_cover_numeric_logic_and_time() -> None:
    result = extract_obligations(
        source(
            "Release v1.2.3 on 2026-08-01 at 12:30 costs $4.50 or 5%. "
            "It is not allowed: all users must not bypass it."
        )
    )
    classes = {item.class_name for item in result.obligations}
    assert {
        "identifier.version",
        "temporal.date",
        "temporal.timestamp",
        "numeric.currency",
        "numeric.percentage",
        "logic.negation",
        "logic.quantifier",
        "policy.permission",
        "policy.prohibition",
    }.issubset(classes)
