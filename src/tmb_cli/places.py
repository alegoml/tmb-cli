"""Places: the user's usual locations (home, work…) with their nearby stops and walk times.

Stored in `places.json` next to favourites and credentials, in a file of its own. Only on the
user's machine (spec v0.3).
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from tmb_cli.config import config_dir
from tmb_cli.errors import NotFound, UsageError
from tmb_cli.favourites import check_name


class PlaceStop(BaseModel):
    type: Literal["bus", "metro"]
    name: str
    codes: list[str]
    network: Literal["TMB", "AMB"]
    distance_m: int
    walk_minutes: int = Field(ge=0)
    estimated: bool = True  # False once the user gives their own walk time


class Place(BaseModel):
    name: str
    lat: float
    lon: float
    label: str | None = None  # the address as the user said it
    stops: list[PlaceStop]


class Places(BaseModel):
    places: list[Place] = []


def places_path() -> Path:
    return config_dir() / "places.json"


def load() -> Places:
    path = places_path()
    try:
        return Places.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return Places()
    except (OSError, ValidationError):
        raise UsageError(
            "The places file is unreadable or not valid.", hint=f"Fix or delete {path}."
        ) from None


def _save(places: Places) -> None:
    path = places_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(places.model_dump_json(indent=2))
    os.replace(tmp, path)


def find(name: str) -> Place | None:
    return next((p for p in load().places if p.name == name), None)


def add(place: Place) -> bool:
    """Save it, replacing one with the same name. True if it replaced one."""
    check_name(place.name)
    current = load()
    others = [p for p in current.places if p.name != place.name]
    _save(Places(places=[*others, place]))
    return len(others) < len(current.places)


def remove(name: str) -> None:
    current = load()
    others = [p for p in current.places if p.name != name]
    if len(others) == len(current.places):
        raise NotFound(f"No place named `{name}`.", hint="See them with `tmb place list`.")
    _save(Places(places=others))


def set_walk(name: str, code: str, minutes: int) -> Place:
    """The user's own walk time to one of a place's stops (`code`: any of the stop's codes)."""
    current = load()
    place = next((p for p in current.places if p.name == name), None)
    if place is None:
        raise NotFound(f"No place named `{name}`.", hint="See them with `tmb place list`.")
    stop = next((s for s in place.stops if code in s.codes), None)
    if stop is None:
        raise NotFound(
            f"Place `{name}` has no stop {code}.",
            hint=f"Its stops: {', '.join(s.codes[0] for s in place.stops) or 'none'}.",
        )
    stop.walk_minutes, stop.estimated = minutes, False
    _save(current)
    return place
