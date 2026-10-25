"""Data models.

`Wire*` models describe the TMB responses we read, with only the fields we use; anything else
TMB sends is ignored, so new fields don't break us. Shapes come from real captures
(docs/tmb-api.md). The other models are our own output: the stable JSON contract of the CLI.
"""

from pydantic import BaseModel, ConfigDict


class Wire(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


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
    name: str | None  # the real-time response has no names; filled from the cache (roadmap 6)
    arrivals: list[MetroArrival]


class MetroArrivals(Output):
    stations: list[Station]
    source: str = "TMB"
    updated_at: str
