from tracefold.extractors import extract_obligations
from tracefold.schemas.common import DiscoveryStatus
from tracefold.schemas.phase2 import CoverageState, SourceArtifact
from tracefold.schemas.source import SourceInput
from tracefold.sources import ingest_source


def json_source(text: str) -> SourceArtifact:
    return ingest_source(
        SourceInput(
            input_ordinal=0,
            kind="json",
            authority="tool",
            media_type="application/json",
            text=text,
        )
    )


def test_json_paths_arrays_nulls_anomalies_and_exact_offsets() -> None:
    text = (
        '{"records":[{"id":"ok","value":15,"unit":"ms","owner":"api","status":"ok"},'
        '{"id":"bad","value":20,"unit":"ms","owner":"api","status":"error",'
        '"trace_id":"t-1","optional":null}]}'
    )
    result = extract_obligations(json_source(text))
    assert result.coverage == CoverageState.KNOWN
    paths = {
        item.metadata.get("json_path")
        for item in result.obligations
        if item.class_name == "structured.json_schema_path"
    }
    assert "/records/0/value" in paths
    assert "/records/1/trace_id" in paths
    assert any(item.class_name == "structured.anomalous_row" for item in result.obligations)
    assert all(
        item.discovery_status == DiscoveryStatus.PARTIAL
        for item in result.obligations
        if item.class_name == "structured.anomalous_row"
    )
    null_item = next(
        item
        for item in result.obligations
        if item.class_name == "structured.json_schema_path"
        and item.metadata.get("json_path") == "/records/1/optional"
    )
    null_span = next(span for span in result.spans if span.span_id == null_item.source_span_ids[0])
    assert text[null_span.char_start : null_span.char_end] == "null"
    assert json_source(text).raw_bytes[null_span.byte_start : null_span.byte_end] == b"null"
    assert "relation.value_unit_owner" in {item.relation_type for item in result.relations}
    assert "relation.event_trace" in {item.relation_type for item in result.relations}


def test_json_escaped_unicode_and_array_indices_keep_raw_coordinates() -> None:
    text = '{"name":"\\u00e9","items":[true,false]}'
    result = extract_obligations(json_source(text))
    item = next(
        item
        for item in result.obligations
        if item.metadata.get("json_path") == "/name"
        and item.class_name == "structured.json_schema_path"
    )
    span = next(span for span in result.spans if span.span_id == item.source_span_ids[0])
    assert text[span.char_start : span.char_end] == '"\\u00e9"'
    assert span.byte_end - span.byte_start == len(b'"\\u00e9"')
    assert any(item.metadata.get("json_path") == "/items/1" for item in result.obligations)


def test_json_bom_is_parsed_with_raw_offsets() -> None:
    text = '\ufeff{"value": 15}'
    result = extract_obligations(json_source(text))
    assert result.coverage == CoverageState.KNOWN
    item = next(
        item
        for item in result.obligations
        if item.metadata.get("json_path") == "/value" and item.class_name == "numeric.number"
    )
    span = next(span for span in result.spans if span.span_id == item.source_span_ids[0])
    assert text[span.char_start : span.char_end] == "15"


def test_invalid_json_and_duplicate_keys_are_typed_failures() -> None:
    for text in ('{"x": 1, "x": 2}', '{"x":'):
        result = extract_obligations(json_source(text))
        assert result.coverage == CoverageState.FAILED
        assert result.failure is not None
        assert result.failure.code == "INVALID_JSON"
        assert result.obligations == []
