"""Command-line entry point (`tmb`)."""

import os
import secrets
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from typing import Annotated, NoReturn

import typer

from tmb_cli import (
    __version__,
    amb,
    answers,
    arrivals,
    favourites,
    nearby,
    network,
    notify,
    places,
    profile,
    routes,
    say,
)
from tmb_cli.arrivals import MADRID
from tmb_cli.client import AmbClient, TmbClient
from tmb_cli.config import (
    ENV_APP_ID,
    ENV_APP_KEY,
    credentials_path,
    find_credentials,
    load_credentials,
    mask,
    save_credentials,
)
from tmb_cli.errors import Interrupted, MissingCredentials, NotFound, TmbError, UsageError
from tmb_cli.favourites import Favourite
from tmb_cli.models import BusArrivals, MetroArrivals, StopRef, StopSearch, WatchEvent
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
place_app = typer.Typer(
    help="Your usual places (home, work…) with their nearby stops and walk times.",
    no_args_is_help=True,
)
app.add_typer(place_app, name="place")
trip_app = typer.Typer(
    help="Usual trips (casa → trabajo by 9:00, on weekdays): `tmb leave <trip>` uses them.",
    no_args_is_help=True,
)
app.add_typer(trip_app, name="trip")
skills_app = typer.Typer(help="The guide for coding agents (SKILL.md).", no_args_is_help=True)
app.add_typer(skills_app, name="skills")


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


def _run(action: Callable[[], object], *, text: bool = False) -> None:
    """Run a command body and print its result as JSON (or as is, with `text`). Every command goes
    through here, so any failure becomes the JSON error on stderr: our typed errors as they are,
    anything else by its exception type only (messages can embed the request URL, which carries
    the credentials)."""
    try:
        result = action()
        if text:
            sys.stdout.write(str(result))
        else:
            emit(result)
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


def _amb_client() -> AmbClient:
    return AmbClient()


def _session() -> answers.Session:
    # Lambdas, so tests that swap _client/_amb_client are honoured at call time.
    return answers.Session(lambda: _client(), lambda: _amb_client())


def _bus(stop: str, lines: list[str]) -> BusArrivals:
    return _session().bus(stop, lines)


def _metro(stations: list[str], lines: list[str]) -> MetroArrivals:
    return _session().metro(stations, lines)


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
        list[str],
        typer.Argument(
            help="Anything: a place (casa), a favourite, a line (67), a stop code, a lat,lon "
            "point or a name (plaça catalunya)."
        ),
    ],
    walk: Annotated[
        int | None,
        typer.Option("--walk", min=0, help="Minutes you take to get there (overrides saved ones)."),
    ] = None,
    margin: Annotated[
        int | None,
        typer.Option("--margin", min=0, help="Spare minutes at the stop (default: your prefs)."),
    ] = None,
    metro_code: Annotated[
        bool, typer.Option("--metro", help="TARGET is a metro station code, not a bus stop.")
    ] = False,
    line: LineOption = None,
) -> None:
    """What's coming and when to leave, as one list by time with `leave_in`/`make_it` per arrival
    and a ready-to-send `say` sentence."""

    def action() -> object:
        text = " ".join(target)
        session = _session()
        if metro_code:
            answers.check_codes("Station", [text])
            goal = answers.Target(
                "station", text, [StopRef(type="metro", name=None, codes=[str(int(text))])]
            )
        else:
            goal = answers.resolve(text, session)
        goal.lines += line or []
        spare = profile.load_prefs().margin if margin is None else margin
        return answers.answer(goal, session, walk=walk, margin=spare).model_dump()

    _run(action)


@app.command()
def near(
    where: Annotated[
        list[str],
        typer.Argument(help="Your location as lat,lon, a place (casa) or a name."),
    ],
    limit: Annotated[int, typer.Option("--limit", min=1, max=6, help="Most stops to show.")] = 4,
) -> None:
    """The stops and stations around a point, each with its next arrivals and the walk there."""

    def action() -> object:
        session = _session()
        return answers.near(
            answers.resolve(" ".join(where), session), session, limit=limit
        ).model_dump()

    _run(action)


NotifyOption = Annotated[
    str | None,
    typer.Option(
        "--notify",
        help="Also send the alert: ntfy:<topic>, ntfy:https://host/<topic>, webhook:<url>, "
        "or none (default: your prefs).",
    ),
]


