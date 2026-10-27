"""Answers for messaging agents (spec v0.3): resolve whatever the user said (a place, a favourite,
a line, a stop code, a point, or words) into stops, fetch each source once, and answer with
arrivals and a ready-to-send `say` sentence.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from tmb_cli import amb, arrivals, favourites, nearby, network, places, profile, say
from tmb_cli.client import AmbClient, TmbClient
from tmb_cli.errors import MissingCredentials, NotFound, UsageError
from tmb_cli.models import (
    Alternative,
    BusArrivals,
    MetroArrivals,
    NearAnswer,
    NearStop,
    PlannedArrival,
    Resolved,
    StopRef,
    TargetAnswer,
)

AMB_RETRY_AFTER_SECONDS = 3600  # don't re-download AMB's zip more than hourly for unknown trips
LINE = re.compile(r"[A-Za-z]{0,3}\d{1,3}[A-Za-z]{0,2}")  # 67, V15, H12, B7, L3, L9N, X1


def check_codes(kind: str, codes: list[str]) -> None:
    """Codes are numbers; checking keeps anything else out of the request path."""
    for code in codes:
        if not code.isascii() or not code.isdigit():
            raise UsageError(f"{kind} codes are numbers; got `{code}`.")


class Session:
    """One command's view of the sources: caches loaded once, AMB's feed downloaded once."""

    def __init__(
        self, tmb_client: Callable[[], TmbClient], amb_client: Callable[[], AmbClient]
    ) -> None:
        self._tmb_client, self._amb_client = tmb_client, amb_client
        self._tmb_net: network.Network | None = None
        self._tmb_net_loaded = False
        self._amb_net: amb.AmbCache | None = None
        self._feed: amb.Feed | None = None

    @property
    def tmb_net(self) -> network.Network | None:
        """TMB's cached stop list, never downloaded here (it's names and codes only)."""
        if not self._tmb_net_loaded:
            self._tmb_net, self._tmb_net_loaded = network.load_cached(), True
        return self._tmb_net

    def tmb_net_for_search(self) -> network.Network | None:
        """TMB's stop list, downloaded if missing (with keys); None without keys or cache."""
        if self.tmb_net is None:
            try:
                self._tmb_net = network.get_network(self._tmb_client)
            except MissingCredentials:
                pass
        return self._tmb_net

    @property
    def amb_net(self) -> amb.AmbCache:
        if self._amb_net is None:
            self._amb_net = amb.get_cache(self._amb_client)  # AMB's lines come from it (D13)
        return self._amb_net

    @property
    def feed(self) -> amb.Feed:
        if self._feed is None:
            with self._amb_client() as client:
                self._feed = amb.parse_realtime(client.realtime())
        return self._feed

    def bus(self, stop: str, lines: list[str]) -> BusArrivals:
        """TMB and AMB real time for one stop code, merged (spec "AMB"). TMB is asked unless the
        stop is AMB-only, so an AMB-only stop needs no TMB keys."""
        check_codes("Stop", [stop])
        code = str(int(stop))
        amb_stop = self.amb_net.stops.get(code)
        tmb_lists = self.tmb_net.has_stop(code) if self.tmb_net else None
        # Without TMB's list, AMB's zero-padded ids ("001103") mark the stops that are TMB's too.
        amb_only = amb_stop is not None and (
            tmb_lists is False or (tmb_lists is None and not amb_stop.padded)
        )

        parts = []
        if not amb_only:
            with self._tmb_client() as client:
                payload = client.bus_arrivals(stop)
            parts.append(
                arrivals.tmb_bus(payload, lines, drop_other_operators=amb_stop is not None)
            )
        if amb_stop is not None:
            part, unknown = arrivals.amb_bus(self.feed, self.amb_net, code, lines)
            if unknown and time.time() - self.amb_net.downloaded_at > AMB_RETRY_AFTER_SECONDS:
                # New trip ids: AMB republished its GTFS.
                self._amb_net = amb.get_cache(self._amb_client, refresh=True)
                part, _ = arrivals.amb_bus(self.feed, self.amb_net, code, lines)
            parts.append(part)

        result = arrivals.combine(stop, parts)
        # TMB answers an unknown stop like one with no data: only the stop lists can tell.
        if result.stop.name is None and amb_stop is None and tmb_lists is False:
            raise NotFound(
                f"{stop} is not a TMB or AMB bus stop.", hint="Find stops with `tmb stops <name>`."
            )
        return result

    def metro(self, stations: list[str], lines: list[str]) -> MetroArrivals:
        check_codes("Station", stations)
        with self._tmb_client() as client:
            payload = client.metro_arrivals(stations)
        cached = self.tmb_net
        name = cached.station_name if cached else (lambda code: None)
        return arrivals.metro_arrivals(payload, stations, lines, name)


