import json
from pathlib import Path
from typing import Any

import typer

from tracefold import __version__
from tracefold.schemas.certificate import PreservationCertificate
from tracefold.schemas.source_map import SourceMap
from tracefold.serialization import canonical_json_bytes

app = typer.Typer(add_completion=False, no_args_is_help=True)
schema_app = typer.Typer()
app.add_typer(schema_app, name="schema")


@app.command()
def version() -> None:
    typer.echo(__version__)


def _check_schema(name: str, model: Any, fixture: str) -> None:
    root = Path(__file__).resolve().parents[2]
    fixture_path = root / "tests" / "fixtures" / "canonical" / fixture
    exported = root / "schemas" / "v1" / name
    value = json.loads(fixture_path.read_text(encoding="utf-8"))
    model.model_validate(value)
    schema = model.model_json_schema()
    if canonical_json_bytes(schema) != exported.read_bytes():
        raise typer.BadParameter(f"schema drift: {name}")
    typer.echo("ok")


@schema_app.command("certificate")
def certificate_schema(check: bool = typer.Option(False, "--check")) -> None:
    if check:
        _check_schema(
            "preservation-certificate.schema.json",
            PreservationCertificate,
            "certificate-synthetic.json",
        )


@schema_app.command("source-map")
def source_map_schema(check: bool = typer.Option(False, "--check")) -> None:
    if check:
        _check_schema("source-map.schema.json", SourceMap, "source-map-synthetic.json")


@app.command()
def compress() -> None:
    typer.echo("PHASE_1_NOT_IMPLEMENTED", err=True)
    raise typer.Exit(code=3)


@app.command()
def serve() -> None:
    typer.echo("Import tracefold.api:app and run with an ASGI server.")