def _notify_target(option: str | None) -> str | None:
    """The target for this alert: the option, else the user's default; checked up front."""
    target = profile.load_prefs().notify if option is None else option
    if target in (None, "", "none"):
        return None
    notify.parse(target)  # a bad target is a usage error now, not when the alert fires
    return target


def _deliver(target: str | None, event: dict) -> dict:
    if target is None or event.get("event") == "timeout":
        return event
    result = notify.send(target, "tmb", event["say"], event)
    if warning := notify.warning(target):
        result["warning"] = warning
    return {**event, "notified": result}


_sleep = time.sleep  # swapped in tests
_now = time.monotonic


@app.command()
def watch(
    target: Annotated[
        list[str], typer.Argument(help="Like `tmb next`: a place, favourite, line, code or name.")
    ],
    minutes: Annotated[
        int | None,
        typer.Option("--minutes", min=0, help="Fire when the next arrival is this close."),
    ] = None,
    leave: Annotated[
        bool, typer.Option("--leave", help="Fire when it's time to set off to catch the next one.")
    ] = False,
    walk: Annotated[
        int | None, typer.Option("--walk", min=0, help="Minutes you take to get there.")
    ] = None,
    margin: Annotated[
        int | None,
        typer.Option("--margin", min=0, help="Spare minutes at the stop (default: your prefs)."),
    ] = None,
    every: Annotated[
        int, typer.Option("--every", min=20, max=300, help="Seconds between checks.")
    ] = 30,
    timeout: Annotated[
        int, typer.Option("--timeout", min=1, max=240, help="Give up after this many minutes.")
    ] = 60,
    to: NotifyOption = None,
    line: LineOption = None,
) -> None:
    """Wait, checking every --every seconds, and exit with one event as soon as the condition
    holds: run it in the background and tell the user when it ends."""

    def action() -> object:
        if (minutes is None) == (not leave):
            raise UsageError("Pass either --minutes N or --leave.")
        text = " ".join(target)
        alert_to = _notify_target(to)
        goal = answers.resolve(text, _session())
        goal.lines += line or []
        if leave and walk is None and all(s.walk_minutes is None for s in goal.stops):
            raise UsageError(
                "--leave needs a walk time.",
                hint="Use a place or favourite, or pass --walk <minutes>.",
            )
        spare = profile.load_prefs().margin if margin is None else margin
        started, checked = _now(), 0
        while True:
            checked += 1
            try:
                found = answers.answer(goal, _session(), walk=walk, margin=spare)
            except TmbError as err:
                if not err.retryable:
                    raise
                found = None
            if found:
                event = _watch_event(found, minutes, leave, spare, checked)
                if event:
                    return _deliver(alert_to, event.model_dump())
            if _now() - started + every > timeout * 60:
                return WatchEvent(
                    event="timeout",
                    target=found.resolved
                    if found
                    else answers.Resolved(kind=goal.kind, name=goal.name),
                    arrival=None,
                    say=say.watch_timeout(goal.name, timeout),
                    checked=checked,
                    source=found.source if found else "TMB",
                    updated_at=found.updated_at if found else "",
                ).model_dump()
            _sleep(every)

    _run(action)


def _watch_event(found, minutes: int | None, leave: bool, margin: int, checked: int):
    def event(name: str, arrival, text: str) -> WatchEvent:
        return WatchEvent(
            event=name,
            target=found.resolved,
            arrival=arrival,
            say=text,
            checked=checked,
            source=found.source,
            updated_at=found.updated_at,
        )

    if minutes is not None:
        due = next((a for a in found.arrivals if a.minutes <= minutes), None)
        return event("due", due, say.due(due.line, due.minutes, due.stop)) if due else None
    # --leave: the next arrival the user can still catch; fire when it's time to go.
    catchable = next(
        (a for a in found.arrivals if a.leave_in is not None and a.leave_in >= 0), None
    )
    if catchable and catchable.leave_in <= margin:
        text = say.leave_now(
            catchable.line, catchable.eta, catchable.minutes, catchable.stop, catchable.walk_minutes
        )
        return event("leave_now", catchable, text)
    return None


def _clock() -> datetime:  # swapped in tests
    return datetime.now(MADRID)


ByOption = Annotated[
    str | None, typer.Option("--by", help="Arrive by this time (HH:MM, Barcelona time).")
]
DayOption = Annotated[
    str | None, typer.Option("--day", help="YYYY-MM-DD (default: today, or tomorrow if past).")
]