# --- resolving a target -------------------------------------------------------------


@dataclass
class Target:
    kind: str
    name: str
    stops: list[StopRef]
    lines: list[str] = field(default_factory=list)
    point: tuple[float, float] | None = None
    town: str | None = None
    alternatives: list[Alternative] = field(default_factory=list)

    def resolved(self, point: tuple[float, float] | None = None) -> Resolved:
        lat, lon = point or (None, None)
        return Resolved(
            kind=self.kind,
            name=self.name,
            lat=lat,
            lon=lon,
            ambiguous=bool(self.alternatives),
            alternatives=self.alternatives,
        )

    def hedge(self) -> str:
        """ "Entiendo X (Barcelona); si te referías a Y (Gavà), dímelo. " when ambiguous."""
        if not self.alternatives:
            return ""
        alt = self.alternatives[0]
        here = f" ({self.town})" if self.town else ""
        there = alt.town or ("metro" if alt.type == "metro" else "otro sitio")
        return f"Entiendo {self.name}{here}; si te referías a {alt.name} ({there}), dímelo. "


def _place_stops(place: places.Place) -> list[StopRef]:
    return [
        StopRef(type=s.type, name=s.name, codes=s.codes, walk_minutes=s.walk_minutes)
        for s in place.stops
    ]


def _favourite_stops(fav: favourites.Favourite) -> list[StopRef]:
    if fav.type == "bus":
        return [StopRef(type="bus", name=None, codes=fav.codes, walk_minutes=fav.walk_minutes)]
    return [StopRef(type="metro", name=None, codes=fav.codes, walk_minutes=fav.walk_minutes)]


def user_stops() -> list[StopRef]:
    """Every stop of the user's places and favourites, once each (the shortest walk wins)."""
    found: dict[tuple[str, ...], StopRef] = {}
    refs = [s for p in places.load().places for s in _place_stops(p)]
    refs += [s for f in favourites.load().favourites for s in _favourite_stops(f)]
    for ref in refs:
        key = tuple(ref.codes)
        if key not in found or (ref.walk_minutes or 0) < (found[key].walk_minutes or 0):
            found[key] = ref
    return list(found.values())


def resolve(text: str, session: Session) -> Target:
    """Place, favourite, line (when the user has stops), stop code, point, else a name search."""
    if place := places.find(text):
        return Target("place", place.name, _place_stops(place), point=(place.lat, place.lon))
    if fav := favourites.find(text):
        return Target("favourite", fav.name, _favourite_stops(fav))
    mine = user_stops()
    if mine and LINE.fullmatch(text) and len(text) <= 4:
        return Target("line", text.upper(), mine, lines=[text])
    if text.isascii() and text.isdigit():
        return Target("stop", text, [StopRef(type="bus", name=None, codes=[text])])
    if point := nearby.parse_point(text):
        return Target("point", text, _around(point, session), point=point)
    return _search(text, session)


def _around(point: tuple[float, float], session: Session, radius: float = 450) -> list[StopRef]:
    pace = profile.load_prefs().walk_m_per_min
    found = nearby.nearby(
        *point, session.tmb_net_for_search(), session.amb_net, radius=radius, m_per_min=pace
    )
    return [
        StopRef(
            type=c.type,
            name=c.name,
            codes=c.codes,
            walk_minutes=c.walk_minutes,
            distance_m=c.distance_m,
        )
        for c in found
    ]


AMBIGUOUS_M = 500  # an equally good match farther than this is another place


