"""Command-line entry point (`tmb`)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, NoReturn

import typer

from tmb_cli import __version__
from tmb_cli.client import TmbClient
from tmb_cli.config import (
    ENV_APP_ID,
    ENV_APP_KEY,
    credentials_path,
    find_credentials,
    load_credentials,
    mask,
    save_credentials,
)
from tmb_cli.errors import Interrupted, TmbError, UsageError
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


@dataclass
class State:
    no_input: bool = False


@app.callback()
def root(
    ctx: typer.Context,
    no_input: Annotated[
        bool,
        typer.Option(
            "--no-input",
            envvar="TMB_NO_INPUT",
            help="Never prompt; fail with a usage error if input is needed (for agents/scripts).",
        ),
    ] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    ctx.obj = State(no_input=no_input)


def _fail(err: TmbError) -> NoReturn:
    emit_error(err)
    raise typer.Exit(err.exit_code)


def _run(action: Callable[[], object]) -> None:
    """Run a command body and print its result as JSON. Every command goes through here, so any
    failure becomes the JSON error on stderr: our typed errors as they are, anything else by its
    exception type only (messages can embed the request URL, which carries the credentials)."""
    try:
        emit(action())
    except typer.Exit:
        raise
    except TmbError as err:
        _fail(err)
    except typer.Abort:  # a prompt got end of input or Ctrl-C
        _fail(UsageError("Input cancelled."))
    except KeyboardInterrupt:
        _fail(Interrupted("Interrupted."))
    except Exception as exc:
        _fail(TmbError(f"Unexpected internal error: {type(exc).__name__}."))


def _client() -> TmbClient:
    creds = load_credentials()
    return TmbClient(creds.app_id, creds.app_key)


# --- auth ---------------------------------------------------------------------


@auth_app.command("set")
def auth_set(ctx: typer.Context) -> None:
    """Save your app_id and app_key (prompted; the key is hidden)."""

    def action() -> object:
        if ctx.obj.no_input:
            raise UsageError(
                "`tmb auth set` needs to prompt for the keys.",
                hint=f"Run it in a terminal, or export {ENV_APP_ID} and {ENV_APP_KEY} instead.",
            )
        # Prompts go to stderr so stdout stays pure JSON.
        try:
            app_id = typer.prompt("app_id", err=True).strip()
            app_key = typer.prompt("app_key", hide_input=True, err=True).strip()
        except typer.Abort:
            typer.echo(err=True)  # end the prompt line, so the JSON error is a line of its own
            raise UsageError("Input cancelled.") from None
        if not app_id or not app_key:
            raise UsageError("Both app_id and app_key are required.")
        path = save_credentials(app_id, app_key)
        return {"saved": True, "path": str(path)}

    _run(action)


@auth_app.command("status")
def auth_status() -> None:
    """Show whether credentials are configured (offline, never prints the key)."""

    def action() -> object:
        creds = find_credentials()
        return {
            "configured": creds is not None,
            "source": creds.source if creds else None,
            "app_id": mask(creds.app_id) if creds else None,
            "config_path": str(credentials_path()),
        }

    _run(action)


# --- arrivals -------------------------------------------------------------------


@app.command()
def bus(
    stop: Annotated[str, typer.Argument(help="Bus stop code, e.g. 1103.")],
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