def _plan(origin: str, destination: str, by: str | None, at: str | None, day: str | None):
    if by and at:
        raise UsageError("Pass --by or --at, not both.")
    session = _session()
    start = answers.locate(origin, session)
    end = answers.locate(destination, session)
    now = _clock()
    when = routes.deadline(by or at, day, now) if (by or at) else now
    with _client() as client:
        payload = client.plan(
            (start.lat, start.lon), (end.lat, end.lon), routes.planner_params(when, bool(by))
        )
    found = routes.answer(payload, start, end, when=when, arrive_by=bool(by), now=now)
    note = answers.hedge(start) + answers.hedge(end)
    return found.model_copy(update={"say": note + found.say}) if note else found


@app.command()
def route(
    origin: Annotated[
        str, typer.Argument(help="From: a place, lat,lon, a stop/station name, or a saved trip.")
    ],
    destination: Annotated[
        str | None, typer.Argument(help="To: the same kinds as FROM (not with a trip).")
    ] = None,
    by: ByOption = None,
    at: Annotated[
        str | None, typer.Option("--at", help="Leave at this time (HH:MM). Default: now.")
    ] = None,
    day: DayOption = None,
) -> None:
    """Up to 3 public-transport options from TMB's trip planner (timetables, not real time)."""

    def action() -> object:
        start, end, deadline = origin, destination, by
        if end is None:
            trip = profile.find_trip(origin)
            if trip is None:
                raise UsageError("Where to?", hint="`tmb route <from> <to>`, or a saved trip name.")
            start, end, deadline = trip.origin, trip.to, by or (None if at else trip.by)
        return _plan(start, end, deadline, at, day).model_dump(by_alias=True)

    _run(action)


@app.command()
def leave(
    destination: Annotated[
        list[str],
        typer.Argument(help="Where to: a place, lat,lon, a stop/station name, or a saved trip."),
    ],
    origin: Annotated[
        str | None, typer.Option("--from", help="From where (default: the place `casa`).")
    ] = None,
    by: ByOption = None,
    day: DayOption = None,
    wait: Annotated[
        bool, typer.Option("--wait", help="Wait and exit with an event when it's time to go.")
    ] = False,
    to: NotifyOption = None,
) -> None:
    """When to leave to get somewhere (by --by, else leaving now): the best option, with
    `leave_in`. With --wait, re-plans every 5 min and exits at the departure time."""

    def action() -> object:
        target, deadline = " ".join(destination), by
        start = origin
        if trip := profile.find_trip(target):
            start, target, deadline = origin or trip.origin, trip.to, by or trip.by
        start = start or ("casa" if places.find("casa") else None)
        if start is None:
            raise UsageError(
                "Where from? Pass --from.",
                hint="Or save your home: `tmb place add casa <lat,lon>`.",
            )
        alert_to = _notify_target(to) if wait else None
        checked = 0
        while True:
            checked += 1
            found = _plan(start, target, deadline, None, day)
            best = found.options[0]
            if not wait:
                return found.model_copy(update={"options": [best]}).model_dump(by_alias=True)
            if best.leave_in <= 0:
                return _deliver(
                    alert_to,
                    {
                        "event": "leave_now",
                        "option": best.model_dump(by_alias=True),
                        "say": found.say,  # already "Sal ya (HH:MM): …" at departure time
                        "checked": checked,
                        "source": "TMB",
                        "updated_at": found.updated_at,
                    },
                )
            _sleep(min(300, best.leave_in * 60))

    _run(action)


# --- trips, preferences, setup -----------------------------------------------------


@trip_app.command("add")
def trip_add(
    name: Annotated[str, typer.Argument(help="Lowercase name, e.g. trabajo.")],
    origin: Annotated[str, typer.Option("--from", help="A place, lat,lon or stop name.")],
    destination: Annotated[str, typer.Option("--to", help="A place, lat,lon or stop name.")],
    by: Annotated[str | None, typer.Option("--by", help="Arrive by (HH:MM).")] = None,
    days: Annotated[
        str | None, typer.Option("--days", help="lun-vie, sab,dom, laborables, diario…")
    ] = None,
) -> None:
    """Save (or replace) a usual trip. `--days` is for the agent's own reminders."""

    def action() -> object:
        trip = profile.Trip(
            name=name,
            origin=origin,
            to=destination,
            by=by,
            days=profile.parse_days(days) if days else [],
        )
        replaced = profile.add_trip(trip)
        when = f" para llegar a las {by}" if by else ""
        on = f" ({', '.join(trip.days)})" if trip.days else ""
        return {
            "trip": trip.model_dump(by_alias=True),
            "replaced": replaced,
            "say": f"Guardado el trayecto «{name}»: de {origin} a {destination}{when}{on}.",
        }

    _run(action)


