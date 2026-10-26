import json
import time
from pathlib import Path

import pytest
from conftest import GTFS_FILES, FakeAmb, T, feed, gtfs_zip
from typer.testing import CliRunner

from tmb_cli import amb, cli
from tmb_cli.cli import app
from tmb_cli.errors import ApiChanged, NetworkError

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("TMB_APP_ID", raising=False)
    monkeypatch.delenv("TMB_APP_KEY", raising=False)


@pytest.fixture
def tmb(monkeypatch):
    """TMB keys, and TMB's real time from a synthetic fixture (the payload can be edited)."""
    monkeypatch.setenv("TMB_APP_ID", "test-id")
    monkeypatch.setenv("TMB_APP_KEY", "test-secret-key")
    payload = json.loads((FIXTURES / "bus_stop.json").read_text())
    monkeypatch.setattr(cli.TmbClient, "bus_arrivals", lambda self, code: payload)
    return payload


def run(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, list(args))
    return result.exit_code, json.loads(result.stdout or result.stderr)


# --- static cache -------------------------------------------------------------------


def test_parse_static_keeps_stops_lines_and_trips():
    cache = amb.parse_static(gtfs_zip())
    assert cache.valid_until == "20991231"
    assert cache.updated_at == "2026-01-01"
    assert cache.stops["100001"].model_dump() == {
        "name": "Parada AMB de prova",
        "town": "Vila Inventada",  # trailing tab stripped
        "padded": False,
        "in_service": True,
        "lat": 41.0015,
        "lon": 2.001,
    }
    assert cache.stops["5"].padded is True  # "000005": a TMB stop code too
    assert cache.stops["100002"].in_service is False
    assert cache.lines == {"900": ("Y7", "Operador de prova")}
    assert cache.trips["900.1.1"] == ("900", "Destí de prova")


def test_broken_static_or_feed_is_api_changed():
    with pytest.raises(ApiChanged):
        amb.parse_static(b"not a zip")
    with pytest.raises(ApiChanged):
        amb.parse_static(gtfs_zip({k: v for k, v in GTFS_FILES.items() if k != "trips.txt"}))
    with pytest.raises(ApiChanged):
        amb.parse_realtime(b"\xff\xff not protobuf")


def test_cache_is_reused_until_it_expires(fake_amb):
    amb.get_cache(FakeAmb)
    amb.get_cache(FakeAmb)
    assert fake_amb.downloads == 1
    expired = amb.load_cached().model_copy(update={"valid_until": "20200101"})
    amb.save(expired)
    amb.get_cache(FakeAmb)
    assert fake_amb.downloads == 2


def test_parse_realtime_indexes_by_stop_code_and_skips_skipped_stops():
    parsed = amb.parse_realtime(feed([("t", "000005", 60), ("t", "100002", None)]))
    assert parsed.timestamp_ms == T * 1000
    assert [p.arrival_ms for p in parsed.passages["5"]] == [(T + 60) * 1000]
    assert "100002" not in parsed.passages


# --- tmb bus ------------------------------------------------------------------------


def test_amb_only_stop_needs_no_tmb_keys():
    code, out = run("bus", "100001")
    assert code == 0, out
    assert out["stop"] == {"code": "100001", "name": "Parada AMB de prova"}
    assert out["source"] == "AMB"
    assert out["updated_at"] == "2026-01-01T01:00:00+01:00"
    # The bus that passed 5 min ago and the trip the cache doesn't know are left out.
    assert out["arrivals"] == [
        {
            "line": "Y7",
            "destination": "Altre destí",
            "minutes": 2,
            "eta": "2026-01-01T01:02:00+01:00",
            "operator": "Operador de prova",
        },
        {
            "line": "Y7",
            "destination": "Destí de prova",
            "minutes": 6,
            "eta": "2026-01-01T01:06:40+01:00",
            "operator": "Operador de prova",
        },
    ]


def test_line_filter_applies_to_amb_too():
    assert run("bus", "100001", "--line", "x1")[1]["arrivals"] == []
    assert len(run("bus", "100001", "-l", "y7")[1]["arrivals"]) == 2


