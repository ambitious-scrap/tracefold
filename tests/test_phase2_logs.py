from pathlib import Path

from tracefold.extractors import extract_obligations
from tracefold.schemas.phase2 import ContentType, SourceArtifact
from tracefold.schemas.source import SourceInput
from tracefold.sources import ingest_source


def log_source(text: str) -> SourceArtifact:
    return ingest_source(
        SourceInput(
            input_ordinal=0,
            kind="log",
            authority="tool",
            media_type="text/plain",
            text=text,
        )
    )


def test_logs_extract_timestamp_trace_transition_and_explicit_cause(
    fixture_root: Path,
) -> None:
    text = (fixture_root.parent / "phase2" / "events.log").read_text()
    result = extract_obligations(log_source(text))
    assert result.content_type == ContentType.LOG
    assert sum(item.class_name == "temporal.timestamp" for item in result.obligations) == 3
    assert any(
        item.class_name == "log.severity_change"
        and isinstance(item.value, dict)
        and item.value.get("from") == "info"
        and item.value.get("to") == "error"
        for item in result.obligations
    )
    assert any(
        item.relation_type == "relation.error_causal_predecessor"
        and item.exactness.value == "exact"
        for item in result.relations
    )
    assert sum(item.relation_type == "relation.event_trace" for item in result.relations) >= 2
    event_spans = [span for span in result.spans if span.kind == "log_event"]
    assert len(event_spans) == 3
    assert text[event_spans[0].char_start : event_spans[0].char_end].startswith("2026-08-01")


def test_unrelated_trace_events_do_not_create_causal_relation() -> None:
    text = (
        "2026-08-01T00:00:00Z INFO trace=t-a event_id=a\n"
        "2026-08-01T00:00:01Z ERROR trace=t-b event_id=b error_code=E1\n"
    )
    result = extract_obligations(log_source(text))
    assert not any(
        item.relation_type == "relation.error_causal_predecessor" for item in result.relations
    )