@trip_app.command("list")
def trip_list() -> None:
    """List your usual trips."""
    _run(lambda: profile.load_trips().model_dump(by_alias=True))


@trip_app.command("remove")
def trip_remove(name: Annotated[str, typer.Argument(help="The trip's name.")]) -> None:
    """Delete a trip."""

    def action() -> object:
        profile.remove_trip(name)
        return {"removed": name}

    _run(action)


@app.command()
def prefs(
    margin: Annotated[
        int | None, typer.Option("--margin", min=0, max=15, help="Spare minutes at the stop.")
    ] = None,
    pace: Annotated[
        str | None, typer.Option("--pace", help="Walking pace: slow, normal or fast.")
    ] = None,
    notify_to: Annotated[
        str | None,
        typer.Option(
            "--notify", help="Default alert target (ntfy:<topic>, webhook:<url>) or none."
        ),
    ] = None,
) -> None:
    """Show or set your preferences: default margin, walking pace (scales estimated walks) and
    where alerts are sent."""

    def action() -> object:
        current = profile.load_prefs()
        changes: dict = {}
        if margin is not None:
            changes["margin"] = margin
        if pace is not None:
            if pace not in profile.PACE_M_PER_MIN:
                raise UsageError("--pace is slow, normal or fast.")
            changes["pace"] = pace
        if notify_to is not None:
            if notify_to not in ("", "none"):
                notify.parse(notify_to)
            changes["notify"] = None if notify_to in ("", "none") else notify_to
        if changes:
            asked = current.asked if "prefs" in current.asked else [*current.asked, "prefs"]
            current = current.model_copy(update={**changes, "asked": asked})
            profile.save_prefs(current)
        shown = current.model_dump(exclude={"asked"})
        if current.notify:  # webhook URLs often carry a token: don't echo them
            shown["notify"] = notify.label(current.notify)
        result: dict = {"prefs": shown}
        if current.notify and (warning := notify.warning(current.notify)):
            result["warning"] = warning
        return result

    _run(action)


@app.command("notify-test")
def notify_test(
    target: Annotated[
        str | None, typer.Argument(help="ntfy:<topic> or webhook:<url> (default: your prefs).")
    ] = None,
) -> None:
    """Send a test alert, to check notifications reach the phone."""

    def action() -> object:
        destination = _notify_target(target)
        if destination is None:
            raise UsageError(
                "No notification target.",
                hint="Pass one, or set it: tmb prefs --notify ntfy:<topic>.",
            )
        event = {
            "event": "test",
            "say": "Las notificaciones de tmb funcionan: aquí te llegarán los avisos.",
        }
        return _deliver(destination, event)

    _run(action)


SETUP_ITEMS = ["home", "places", "walks", "trips", "prefs", "notify", "keys"]


@app.command()
def setup(
    done: Annotated[
        str | None,
        typer.Option("--done", help=f"Mark an item asked/skipped: {', '.join(SETUP_ITEMS)}."),
    ] = None,
) -> None:
    """What's set up and what's missing, with the next question to ask the user (for agents
    onboarding someone). Loop: ask, run the command it suggests, call `tmb setup` again."""

    def action() -> object:
        if done is not None:
            if done not in SETUP_ITEMS:
                raise UsageError(f"--done takes one of: {', '.join(SETUP_ITEMS)}.")
            profile.mark_asked(done)
        return _setup_status()

    _run(action)


