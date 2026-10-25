"""Read-only checks against the real TMB API, with your own credentials.

Skipped unless TMB_LIVE=1. Pick the stop and station with TMB_LIVE_STOP and TMB_LIVE_STATION:

    TMB_LIVE=1 TMB_LIVE_STOP=1103 TMB_LIVE_STATION=126 uv run pytest -m live
"""

import json
import os

import pytest
from typer.testing import CliRunner

from tmb_cli.cli import app

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("TMB_LIVE") != "1", reason="set TMB_LIVE=1 to hit the API"),
]


def _run(*args: str) -> object:
    result = CliRunner().invoke(app, ["--no-input", *args])
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"set {name}")
    return value


def test_bus_arrivals():
    assert isinstance(_run("bus", _env("TMB_LIVE_STOP")), dict)


def test_metro_arrivals():
    assert isinstance(_run("metro", _env("TMB_LIVE_STATION")), dict)
