"""Data models.

`Wire*` models describe the TMB responses we read, with only the fields we use; anything else
TMB sends is ignored, so new fields don't break us. Shapes come from real captures
(docs/tmb-api.md). The other models are our own output: the stable JSON contract of the CLI.
"""

from pydantic import BaseModel, ConfigDict, ValidationError

from tmb_cli.errors import ApiChanged


class Wire(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


def parse[W: Wire](model: type[W], payload: object) -> W:
    """Validate a TMB response; a mismatch means TMB changed something (`api_changed`)."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        where = ".".join(str(part) for part in exc.errors()[0]["loc"]) or "response"
        raise ApiChanged(
            f"TMB API response has an unexpected shape (at `{where}`).",
            hint="The TMB API may have changed; please open an issue.",
        ) from None


# --- TMB real time: bus (itransit/bus/parades/{stop}) ---------------------------


class WireBus(Wire):
    temps_arribada: int  # epoch milliseconds


class WireBusRoute(Wire):
    transit_namespace: str  # "bus" = TMB's line, "amb" = another AMB operator's
    nom_linia: str
    desti_trajecte: str
    propers_busos: list[WireBus]


class WireBusStop(Wire):
    codi_parada: str
    nom_parada: str
    linies_trajectes: list[WireBusRoute]


class WireBusResponse(Wire):
    timestamp: int  # epoch milliseconds
    parades: list[WireBusStop]


# --- TMB real time: metro (itransit/metro/estacions?estacions=…) ------------------


class WireTrain(Wire):
    temps_arribada: int


class WireMetroRoute(Wire):
    nom_linia: str
    desti_trajecte: str
    propers_trens: list[WireTrain]


class WireMetroStation(Wire):
    codi_via: int
    codi_estacio: int
    linies_trajectes: list[WireMetroRoute]


class WireMetroLine(Wire):
    estacions: list[WireMetroStation]


class WireMetroResponse(Wire):
    timestamp: int
    linies: list[WireMetroLine]


# --- TMB static network (transit/…, GeoJSON) ----------------------------------------


class WireStopProps(Wire):
    CODI_PARADA: int
    NOM_PARADA: str
    DESC_PARADA: str | None  # null on one stop in the 25/10/2026 capture
    NOM_POBLACIO: str  # town: "Barcelona", "Montcada i Reixac", …
    DATA: str  # dataset date, "2026-10-24Z"


class WirePoint(Wire):
    coordinates: tuple[float, float]  # GeoJSON order: (lon, lat), EPSG:4326


class WireStopFeature(Wire):
    geometry: WirePoint
    properties: WireStopProps


class WireStops(Wire):  # transit/parades
    features: list[WireStopFeature]


class WireLineProps(Wire):
    CODI_LINIA: int
    NOM_LINIA: str


class WireLineFeature(Wire):
    properties: WireLineProps


class WireLines(Wire):  # transit/linies/metro
    features: list[WireLineFeature]


class WireStationProps(Wire):
    CODI_ESTACIO: int  # the real-time code, one per line
    CODI_GRUP_ESTACIO: int  # shared by the lines of an interchange
    NOM_ESTACIO: str
    NOM_LINIA: str
    DATA: str


class WireStationFeature(Wire):
    geometry: WirePoint
    properties: WireStationProps


class WireStations(Wire):  # transit/linies/metro/{line}/estacions
    features: list[WireStationFeature]


# --- Output ---------------------------------------------------------------------


class Output(BaseModel):
    model_config = ConfigDict(frozen=True)


class Arrival(Output):
    line: str
    destination: str
    minutes: int
    eta: str
    operator: str  # "TMB", or the AMB operator's name as AMB publishes it


class MetroArrival(Output):
    line: str
    destination: str
    track: int
    minutes: int
    eta: str


class Stop(Output):
    code: str
    name: str | None


class BusArrivals(Output):
    stop: Stop
    arrivals: list[Arrival]
    say: str = ""
    source: str = "TMB"
    updated_at: str


class Station(Output):
    code: str
    name: str | None  # not in the real-time response: from the cache, None without one
    arrivals: list[MetroArrival]


class MetroArrivals(Output):
    stations: list[Station]
    say: str = ""
    source: str = "TMB"
    updated_at: str


class BusStopResult(Output):
    type: str = "bus"
    code: str
    name: str
    description: str | None
    town: str | None
    network: str  # "TMB" or "AMB" (an AMB-only stop: no TMB keys needed)


class StationResult(Output):
    type: str = "metro"
    name: str
    codes: dict[str, str]  # line → real-time station code, e.g. {"L1": "126", "L3": "326"}


class StopSearch(Output):
    query: str
    results: list[BusStopResult | StationResult]
    source: str = "TMB"
    updated_at: str  # the older dataset date of the cached networks


# --- v0.3: any target, near (spec "v0.3: agent-native") -----------------------------


class StopRef(Output):
    type: str  # "bus" or "metro"
    name: str | None
    codes: list[str]
    walk_minutes: int | None = None  # None: no walk time known (a bare code or a search)
    distance_m: int | None = None  # from the point asked, when there is one


class PlannedArrival(Output):
    line: str
    destination: str
    minutes: int
    eta: str
    operator: str
    stop: str
    type: str
    track: int | None  # metro only
    walk_minutes: int | None
    leave_in: int | None  # None without a walk time
    make_it: bool | None


class Resolved(Output):
    kind: str  # place, favourite, line, stop, station, point
    name: str
    lat: float | None = None
    lon: float | None = None


class TargetAnswer(Output):
    resolved: Resolved
    stops: list[StopRef]
    arrivals: list[PlannedArrival]
    say: str
    source: str
    updated_at: str


class NearStop(Output):
    type: str
    name: str | None
    codes: list[str]
    distance_m: int | None
    walk_minutes: int | None
    arrivals: list[PlannedArrival]


class NearAnswer(Output):
    near: Resolved
    stops: list[NearStop]
    say: str
    source: str
    updated_at: str
