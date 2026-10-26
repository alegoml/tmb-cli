"""Turn TMB real-time responses into our compact output (docs/spec.md, `bus` and `metro`)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from tmb_cli.amb import AmbCache, Feed
from tmb_cli.models import (
    Arrival,
    BusArrivals,
    MetroArrival,
    MetroArrivals,
    Station,
    Stop,
    WireBusResponse,
    WireMetroResponse,
    parse,
)

MADRID = ZoneInfo("Europe/Madrid")


def clock(ms: int) -> str:
    """Epoch milliseconds → ISO 8601 in Barcelona time (D8)."""
    return datetime.fromtimestamp(ms // 1000, MADRID).isoformat()


def minutes_until(arrival_ms: int, now_ms: int) -> int:
    """Whole minutes, rounded down so we never promise more time than there is (D1). A bus already
    due counts as 0."""
    return max(0, (arrival_ms - now_ms) // 60_000)


def _wanted(line: str, lines: set[str]) -> bool:
    return not lines or line.upper() in lines


def _by_time[A: Arrival | MetroArrival](timed: list[tuple[int, A]]) -> list[A]:
    """Sort by arrival time, then line (sorting by the `eta` text would break on DST changes)."""
    return [arrival for _, arrival in sorted(timed, key=lambda pair: (pair[0], pair[1].line))]


@dataclass
class BusPart:
    """What one source (TMB or AMB) says about a stop."""

    source: str
    timestamp_ms: int
    name: str | None
    timed: list[tuple[int, Arrival]]


def tmb_bus(payload: object, lines: list[str], *, drop_other_operators: bool = False) -> BusPart:
    """TMB's answer. With `drop_other_operators`, lines TMB lists for other AMB operators are left
    out, because AMB's own feed (asked too) is the reference for them: no bus twice."""
    wire = parse(WireBusResponse, payload)
    wanted = {line.upper() for line in lines}
    timed = [
        (
            bus.temps_arribada,
            Arrival(
                line=route.nom_linia,
                destination=route.desti_trajecte,
                minutes=minutes_until(bus.temps_arribada, wire.timestamp),
                eta=clock(bus.temps_arribada),
                operator="TMB",
            ),
        )
        for stop in wire.parades
        for route in stop.linies_trajectes
        if _wanted(route.nom_linia, wanted)
        and not (drop_other_operators and route.transit_namespace == "amb")
        for bus in route.propers_busos
    ]
    # An unknown stop comes back as an empty `parades`: no name, no arrivals.
    name = wire.parades[0].nom_parada if wire.parades else None
    return BusPart("TMB", wire.timestamp, name, timed)


GONE_MS = 60_000  # AMB's feed keeps some stops a bus already passed; drop those over a minute old
PER_ROUTE = 2  # AMB predicts up to 2 h ahead; keep the next 2 per line and destination, as TMB does


def amb_bus(feed: Feed, cache: AmbCache, code: str, lines: list[str]) -> tuple[BusPart, bool]:
    """AMB's answer for a stop, and whether the feed named trips the cache doesn't know (then the
    cache is out of date: refresh it and ask again)."""
    wanted = {line.upper() for line in lines}
    stop = cache.stops.get(code)
    timed, unknown = [], False
    for passage in feed.passages.get(code, []):
        trip = cache.trips.get(passage.trip_id)
        line = cache.lines.get(trip[0]) if trip else None
        if trip is None or line is None:
            unknown = True
            continue
        if passage.arrival_ms < feed.timestamp_ms - GONE_MS or not _wanted(line[0], wanted):
            continue
        arrival = Arrival(
            line=line[0],
            destination=trip[1],
            minutes=minutes_until(passage.arrival_ms, feed.timestamp_ms),
            eta=clock(passage.arrival_ms),
            operator=line[1],
        )
        timed.append((passage.arrival_ms, arrival))
    kept, seen = [], {}
    for pair in sorted(timed, key=lambda p: p[0]):
        route = (pair[1].line, pair[1].destination)
        seen[route] = seen.get(route, 0) + 1
        if seen[route] <= PER_ROUTE:
            kept.append(pair)
    return BusPart("AMB", feed.timestamp_ms, stop.name if stop else None, kept), unknown


def combine(stop_code: str, parts: list[BusPart]) -> BusArrivals:
    """One answer from one or two sources: one list by time (D2), the first source's stop name,
    `source` "TMB", "AMB" or "TMB+AMB", and the older source's time as `updated_at` (D12)."""
    return BusArrivals(
        stop=Stop(code=stop_code, name=next((p.name for p in parts if p.name), None)),
        arrivals=_by_time([pair for part in parts for pair in part.timed]),
        source="+".join(part.source for part in parts),
        updated_at=clock(min(part.timestamp_ms for part in parts)),
    )


def bus_arrivals(payload: object, stop_code: str, lines: list[str]) -> BusArrivals:
    """TMB only (used by `doctor` and where AMB isn't asked)."""
    return combine(stop_code, [tmb_bus(payload, lines)])


def metro_arrivals(
    payload: object,
    station_codes: list[str],
    lines: list[str],
    station_name: Callable[[str], str | None] = lambda code: None,
) -> MetroArrivals:
    """TMB groups by line, then by station and track; we regroup by station, in the order asked.
    The response has no station names: `station_name` looks them up (in the cache)."""
    wire = parse(WireMetroResponse, payload)
    wanted = {line.upper() for line in lines}
    # TMB returns codes as ints, so "0126" comes back as 126.
    by_station: dict[int, list[tuple[int, MetroArrival]]] = {int(c): [] for c in station_codes}
    for line in wire.linies:
        for station in line.estacions:
            for route in station.linies_trajectes:
                if not _wanted(route.nom_linia, wanted):
                    continue
                for train in route.propers_trens:
                    arrival = MetroArrival(
                        line=route.nom_linia,
                        destination=route.desti_trajecte,
                        track=station.codi_via,
                        minutes=minutes_until(train.temps_arribada, wire.timestamp),
                        eta=clock(train.temps_arribada),
                    )
                    by_station.setdefault(station.codi_estacio, []).append(
                        (train.temps_arribada, arrival)
                    )
    return MetroArrivals(
        stations=[
            Station(code=str(code), name=station_name(str(code)), arrivals=_by_time(timed))
            for code, timed in by_station.items()
        ],
        updated_at=clock(wire.timestamp),
    )
