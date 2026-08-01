from tracefold.extractors import extract_obligations
from tracefold.schemas.phase2 import CoverageState, SourceArtifact
from tracefold.schemas.source import SourceInput
from tracefold.sources import ingest_source


def python_source(text: str, path: str = "pkg/example.py") -> SourceArtifact:
    return ingest_source(
        SourceInput(
            input_ordinal=0,
            kind="python",
            authority="user",
            media_type="text/x-python",
            text=text,
            file_path=path,
        )
    )


def test_python_ast_obligations_relations_and_utf8_coordinates() -> None:
    text = (
        "import math as m\n\n"
        "LIMIT_MS = 15\n\n"
        "def run(value: int) -> int:\n"
        "    if value > LIMIT_MS:\n"
        "        return m.ceil(value)\n"
        "    raise ValueError('é')\n"
    )
    result = extract_obligations(python_source(text))
    classes = {item.class_name for item in result.obligations}
    assert result.coverage == CoverageState.PARTIAL
    assert {"code.import", "code.definition", "code.constant", "code.call"}.issubset(classes)
    assert {"code.branch_guard", "code.exception_path"}.issubset(classes)
    assert "relation.import_symbol" in {item.relation_type for item in result.relations}
    assert "relation.condition_consequence" in {item.relation_type for item in result.relations}
    assert "relation.caller_callee" in {item.relation_type for item in result.relations}
    for span in result.spans:
        if span.file_path is not None:
            assert span.file_path == "pkg/example.py"
        assert (
            text[span.char_start : span.char_end].encode()
            == python_source(text).raw_bytes[span.byte_start : span.byte_end]
        )


def test_python_same_names_have_distinct_symbol_ids_and_dynamic_calls_are_partial() -> None:
    text = (
        "def outer():\n    def same():\n        return 1\n    return same()\n\n"
        "def same():\n    return 2\n\nx = obj.method()\n"
    )
    result = extract_obligations(python_source(text))
    symbols = {
        item.metadata["symbol_id"]
        for item in result.obligations
        if item.class_name == "code.definition"
        and item.metadata.get("name") == "same"
        and item.metadata.get("kind") in {"function", "class"}
    }
    assert len(symbols) == 2
    assert any(
        item.relation_type == "relation.caller_callee" and item.exactness.value == "inferred"
        for item in result.relations
    )
    assert result.coverage == CoverageState.PARTIAL


def test_python_syntax_error_is_failed_without_coordinates() -> None:
    result = extract_obligations(python_source("def broken(:\n    pass\n"))
    assert result.coverage == CoverageState.FAILED
    assert result.failure is not None
    assert result.failure.code == "PYTHON_SYNTAX_ERROR"
    assert result.spans == []
