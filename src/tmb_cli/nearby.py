"""Stops and stations near a point, from the cached networks (TMB's and AMB's), with walk times.

Walk time is an estimate: straight-line distance × 1.3 (streets aren't straight) at 80 m/min,
rounded up, at least 1 minute (spec v0.3). The user corrects it per stop.
"""

import math
import re
from typing import Literal

from pydantic import BaseModel

from tmb_cli.amb import AmbCache
from tmb_cli.network import Network

DETOUR = 1.3
WALK_M_PER_MIN = 80
POINT = re.compile(r"\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*")


def parse_point(text: str) -> tuple[float, float] | None:
    """ "41.3874,2.17" → (41.3874, 2.17); anything else → None."""
    match = POINT.fullmatch(text)
    if not match:
        return None
    lat, lon = float(match[1]), float(match[2])
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (haversine)."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def walk_minutes(metres: float) -> int:
    return max(1, math.ceil(metres * DETOUR / WALK_M_PER_MIN))


class Candidate(BaseModel):
    type: Literal["bus", "metro"]
    name: str
    codes: list[str]  # one bus stop code, or a station's per-line codes
    network: Literal["TMB", "AMB"]
    lat: float
    lon: float
    distance_m: int
    walk_minutes: int


def nearby(
    lat: float,
    lon: float,
    tmb: Network | None,
    amb: AmbCache | None,
    *,
    radius: float = 450,
    max_bus: int = 3,
    max_metro: int = 1,
) -> list[Candidate]:
    """The closest bus stops and metro stations within `radius` metres, closest first."""
    found: list[Candidate] = []

    def add(kind: str, name: str, codes: list[str], net: str, plat: float, plon: float) -> None:
        d = distance_m(lat, lon, plat, plon)
        if d <= radius:
            found.append(
                Candidate(
                    type=kind,
                    name=name,
                    codes=codes,
                    network=net,
                    lat=plat,
                    lon=plon,
                    distance_m=round(d),
                    walk_minutes=walk_minutes(d),
                )
            )

    tmb_codes = set()
    if tmb:
        for stop in tmb.stops:
            tmb_codes.add(stop.code)
            add("bus", stop.name, [stop.code], "TMB", stop.lat, stop.lon)
        for station in tmb.stations:
            add(
                "metro", station.name, list(station.codes.values()), "TMB", station.lat, station.lon
            )
    if amb:
        for code, stop in amb.stops.items():
            if stop.in_service and code not in tmb_codes:
                add("bus", stop.name, [code], "AMB", stop.lat, stop.lon)

    found.sort(key=lambda c: c.distance_m)
    buses = [c for c in found if c.type == "bus"][:max_bus]
    stations = [c for c in found if c.type == "metro"][:max_metro]
    return sorted(buses + stations, key=lambda c: c.distance_m)
