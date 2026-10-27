import json
from datetime import datetime
from pathlib import Path

import pytest
from conftest import GTFS_FILES, FakeAmb, gtfs_zip
from test_network import FakeClient
from typer.testing import CliRunner

from tmb_cli import cli, profile
from tmb_cli.arrivals import MADRID
from tmb_cli.cli import app
from tmb_cli.errors import UsageError

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()
HOME = "41.0000,2.0000"


class FakeTmb(FakeClient):
    planned: list = []

    def bus_arrivals(self, code):
        return json.loads((FIXTURES / "bus_stop.json").read_text())

    def metro_arrivals(self, codes):
        return json.loads((FIXTURES / "metro_stations.json").read_text())

    def plan(self, origin, destination, when):
        FakeTmb.planned.append((origin, destination, when))
        return json.loads((FIXTURES / "planner_plan.json").read_text())


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("TMB_APP_ID", raising=False)
    monkeypatch.delenv("TMB_APP_KEY", raising=False)
    monkeypatch.setattr(cli, "_client", FakeTmb)
    monkeypatch.setattr(cli, "_clock", lambda: datetime(2026, 1, 1, 1, 0, tzinfo=MADRID))
    FakeTmb.planned = []


def ok(*args: str) -> dict:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def missing() -> list[str]:
    return [i["item"] for i in ok("setup")["items"] if not i["done"]]


def test_setup_walks_the_agent_through_every_question(monkeypatch):
    first = ok("setup")
    assert first["complete"] is False
    assert first["next_question"].startswith("¿Dónde vives?")
    assert missing() == ["home", "places", "trips", "prefs", "keys"]

    ok("place", "add", "casa", HOME)
    status = ok("setup")
    assert missing() == ["places", "walks", "trips", "prefs", "keys"]
    walks = next(i for i in status["items"] if i["item"] == "walks")
    assert walks["question"].startswith("He estimado lo que tardas andando a las paradas de «casa»")

    ok("setup", "--done", "places")  # "no, ningún otro sitio"
    ok("place", "confirm", "casa")
    ok(
        "trip",
        "add",
        "trabajo",
        "--from",
        "casa",
        "--to",
        "41.02,2.0",
        "--by",
        "9:00",
        "--days",
        "l-v",
    )
    ok("prefs", "--margin", "2")
    assert missing() == ["keys"]
    monkeypatch.setenv("TMB_APP_ID", "test-id")
    monkeypatch.setenv("TMB_APP_KEY", "test-secret-key")
    done = ok("setup")
    assert (done["complete"], done["next_question"]) == (True, None)
    assert done["say"].startswith("Todo listo")


def test_setup_rejects_unknown_items():
    result = runner.invoke(app, ["setup", "--done", "everything"])
    assert result.exit_code == 2


def test_trips_feed_leave_and_route():
    ok("place", "add", "casa", HOME)
    saved = ok(
        "trip",
        "add",
        "trabajo",
        "--from",
        "casa",
        "--to",
        "41.02,2.0",
        "--by",
        "2:00",
        "--days",
        "laborables",
    )
    assert saved["trip"] == {
        "name": "trabajo",
        "from": "casa",
        "to": "41.02,2.0",
        "by": "2:00",
        "days": ["lun", "mar", "mie", "jue", "vie"],
    }
    assert saved["say"] == (
        "Guardado el trayecto «trabajo»: de casa a 41.02,2.0 para llegar a las 2:00 "
        "(lun, mar, mie, jue, vie)."
    )
    out = ok("leave", "trabajo")  # "¿cuándo salgo para el trabajo?"
    assert out["arrive_by"] == "2026-01-01T02:00:00+01:00"
    assert FakeTmb.planned[-1][:2] == ((41.0, 2.0), (41.02, 2.0))
    assert ok("route", "trabajo")["options"][0]["leave_at"][11:16] == "01:40"
    assert ok("trip", "list")["trips"][0]["from"] == "casa"
    assert ok("trip", "remove", "trabajo") == {"removed": "trabajo"}


def test_days_parse_the_way_people_say_them():
    assert profile.parse_days("sab,dom") == ["sab", "dom"]
    assert profile.parse_days("finde") == ["sab", "dom"]
    assert profile.parse_days("vie-lun") == ["lun", "vie", "sab", "dom"]
    with pytest.raises(UsageError):
        profile.parse_days("someday")


def test_prefs_margin_is_the_default_margin():
    ok("fav", "add", "casa", "0001", "--walk", "4")
    assert ok("prefs", "--margin", "2")["prefs"] == {"margin": 2, "pace": "normal"}
    out = ok("next", "casa")
    # The 5-min bus leaves 1 min to spare: not enough with a 2-min margin.
    assert [(a["minutes"], a["make_it"]) for a in out["arrivals"]][2] == (5, False)
    assert [(a["minutes"], a["make_it"]) for a in ok("next", "casa", "--margin", "0")["arrivals"]][
        2
    ] == (5, True)


def test_a_slow_pace_lengthens_estimated_walks():
    normal = ok("place", "add", "casa", HOME)["place"]["stops"]
    ok("prefs", "--pace", "slow")
    slow = ok("place", "add", "casa", HOME)["place"]["stops"]
    walk = {tuple(s["codes"]): s["walk_minutes"] for s in normal}
    walk_slow = {tuple(s["codes"]): s["walk_minutes"] for s in slow}
    assert (walk[("1",)], walk_slow[("1",)]) == (2, 3)  # 111 m × 1.3 at 80 vs 65 m/min
    assert runner.invoke(app, ["prefs", "--pace", "running"]).exit_code == 2


def test_a_name_matching_two_places_is_flagged(monkeypatch):
    files = dict(GTFS_FILES)
    files["stops.txt"] += '200001,200001,"Prova",Pal,41.2000,2.0000,0\n'  # 22 km away
    monkeypatch.setattr(FakeAmb, "gtfs_bytes", gtfs_zip(files))
    out = ok("next", "prova")
    assert out["resolved"]["ambiguous"] is True
    assert out["resolved"]["alternatives"] == [
        {"name": "Prova", "type": "bus", "town": None, "codes": ["200001"]}
    ]
    assert out["say"].startswith("Entiendo Prova; si te referías a Prova (otro sitio), dímelo. ")


def test_a_name_with_nearby_twins_is_not_ambiguous():
    out = ok("next", "prova")
    assert out["resolved"]["ambiguous"] is False