def _setup_status() -> dict:
    current = profile.load_prefs()
    asked = set(current.asked)
    topic = "tmb-" + secrets.token_hex(6)  # a suggestion: long and random, so nobody guesses it
    saved = places.load().places
    names = [p.name for p in saved]
    unconfirmed = [p for p in saved if any(s.estimated for s in p.stops)]
    try:
        keys = find_credentials() is not None
    except TmbError:
        keys = False
    items = [
        {
            "item": "home",
            "done": "casa" in names,
            "question": "¿Dónde vives? Dime la dirección (calle, número y municipio) y la guardo "
            "como «casa» con sus paradas cercanas.",
            "command": 'tmb place add casa <lat,lon> --label "<address>"',
        },
        {
            "item": "places",
            "done": len(names) > 1 or "places" in asked,
            "question": "¿Qué otros sitios usas a menudo? Trabajo, estudios, gimnasio, la casa de "
            "alguien… Dime nombre y dirección de cada uno.",
            "command": "tmb place add <name> <lat,lon> --label …; none: tmb setup --done places",
        },
        {
            "item": "walks",
            "done": not unconfirmed or "walks" in asked,
            "question": (
                f"He estimado lo que tardas andando a las paradas de «{unconfirmed[0].name}»: "
                + ", ".join(f"{s.name} ({s.walk_minutes} min)" for s in unconfirmed[0].stops)
                + ". ¿Es así, o tardas otra cosa en alguna?"
            )
            if unconfirmed
            else "",
            "command": "tmb place walk <place> <code> <min>; all fine: tmb place confirm <place>",
        },
        {
            "item": "trips",
            "done": bool(profile.load_trips().trips) or "trips" in asked,
            "question": "¿Haces algún trayecto habitual a una hora fija? Por ejemplo, ir al "
            "trabajo de lunes a viernes para llegar a las 9. Lo guardo y, si quieres, te aviso "
            "cada día cuando tengas que salir.",
            "command": "tmb trip add <name> --from <place> --to <place> --by HH:MM --days lun-vie; "
            "none: tmb setup --done trips",
        },
        {
            "item": "prefs",
            "done": "prefs" in asked,
            "question": "¿Te gusta llegar a la parada con algo de margen, por ejemplo 2 minutos? "
            "¿Y andas rápido, normal o despacio?",
            "command": "tmb prefs --margin N --pace slow|normal|fast; keep: tmb setup --done prefs",
        },
        {
            "item": "notify",
            "done": bool(current.notify) or "notify" in asked,
            "question": "¿Quieres que los avisos («sal ya», «le quedan 5 min») te lleguen como "
            "notificación en el móvil? Instala la app ntfy (gratis) y suscríbete al tema "
            f"«{topic}»; te los mando ahí.",
            "command": f"tmb prefs --notify ntfy:{topic}, then tmb notify-test; you can message "
            "the user yourself, or no: tmb setup --done notify",
        },
        {
            "item": "keys",
            "done": keys or "keys" in asked,
            "question": "Para el metro y los buses de TMB necesito tus claves gratuitas de TMB (2 "
            "minutos en developer.tmb.cat). Guárdalas tú con `tmb auth set` en tu terminal; nunca "
            "me las pases. Los buses metropolitanos de AMB funcionan sin ellas. ¿Las configuras?",
            "command": "the user runs `tmb auth set` themselves; skipped: tmb setup --done keys",
        },
    ]
    missing = [i for i in items if not i["done"]]
    return {
        "complete": not missing,
        "items": items,
        "next_question": missing[0]["question"] if missing else None,
        "say": missing[0]["question"]
        if missing
        else "Todo listo. Pregúntame cuándo pasa tu bus, cuándo salir o qué tienes cerca.",
    }


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
        answers.check_codes("Station" if metro_codes else "Stop", codes)
        if not metro_codes and len(codes) > 1:
            raise UsageError("A bus favourite has one stop code.", hint="For metro, add --metro.")
        # Check the codes when the lists are cached; never download for this.
        tmb_net, amb_net = network.load_cached(), amb.load_cached()
        for code in (str(int(c)) for c in codes):
            if metro_codes:
                unknown = tmb_net is not None and not tmb_net.station_name(code)
            else:  # a bus stop can be TMB's or AMB's: only both lists can rule it out
                unknown = (
                    tmb_net is not None
                    and amb_net is not None
                    and not tmb_net.has_stop(code)
                    and code not in amb_net.stops
                )
            if unknown:
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


# --- places -------------------------------------------------------------------------


def _networks(refresh: bool = False) -> tuple["network.Network | None", "amb.AmbCache"]:
    """Both stop lists. Without TMB keys, TMB's is whatever is cached (maybe none): AMB's
    metropolitan buses still work."""
    try:
        tmb_net = network.get_network(_client, refresh=refresh)
    except MissingCredentials:
        tmb_net = network.load_cached()
    return tmb_net, amb.get_cache(_amb_client, refresh=refresh)