def _search(words: str, session: Session) -> Target:
    tmb_net = session.tmb_net_for_search()
    if not network.normalize(words):
        raise UsageError("Say a place, a stop, a line or a lat,lon point.")
    ranked = (
        network.search(tmb_net, words, amb=session.amb_net, limit=30, ranked=True)
        if tmb_net
        else _search_amb_only(words, session)
    )
    if not ranked:
        raise NotFound(
            f"Nothing called `{words}` among your places, favourites, stops or stations.",
            hint="Save it with `tmb place add`, or search with `tmb stops <words>`.",
        )
    best_rank, best = ranked[0]
    point = _position(best, tmb_net, session.amb_net)
    best_town = getattr(best, "town", None)
    alternatives: list[Alternative] = []
    for rank, other in ranked[1:]:
        if len(alternatives) == 3:
            break
        town = getattr(other, "town", None)
        # Another place, not a neighbour: an exact name elsewhere ("Plaça Catalunya" in Gavà),
        # or as good a match in another town. Prefix twins in the same area aren't ambiguous.
        exact = rank == 0
        other_town = best_town is not None and town is not None and town != best_town
        if not (exact or (other_town and rank <= best_rank)):
            continue
        where = _position(other, tmb_net, session.amb_net)
        if not (point and where and nearby.distance_m(*point, *where) > AMBIGUOUS_M):
            continue
        if (other.name, town) in {(a.name, a.town) for a in alternatives}:
            continue
        codes = list(other.codes.values()) if other.type == "metro" else [other.code]
        alternatives.append(Alternative(name=other.name, type=other.type, town=town, codes=codes))
    town = getattr(best, "town", None)
    if best.type == "metro":
        stop = StopRef(type="metro", name=best.name, codes=list(best.codes.values()))
        return Target(
            "station", best.name, [stop], point=point, town=town, alternatives=alternatives
        )
    stop = StopRef(type="bus", name=best.name, codes=[best.code])
    return Target("stop", best.name, [stop], point=point, town=town, alternatives=alternatives)


def _search_amb_only(words: str, session: Session) -> list:
    empty = network.Network(downloaded_at=0, updated_at="", stops=[], stations=[])
    return network.search(empty, words, amb=session.amb_net, metro=False, limit=30, ranked=True)


def _position(result, tmb_net: network.Network | None, amb_net: amb.AmbCache):
    if result.type == "metro" and tmb_net:
        station = next((s for s in tmb_net.stations if s.codes == result.codes), None)
        return (station.lat, station.lon) if station else None
    if tmb_net and (stop := next((s for s in tmb_net.stops if s.code == result.code), None)):
        return (stop.lat, stop.lon)
    if stop := amb_net.stops.get(result.code):
        return (stop.lat, stop.lon)
    return None


# --- answering ----------------------------------------------------------------------


def _fetch(ref: StopRef, lines: list[str], session: Session) -> tuple[str | None, list, str, str]:
    """(stop name, [(line, destination, minutes, eta, operator, track)], source, updated_at)."""
    if ref.type == "bus":
        result = session.bus(ref.codes[0], lines)
        rows = [
            (a.line, a.destination, a.minutes, a.eta, a.operator, None) for a in result.arrivals
        ]
        return result.stop.name or ref.name, rows, result.source, result.updated_at
    result = session.metro(ref.codes, lines)
    name = next((s.name for s in result.stations if s.name), ref.name)
    rows = [
        (a.line, a.destination, a.minutes, a.eta, "TMB", a.track)
        for s in result.stations
        for a in s.arrivals
    ]
    return name, rows, "TMB", result.updated_at


def _sources(sources: set[str]) -> str:
    return "+".join(s for s in ("TMB", "AMB") if any(s in x for x in sources)) or "TMB"


def answer(
    target: Target, session: Session, *, walk: int | None = None, margin: int = 0
) -> TargetAnswer:
    """Every stop of the target, fetched once each, as one list by time with when to leave."""
    planned: list[PlannedArrival] = []
    stops: list[StopRef] = []
    sources, times = set(), []
    for ref in target.stops:
        name, rows, source, updated_at = _fetch(ref, target.lines, session)
        sources.add(source)
        times.append(updated_at)
        walk_minutes = walk if walk is not None else ref.walk_minutes
        stops.append(ref.model_copy(update={"name": name, "walk_minutes": walk_minutes}))
        for line, destination, minutes, eta, operator, track in rows:
            leave_in = None if walk_minutes is None else minutes - walk_minutes
            planned.append(
                PlannedArrival(
                    line=line,
                    destination=destination,
                    minutes=minutes,
                    eta=eta,
                    operator=operator,
                    stop=name or ref.codes[0],
                    type=ref.type,
                    track=track,
                    walk_minutes=walk_minutes,
                    leave_in=leave_in,
                    make_it=None if leave_in is None else leave_in >= margin,
                )
            )
    planned.sort(key=lambda a: (a.eta, a.line))
    return TargetAnswer(
        resolved=target.resolved(),
        stops=stops,
        arrivals=planned,
        say=target.hedge() + _say(target, planned),
        source=_sources(sources),
        updated_at=min(times) if times else "",
    )


