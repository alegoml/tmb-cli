"""Local cache of the static network (stops and stations) and name search over it.

The cache holds only what we search and show (codes and names), not TMB's full GeoJSON: about
250 KB instead of ~3 MB. It is downloaded on first use and refreshed when older than a week (D4).
Real-time data is never cached.
"""

import os
import re
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ValidationError

from tmb_cli.client import TmbClient
from tmb_cli.models import (
    BusStopResult,
    StationResult,
    WireLines,
    WireStations,
    WireStops,
    parse,
)

ENV_CACHE_DIR = "TMB_CLI_CACHE_DIR"  # override, mainly for tests
MAX_AGE_SECONDS = 7 * 24 * 3600
CACHE_VERSION = 1


class CachedStop(BaseModel):
    code: str
    name: str
    description: str | None


class CachedStation(BaseModel):
    name: str
    codes: dict[str, str]  # line → real-time code


class Network(BaseModel):
    version: int = CACHE_VERSION
    downloaded_at: float  # epoch seconds
    updated_at: str  # TMB's dataset date, "2026-10-24"
    stops: list[CachedStop]
    stations: list[CachedStation]

    def station_name(self, code: str) -> str | None:
        for station in self.stations:
            if code in station.codes.values():
                return station.name
        return None

    def has_stop(self, code: str) -> bool:
        return any(stop.code == code for stop in self.stops)


def cache_dir() -> Path:
    if override := os.environ.get(ENV_CACHE_DIR):
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "tmb-cli"


def cache_path() -> Path:
    return cache_dir() / "network.json"


def load_cached() -> Network | None:
    """The cached network, or None if there is none or it is unreadable (it is only a cache)."""
    try:
        network = Network.model_validate_json(cache_path().read_bytes())
    except (OSError, ValidationError):
        return None
    return network if network.version == CACHE_VERSION else None


def save(network: Network) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(network.model_dump_json())
    os.replace(tmp, path)  # never leave half a file behind


def line_order(line: str) -> tuple[bool, int, str]:
    """L1, L2, …, L9N, L9S, L10N, L10S, L11, then FM (TMB lists lines in another order)."""
    match = re.fullmatch(r"L(\d+)(.*)", line)
    return (False, int(match[1]), match[2]) if match else (True, 0, line)


def download(client: TmbClient) -> Network:
    """13 requests: all bus stops, the metro lines, then the stations of each line."""
    stops = parse(WireStops, client.bus_stops())
    lines = parse(WireLines, client.metro_lines())
    dates = {f.properties.DATA for f in stops.features}

    groups: dict[int, CachedStation] = {}  # CODI_GRUP_ESTACIO → station, joins interchanges
    for line in lines.features:
        stations = parse(WireStations, client.metro_line_stations(line.properties.CODI_LINIA))
        for feature in stations.features:
            props = feature.properties
            dates.add(props.DATA)
            station = groups.setdefault(
                props.CODI_GRUP_ESTACIO, CachedStation(name=props.NOM_ESTACIO, codes={})
            )
            station.codes[props.NOM_LINIA] = str(props.CODI_ESTACIO)

    return Network(
        downloaded_at=time.time(),
        updated_at=max(dates, default="").removesuffix("Z"),
        stops=[
            CachedStop(
                code=str(f.properties.CODI_PARADA),
                name=f.properties.NOM_PARADA,
                description=f.properties.DESC_PARADA,
            )
            for f in stops.features
        ],
        stations=[
            CachedStation(
                name=s.name, codes=dict(sorted(s.codes.items(), key=lambda c: line_order(c[0])))
            )
            for s in groups.values()
        ],
    )


def get_network(client_factory: Callable[[], TmbClient], *, refresh: bool = False) -> Network:
    """The cached network, downloading it first if missing, older than a week, or `refresh`."""
    cached = None if refresh else load_cached()
    if cached and time.time() - cached.downloaded_at < MAX_AGE_SECONDS:
        return cached
    with client_factory() as client:
        network = download(client)
    save(network)
    return network


# --- search -------------------------------------------------------------------------


# TMB's stop names abbreviate street types ("Pl Catalunya"); spell queries and names the same way.
ABBREVIATIONS = {"placa": "pl", "avinguda": "av", "passeig": "pg", "carretera": "ctra"}


def normalize(text: str) -> str:
    """Lowercase, no accents, punctuation as spaces, street types abbreviated:
    "Plaça Catalunya/Portal de l'Àngel" → "pl catalunya portal de l angel"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    words = re.sub(r"[^a-z0-9]+", " ", plain).split()
    return " ".join(ABBREVIATIONS.get(word, word) for word in words)


def _all_tokens(tokens: list[str], words: list[str]) -> bool:
    """Every query word starts some word of the text: "pl cat" finds "Pl Catalunya"."""
    return all(any(word.startswith(token) for word in words) for token in tokens)


def rank(query: str, name: str, description: str | None = None) -> int | None:
    """Lower is better: exact name, name prefix, every word in the name, substring of the name,
    every word in name + description. None if it doesn't match."""
    name = normalize(name)
    tokens = query.split()
    if name == query:
        return 0
    if name.startswith(query):
        return 1
    if _all_tokens(tokens, name.split()):
        return 2
    if query in name:
        return 3
    if description and _all_tokens(tokens, (name + " " + normalize(description)).split()):
        return 4
    return None


def search(
    network: Network, query: str, *, bus: bool = True, metro: bool = True, limit: int = 10
) -> list[BusStopResult | StationResult]:
    q = normalize(query)
    found: list[tuple[int, int, str, BusStopResult | StationResult]] = []
    if metro:
        for station in network.stations:
            if (r := rank(q, station.name)) is not None:
                found.append((r, 0, station.name, StationResult(**station.model_dump())))
    if bus:
        for stop in network.stops:
            r = 0 if q == stop.code else rank(q, stop.name, stop.description)
            if r is not None:
                found.append((r, 1, stop.name, BusStopResult(**stop.model_dump())))
    found.sort(key=lambda item: item[:3])  # rank, then metro before bus, then name
    return [result for *_, result in found[:limit]]
