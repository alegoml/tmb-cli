import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tmb_cli import cli
from tmb_cli.cli import app
from tmb_cli.errors import NetworkError

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()
T = 1767225600000  # the fixture's TMB timestamp


def bus_in(*minutes: float) -> dict:
    """A stop where line X1 comes in each of `minutes` (and nothing else)."""
    payload = json.loads((FIXTURES / "bus_stop.json").read_text())
    route = payload["parades"][0]["linies_trajectes"][0]
    route["propers_busos"] = [{"temps_arribada": int(T + m * 60_000)} for m in minutes]
    payload["parades"][0]["linies_trajectes"] = [route]
    return payload


@pytest.fixture
def polls(tmp_path, monkeypatch):
    """Serve one payload per check and a fake clock that advances with each sleep."""
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TMB_APP_ID", "test-id")
    monkeypatch.setenv("TMB_APP_KEY", "test-secret-key")
    clock = {"now": 0.0}
    queue: list = []

    def serve(self, code):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(cli.TmbClient, "bus_arrivals", serve)
    monkeypatch.setattr(cli, "_now", lambda: clock["now"])
    monkeypatch.setattr(cli, "_sleep", lambda s: clock.__setitem__("now", clock["now"] + s))
    return queue


def run(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, ["watch", *args])
    return result.exit_code, json.loads(result.stdout or result.stderr)


def test_minutes_fires_when_the_bus_is_close_enough(polls):
    polls += [bus_in(10), bus_in(7), bus_in(4.5)]
    code, out = run("0001", "--minutes", "5")
    assert code == 0, out
    assert out["event"] == "due"
    assert out["checked"] == 3
    assert out["arrival"]["minutes"] == 4
    assert out["say"] == "El X1 llega en 4 min a Parada de prova."


def test_leave_fires_when_its_time_to_set_off(polls):
    ok = runner.invoke(app, ["fav", "add", "casa", "0001", "--walk", "4"])
    assert ok.exit_code == 0
    # leave_in: 6, then 2, then 0 → go.
    polls += [bus_in(10), bus_in(6), bus_in(4.2)]
    code, out = run("casa", "--leave")
    assert (code, out["event"], out["checked"]) == (0, "leave_now", 3)
    assert out["arrival"]["leave_in"] == 0
    assert out["say"].startswith("¡Sal ya! El X1 de las 01:04 pasa por Parada de prova en 4 min")


def test_leave_skips_a_bus_already_missed(polls):
    polls += [bus_in(1, 5.5)]  # the 1-min one is gone with a 5-min walk; the next is 0 to leave
    code, out = run("0001", "--leave", "--walk", "5")
    assert out["event"] == "leave_now"
    assert out["arrival"]["minutes"] == 5


def test_timeout_ends_quietly(polls):
    polls += [bus_in(30)]
    code, out = run("0001", "--minutes", "5", "--timeout", "2", "--every", "30")
    assert (code, out["event"], out["arrival"]) == (0, "timeout", None)
    assert out["checked"] == 5  # at 0, 30, 60, 90 and 120 s: the last one at the deadline


def test_retryable_errors_are_ridden_out(polls):
    polls += [NetworkError("Could not reach the TMB API (ConnectError)."), bus_in(3)]
    code, out = run("0001", "--minutes", "5")
    assert (code, out["event"], out["checked"]) == (0, "due", 2)


@pytest.mark.parametrize(
    "args",
    [["0001"], ["0001", "--minutes", "5", "--leave"], ["0001", "--leave"]],
)
def test_usage_errors(polls, args):
    polls += [bus_in(3)]
    code, out = run(*args)
    assert (code, out["error"]["code"]) == (2, "usage")
