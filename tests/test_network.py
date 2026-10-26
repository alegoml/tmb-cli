import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tmb_cli import cli, network
from tmb_cli.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    """Answers the static endpoints from synthetic fixtures and counts requests."""

    requests = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def _answer(self, name: str) -> dict:
        FakeClient.requests += 1
        return fixture(name)

    def bus_stops(self):
        return self._answer("static_stops.json")

    def metro_lines(self):
        return self._answer("static_metro_lines.json")

    def metro_line_stations(self, line_code):
        return self._answer(f"static_metro_{line_code}_stations.json")


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TMB_CLI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TMB_APP_ID", "test-id")
    monkeypatch.setenv("TMB_APP_KEY", "test-secret-key")
    FakeClient.requests = 0


@pytest.fixture
def net() -> network.Network:
    return network.download(FakeClient())


def test_download_keeps_codes_and_names_and_joins_interchanges(net):
    assert net.updated_at == "2026-01-02"  # the newest dataset date
    assert net.stops[1].model_dump() == {
        "code": "2",
        "name": "Av Inventada - Rambla Fictícia",
        "description": None,
        "town": "Vila Inventada",
        "lat": 41.003,
        "lon": 2.0,
    }
    assert [s.model_dump() for s in net.stations] == [
        {"name": "Prova", "codes": {"X8": "801", "X9": "901"}, "lat": 41.0008, "lon": 1.9995},
        {"name": "Estació Inventada", "codes": {"X9": "902"}, "lat": 41.02, "lon": 2.0},
    ]
    assert net.station_name("801") == "Prova"
    assert net.station_name("999") is None


def test_lines_sort_by_number_then_others():
    lines = ["FM", "L10S", "L3", "L9N", "L1", "L10N", "L9S", "L11"]
    assert sorted(lines, key=network.line_order) == [
        "L1",
        "L3",
        "L9N",
        "L9S",
        "L10N",
        "L10S",
        "L11",
        "FM",
    ]


def test_cache_is_reused_while_fresh(net):
    network.get_network(FakeClient)
    FakeClient.requests = 0
    network.get_network(FakeClient)
    assert FakeClient.requests == 0
    network.get_network(FakeClient, refresh=True)
    assert FakeClient.requests == 4  # stops, lines, two lines' stations


def test_cache_from_an_older_version_is_downloaded_again(net):
    network.save(net.model_copy(update={"version": network.CACHE_VERSION - 1}))
    assert network.load_cached() is None


def test_stale_cache_is_downloaded_again(net):
    network.save(net.model_copy(update={"downloaded_at": time.time() - 8 * 24 * 3600}))
    FakeClient.requests = 0
    network.get_network(FakeClient)
    assert FakeClient.requests == 4


def test_unreadable_cache_counts_as_missing():
    network.cache_path().parent.mkdir(parents=True)
    network.cache_path().write_text("{not json")
    assert network.load_cached() is None


def test_normalize_drops_case_accents_punctuation_and_spells_street_types_short():
    assert network.normalize("Plaça Catalunya/Portal de l'Àngel") == (
        "pl catalunya portal de l angel"
    )
    assert network.normalize("Paral·lel") == network.normalize("paral.lel") == "paral lel"
    assert network.normalize("Avinguda Fictícia") == "av ficticia"


def _found(results) -> list:
    return [getattr(r, "code", None) or r.codes for r in results]


def test_search_ranks_exact_names_first_then_metro_then_barcelona(net):
    # 4 and 1 tie on rank; 4 is in Barcelona. 3 only matches in its description.
    assert _found(network.search(net, "prova")) == [{"X8": "801", "X9": "901"}, "4", "1", "3"]


def test_search_matches_word_prefixes_abbreviations_and_codes(net):
    assert _found(network.search(net, "plaça prov")) == ["4", "1"]
    assert _found(network.search(net, "inventada ficticia")) == ["2"]
    assert _found(network.search(net, "2")) == ["2"]
    assert _found(network.search(net, "estacio inv")) == [{"X9": "902"}]


def test_position_prefers_names_that_start_with_the_query():
    assert network.position("catalunya", "Pl Catalunya - Portal de l'Àngel") == 1
    assert network.position("catalunya", "La Rambla - Pl Catalunya") == 3


def test_search_matches_the_town_too(net):
    assert _found(network.search(net, "carrer fals barcelona")) == []  # 1 and 3 aren't there
    assert _found(network.search(net, "prova barcelona")) == ["4"]
    assert _found(network.search(net, "rambla vila")) == ["2"]


def test_a_town_match_beats_a_description_match():
    assert network.rank("badalona", "Pavelló Olímpic", "Alfons XIII", "Badalona") == 4
    assert network.rank("badalona", "Metro Provençana", "Aprestadora/Badalona", "L'Hospitalet") == 5


def test_cli_stops_takes_words_without_quotes(fake_api):
    out = json.loads(runner.invoke(app, ["stops", "carrer", "fals"]).stdout)
    assert out["query"] == "carrer fals"
    assert [r["code"] for r in out["results"]] == ["3", "1"]  # 3 starts with it


def test_search_filters_and_limit(net):
    assert _found(network.search(net, "prova", metro=False)) == ["4", "1", "3"]
    assert _found(network.search(net, "prova", bus=False)) == [{"X8": "801", "X9": "901"}]
    assert len(network.search(net, "prova", limit=1)) == 1


@pytest.fixture
def fake_api(monkeypatch):
    monkeypatch.setattr(cli, "_client", FakeClient)


def test_cli_stops(fake_api):
    result = runner.invoke(app, ["stops", "Prova", "--limit", "2"])
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "query": "Prova",
        "results": [
            {"type": "metro", "name": "Prova", "codes": {"X8": "801", "X9": "901"}},
            {
                "type": "bus",
                "code": "4",
                "name": "Pl de Prova - Carrer Inventat",
                "description": "Pl. Prova/Inventat",
                "town": "Barcelona",
                "network": "TMB",
            },
        ],
        "source": "TMB+AMB",
        "updated_at": "2026-01-01",  # the older of TMB's (01-02) and AMB's (01-01) dates
    }


@pytest.mark.parametrize("args", [["stops", "x", "--bus", "--metro"], ["stops", "·/·"]])
def test_cli_stops_usage_errors(fake_api, args):
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "usage"
    assert FakeClient.requests == 0


def test_cli_metro_names_stations_from_the_cache(net, monkeypatch):
    network.save(net)
    monkeypatch.setattr(
        cli.TmbClient, "metro_arrivals", lambda self, codes: fixture("metro_stations.json")
    )
    result = runner.invoke(app, ["metro", "901", "801", "999"])
    stations = json.loads(result.stdout)["stations"]
    assert [(s["code"], s["name"]) for s in stations] == [
        ("901", "Prova"),
        ("801", "Prova"),
        ("999", None),
    ]


def test_cli_bus_unknown_stop_is_not_found_when_the_cache_knows(net, monkeypatch):
    monkeypatch.setattr(
        cli.TmbClient, "bus_arrivals", lambda self, code: fixture("bus_unknown_stop.json")
    )
    result = runner.invoke(app, ["bus", "0009"])  # no cache yet: can't tell
    assert result.exit_code == 0
    assert json.loads(result.stdout)["arrivals"] == []

    network.save(net)
    result = runner.invoke(app, ["bus", "0002"])  # in the stops list, just no buses now
    assert result.exit_code == 0
    result = runner.invoke(app, ["bus", "0009"])
    assert result.exit_code == 4
    assert json.loads(result.stderr)["error"]["code"] == "not_found"