def _say(target: Target, planned: list[PlannedArrival]) -> str:
    where = target.name if target.kind in ("place", "favourite") else None
    if any(a.make_it is not None for a in planned):
        first = next((a for a in planned if a.make_it), None)
        # "Ya no lo pillas" only for an earlier bus of the same line: other lines are noise.
        missed = next(
            (
                a
                for a in planned
                if a.make_it is False and first and a.line == first.line and a.eta < first.eta
            ),
            None,
        )
        return say.catch(
            (first.line, first.eta, first.leave_in, first.stop) if first else None,
            (missed.line, missed.eta) if missed else None,
            nothing=(
                "No llegas a ninguno de los próximos."
                if planned
                else f"Ahora mismo no hay previsiones{' para ' + where if where else ''}."
            ),
        )
    stop = planned[0].stop if planned and len(target.stops) == 1 else None
    return say.arrivals(
        stop,
        [(a.line, a.minutes) for a in planned],
        none=f"Ahora mismo no hay previsiones para {target.name}.",
    )


def near(target: Target, session: Session, *, limit: int = 4) -> NearAnswer:
    """The stops around a point, each with its next arrivals and the walk from there."""
    if target.point is None:
        raise UsageError(f"I don't know where `{target.name}` is.", hint="Pass a lat,lon point.")
    refs = (
        _around(target.point, session)[:limit] if target.kind != "point" else target.stops[:limit]
    )
    result: list[NearStop] = []
    sources, times = set(), []
    for ref in refs:
        name, rows, source, updated_at = _fetch(ref, [], session)
        sources.add(source)
        times.append(updated_at)
        result.append(
            NearStop(
                type=ref.type,
                name=name,
                codes=ref.codes,
                distance_m=ref.distance_m,
                walk_minutes=ref.walk_minutes,
                arrivals=[
                    PlannedArrival(
                        line=line,
                        destination=destination,
                        minutes=minutes,
                        eta=eta,
                        operator=operator,
                        stop=name or ref.codes[0],
                        type=ref.type,
                        track=track,
                        walk_minutes=ref.walk_minutes,
                        leave_in=minutes - (ref.walk_minutes or 0),
                        make_it=minutes >= (ref.walk_minutes or 0),
                    )
                    for line, destination, minutes, eta, operator, track in rows
                ],
            )
        )
    return NearAnswer(
        near=target.resolved(target.point),
        stops=result,
        say=target.hedge() + _say_near(target.name, result),
        source=_sources(sources),
        updated_at=min(times) if times else "",
    )


def _say_near(where: str, stops: list[NearStop]) -> str:
    if not stops:
        return f"No hay paradas de TMB ni AMB a menos de 450 m de {where}."
    parts = []
    for stop in stops:
        catchable = [a for a in stop.arrivals if a.make_it][:2]
        if catchable and len(parts) < 3:
            lines = ", ".join(f"{a.line} en {a.minutes} min" for a in catchable)
            parts.append(f"{stop.name} ({stop.walk_minutes} min andando): {lines}")
    if not parts:
        return "Hay paradas cerca, pero ahora mismo no llegas a nada que pase por ellas."
    return "Cerca: " + "; ".join(parts) + "."


# --- positions, for routes ----------------------------------------------------------


def locate(text: str, session: Session) -> Resolved:
    """Where a target is, for the trip planner: a place, a lat,lon, a stop or station (by name,
    code or favourite). Lines have no position."""
    target = resolve(text, session)
    if target.kind == "line":
        raise UsageError(f"`{text}` is a line, not a place.", hint="Say a place, stop or lat,lon.")
    point = target.point or _position_of_codes(target.stops[0].codes, session)
    if point is None:
        raise NotFound(
            f"I don't know where `{text}` is.",
            hint="Save it with `tmb place add <name> <lat,lon>`, or pass lat,lon.",
        )
    return target.resolved(point)


def _position_of_codes(codes: list[str], session: Session) -> tuple[float, float] | None:
    tmb_net = session.tmb_net_for_search()
    wanted = {str(int(c)) for c in codes}
    if tmb_net:
        for stop in tmb_net.stops:
            if stop.code in wanted:
                return (stop.lat, stop.lon)
        for station in tmb_net.stations:
            if wanted & set(station.codes.values()):
                return (station.lat, station.lon)
    for code in wanted:
        if stop := session.amb_net.stops.get(code):
            return (stop.lat, stop.lon)
    return None


def hedge(resolved: Resolved) -> str:
    """The ambiguity note for a resolved position (routes): "Entiendo X; si te referías a Y…"."""
    if not resolved.ambiguous or not resolved.alternatives:
        return ""
    alt = resolved.alternatives[0]
    there = alt.town or ("metro" if alt.type == "metro" else "otro sitio")
    return f"Entiendo {resolved.name}; si te referías a {alt.name} ({there}), dímelo. "
