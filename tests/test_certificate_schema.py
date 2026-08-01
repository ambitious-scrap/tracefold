import json
from pathlib import Path

from tracefold.schemas.certificate import PreservationCertificate
from tracefold.serialization import canonical_json_bytes


def test_synthetic_certificate_valid(fixture_root: Path) -> None:
    data = json.loads((fixture_root / "certificate-synthetic.json").read_text())
    PreservationCertificate.model_validate(data)


def test_certificate_schema_export_has_no_drift(tmp_path: Path) -> None:
    generated = tmp_path / "preservation-certificate.schema.json"
    generated.write_bytes(canonical_json_bytes(PreservationCertificate.model_json_schema()))
    committed = Path("schemas/v1/preservation-certificate.schema.json")
    assert generated.read_bytes() == committed.read_bytes()
