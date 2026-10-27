import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from test_network import FakeClient
from typer.testing import CliRunner

from tmb_cli import cli, routes
from tmb_cli.arrivals import MADRID
from tmb_cli.cli import app
from tmb_cli.errors import UsageError

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()
NOW = datetime(2026, 1, 1, 1, 0, tzinfo=MADRID)  # the fixture's T


class FakePlanner(FakeClient):
    asked: list = []
    payload: dict = {}

    def plan(self, origin, destination, when):
        FakePlanner.asked.append((origin, destination, when))
        return FakePlanner.payload


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(cli, "_client", FakePlanner)
    FakePlanner.asked = []
    FakePlanner.payload = json.loads((FIXTURES / "planner_plan.json").read_text())
    clock = {"now": NOW}
    monkeypatch.setattr(cli, "_clock", lambda: clock["now"])
    monkeypatch.setattr(
        cli, "_sleep", lambda s: clock.__setitem__("now", clock["now"] + timedelta(seconds=s))
    )


def run(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, list(args))
    return result.exit_code, json.loads(result.stdout or result.stderr)


def test_deadlines_and_planner_formats():
    assert routes.deadline("2:00", None, NOW) == datetime(2026, 1, 1, 2, 0, tzinfo=MADRID)
    assert routes.deadline("0:30", None, NOW).day == 2  # passed today: tomorrow
    assert routes.deadline("18h30", "2026-03-05", NOW).isoformat() == "2026-03-05T18:30:00+01:00"
    assert routes.deadline("9", None, NOW).hour == 9
    for bad in ("25:00", "9:75", "nine"):
        with pytest.raises(UsageError):
            routes.deadline(bad, None, NOW)
    assert routes.planner_params(datetime(2026, 1, 1, 18, 0, tzinfo=MADRID), True) == {
        "date": "01-01-2026",
        "time": "6:00pm",
        "arriveBy": "true",
    }
    assert (
        routes.planner_params(datetime(2026, 1, 1, 0, 5, tzinfo=MADRID), False)["time"] == "12:05am"
    )


def test_route_arriving_by_leaves_as_late_as_possible():
    code, out = run("route", "41.0,2.0", "41.02,2.0", "--by", "2:00")
    assert code == 0, out
    assert out["arrive_by"] == "2026-01-01T02:00:00+01:00"
    # The one arriving 02:06 is too late; the metro leaves later than walking.
    assert [o["leave_at"][11:16] for o in out["options"]] == ["01:40", "01:10"]
    best = out["options"][0]
    assert (best["leave_in"], best["minutes"], best["walk_minutes"], best["scheduled"]) == (
        40,
        19,
        9,
        True,
    )
    assert best["legs"][1] == {
        "mode": "metro",
        "line": "X9",
        "direction": "Destí de prova",
        "from": "Prova",
        "to": "Estació Inventada",
        "from_code": "901",
        "depart": "2026-01-01T01:45:00+01:00",
        "arrive": "2026-01-01T01:55:00+01:00",
        "minutes": 10,
    }
    assert best["legs"][2]["to"] == "tu destino"  # the planner's "Destination", for a bare point
    assert out["say"] == (
        "Sal a las 01:40 (en 40 min): 5 min andando hasta Prova, X9 dirección Destí de prova "
        "hasta Estació Inventada (10 min) y 4 min andando hasta tu destino. "
        "Llegas a las 01:59. Según horarios."
    )
    origin, destination, when = FakePlanner.asked[0]
    assert (origin, destination, when["arriveBy"], when["time"]) == (
        (41.0, 2.0),
        (41.02, 2.0),
        "true",
        "2:00am",
    )


def test_route_leaving_now_arrives_earliest_first():
    code, out = run("route", "41.0,2.0", "41.02,2.0")
    assert [o["arrive_at"][11:16] for o in out["options"]] == ["01:59", "02:00", "02:06"]
    assert out["depart_at"] == NOW.isoformat()


def test_route_from_a_place_to_a_named_station(monkeypatch):
    for name in ("bus_stops", "metro_lines", "metro_line_stations"):
        assert hasattr(FakePlanner, name)
    assert run("place", "add", "casa", "41.0,2.0")[0] == 0
    code, out = run("route", "casa", "estació inventada", "--by", "2:00")
    assert (out["from"]["kind"], out["to"]["kind"], out["to"]["name"]) == (
        "place",
        "station",
        "Estació Inventada",
    )
    assert FakePlanner.asked[-1][1] == (41.02, 2.0)


def test_leave_defaults_from_casa_and_keeps_the_best_option():
    assert run("leave", "41.02,2.0", "--by", "2:00")[1]["error"]["code"] == "usage"
    run("place", "add", "casa", "41.0,2.0")
    code, out = run("leave", "41.02,2.0", "--by", "2:00")
    assert code == 0 and len(out["options"]) == 1
    assert out["options"][0]["leave_in"] == 40


def test_leave_wait_exits_at_the_departure_time():
    run("place", "add", "casa", "41.0,2.0")
    code, out = run("leave", "41.02,2.0", "--by", "2:00", "--wait")
    assert (code, out["event"]) == (0, "leave_now")
    assert out["checked"] > 1
    assert out["say"].startswith("Sal ya (01:40): 5 min andando hasta Prova")


def test_no_route_is_not_found():
    FakePlanner.payload = {"requestParameters": {}, "error": {"message": "PATH_NOT_FOUND"}}
    code, out = run("route", "41.0,2.0", "41.02,2.0")
    assert (code, out["error"]["code"]) == (4, "not_found")


def test_a_line_has_no_position():
    run("place", "add", "casa", "41.0,2.0")
    assert run("route", "casa", "x9")[1]["error"]["code"] == "usage"
