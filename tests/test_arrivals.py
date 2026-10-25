import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tmb_cli import arrivals, cli
from tmb_cli.cli import app
from tmb_cli.errors import ApiChanged

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def fake_api(tmp_path, monkeypatch):
    """Fake credentials, and the client answers from a synthetic fixture instead of the network."""
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("TMB_APP_ID", "test-id")
    monkeypatch.setenv("TMB_APP_KEY", "test-secret-key")
    calls = []

    def serve(name: str) -> None:
        def answer(self, codes):
            calls.append(codes)
            return fixture(name)

        monkeypatch.setattr(cli.TmbClient, "bus_arrivals", answer)
        monkeypatch.setattr(cli.TmbClient, "metro_arrivals", answer)

    serve.calls = calls
    return serve


def test_bus_is_one_flat_list_by_time():
    out = arrivals.bus_arrivals(fixture("bus_stop.json"), "0001", []).model_dump()
    assert out["stop"] == {"code": "0001", "name": "Parada de prova"}
    assert out["arrivals"][1] == {
        "line": "X1",
        "destination": "Destí de prova",
        "minutes": 3,
        "eta": "2026-01-01T01:03:50+01:00",
    }
    assert [(a["line"], a["minutes"], a["eta"][11:19]) for a in out["arrivals"]] == [
        ("X2", 0, "00:59:50"),  # already due
        ("X1", 3, "01:03:50"),  # 3 min 50 s rounds down
        ("X2", 5, "01:05:00"),
        ("X1", 15, "01:15:00"),
    ]
    assert out["source"] == "TMB"
    assert out["updated_at"] == "2026-01-01T01:00:00+01:00"


def test_bus_line_filter_is_case_insensitive_and_repeatable():
    out = arrivals.bus_arrivals(fixture("bus_stop.json"), "0001", ["x1"])
    assert {a.line for a in out.arrivals} == {"X1"}
    out = arrivals.bus_arrivals(fixture("bus_stop.json"), "0001", ["x1", "X2"])
    assert len(out.arrivals) == 4


def test_unknown_stop_has_no_name_and_no_arrivals():
    out = arrivals.bus_arrivals(fixture("bus_unknown_stop.json"), "0002", [])
    assert out.stop.name is None
    assert out.arrivals == []


def test_minutes_round_down_and_never_go_negative():
    assert arrivals.minutes_until(1_000 + 3 * 60_000 + 59_000, 1_000) == 3
    assert arrivals.minutes_until(1_000, 61_000) == 0


def test_eta_follows_summer_time():
    assert arrivals.clock(1784538000000) == "2026-07-20T11:00:00+02:00"


def test_metro_regroups_by_station_in_the_order_asked():
    out = arrivals.metro_arrivals(fixture("metro_stations.json"), ["0801", "901"], []).model_dump()
    assert [(s["code"], s["name"]) for s in out["stations"]] == [("801", None), ("901", None)]
    assert out["stations"][0]["arrivals"] == [
        {
            "line": "X8",
            "destination": "Final de prova",
            "track": 1,
            "minutes": 4,
            "eta": "2026-01-01T01:04:00+01:00",
        }
    ]
    station = out["stations"][1]
    assert [(a["destination"], a["track"], a["minutes"]) for a in station["arrivals"]] == [
        ("Altre destí", 2, 1),
        ("Destí de prova", 1, 2),
        ("Destí de prova", 1, 8),
    ]
    assert out["source"] == "TMB"


def test_metro_station_without_trains_is_listed_empty():
    out = arrivals.metro_arrivals(fixture("metro_stations.json"), ["901", "902"], ["X9"])
    assert [(s.code, len(s.arrivals)) for s in out.stations] == [("901", 3), ("902", 0)]


def test_unexpected_shape_is_api_changed():
    payload = fixture("bus_stop.json")
    del payload["parades"][0]["linies_trajectes"][0]["propers_busos"][0]["temps_arribada"]
    with pytest.raises(ApiChanged) as err:
        arrivals.bus_arrivals(payload, "0001", [])
    assert "parades.0.linies_trajectes.0.propers_busos.0.temps_arribada" in err.value.message


def test_cli_bus_prints_compact_json(fake_api):
    fake_api("bus_stop.json")
    result = runner.invoke(app, ["bus", "0001", "--line", "X1"])
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert [a["minutes"] for a in data["arrivals"]] == [3, 15]


def test_cli_metro_prints_compact_json(fake_api):
    fake_api("metro_stations.json")
    result = runner.invoke(app, ["metro", "901", "801", "-l", "x8"])
    assert result.exit_code == 0, result.stderr
    stations = json.loads(result.stdout)["stations"]
    assert [(s["code"], len(s["arrivals"])) for s in stations] == [("901", 0), ("801", 1)]


def test_cli_api_change_exits_7(fake_api, monkeypatch):
    monkeypatch.setattr(cli.TmbClient, "bus_arrivals", lambda self, code: {"parades": []})
    result = runner.invoke(app, ["bus", "0001"])
    assert result.exit_code == 7
    assert json.loads(result.stderr)["error"]["code"] == "api_changed"


@pytest.mark.parametrize("args", [["bus", "../transit/parades"], ["metro", "901", "12a"]])
def test_cli_rejects_non_numeric_codes_before_any_request(fake_api, args):
    fake_api("bus_stop.json")
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "usage"
    assert fake_api.calls == []
