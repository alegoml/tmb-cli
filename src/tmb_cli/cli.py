"""Command-line entry point (`tmb`)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, NoReturn

import typer

from tmb_cli import __version__, arrivals, favourites, network
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
from tmb_cli.errors import Interrupted, NotFound, TmbError, UsageError
from tmb_cli.favourites import Favourite
from tmb_cli.models import BusArrivals, MetroArrivals, StopSearch, Target
from tmb_cli.output import emit, emit_error

app = typer.Typer(
    help="Unofficial CLI for TMB (Barcelona) bus and metro arrivals. JSON on stdout.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
auth_app = typer.Typer(help="Manage your TMB API credentials.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")
fav_app = typer.Typer(
    help="Favourite stops and stations, with your walk time to them.", no_args_is_help=True
)
app.add_typer(fav_app, name="fav")


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


def _check_codes(kind: str, codes: list[str]) -> None:
    """Codes are numbers; checking keeps anything else out of the request path."""
    for code in codes:
        if not code.isascii() or not code.isdigit():
            raise UsageError(f"{kind} codes are numbers; got `{code}`.")


LineOption = Annotated[
    list[str] | None,
    typer.Option("--line", "-l", help="Only this line (case-insensitive). Repeatable."),
]


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


def _bus(stop: str, lines: list[str]) -> BusArrivals:
    _check_codes("Stop", [stop])
    with _client() as client:
        payload = client.bus_arrivals(stop)
    result = arrivals.bus_arrivals(payload, stop, lines)
    # TMB answers an unknown stop like one with no data: only the cache can tell them apart.
    cached = network.load_cached() if result.stop.name is None else None
    if cached and not cached.has_stop(str(int(stop))):
        raise NotFound(f"No bus stop {stop}.", hint="Find it with `tmb stops <name>`.")
    return result


def _metro(stations: list[str], lines: list[str]) -> MetroArrivals:
    _check_codes("Station", stations)
    with _client() as client:
        payload = client.metro_arrivals(stations)
    cached = network.load_cached()  # names only: never download for a real-time query
    name = cached.station_name if cached else (lambda code: None)
    return arrivals.metro_arrivals(payload, stations, lines, name)


@app.command()
def bus(
    stop: Annotated[str, typer.Argument(help="Bus stop code, e.g. 1103.")],
    line: LineOption = None,
) -> None:
    """Next buses at a stop, soonest first."""
    _run(lambda: _bus(stop, line or []).model_dump())


@app.command()
def metro(
    stations: Annotated[
        list[str],
        typer.Argument(help="Station codes, one per line: Catalunya is 126 (L1), 326 (L3)."),
    ],
    line: LineOption = None,
) -> None:
    """Next trains at metro stations, soonest first per station."""
    _run(lambda: _metro(stations, line or []).model_dump())


@app.command("next")
def next_(
    target: Annotated[
        str, typer.Argument(help="A favourite's name, or a stop/station code with --walk.")
    ],
    walk: Annotated[
        int | None,
        typer.Option(
            "--walk", min=0, help="Minutes you take to get there (overrides the favourite's)."
        ),
    ] = None,
    margin: Annotated[
        int, typer.Option("--margin", min=0, help="Spare minutes you want at the stop.")
    ] = 0,
    metro_code: Annotated[
        bool, typer.Option("--metro", help="TARGET is a metro station code, not a bus stop.")
    ] = False,
    line: LineOption = None,
) -> None:
    """Next arrivals, each with `leave_in` (minutes until you must set off) and `make_it`."""

    def action() -> object:
        if target.isascii() and target.isdigit():
            if walk is None:
                raise UsageError(
                    "Pass --walk with a code (minutes you take to get there).",
                    hint="Or save it once: `tmb fav add <name> <code> --walk <minutes>`.",
                )
            kind = "metro" if metro_code else "bus"
            goal = Target(name=None, type=kind, codes=[target], walk_minutes=walk)
        else:
            fav = favourites.find(target)
            if fav is None:
                raise NotFound(f"No favourite named `{target}`.", hint="See them: `tmb fav list`.")
            if metro_code:
                raise UsageError("--metro is for codes; a favourite already knows its type.")
            minutes = fav.walk_minutes if walk is None else walk
            goal = Target(name=fav.name, type=fav.type, codes=fav.codes, walk_minutes=minutes)

        if goal.type == "bus":
            return arrivals.bus_next(_bus(goal.codes[0], line or []), goal, margin).model_dump()
        return arrivals.metro_next(_metro(goal.codes, line or []), goal, margin).model_dump()

    _run(action)


# --- favourites ---------------------------------------------------------------------


@fav_app.command("add")
def fav_add(
    name: Annotated[str, typer.Argument(help="Lowercase name, e.g. casa.")],
    codes: Annotated[
        list[str], typer.Argument(help="Bus stop code, or a station's codes (one per line).")
    ],
    walk: Annotated[int, typer.Option("--walk", min=0, help="Minutes you take to get there.")],
    metro_codes: Annotated[bool, typer.Option("--metro", help="CODES are metro stations.")] = False,
) -> None:
    """Save (or replace) a favourite stop or station with your walk time to it."""

    def action() -> object:
        favourites.check_name(name)
        _check_codes("Station" if metro_codes else "Stop", codes)
        if not metro_codes and len(codes) > 1:
            raise UsageError("A bus favourite has one stop code.", hint="For metro, add --metro.")
        cached = network.load_cached()  # check the codes when we can; never download for this
        if cached:
            for code in codes:
                known = (
                    cached.station_name(str(int(code)))
                    if metro_codes
                    else cached.has_stop(str(int(code)))
                )
                if not known:
                    kind = "metro station" if metro_codes else "bus stop"
                    raise NotFound(f"No {kind} {code}.", hint="Find it with `tmb stops <name>`.")
        fav = Favourite(
            name=name,
            type="metro" if metro_codes else "bus",
            codes=[str(int(code)) for code in codes],
            walk_minutes=walk,
        )
        replaced = favourites.add(fav)
        return {"favourite": fav.model_dump(), "replaced": replaced}

    _run(action)


@fav_app.command("list")
def fav_list() -> None:
    """List your favourites."""
    _run(lambda: favourites.load().model_dump())


@fav_app.command("remove")
def fav_remove(name: Annotated[str, typer.Argument(help="The favourite's name.")]) -> None:
    """Delete a favourite."""

    def action() -> object:
        favourites.remove(name)
        return {"removed": name}

    _run(action)


# --- static network -------------------------------------------------------------------


@app.command()
def stops(
    query: Annotated[str, typer.Argument(help="Part of a stop or station name, e.g. catalunya.")],
    bus_only: Annotated[bool, typer.Option("--bus", help="Only bus stops.")] = False,
    metro_only: Annotated[bool, typer.Option("--metro", help="Only metro stations.")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Most results to return.")] = 10,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Download the network again first.")
    ] = False,
) -> None:
    """Find stop and station codes by name (ignores case and accents). Metro stations list one
    code per line. Downloads the static network on first use and weekly after that."""

    def action() -> object:
        if bus_only and metro_only:
            raise UsageError("Pass --bus or --metro, not both.")
        if not network.normalize(query):
            raise UsageError("The query needs at least one letter or digit.")
        net = network.get_network(_client, refresh=refresh)
        results = network.search(net, query, bus=not metro_only, metro=not bus_only, limit=limit)
        return StopSearch(query=query, results=results, updated_at=net.updated_at).model_dump()

    _run(action)


def main() -> None:
    app()
