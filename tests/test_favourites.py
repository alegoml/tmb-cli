import json
from pathlib import Path

import pytest
from conftest import FakeAmb
from typer.testing import CliRunner

from tmb_cli import amb, cli, network
from tmb_cli.cli import app
from tmb_cli.favourites import favourites_path

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def fake_api(tmp_path, monkeypatch):
    """Isolated config and cache, fake credentials, and arrivals from synthetic fixtures."""
    monkeypatch.setenv("TMB_CLI_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TMB_CLI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TMB_APP_ID", "test-id")
    monkeypatch.setenv("TMB_APP_KEY", "test-secret-key")
    asked = []

    def bus(self, code):
        asked.append(code)
        return fixture("bus_stop.json")

    def metro(self, codes):
        asked.append(codes)
        return fixture("metro_stations.json")

    monkeypatch.setattr(cli.TmbClient, "bus_arrivals", bus)
    monkeypatch.setattr(cli.TmbClient, "metro_arrivals", metro)
    return asked


def ok(*args: str) -> dict:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def error(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, json.loads(result.stderr)["error"]["code"]


def test_add_list_replace_remove():
    added = ok("fav", "add", "casa", "0001", "--walk", "4")
    assert added == {
        "favourite": {"name": "casa", "type": "bus", "codes": ["1"], "walk_minutes": 4},
        "replaced": False,
    }
    ok("fav", "add", "feina", "901", "801", "--walk", "6", "--metro")
    assert ok("fav", "add", "casa", "0001", "--walk", "5")["replaced"] is True

    favs = ok("fav", "list")["favourites"]
    assert [(f["name"], f["walk_minutes"]) for f in favs] == [("feina", 6), ("casa", 5)]

    assert ok("fav", "remove", "feina") == {"removed": "feina"}
    assert [f["name"] for f in ok("fav", "list")["favourites"]] == ["casa"]
    assert error("fav", "remove", "feina") == (4, "not_found")


def test_favourites_live_apart_from_credentials():
    ok("fav", "add", "casa", "0001", "--walk", "4")
    assert favourites_path().name == "favourites.json"
    assert "test-secret-key" not in favourites_path().read_text()


@pytest.mark.parametrize("name", ["Casa", "1casa", "ca sa", "casa_"])
def test_add_rejects_bad_names(name):
    assert error("fav", "add", name, "0001", "--walk", "4") == (2, "usage")


def test_a_bus_favourite_has_one_stop():
    assert error("fav", "add", "casa", "0001", "0002", "--walk", "4") == (2, "usage")


def test_add_checks_codes_against_the_cache_when_there_is_one():
    ok("fav", "add", "casa", "9", "--walk", "4")  # no cache: can't check, accepted
    network.save(network.download(FakeStatic()))
    ok("fav", "add", "casa", "9", "--walk", "4")  # TMB's list only: it may be an AMB stop
    amb.get_cache(FakeAmb)
    assert error("fav", "add", "casa", "9", "--walk", "4") == (4, "not_found")
    ok("fav", "add", "bufala", "100001", "--walk", "4")  # an AMB-only stop
    assert error("fav", "add", "feina", "999", "--walk", "4", "--metro") == (4, "not_found")
    ok("fav", "add", "feina", "901", "801", "--walk", "4", "--metro")


def test_corrupt_favourites_file_is_a_usage_error():
    favourites_path().parent.mkdir(parents=True)
    favourites_path().write_text("[")
    assert error("fav", "list") == (2, "usage")


def test_next_from_a_favourite(fake_api):
    ok("fav", "add", "casa", "0001", "--walk", "4")
    out = ok("next", "casa")
    assert fake_api == ["1"]
    assert out["favourite"] == {"name": "casa", "type": "bus", "codes": ["1"], "walk_minutes": 4}
    assert out["stop"]["name"] == "Parada de prova"
    # minutes 0, 3, 5, 15 with a 4-minute walk
    assert [(a["minutes"], a["leave_in"], a["make_it"]) for a in out["arrivals"]] == [
        (0, -4, False),
        (3, -1, False),
        (5, 1, True),
        (15, 11, True),
    ]
    assert list(out["arrivals"][0]) == [
        "line",
        "destination",
        "minutes",
        "eta",
        "operator",
        "make_it",
        "leave_in",
    ]
    assert out["source"] == "TMB"


def test_next_margin_walk_override_and_line_filter():
    ok("fav", "add", "casa", "0001", "--walk", "4")
    out = ok("next", "casa", "--margin", "2", "--walk", "2", "-l", "x1")
    assert out["favourite"]["walk_minutes"] == 2
    assert [(a["line"], a["leave_in"], a["make_it"]) for a in out["arrivals"]] == [
        ("X1", 1, False),
        ("X1", 13, True),
    ]


def test_next_with_a_code_needs_walk():
    assert error("next", "0001") == (2, "usage")
    out = ok("next", "0001", "--walk", "3")
    assert out["favourite"] == {"name": None, "type": "bus", "codes": ["0001"], "walk_minutes": 3}


def test_next_metro_favourite_and_code(fake_api):
    ok("fav", "add", "feina", "901", "801", "--walk", "2", "--metro")
    out = ok("next", "feina")
    assert fake_api == [["901", "801"]]
    first = out["stations"][0]
    assert first["code"] == "901"
    assert [(a["minutes"], a["leave_in"], a["make_it"]) for a in first["arrivals"]] == [
        (1, -1, False),
        (2, 0, True),
        (8, 6, True),
    ]
    assert ok("next", "801", "--metro", "--walk", "1")["favourite"]["type"] == "metro"


def test_next_unknown_favourite_or_misused_metro_flag():
    assert error("next", "enlloc") == (4, "not_found")
    ok("fav", "add", "casa", "0001", "--walk", "4")
    assert error("next", "casa", "--metro") == (2, "usage")


class FakeStatic:
    """The static network from synthetic fixtures, for `network.download`."""

    def bus_stops(self):
        return fixture("static_stops.json")

    def metro_lines(self):
        return fixture("static_metro_lines.json")

    def metro_line_stations(self, line_code):
        return fixture(f"static_metro_{line_code}_stations.json")
