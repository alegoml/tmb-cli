"""Favourites: a local name for a stop or station plus the user's walk time to it.

Stored in `favourites.json` next to `credentials.json` but in a separate file, so sharing one never
leaks the other. Only on the user's machine.
"""

import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from tmb_cli.config import config_dir
from tmb_cli.errors import NotFound, UsageError

NAME = re.compile(r"[a-z][a-z0-9-]*")  # starts with a letter, so it never looks like a code


class Favourite(BaseModel):
    name: str
    type: Literal["bus", "metro"]
    codes: list[str]  # one for a bus stop; a metro station can have one per line
    walk_minutes: int = Field(ge=0)


class Favourites(BaseModel):
    favourites: list[Favourite] = []


def favourites_path() -> Path:
    return config_dir() / "favourites.json"


def load() -> Favourites:
    path = favourites_path()
    try:
        return Favourites.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return Favourites()
    except (OSError, ValidationError):
        raise UsageError(
            "The favourites file is unreadable or not valid.",
            hint=f"Fix or delete {path}.",
        ) from None


def _save(favourites: Favourites) -> None:
    path = favourites_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(favourites.model_dump_json(indent=2))
    os.replace(tmp, path)


def check_name(name: str) -> None:
    if not NAME.fullmatch(name):
        raise UsageError(
            f"Invalid favourite name `{name}`.",
            hint="Use lowercase letters, digits and `-`, starting with a letter (e.g. `casa`).",
        )


def find(name: str) -> Favourite | None:
    return next((f for f in load().favourites if f.name == name), None)


def add(favourite: Favourite) -> bool:
    """Save it, replacing one with the same name. True if it replaced one."""
    check_name(favourite.name)
    current = load()
    others = [f for f in current.favourites if f.name != favourite.name]
    _save(Favourites(favourites=[*others, favourite]))
    return len(others) < len(current.favourites)


def remove(name: str) -> None:
    current = load()
    others = [f for f in current.favourites if f.name != name]
    if len(others) == len(current.favourites):
        raise NotFound(f"No favourite named `{name}`.", hint="See them with `tmb fav list`.")
    _save(Favourites(favourites=others))