def _point(text: str) -> tuple[float, float]:
    point = nearby.parse_point(text)
    if point is None:
        raise UsageError(
            f"`{text}` is not a lat,lon point.", hint="For example 41.3874,2.1700 (lat first)."
        )
    return point


@place_app.command("add")
def place_add(
    name: Annotated[str, typer.Argument(help="Lowercase name, e.g. casa.")],
    point: Annotated[str, typer.Argument(help="Where it is, as lat,lon (e.g. 41.3874,2.1700).")],
    label: Annotated[
        str | None, typer.Option("--label", help="The address as the user said it.")
    ] = None,
    radius: Annotated[
        int, typer.Option("--radius", min=50, max=2000, help="Search radius in metres.")
    ] = 450,
    max_bus: Annotated[int, typer.Option("--max-bus", min=0, max=6, help="Bus stops to keep.")] = 3,
) -> None:
    """Save (or replace) a place and pick its closest bus stops and metro station, with an
    estimated walk time for each (fix them with `tmb place walk`)."""

    def action() -> object:
        favourites.check_name(name)
        lat, lon = _point(point)
        tmb_net, amb_net = _networks()
        pace = profile.load_prefs().walk_m_per_min
        found = nearby.nearby(
            lat, lon, tmb_net, amb_net, radius=radius, max_bus=max_bus, m_per_min=pace
        )
        place = places.Place(
            name=name,
            lat=lat,
            lon=lon,
            label=label,
            stops=[places.PlaceStop(**c.model_dump(exclude={"lat", "lon"})) for c in found],
        )
        replaced = places.add(place)
        return {
            "place": place.model_dump(),
            "replaced": replaced,
            "say": say.place_saved(name, [(s.name, s.walk_minutes) for s in place.stops], replaced),
        }

    _run(action)


@place_app.command("walk")
def place_walk(
    name: Annotated[str, typer.Argument(help="The place's name.")],
    code: Annotated[str, typer.Argument(help="One of its stops' codes.")],
    minutes: Annotated[int, typer.Argument(min=0, help="Minutes you take to walk there.")],
) -> None:
    """Set your own walk time from a place to one of its stops."""
    _run(lambda: {"place": places.set_walk(name, code, minutes).model_dump()})


@place_app.command("confirm")
def place_confirm(name: Annotated[str, typer.Argument(help="The place's name.")]) -> None:
    """Keep a place's estimated walk times as they are (the user agreed with them)."""
    _run(lambda: {"place": places.confirm(name).model_dump()})


@place_app.command("list")
def place_list() -> None:
    """List your places and their stops."""
    _run(lambda: places.load().model_dump())


@place_app.command("remove")
def place_remove(name: Annotated[str, typer.Argument(help="The place's name.")]) -> None:
    """Delete a place."""

    def action() -> object:
        places.remove(name)
        return {"removed": name}

    _run(action)


# --- static network -------------------------------------------------------------------


