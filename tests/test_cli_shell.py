from typer.testing import CliRunner

from tracefold.cli import app


def test_cli_help_and_version() -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["--help"]).exit_code == 0
    assert runner.invoke(app, ["version"]).output.strip() == "0.1.0"


def test_compress_refuses_future_behavior() -> None:
    result = CliRunner().invoke(app, ["compress"])
    assert result.exit_code == 3
    assert "PHASE_1_NOT_IMPLEMENTED" in result.output
