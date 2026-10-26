"""`say`: one or two Spanish sentences, ready to forward as a text message (spec v0.3, D16).

Built only from the JSON answer next to it: no data here that isn't there.
"""

from collections.abc import Sequence


def hhmm(eta: str) -> str:
    """ "2026-10-26T11:19:02+01:00" → "11:19"."""
    return eta[11:16]


def _stop_list(items: Sequence[tuple[str, int]]) -> str:
    parts = [f"{name} ({walk} min andando)" for name, walk in items]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " y " + parts[-1]


def place_saved(name: str, stops: Sequence[tuple[str, int]], replaced: bool) -> str:
    verb = "He actualizado" if replaced else "He guardado"
    if not stops:
        return (
            f"{verb} «{name}», pero no hay paradas de TMB ni AMB cerca. Prueba con un radio mayor."
        )
    return (
        f"{verb} «{name}» con {len(stops)} parada{'s' if len(stops) > 1 else ''}: "
        f"{_stop_list(stops)}. Los tiempos andando son estimados: dime si tardas otra cosa."
    )


def arrivals(stop: str | None, items: Sequence[tuple[str, int]], none: str) -> str:
    """Plain arrivals: "Pl Catalunya: V15 en 3 min, H16 en 5 min y V15 en 11 min."."""
    if not items:
        return none
    shown = [f"{line} en {minutes} min" for line, minutes in items[:3]]
    text = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " y " + shown[-1]
    return f"{stop}: {text}." if stop else text[0].upper() + text[1:] + "."


def catch(
    first: tuple[str, str, int, str] | None,
    missed: tuple[str, str] | None,
    nothing: str,
) -> str:
    """When to leave: first = (line, eta, leave_in, stop) of the next one the user can catch,
    missed = (line, eta) of an earlier one they can't."""
    if first is None:
        return nothing
    line, eta, leave_in, stop = first
    head = (
        f"Sal ya para pillar el {line} de las {hhmm(eta)} en {stop}."
        if leave_in <= 0
        else f"Sal en {leave_in} min para pillar el {line} de las {hhmm(eta)} en {stop}."
    )
    if missed:
        head += f" El {missed[0]} de las {hhmm(missed[1])} ya no lo pillas."
    return head
