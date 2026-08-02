import json
from pathlib import Path
from typing import Any

import typer

from tracefold import __version__
from tracefold.benchmark import (
    DEFAULT_METHOD_IDS,
    PRIMARY_METHOD_IDS,
    _manifest,
    _request_for,
    prepare_artifacts,
    run_benchmark,
)
from tracefold.phase7_report import build_report
from tracefold.schemas.certificate import PreservationCertificate
from tracefold.schemas.phase7 import BenchmarkRunMode, PreparedContext, TargetMode
from tracefold.schemas.source_map import SourceMap
from tracefold.serialization import canonical_json_bytes
from tracefold.target import TargetAdapter, load_replay_records, replay_record_from_response

app = typer.Typer(add_completion=False, no_args_is_help=True)
schema_app = typer.Typer()
benchmark_app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(schema_app, name="schema")
app.add_typer(benchmark_app, name="benchmark")


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


def _artifact_dir() -> Path:
    return Path("reports/final")


def _ensure_prepared() -> tuple[list[Any], list[PreparedContext]]:
    directory = _artifact_dir()
    if not (directory / "prepared-contexts.jsonl").exists():
        prepare_artifacts(directory)
    items = [
        __import__(
            "tracefold.schemas.phase7", fromlist=["BenchmarkItem"]
        ).BenchmarkItem.model_validate(json.loads(line))
        for line in (directory / "benchmark-items.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    prepared = [
        PreparedContext.model_validate(json.loads(line))
        for line in (directory / "prepared-contexts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return items, prepared


def _selected_prepared(
    prepared: list[PreparedContext],
    method_ids: tuple[str, ...],
    item_ids: set[str] | None = None,
) -> list[PreparedContext]:
    return [
        item
        for item in prepared
        if item.method_id in method_ids and (item_ids is None or item.item_id in item_ids)
    ]


def _live_allowed(confirm_live: bool) -> bool:
    return confirm_live or __import__("os").getenv("TRACEFOLD_ALLOW_LIVE_BENCHMARK") == "1"


def _run_live(
    mode: BenchmarkRunMode,
    *,
    confirm_live: bool,
    item_limit: int | None,
    method_list: str | None,
) -> None:
    if not _live_allowed(confirm_live):
        raise typer.BadParameter(
            "live benchmark requires --confirm-live or TRACEFOLD_ALLOW_LIVE_BENCHMARK=1"
        )
    items, prepared = _ensure_prepared()
    if item_limit is not None:
        if item_limit < 1:
            raise typer.BadParameter("--items must be positive")
        items = items[:item_limit]
    methods = (
        tuple(item.strip() for item in method_list.split(","))
        if method_list
        else (
            ("full_context", "head_tail", "lexical_top_k", "cprgc_target")
            if mode == BenchmarkRunMode.SMOKE_LIVE
            else PRIMARY_METHOD_IDS
        )
    )
    prepared = _selected_prepared(prepared, methods, {item.item_id for item in items})
    expected = len(items) * len(methods)
    model = __import__("os").getenv("TRACEFOLD_TARGET_MODEL", "unconfigured")
    typer.echo(
        f"mode={mode.value} model={model} items={len(items)} "
        f"methods={len(methods)} requests={expected}"
    )
    adapter = TargetAdapter.from_environment(mode=TargetMode.LIVE, allow_live=True)
    scores = run_benchmark(items, prepared, adapter)
    directory = _artifact_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "scored-results.jsonl").write_text(
        "".join(
            canonical_json_bytes(item.model_dump(mode="json")).decode("utf-8") + "\n"
            for item in scores
        ),
        encoding="utf-8",
    )
    request_by_key = {
        (item.item_id, item.method_id): _request_for(item, prepared_item, adapter.settings)
        for prepared_item in prepared
        for item in items
        if item.item_id == prepared_item.item_id
    }
    replay = [
        replay_record_from_response(
            request_by_key[(score.item_id, score.method_id)], score.target_response
        )
        for score in scores
        if score.target_response.status.value != "unavailable"
    ]
    (directory / "responses-sanitized.jsonl").write_text(
        "".join(
            canonical_json_bytes(item.model_dump(mode="json")).decode("utf-8") + "\n"
            for item in replay
        ),
        encoding="utf-8",
    )
    manifest = _manifest(mode=mode, item_count=len(items), method_ids=methods, model_id=model)
    (directory / "run-manifest.json").write_bytes(
        canonical_json_bytes(manifest.model_dump(mode="json")) + b"\n"
    )
    build_report(directory)


@benchmark_app.command("prepare")
def benchmark_prepare() -> None:
    result = prepare_artifacts(_artifact_dir())
    typer.echo(
        f"mode=prepare items={len(result['items'])} methods={len(DEFAULT_METHOD_IDS)} "
        f"requests={len(result['items']) * len(DEFAULT_METHOD_IDS)}"
    )


@benchmark_app.command("smoke-live")
def benchmark_smoke_live(
    confirm_live: bool = typer.Option(False, "--confirm-live"),
    items: int | None = typer.Option(10, "--items"),
    methods: str | None = typer.Option(None, "--methods"),
) -> None:
    _run_live(
        BenchmarkRunMode.SMOKE_LIVE,
        confirm_live=confirm_live,
        item_limit=items,
        method_list=methods,
    )


@benchmark_app.command("full-live")
def benchmark_full_live(
    confirm_live: bool = typer.Option(False, "--confirm-live"),
    items: int | None = typer.Option(None, "--items"),
    methods: str | None = typer.Option(None, "--methods"),
) -> None:
    _run_live(
        BenchmarkRunMode.FULL_LIVE, confirm_live=confirm_live, item_limit=items, method_list=methods
    )


@benchmark_app.command("replay")
def benchmark_replay(
    replay_path: Path = Path("reports/final/responses-sanitized.jsonl"),
) -> None:
    items, prepared = _ensure_prepared()
    records = load_replay_records(replay_path)
    adapter = TargetAdapter.from_environment(mode=TargetMode.REPLAY, replay_records=records)
    scores = run_benchmark(items, prepared, adapter)
    directory = _artifact_dir()
    (directory / "scored-results.jsonl").write_text(
        "".join(
            canonical_json_bytes(item.model_dump(mode="json")).decode("utf-8") + "\n"
            for item in scores
        ),
        encoding="utf-8",
    )
    build_report(directory)
    typer.echo(f"mode=replay items={len(items)} records={len(records)}")


@benchmark_app.command("report")
def benchmark_report() -> None:
    payload = build_report(_artifact_dir())
    typer.echo(canonical_json_bytes(payload).decode("utf-8"))
