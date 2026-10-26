import json

import pytest
from test_network import FakeClient
from typer.testing import CliRunner

from tmb_cli import cli, nearby
from tmb_cli.cli import app
from tmb_cli.errors import MissingCredentials

runner = CliRunner()
HOME = "41.0000,2.0000"  # the made-up origin of the fixtures' geography


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TMB_APP_ID", "test-id")
    monkeypatch.setenv("TMB_APP_KEY", "test-secret-key")
    monkeypatch.setattr(cli, "_client", FakeClient)


def ok(*args: str) -> dict:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def error(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, json.loads(result.stderr)["error"]["code"]


def test_points_distances_and_walk_estimates():
    assert nearby.parse_point(" 41.3874 , 2.17 ") == (41.3874, 2.17)
    assert nearby.parse_point("Carrer Fals 1") is None
    assert nearby.parse_point("141,2") is None
    assert round(nearby.distance_m(41.0, 2.0, 41.001, 2.0)) == 111
    assert nearby.walk_minutes(111) == 2  # 111 m × 1.3 / 80 m/min = 1.8 → 2
    assert nearby.walk_minutes(5) == 1


def test_place_add_picks_the_closest_stops_and_station():
    out = ok("place", "add", "casa", HOME, "--label", "Carrer de Prova 1")
    place = out["place"]
    assert place["label"] == "Carrer de Prova 1"
    # Within 450 m: TMB stops 4 (70 m), 1 (111 m) and 2 (334 m), AMB 100001 (187 m), and the
    # metro station Prova (98 m). Three bus stops max; 3 (1.1 km) is too far.
    assert [(s["type"], s["codes"], s["network"]) for s in place["stops"]] == [
        ("bus", ["4"], "TMB"),
        ("metro", ["801", "901"], "TMB"),
        ("bus", ["1"], "TMB"),
        ("bus", ["100001"], "AMB"),
    ]
    assert [(s["distance_m"], s["walk_minutes"]) for s in place["stops"]] == [
        (70, 2),
        (98, 2),
        (111, 2),
        (187, 4),
    ]
    assert all(s["estimated"] for s in place["stops"])
    assert out["say"].startswith("He guardado «casa» con 4 paradas: Pl de Prova - Carrer Inventat")


def test_place_walk_list_remove():
    ok("place", "add", "casa", HOME)
    place = ok("place", "walk", "casa", "100001", "5")["place"]
    amb_stop = next(s for s in place["stops"] if s["codes"] == ["100001"])
    assert (amb_stop["walk_minutes"], amb_stop["estimated"]) == (5, False)
    assert ok("place", "walk", "casa", "901", "4")["place"]["stops"][1]["walk_minutes"] == 4

    assert [p["name"] for p in ok("place", "list")["places"]] == ["casa"]
    assert error("place", "walk", "casa", "999", "4") == (4, "not_found")
    assert ok("place", "remove", "casa") == {"removed": "casa"}
    assert error("place", "remove", "casa") == (4, "not_found")


def test_place_add_validates_name_and_point():
    assert error("place", "add", "Casa", HOME) == (2, "usage")
    assert error("place", "add", "casa", "Carrer Fals") == (2, "usage")


def test_a_place_with_nothing_around_says_so():
    out = ok("place", "add", "lluny", "42.0,3.0")
    assert out["place"]["stops"] == []
    assert "no hay paradas" in out["say"]


def test_place_add_works_without_tmb_keys(monkeypatch):
    def no_keys():
        raise MissingCredentials("No TMB API credentials found.")

    monkeypatch.setattr(cli, "_client", no_keys)
    out = ok("place", "add", "casa", HOME)
    assert [s["codes"] for s in out["place"]["stops"]] == [["100001"]]  # AMB only
