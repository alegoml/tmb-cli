"""Turn TMB real-time responses into our compact output (docs/spec.md, `bus` and `metro`)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from tmb_cli.errors import ApiChanged
from tmb_cli.models import (
    Arrival,
    BusArrivals,
    MetroArrival,
    MetroArrivals,
    Station,
    Stop,
    WireBusResponse,
    WireMetroResponse,
)

MADRID = ZoneInfo("Europe/Madrid")


def parse[M: BaseModel](model: type[M], payload: object) -> M:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        where = ".".join(str(part) for part in exc.errors()[0]["loc"]) or "response"
        raise ApiChanged(
            f"TMB API response has an unexpected shape (at `{where}`).",
            hint="The TMB API may have changed; please open an issue.",
        ) from None


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


def metro_arrivals(payload: object, station_codes: list[str], lines: list[str]) -> MetroArrivals:
    """TMB groups by line, then by station and track; we regroup by station, in the order asked."""
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
            Station(code=str(code), name=None, arrivals=_by_time(timed))
            for code, timed in by_station.items()
        ],
        updated_at=clock(wire.timestamp),
    )
