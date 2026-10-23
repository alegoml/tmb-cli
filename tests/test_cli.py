import json
import stat

import pytest
from typer.testing import CliRunner

from tmb_cli import __version__
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
    result = runner.invoke(app, ["bus", "108"])
    assert result.exit_code == 3
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "missing_credentials"
    assert "tmb auth set" in error["hint"]


def test_auth_status_when_not_configured():
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["configured"] is False


def test_auth_set_saves_owner_only_file_and_status_masks_id(isolated_config):
    result = runner.invoke(app, ["auth", "set"], input="my-app-id\nmy-secret-key\n")
    assert result.exit_code == 0

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
