"""Turn TMB real-time responses into our compact output (docs/spec.md, `bus` and `metro`)."""

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from tmb_cli.models import (
    Arrival,
    BusArrivals,
    BusNext,
    MetroArrival,
    MetroArrivals,
    MetroNext,
    NextArrival,
    NextMetroArrival,
    NextStation,
    Station,
    Stop,
    Target,
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


def bus_arrivals(payload: object, stop_code: str, lines: list[str]) -> BusArrivals:
    wire = parse(WireBusResponse, payload)
    wanted = {line.upper() for line in lines}
    # An unknown stop comes back as an empty `parades`: no name, no arrivals.
    name = wire.parades[0].nom_parada if wire.parades else None
    timed = [
        (
            bus.temps_arribada,
            Arrival(
                line=route.nom_linia,
                destination=route.desti_trajecte,
                minutes=minutes_until(bus.temps_arribada, wire.timestamp),
                eta=clock(bus.temps_arribada),
            ),
        )
        for stop in wire.parades
        for route in stop.linies_trajectes
        if _wanted(route.nom_linia, wanted)
        for bus in route.propers_busos
    ]
    return BusArrivals(
        stop=Stop(code=stop_code, name=name),
        arrivals=_by_time(timed),  # one flat list (D2)
        updated_at=clock(wire.timestamp),
    )


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


# --- `tmb next` ---------------------------------------------------------------------


def _timing(arrival: Arrival | MetroArrival, walk: int, margin: int) -> dict:
    leave_in = arrival.minutes - walk
    return {**arrival.model_dump(), "leave_in": leave_in, "make_it": leave_in >= margin}


def bus_next(result: BusArrivals, target: Target, margin: int) -> BusNext:
    walk = target.walk_minutes
    return BusNext(
        favourite=target,
        stop=result.stop,
        arrivals=[NextArrival(**_timing(a, walk, margin)) for a in result.arrivals],
        updated_at=result.updated_at,
    )


def metro_next(result: MetroArrivals, target: Target, margin: int) -> MetroNext:
    walk = target.walk_minutes
    return MetroNext(
        favourite=target,
        stations=[
            NextStation(
                code=s.code,
                name=s.name,
                arrivals=[NextMetroArrival(**_timing(a, walk, margin)) for a in s.arrivals],
            )
            for s in result.stations
        ],
        updated_at=result.updated_at,
    )
