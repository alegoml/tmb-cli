"""Credential lookup: environment variables first, then the user's config file.

Get a free app_id / app_key at https://developer.tmb.cat/ (create an application).
Credentials are never printed, logged or included in error messages.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from tmb_cli.errors import MissingCredentials

ENV_APP_ID = "TMB_APP_ID"
ENV_APP_KEY = "TMB_APP_KEY"
ENV_CONFIG_DIR = "TMB_CLI_CONFIG_DIR"  # override, mainly for tests


@dataclass(frozen=True)
class Credentials:
    app_id: str
    app_key: str
    source: str  # "env" or "file"


def config_dir() -> Path:
    if override := os.environ.get(ENV_CONFIG_DIR):
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "tmb-cli"


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


def find_credentials() -> Credentials | None:
    app_id, app_key = os.environ.get(ENV_APP_ID), os.environ.get(ENV_APP_KEY)
    if app_id and app_key:
        return Credentials(app_id, app_key, "env")

    path = credentials_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        # Never echo the file's content: it holds the key.
        raise MissingCredentials(
            "The credentials file is unreadable or not valid JSON.",
            hint="Run `tmb auth set` to write it again.",
        ) from None
    if isinstance(data, dict) and data.get("app_id") and data.get("app_key"):
        return Credentials(str(data["app_id"]), str(data["app_key"]), "file")
    return None


def load_credentials() -> Credentials:
    creds = find_credentials()
    if creds is None:
        raise MissingCredentials(
            "No TMB API credentials found.",
            hint=f"Run `tmb auth set` or export {ENV_APP_ID} and {ENV_APP_KEY}. "
            "Free keys, step by step: https://github.com/alegoml/tmb-cli#get-your-tmb-keys-about-2-minutes",
        )
    return creds


def save_credentials(app_id: str, app_key: str) -> Path:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create the file as owner-only before writing the secret into it.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"app_id": app_id, "app_key": app_key}, f)
    path.chmod(0o600)
    return path


def mask(value: str) -> str:
    return value[:3] + "…" if len(value) > 3 else "…"
