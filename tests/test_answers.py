import json
from pathlib import Path

import pytest
from test_network import FakeClient
from typer.testing import CliRunner

from tmb_cli import cli
from tmb_cli.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()
HOME = "41.0000,2.0000"  # the made-up origin of the fixtures' geography


class FakeTmb(FakeClient):
    """Static network and real time, all from synthetic fixtures."""

    asked: list = []

    def bus_arrivals(self, code):
        FakeTmb.asked.append(("bus", code))
        return json.loads((FIXTURES / "bus_stop.json").read_text())

    def metro_arrivals(self, codes):
        FakeTmb.asked.append(("metro", tuple(codes)))
        return json.loads((FIXTURES / "metro_stations.json").read_text())


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(cli, "_client", FakeTmb)
    FakeTmb.asked = []


def ok(*args: str) -> dict:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_next_place_merges_all_its_stops_with_their_own_walks():
    ok("place", "add", "casa", HOME)
    ok("place", "walk", "casa", "100001", "1")
    out = ok("next", "casa")
    assert out["resolved"]["kind"] == "place"
    assert [s["codes"] for s in out["stops"]] == [["4"], ["801", "901"], ["1"], ["100001"]]
    etas = [a["eta"] for a in out["arrivals"]]
    assert etas == sorted(etas)
    amb = [a for a in out["arrivals"] if a["operator"] == "Operador de prova"]
    assert [(a["line"], a["walk_minutes"], a["leave_in"]) for a in amb] == [
        ("Y7", 1, 1),
        ("Y7", 1, 5),
    ]
    assert out["source"] == "TMB+AMB"
    assert out["say"].startswith("Sal ")


def test_next_line_looks_in_the_users_stops():
    ok("place", "add", "casa", HOME)
    out = ok("next", "y7")
    assert out["resolved"] == {"kind": "line", "name": "Y7", "lat": None, "lon": None}
    assert {a["line"] for a in out["arrivals"]} == {"Y7"}
    metro = ok("next", "X9")
    assert {(a["line"], a["type"]) for a in metro["arrivals"]} == {("X9", "metro")}


def test_a_number_is_a_stop_until_the_user_has_stops():
    out = ok("next", "67")
    assert out["resolved"]["kind"] == "stop"
    assert FakeTmb.asked == [("bus", "67")]


def test_next_point_uses_the_closest_stops_and_estimated_walks():
    out = ok("next", HOME)
    assert out["resolved"]["kind"] == "point"
    assert [(s["codes"], s["walk_minutes"]) for s in out["stops"]][:2] == [
        (["4"], 2),
        (["801", "901"], 2),
    ]


def test_next_words_search_stops_and_stations():
    out = ok("next", "prova")
    assert out["resolved"]["kind"] == "station"
    assert out["stops"][0]["codes"] == ["801", "901"]
    assert FakeTmb.asked == [("metro", ("801", "901"))]


@pytest.mark.parametrize("where", [[HOME], ["prova"], ["casa"]])
def test_near_point_name_or_place(where):
    ok("place", "add", "casa", HOME)
    out = ok("near", *where, "--limit", "2")
    assert out["near"]["lat"] is not None
    assert len(out["stops"]) == 2
    first = out["stops"][0]
    assert first["walk_minutes"] >= 1 and first["distance_m"] is not None
    assert all(a["leave_in"] is not None for s in out["stops"] for a in s["arrivals"])
    assert out["say"].startswith("Cerca: ")


def test_near_a_line_is_a_usage_error():
    ok("place", "add", "casa", HOME)
    result = runner.invoke(app, ["near", "y7"])
    assert result.exit_code == 2
