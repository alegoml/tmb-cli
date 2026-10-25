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
    DATA: str  # dataset date, "2026-10-24Z"


class WireStopFeature(Wire):
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
    source: str = "TMB"
    updated_at: str


class Station(Output):
    code: str
    name: str | None  # not in the real-time response: from the cache, None without one
    arrivals: list[MetroArrival]


class MetroArrivals(Output):
    stations: list[Station]
    source: str = "TMB"
    updated_at: str


class BusStopResult(Output):
    type: str = "bus"
    code: str
    name: str
    description: str | None


class StationResult(Output):
    type: str = "metro"
    name: str
    codes: dict[str, str]  # line → real-time station code, e.g. {"L1": "126", "L3": "326"}


class StopSearch(Output):
    query: str
    results: list[BusStopResult | StationResult]
    source: str = "TMB"
    updated_at: str  # TMB's dataset date of the cached network
