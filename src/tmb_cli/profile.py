"""The user's trips and preferences (spec v0.5), each in its own file next to places and
favourites. Only on the user's machine.
"""

import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from tmb_cli.config import config_dir
from tmb_cli.errors import NotFound, UsageError
from tmb_cli.favourites import check_name

DAYS = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
DAY_ALIASES = {
    "l": "lun", "lunes": "lun", "mon": "lun",
    "m": "mar", "martes": "mar", "tue": "mar",
    "x": "mie", "mié": "mie", "miercoles": "mie", "miércoles": "mie", "wed": "mie",
    "j": "jue", "jueves": "jue", "thu": "jue",
    "v": "vie", "viernes": "vie", "fri": "vie",
    "s": "sab", "sáb": "sab", "sabado": "sab", "sábado": "sab", "sat": "sab",
    "d": "dom", "domingo": "dom", "sun": "dom",
}  # fmt: skip
DAY_GROUPS = {
    "laborables": DAYS[:5],
    "entresemana": DAYS[:5],
    "finde": DAYS[5:],
    "findesemana": DAYS[5:],
    "diario": DAYS,
    "todos": DAYS,
}
PACE_M_PER_MIN = {"slow": 65, "normal": 80, "fast": 95}
TIME = re.compile(r"\d{1,2}(:\d{2})?")


def parse_days(text: str) -> list[str]:
    """ "lun-vie", "l-v", "sab,dom", "laborables", "diario" → canonical day names, in week order."""
    found: set[str] = set()
    for part in text.lower().replace(" ", "").split(","):
        if part in DAY_GROUPS:
            found.update(DAY_GROUPS[part])
            continue
        ends = [DAY_ALIASES.get(p, p) for p in part.split("-")]
        if not all(e in DAYS for e in ends) or len(ends) > 2:
            raise UsageError(
                f"`{text}` is not a set of days.", hint="E.g. lun-vie, sab,dom, laborables, diario."
            )
        a, b = DAYS.index(ends[0]), DAYS.index(ends[-1])
        found.update(DAYS[a : b + 1] if a <= b else DAYS[a:] + DAYS[: b + 1])
    return [d for d in DAYS if d in found]


class Trip(BaseModel):
    name: str
    origin: str = Field(serialization_alias="from")  # a place name, lat,lon or stop name
    to: str
    by: str | None = None  # arrive by, "HH:MM"
    days: list[str] = []


class Trips(BaseModel):
    trips: list[Trip] = []


class Prefs(BaseModel):
    margin: int = Field(0, ge=0)  # default spare minutes at the stop
    pace: Literal["slow", "normal", "fast"] = "normal"
    notify: str | None = None  # default alert target: ntfy:<topic> or webhook:<url> (spec v0.6)
    # Setup questions already asked (spec v0.5): optional items aren't asked twice.
    asked: list[str] = []

    @property
    def walk_m_per_min(self) -> int:
        return PACE_M_PER_MIN[self.pace]


def _path(name: str) -> Path:
    return config_dir() / name


def _load[M: BaseModel](model: type[M], name: str) -> M:
    path = _path(name)
    try:
        return model.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return model()
    except (OSError, ValidationError):
        raise UsageError(
            f"The file {name} is unreadable or not valid.", hint=f"Fix or delete {path}."
        ) from None


def _save(model: BaseModel, name: str) -> None:
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(model.model_dump_json(indent=2))
    os.replace(tmp, path)


def load_trips() -> Trips:
    return _load(Trips, "trips.json")


def find_trip(name: str) -> Trip | None:
    return next((t for t in load_trips().trips if t.name == name), None)


def add_trip(trip: Trip) -> bool:
    check_name(trip.name)
    if trip.by is not None and not TIME.fullmatch(trip.by):
        raise UsageError(f"`{trip.by}` is not a time.", hint="Use HH:MM, e.g. 9:00.")
    current = load_trips()
    others = [t for t in current.trips if t.name != trip.name]
    _save(Trips(trips=[*others, trip]), "trips.json")
    mark_asked("trips")
    return len(others) < len(current.trips)


def remove_trip(name: str) -> None:
    current = load_trips()
    others = [t for t in current.trips if t.name != name]
    if len(others) == len(current.trips):
        raise NotFound(f"No trip named `{name}`.", hint="See them with `tmb trip list`.")
    _save(Trips(trips=others), "trips.json")


def load_prefs() -> Prefs:
    return _load(Prefs, "prefs.json")


def save_prefs(prefs: Prefs) -> None:
    _save(prefs, "prefs.json")


def mark_asked(item: str) -> None:
    prefs = load_prefs()
    if item not in prefs.asked:
        save_prefs(prefs.model_copy(update={"asked": [*prefs.asked, item]}))
