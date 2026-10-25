import json
import stat

import pytest
from typer.testing import CliRunner

from tmb_cli import __version__, cli
from tmb_cli.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never touch the real ~/.config or real credentials in tests."""
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("TMB_APP_ID", raising=False)
    monkeypatch.delenv("TMB_APP_KEY", raising=False)
    return tmp_path


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_bus_without_credentials_fails_with_json_error():
    result = runner.invoke(app, ["bus", "0001"])
    assert result.exit_code == 3
    assert result.stdout == ""
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "missing_credentials"
    assert error["exit_code"] == 3
    assert error["retryable"] is False
    assert "tmb auth set" in error["hint"]


def test_unexpected_exception_is_reported_by_type_only(monkeypatch):
    monkeypatch.setenv("TMB_APP_ID", "env-id")
    monkeypatch.setenv("TMB_APP_KEY", "env-secret-key")

    def boom(self, stop_code):
        raise RuntimeError("GET https://api.tmb.cat/v1/x?app_key=env-secret-key")

    monkeypatch.setattr(cli.TmbClient, "bus_arrivals", boom)
    result = runner.invoke(app, ["bus", "0001"])

    assert result.exit_code == 1
    assert json.loads(result.stderr)["error"] == {
        "code": "internal",
        "message": "Unexpected internal error: RuntimeError.",
        "exit_code": 1,
        "retryable": False,
    }
    assert "env-secret-key" not in result.output


def test_auth_status_when_not_configured():
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["configured"] is False


def test_auth_set_saves_owner_only_file_and_status_masks_id(isolated_config):
    result = runner.invoke(app, ["auth", "set"], input="my-app-id\nmy-secret-key\n")
    assert result.exit_code == 0
    assert "app_id:" in result.stderr and "app_id:" not in result.stdout
    # CliRunner echoes the simulated typing to stdout (a real terminal doesn't): skip past it.
    assert json.loads(result.stdout[result.stdout.index("{") :])["saved"] is True
    assert "my-secret-key" not in result.output

    path = isolated_config / "credentials.json"
    assert json.loads(path.read_text()) == {"app_id": "my-app-id", "app_key": "my-secret-key"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    status = runner.invoke(app, ["auth", "status"])
    data = json.loads(status.stdout)
    assert data["configured"] is True
    assert data["source"] == "file"
    assert "my-secret-key" not in status.stdout
    assert "my-app-id" not in status.stdout


def test_env_credentials_win_over_file(monkeypatch):
    monkeypatch.setenv("TMB_APP_ID", "env-id")
    monkeypatch.setenv("TMB_APP_KEY", "env-key")
    result = runner.invoke(app, ["auth", "status"])
    assert json.loads(result.stdout)["source"] == "env"


def test_auth_set_with_no_input_is_a_usage_error(isolated_config):
    result = runner.invoke(app, ["--no-input", "auth", "set"], input="id\nkey\n")
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "usage"
    assert not (isolated_config / "credentials.json").exists()


def test_no_input_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("TMB_NO_INPUT", "1")
    result = runner.invoke(app, ["auth", "set"], input="id\nkey\n")
    assert result.exit_code == 2


def test_auth_set_cancelled_prompt_is_a_usage_error(isolated_config):
    result = runner.invoke(app, ["auth", "set"], input="")
    assert result.exit_code == 2
    error_line = result.stderr.splitlines()[-1]  # the prompt is on the line before
    assert json.loads(error_line)["error"]["message"] == "Input cancelled."
    assert not (isolated_config / "credentials.json").exists()


def test_corrupt_credentials_file_is_a_json_error(isolated_config):
    (isolated_config / "credentials.json").write_text('{"app_id": "x", "app_key": "leaky-key"')
    result = runner.invoke(app, ["bus", "0001"])
    assert result.exit_code == 3
    assert json.loads(result.stderr)["error"]["code"] == "missing_credentials"
    assert "leaky-key" not in result.output


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["bus", "1103", "--no-input"], ["--no-input", "bus", "1103"]),
        (["--no-input", "bus", "1103"], ["--no-input", "bus", "1103"]),
        (["fav", "add", "casa", "1", "--no-input", "--walk", "4"],
         ["--no-input", "fav", "add", "casa", "1", "--walk", "4"]),
        (["stops", "--", "--no-input"], ["stops", "--", "--no-input"]),
        (["bus", "1103"], ["bus", "1103"]),
    ],
)  # fmt: skip
def test_global_flags_work_anywhere(args, expected):
    assert cli.hoist_global_flags(args) == expected


def test_no_input_after_the_command_reaches_the_command(isolated_config):
    args = cli.hoist_global_flags(["auth", "set", "--no-input"])
    result = runner.invoke(app, args, input="id\nkey\n")
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "usage"
