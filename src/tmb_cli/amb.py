"""AMB's metropolitan buses (not TMB's): a local cache of its static GTFS, and its real-time feed.

The cache keeps only what we show: stops (name, town), lines (name, operator) and trips (line,
destination), read straight from the zip (`stop_times.txt` and `shapes.txt`, 58 of its 60 MB,
are never needed: the real-time feed has absolute times). AMB republishes the zip every few days
with new trip ids, so the cache follows the feed's own end date (docs/amb-api.md, spec D13).
"""

import csv
import io
import os
import time
import zipfile
from collections.abc import Callable, Iterator
from datetime import date, datetime

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2
from pydantic import BaseModel, ValidationError

from tmb_cli.client import AmbClient
from tmb_cli.errors import ApiChanged
from tmb_cli.network import cache_dir

MAX_AGE_SECONDS = 7 * 24 * 3600
CACHE_VERSION = 2
CHANGED_HINT = "AMB may have changed its open data; please open an issue."


class AmbStop(BaseModel):
    name: str
    town: str | None  # AMB's areas cover about 3 in 4 stops
    padded: bool  # stop_id zero-padded ("001103"): AMB's id for a TMB stop code
    in_service: bool
    lat: float
    lon: float


class AmbCache(BaseModel):
    version: int = CACHE_VERSION
    downloaded_at: float  # epoch seconds
    valid_until: str  # feed_end_date, "20261030"
    updated_at: str  # feed_start_date as a date, "2026-10-25"
    stops: dict[str, AmbStop]  # stop code (no leading zeros) → stop
    lines: dict[str, tuple[str, str]]  # route_id → (line name, operator)
    trips: dict[str, tuple[str, str]]  # trip_id → (route_id, destination)

    def fresh(self) -> bool:
        today = datetime.now().strftime("%Y%m%d")
        return today <= self.valid_until and time.time() - self.downloaded_at < MAX_AGE_SECONDS


def cache_path():
    return cache_dir() / "amb.json"


def load_cached() -> AmbCache | None:
    try:
        cache = AmbCache.model_validate_json(cache_path().read_bytes())
    except (OSError, ValidationError):
        return None
    return cache if cache.version == CACHE_VERSION else None


def save(cache: AmbCache) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(cache.model_dump_json())
    os.replace(tmp, path)


def _rows(archive: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with archive.open(name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig")
        for row in csv.DictReader(text, skipinitialspace=True):
            # areas.txt has "area_id, area_name" and trailing tabs in some names.
            yield {key.strip(): (value or "").strip() for key, value in row.items() if key}


def parse_static(content: bytes) -> AmbCache:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        feed = next(_rows(archive, "feed_info.txt"))
        operators = {r["agency_id"]: r["agency_name"] for r in _rows(archive, "agency.txt")}
        towns = {r["area_id"]: r["area_name"] for r in _rows(archive, "areas.txt")}
        stop_town = {
            r["stop_id"]: towns.get(r["area_id"]) for r in _rows(archive, "stop_areas.txt")
        }
        stops = {
            r["stop_code"]: AmbStop(
                name=r["stop_name"],
                town=stop_town.get(r["stop_id"]),
                padded=r["stop_id"].startswith("0"),
                in_service=r.get("out_of_service", "0") != "1",
                lat=float(r["stop_lat"]),
                lon=float(r["stop_lon"]),
            )
            for r in _rows(archive, "stops.txt")
        }
        lines = {
            r["route_id"]: (r["route_short_name"], operators.get(r["agency_id"], ""))
            for r in _rows(archive, "routes.txt")
        }
        trips = {
            r["trip_id"]: (r["route_id"], r["trip_headsign"]) for r in _rows(archive, "trips.txt")
        }
        start = feed["feed_start_date"]
        return AmbCache(
            downloaded_at=time.time(),
            valid_until=feed["feed_end_date"],
            updated_at=date(int(start[:4]), int(start[4:6]), int(start[6:])).isoformat(),
            stops=stops,
            lines=lines,
            trips=trips,
        )
    except (zipfile.BadZipFile, KeyError, StopIteration, ValueError, ValidationError):
        raise ApiChanged("AMB's GTFS zip has an unexpected shape.", hint=CHANGED_HINT) from None


def get_cache(client_factory: Callable[[], AmbClient], *, refresh: bool = False) -> AmbCache:
    """The cached AMB network, downloading it first if missing, expired, or `refresh`."""
    cached = None if refresh else load_cached()
    if cached and cached.fresh():
        return cached
    with client_factory() as client:
        cache = parse_static(client.gtfs())
    save(cache)
    return cache


# --- real time ----------------------------------------------------------------------


class Passage(BaseModel):
    """One AMB bus predicted at a stop."""

    trip_id: str
    arrival_ms: int


class Feed(BaseModel):
    timestamp_ms: int
    passages: dict[str, list[Passage]]  # stop code (no leading zeros) → buses


def parse_realtime(content: bytes) -> Feed:
    message = gtfs_realtime_pb2.FeedMessage()
    try:
        message.ParseFromString(content)
    except DecodeError:
        raise ApiChanged(
            "AMB's real-time feed is not valid GTFS-Realtime.", hint=CHANGED_HINT
        ) from None
    passages: dict[str, list[Passage]] = {}
    for entity in message.entity:
        if not entity.HasField("trip_update"):
            continue
        update = entity.trip_update
        for stop in update.stop_time_update:
            if not stop.arrival.HasField("time"):  # SKIPPED stops carry no time
                continue
            passages.setdefault(stop.stop_id.lstrip("0"), []).append(
                Passage(trip_id=update.trip.trip_id, arrival_ms=stop.arrival.time * 1000)
            )
    return Feed(timestamp_ms=message.header.timestamp * 1000, passages=passages)