@app.command()
def stops(
    words: Annotated[
        list[str], typer.Argument(help="Words of a stop or station name (no quotes needed).")
    ],
    bus_only: Annotated[bool, typer.Option("--bus", help="Only bus stops.")] = False,
    metro_only: Annotated[bool, typer.Option("--metro", help="Only metro stations.")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Most results to return.")] = 10,
    refresh: Annotated[
        bool, typer.Option("--refresh", help="Download the network again first.")
    ] = False,
) -> None:
    """Find stop and station codes by name, street or town (ignores case and accents). Metro
    stations list one code per line. Only TMB's network: other operators' stops aren't listed.
    Downloads the static network on first use and weekly after that."""

    query = " ".join(words)

    def action() -> object:
        if bus_only and metro_only:
            raise UsageError("Pass --bus or --metro, not both.")
        if not network.normalize(query):
            raise UsageError("The query needs at least one letter or digit.")
        net = network.get_network(_client, refresh=refresh)
        amb_net = None if metro_only else amb.get_cache(_amb_client, refresh=refresh)
        results = network.search(
            net, query, amb=amb_net, bus=not metro_only, metro=not bus_only, limit=limit
        )
        dates = [net.updated_at] + ([amb_net.updated_at] if amb_net else [])
        return StopSearch(
            query=query,
            results=results,
            source="TMB+AMB" if amb_net else "TMB",
            updated_at=min(dates),
        ).model_dump()

    _run(action)


# --- agents ------------------------------------------------------------------------


@skills_app.command("get")
def skills_get() -> None:
    """Print SKILL.md, the guide for coding agents (Markdown, the one non-JSON output)."""
    _run(lambda: files("tmb_cli").joinpath("SKILL.md").read_text(encoding="utf-8"), text=True)


DOCTOR_STOP = "1103"  # any stop works: one small real-time request checks the keys


def _check(name: str, ok: bool, detail: str, err: TmbError | None = None) -> dict:
    check = {"name": name, "ok": ok, "detail": detail}
    if err:
        check["code"] = err.code
        check["exit_code"] = err.exit_code
    return check


def _doctor_checks() -> list[dict]:
    checks = []
    try:
        creds = find_credentials()
    except TmbError as err:
        creds = None
        checks.append(_check("credentials", False, err.message, err))
    else:
        if creds is None:
            err = MissingCredentials("Not set: run `tmb auth set`.")
            checks.append(_check("credentials", False, err.message, err))
        elif creds.source == "env":
            checks.append(_check("credentials", True, f"from {ENV_APP_ID}/{ENV_APP_KEY}"))
        else:
            mode = stat.S_IMODE(os.stat(credentials_path()).st_mode)
            warn = "" if mode & 0o077 == 0 else ": others can read it, run `chmod 600` on it"
            checks.append(_check("credentials", True, f"from file, mode {mode:04o}{warn}"))

    if creds is None:
        checks.append(_check("api", False, "Skipped: no credentials."))
    else:
        try:
            with TmbClient(creds.app_id, creds.app_key) as client:
                arrivals.bus_arrivals(client.bus_arrivals(DOCTOR_STOP), DOCTOR_STOP, [])
            checks.append(_check("api", True, "TMB API answered with these credentials."))
        except TmbError as err:
            checks.append(_check("api", False, err.message, err))

    try:
        with _amb_client() as client:
            feed = amb.parse_realtime(client.realtime())
        detail = f"AMB real-time feed answered ({len(feed.passages)} stops with buses)."
        checks.append(_check("amb", True, detail))
    except TmbError as err:
        checks.append(_check("amb", False, err.message, err))

    cached = network.load_cached()
    if cached is None:
        checks.append(_check("cache", True, "Not downloaded yet: `tmb stops <name>` does it."))
    else:
        days = int((time.time() - cached.downloaded_at) // 86400)
        checks.append(_check("cache", True, f"{days} days old, TMB data of {cached.updated_at}"))
    amb_cached = amb.load_cached()
    if amb_cached is None:
        checks.append(_check("amb_cache", True, "Not downloaded yet: `tmb stops` or `tmb bus`."))
    else:
        days = int((time.time() - amb_cached.downloaded_at) // 86400)
        detail = f"{days} days old, AMB data valid until {amb_cached.valid_until}"
        checks.append(_check("amb_cache", True, detail))

    try:
        count = len(favourites.load().favourites)
        checks.append(_check("favourites", True, f"{count} saved"))
    except TmbError as err:
        checks.append(_check("favourites", False, err.message, err))
    return checks


@app.command()
def doctor() -> None:
    """Check credentials, API access, the stops cache and favourites. Exit code: the first
    failing check's."""
    exit_code = 0

    def action() -> object:
        nonlocal exit_code
        checks = _doctor_checks()
        failed = [c for c in checks if not c["ok"]]
        exit_code = failed[0].get("exit_code", 1) if failed else 0
        return {"ok": not failed, "version": __version__, "checks": checks}

    _run(action)
    if exit_code:
        raise typer.Exit(exit_code)


GLOBAL_FLAGS = ("--no-input",)


def hoist_global_flags(args: list[str]) -> list[str]:
    """Move global flags to the front, so `tmb bus 1103 --no-input` works like
    `tmb --no-input bus 1103` (agents put flags at the end). Nothing after `--` is touched."""
    end = args.index("--") if "--" in args else len(args)
    found = [flag for flag in GLOBAL_FLAGS if flag in args[:end]]
    rest = [arg for arg in args[:end] if arg not in GLOBAL_FLAGS]
    return [*found, *rest, *args[end:]]


def main() -> None:
    app(args=hoist_global_flags(sys.argv[1:]))
