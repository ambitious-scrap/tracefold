import json
from pathlib import Path

from tracefold.schemas.source_map import SourceMap
from tracefold.serialization import canonical_json_bytes


def test_synthetic_source_map_valid(fixture_root: Path) -> None:
    data = json.loads((fixture_root / "source-map-synthetic.json").read_text())
    SourceMap.model_validate(data)


def test_source_map_schema_export_has_no_drift(tmp_path: Path) -> None:
    generated = tmp_path / "source-map.schema.json"
    generated.write_bytes(canonical_json_bytes(SourceMap.model_json_schema()))
    committed = Path("schemas/v1/source-map.schema.json")
    assert generated.read_bytes() == committed.read_bytes()
