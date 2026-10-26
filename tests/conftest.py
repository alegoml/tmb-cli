"""Shared test setup: an isolated cache dir and a fake AMB for every test (never the network).

The fake AMB serves a synthetic GTFS zip and GTFS-Realtime feed built here, with the shapes seen
in AMB's real files (docs/amb-api.md) and made-up values (AGENTS.md rule 3).
"""

import io
import zipfile

import pytest
from google.transit import gtfs_realtime_pb2

from tmb_cli import cli

T = 1767225600  # 2026-01-01T00:00:00Z, the same base time as the TMB fixtures

GTFS_FILES = {
    "feed_info.txt": "feed_publisher_name,feed_lang,feed_start_date,feed_end_date,feed_version\n"
    "AMBMobilitat,ca,20260101,20991231,20260101\n",
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n"
    "90,Operador de prova,http://example.invalid,Europe/Madrid\n",
    # A space after the comma and a trailing tab, as in AMB's real areas.txt.
    "areas.txt": "area_id, area_name\n08999,Vila Inventada\t\n",
    "stop_areas.txt": "area_id, stop_id\n08999,100001\n",
    "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n"
    '900,90,"Y7","Prova - Inventada",3\n',
    "trips.txt": "route_id,service_id,trip_id,direction_id,trip_headsign\n"
    "900,s1,900.1.0,0,Altre destí\n"
    "900,s1,900.1.1,1,Destí de prova\n"
    "900,s1,900.1.2,0,Altre destí\n",
    "stops.txt": "stop_id,stop_code,stop_name,stop_desc,stop_lat,stop_lon,out_of_service\n"
    '100001,100001,"Parada AMB de prova",Pal,41.0015,2.0010,0\n'
    '100002,100002,"Parada AMB tancada",Pal,41.0002,2.0000,1\n'
    '000005,5,"Parada compartida de prova",Marquesina,41.0500,2.0000,0\n',
    # Never read by tmb-cli, but present in the real zip.
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n",
}


def gtfs_zip(files: dict[str, str] = GTFS_FILES) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, "﻿" + text)  # AMB's files start with a BOM
    return buffer.getvalue()


def feed(passages: list[tuple[str, str, int | None]], timestamp: int = T) -> bytes:
    """A GTFS-Realtime feed: (trip_id, stop_id, seconds from `timestamp`, None = SKIPPED)."""
    message = gtfs_realtime_pb2.FeedMessage()
    message.header.gtfs_realtime_version = "1.0"
    message.header.timestamp = timestamp
    for n, (trip_id, stop_id, offset) in enumerate(passages):
        entity = message.entity.add(id=str(n))
        entity.trip_update.trip.trip_id = trip_id
        update = entity.trip_update.stop_time_update.add(stop_id=stop_id, stop_sequence=1)
        if offset is None:
            update.schedule_relationship = 1  # SKIPPED
        else:
            update.arrival.time = update.departure.time = timestamp + offset
    return message.SerializeToString()


DEFAULT_FEED = [
    ("900.1.0", "100001", 120),  # 2 min, Altre destí
    ("900.1.1", "100001", 400),  # 6 min 40 s, Destí de prova
    ("900.1.2", "100001", -300),  # passed 5 min ago: dropped
    ("999.9.9", "100001", 60),  # a trip the cache doesn't know: dropped
    ("900.1.1", "100002", None),  # SKIPPED, no time
    ("900.1.0", "000005", 200),  # 3 min 20 s at the stop shared with TMB
]


class FakeAmb:
    gtfs_bytes = gtfs_zip()
    feed_bytes = feed(DEFAULT_FEED)
    downloads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def gtfs(self) -> bytes:
        FakeAmb.downloads += 1
        return FakeAmb.gtfs_bytes

    def realtime(self) -> bytes:
        return FakeAmb.feed_bytes


@pytest.fixture(autouse=True)
def fake_amb(tmp_path, monkeypatch):
    monkeypatch.setenv("TMB_CLI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(FakeAmb, "gtfs_bytes", gtfs_zip())
    monkeypatch.setattr(FakeAmb, "feed_bytes", feed(DEFAULT_FEED))
    monkeypatch.setattr(FakeAmb, "downloads", 0)
    monkeypatch.setattr(cli, "_amb_client", FakeAmb)
    return FakeAmb
