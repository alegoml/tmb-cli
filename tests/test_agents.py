import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tmb_cli import cli
from tmb_cli.cli import app
from tmb_cli.errors import AuthFailed

ROOT = Path(__file__).parents[1]
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TMB_CLI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("TMB_APP_ID", raising=False)
    monkeypatch.delenv("TMB_APP_KEY", raising=False)
    return tmp_path


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("TMB_APP_ID", "test-id")
    monkeypatch.setenv("TMB_APP_KEY", "test-secret-key")


def test_skills_get_prints_the_packaged_guide():
    result = runner.invoke(app, ["skills", "get"])
    assert result.exit_code == 0
    assert result.stdout.startswith("---\nname: tmb\n")
    assert "tmb --no-input next casa" in result.stdout


def test_the_repo_root_skill_is_the_packaged_one():
    packaged = (ROOT / "src" / "tmb_cli" / "SKILL.md").read_text()
    assert (ROOT / "SKILL.md").read_text() == packaged, "copy src/tmb_cli/SKILL.md to the root"


def _doctor() -> tuple[int, dict]:
    result = runner.invoke(app, ["doctor"])
    assert "test-secret-key" not in result.output
    return result.exit_code, json.loads(result.stdout)


def _checks(out: dict) -> dict:
    return {c["name"]: c for c in out["checks"]}


def test_doctor_without_credentials_exits_3_and_skips_the_api():
    code, out = _doctor()
    assert code == 3
    assert out["ok"] is False
    checks = _checks(out)
    assert checks["credentials"]["code"] == "missing_credentials"
    assert checks["api"]["ok"] is False
    assert checks["cache"]["ok"] is True


def test_doctor_all_good(credentials, monkeypatch):
    payload = json.loads((ROOT / "tests" / "fixtures" / "bus_stop.json").read_text())
    monkeypatch.setattr(cli.TmbClient, "bus_arrivals", lambda self, code: payload)
    code, out = _doctor()
    assert code == 0
    assert out["ok"] is True
    assert _checks(out)["credentials"]["detail"] == "from TMB_APP_ID/TMB_APP_KEY"


def test_doctor_reports_rejected_keys(credentials, monkeypatch):
    def reject(self, code):
        raise AuthFailed("TMB API rejected the credentials (HTTP 401).")

    monkeypatch.setattr(cli.TmbClient, "bus_arrivals", reject)
    code, out = _doctor()
    assert code == 3
    assert _checks(out)["api"]["code"] == "auth_failed"


def test_doctor_reports_a_broken_favourites_file(credentials, monkeypatch, isolated_dirs):
    payload = json.loads((ROOT / "tests" / "fixtures" / "bus_stop.json").read_text())
    monkeypatch.setattr(cli.TmbClient, "bus_arrivals", lambda self, code: payload)
    (isolated_dirs / "config").mkdir()
    (isolated_dirs / "config" / "favourites.json").write_text("[")
    code, out = _doctor()
    assert code == 2
    assert _checks(out)["favourites"]["code"] == "usage"