def test_shared_stop_merges_tmb_and_amb_without_duplicates(tmb):
    # TMB also lists another operator's line here: AMB's own feed wins, so it's dropped.
    tmb["parades"][0]["linies_trajectes"].append(
        {
            "transit_namespace": "amb",
            "nom_linia": "Y7",
            "desti_trajecte": "Altre destí",
            "propers_busos": [{"temps_arribada": (T + 200) * 1000}],
        }
    )
    code, out = run("bus", "0005")
    assert code == 0, out
    assert out["source"] == "TMB+AMB"
    assert out["stop"]["name"] == "Parada de prova"  # TMB's name first
    assert [(a["line"], a["minutes"], a["operator"]) for a in out["arrivals"]] == [
        ("X2", 0, "TMB"),
        ("Y7", 3, "Operador de prova"),  # 3 min 20 s
        ("X1", 3, "TMB"),  # 3 min 50 s
        ("X2", 5, "TMB"),
        ("X1", 15, "TMB"),
    ]


def test_shared_stop_without_tmb_keys_is_missing_credentials():
    code, out = run("bus", "0005")
    assert code == 3
    assert out["error"]["code"] == "missing_credentials"


def test_tmb_only_stop_is_unchanged(tmb):
    code, out = run("bus", "0001")
    assert out["source"] == "TMB"
    assert {a["operator"] for a in out["arrivals"]} == {"TMB"}


def test_unknown_trips_refresh_an_old_cache_once(fake_amb):
    amb.get_cache(FakeAmb)
    run("bus", "100001")
    assert fake_amb.downloads == 1  # just downloaded: an unknown trip isn't worth another 9 MB
    amb.save(amb.load_cached().model_copy(update={"downloaded_at": time.time() - 7200}))
    run("bus", "100001")
    assert fake_amb.downloads == 2


def test_amb_network_failure_is_a_network_error(monkeypatch):
    def down(self):
        raise NetworkError("Could not reach AMB open data (ConnectError).")

    monkeypatch.setattr(FakeAmb, "realtime", down)
    code, out = run("bus", "100001")
    assert code == 6
    assert out["error"]["retryable"] is True


# --- stops, fav, doctor -------------------------------------------------------------


@pytest.fixture
def tmb_network(monkeypatch):
    from test_network import FakeClient

    monkeypatch.setattr(cli, "_client", FakeClient)


def test_stops_lists_amb_only_stops_by_town(tmb_network):
    code, out = run("stops", "vila", "inventada")
    assert code == 0, out
    amb_results = [r for r in out["results"] if r.get("network") == "AMB"]
    assert amb_results == [
        {
            "type": "bus",
            "code": "100001",
            "name": "Parada AMB de prova",
            "description": None,
            "town": "Vila Inventada",
            "network": "AMB",
        }
    ]  # 100002 is out of service


def test_a_stop_in_both_lists_appears_once_as_tmb(tmb_network, monkeypatch):
    files = dict(GTFS_FILES)
    files["stops.txt"] += '000001,1,"Pl de Prova - Carrer Fals",Pal,41.0,2.0,0\n'
    monkeypatch.setattr(FakeAmb, "gtfs_bytes", gtfs_zip(files))
    results = run("stops", "carrer", "fals")[1]["results"]
    assert [(r["code"], r["network"]) for r in results] == [("3", "TMB"), ("1", "TMB")]


def test_stops_metro_only_skips_amb(tmb_network, fake_amb):
    out = run("stops", "prova", "--metro")[1]
    assert out["source"] == "TMB"
    assert fake_amb.downloads == 0


def test_doctor_checks_amb(tmb):
    out = run("doctor")[1]
    checks = {c["name"]: c for c in out["checks"]}
    assert checks["amb"]["ok"] is True
    assert checks["amb_cache"]["ok"] is True


def test_amb_keeps_the_next_two_per_line_and_destination(fake_amb, monkeypatch):
    passages = [("900.1.0", "100001", 60 * m) for m in (5, 1, 9)]  # same line and destination
    passages.append(("900.1.1", "100001", 600))
    monkeypatch.setattr(FakeAmb, "feed_bytes", feed(passages))
    out = run("bus", "100001")[1]
    assert [(a["destination"], a["minutes"]) for a in out["arrivals"]] == [
        ("Altre destí", 1),
        ("Altre destí", 5),
        ("Destí de prova", 10),
    ]
