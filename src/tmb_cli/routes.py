"""Routes and when to leave, from TMB's trip planner (spec v0.4).

The planner works on timetables, not real time: every option says `scheduled: true` and `say`
says "según horarios".
"""

import re
from datetime import date, datetime, timedelta

from tmb_cli.arrivals import MADRID, clock
from tmb_cli.errors import NotFound, UsageError
from tmb_cli.models import (
    Resolved,
    RouteAnswer,
    RouteLeg,
    RouteOption,
    WireItinerary,
    WirePlanResponse,
    parse,
)
from tmb_cli.say import hhmm

MODES = {"WALK": "walk", "SUBWAY": "metro", "BUS": "bus", "TRAM": "tram", "RAIL": "train"}
TIME = re.compile(r"(\d{1,2})(?::|h|\.)?(\d{2})?")


def deadline(text: str, day: str | None, now: datetime) -> datetime:
    """ "9:00", "9", "18h30" on `day` (YYYY-MM-DD), else today, or tomorrow if it has passed."""
    match = TIME.fullmatch(text.strip())
    if not match or int(match[1]) > 23 or int(match[2] or 0) > 59:
        raise UsageError(f"`{text}` is not a time.", hint="Use HH:MM, e.g. 9:00 or 18:30.")
    hour, minute = int(match[1]), int(match[2] or 0)
    try:
        base = date.fromisoformat(day) if day else now.date()
    except ValueError:
        raise UsageError(f"`{day}` is not a date.", hint="Use YYYY-MM-DD.") from None
    when = datetime(base.year, base.month, base.day, hour, minute, tzinfo=MADRID)
    if day is None and when < now:
        when += timedelta(days=1)
    return when


def planner_params(when: datetime, arrive_by: bool) -> dict[str, str]:
    """The planner's own formats: mm-dd-yyyy and 6:00pm, Barcelona time."""
    hour12 = when.hour % 12 or 12
    return {
        "date": when.strftime("%m-%d-%Y"),
        "time": f"{hour12}:{when.minute:02d}{'am' if when.hour < 12 else 'pm'}",
        "arriveBy": "true" if arrive_by else "false",
    }


def _leg(leg, origin: str, destination: str) -> RouteLeg:
    def place(name: str) -> str:
        return {"Origin": origin, "Destination": destination}.get(name, name)

    return RouteLeg(
        mode=MODES.get(leg.mode, leg.mode.lower()),
        line=leg.routeShortName,
        direction=leg.headsign,
        origin=place(leg.origin.name),
        to=place(leg.to.name),
        from_code=leg.origin.stopCode,
        depart=clock(leg.startTime),
        arrive=clock(leg.endTime),
        minutes=round((leg.endTime - leg.startTime) / 60_000),
    )


def _option(it: WireItinerary, now_ms: int, origin: str, destination: str) -> RouteOption:
    return RouteOption(
        leave_at=clock(it.startTime),
        leave_in=(it.startTime - now_ms) // 60_000,
        arrive_at=clock(it.endTime),
        minutes=round(it.duration / 60),
        walk_minutes=round(it.walkTime / 60),
        transfers=it.transfers,
        legs=[_leg(leg, origin, destination) for leg in it.legs],
    )


def answer(
    payload: object,
    origin: Resolved,
    destination: Resolved,
    *,
    when: datetime,
    arrive_by: bool,
    now: datetime,
    limit: int = 3,
) -> RouteAnswer:
    wire = parse(WirePlanResponse, payload)
    itineraries = wire.plan.itineraries if wire.plan else []
    if arrive_by:
        # In time, leaving as late as possible (a minute of slack for rounding).
        limit_ms = int(when.timestamp() * 1000) + 60_000
        itineraries = sorted(
            (it for it in itineraries if it.endTime <= limit_ms), key=lambda it: -it.startTime
        )
    else:
        itineraries = sorted(itineraries, key=lambda it: it.endTime)
    if not itineraries:
        raise NotFound(
            f"No public-transport route from {origin.name} to {destination.name}"
            + (f" arriving by {when:%H:%M}." if arrive_by else "."),
            hint="Try another time, or check the places with `tmb place list`.",
        )
    now_ms = int(now.timestamp() * 1000)
    # Coordinates read badly in a message: a bare point is "tu ubicación" / "tu destino".
    start = "tu ubicación" if origin.kind == "point" else origin.name
    end = "tu destino" if destination.kind == "point" else destination.name
    options = [_option(it, now_ms, start, end) for it in itineraries[:limit]]
    return RouteAnswer(
        origin=origin,
        to=destination,
        arrive_by=when.isoformat() if arrive_by else None,
        depart_at=None if arrive_by else when.isoformat(),
        options=options,
        say=say_route(options[0]),
        updated_at=now.replace(microsecond=0).isoformat(),
    )


def say_route(option: RouteOption) -> str:
    """ "Sal a las 17:42 (en 15 min): 7 min andando hasta Passeig de Gràcia, L2 dirección …"."""
    steps = []
    for leg in option.legs:
        if leg.mode == "walk":
            steps.append(f"{leg.minutes} min andando hasta {leg.to}")
        else:
            towards = f" dirección {leg.direction}" if leg.direction else ""
            steps.append(f"{leg.line or leg.mode}{towards} hasta {leg.to} ({leg.minutes} min)")
    if len(steps) > 1:
        route = ", ".join(steps[:-1]) + " y " + steps[-1]
    else:
        route = steps[0] if steps else "sin tramos"
    if option.leave_in < 0:
        start = f"Tendrías que haber salido a las {hhmm(option.leave_at)}"
    elif option.leave_in == 0:
        start = f"Sal ya ({hhmm(option.leave_at)})"
    elif option.leave_in <= 120:
        start = f"Sal a las {hhmm(option.leave_at)} (en {option.leave_in} min)"
    else:
        start = f"Sal a las {hhmm(option.leave_at)}"
    return f"{start}: {route}. Llegas a las {hhmm(option.arrive_at)}. Según horarios."
