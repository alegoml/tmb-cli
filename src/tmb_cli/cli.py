"""Command-line entry point (`tmb`)."""

from collections.abc import Callable
from typing import Annotated

import typer

from tmb_cli import __version__
from tmb_cli.client import TmbClient
from tmb_cli.config import (
    credentials_path,
    find_credentials,
    load_credentials,
    mask,
    save_credentials,
)
from tmb_cli.errors import TmbError
from tmb_cli.output import emit, emit_error

app = typer.Typer(
    help="Unofficial CLI for TMB (Barcelona) bus and metro arrivals. JSON on stdout.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
auth_app = typer.Typer(help="Manage your TMB API credentials.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")


def _version(value: bool) -> None:
    if value:
        typer.echo(f"tmb-cli {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    pass


def _run(action: Callable[[], object]) -> None:
    """Run a command body and turn our typed errors into JSON + exit codes."""
    try:
        emit(action())
    except TmbError as err:
        emit_error(err)
        raise typer.Exit(err.exit_code) from None


def _client() -> TmbClient:
    creds = load_credentials()
    return TmbClient(creds.app_id, creds.app_key)


# --- auth ---------------------------------------------------------------------


@auth_app.command("set")
def auth_set() -> None:
    """Save your app_id and app_key (prompted; the key is hidden)."""
    app_id = typer.prompt("app_id").strip()
    app_key = typer.prompt("app_key", hide_input=True).strip()
    path = save_credentials(app_id, app_key)
    emit({"saved": True, "path": str(path)})


@auth_app.command("status")
def auth_status() -> None:
    """Show whether credentials are configured (offline, never prints the key)."""
    creds = find_credentials()
    emit(
        {
            "configured": creds is not None,
            "source": creds.source if creds else None,
            "app_id": mask(creds.app_id) if creds else None,
            "config_path": str(credentials_path()),
        }
    )


# --- arrivals -------------------------------------------------------------------


@app.command()
def bus(
    stop: Annotated[str, typer.Argument(help="Bus stop code, e.g. 108.")],
) -> None:
    """Real-time arrivals at a bus stop (raw TMB payload for now)."""

    def action() -> object:
        with _client() as client:
            return client.bus_arrivals(stop)

    _run(action)


@app.command()
def metro(
    stations: Annotated[list[str], typer.Argument(help="One or more metro station codes.")],
) -> None:
    """Real-time arrivals at metro stations (raw TMB payload for now)."""

    def action() -> object:
        with _client() as client:
            return client.metro_arrivals(stations)

    _run(action)


def main() -> None:
    app()
