"""Deliver an alert to a target the user configured (spec v0.6): an ntfy topic or a webhook.

The only outbound traffic besides TMB and AMB (AGENTS.md rule 4): the alert's text, when an alert
fires. Never credentials. A failed delivery is reported, not raised: the alert itself still prints.
"""

import httpx

from tmb_cli.errors import UsageError

NTFY_SERVER = "https://ntfy.sh"
SHORT_TOPIC = 12  # anyone who knows a topic on ntfy.sh can read it: warn below this length


def _client() -> httpx.Client:  # swapped in tests
    return httpx.Client(timeout=10)


def parse(target: str) -> tuple[str, str, str]:
    """ "ntfy:topic" → ("ntfy", "https://ntfy.sh", "topic"); "ntfy:https://host/topic" → ("ntfy",
    "https://host", "topic"); "webhook:https://…" → ("webhook", url, "")."""
    kind, _, rest = target.partition(":")
    if kind == "ntfy" and rest:
        if rest.startswith(("https://", "http://")):
            server, _, topic = rest.rstrip("/").rpartition("/")
            if topic and "://" in server:
                return "ntfy", server, topic
        elif "/" not in rest:
            return "ntfy", NTFY_SERVER, rest
    if kind == "webhook" and rest.startswith(("https://", "http://")):
        return "webhook", rest, ""
    raise UsageError(
        f"`{target}` is not a notification target.",
        hint="Use ntfy:<topic>, ntfy:https://host/<topic> or webhook:https://….",
    )


def label(target: str) -> str:
    """What to show of a target: ntfy topics as is, webhooks without their URL (tokens)."""
    kind, server, topic = parse(target)
    if kind == "webhook":
        return "webhook"
    return f"ntfy:{topic}" if server == NTFY_SERVER else f"ntfy:{server}/{topic}"


def warning(target: str) -> str | None:
    kind, server, topic = parse(target)
    if kind == "ntfy" and server == NTFY_SERVER and len(topic) < SHORT_TOPIC:
        return (
            f"The ntfy topic `{topic}` is short: anyone who guesses it can read your alerts. "
            "Use a long random one."
        )
    return None


def send(target: str, title: str, message: str, event: dict, *, urgent: bool = True) -> dict:
    """Deliver; returns {"target", "ok"} plus "error" when it failed."""
    kind, server, topic = parse(target)
    result: dict = {"target": label(target)}
    try:
        with _client() as client:
            if kind == "ntfy":
                response = client.post(
                    f"{server}/",
                    json={
                        "topic": topic,
                        "title": title,
                        "message": message,
                        "priority": 4 if urgent else 3,
                        "tags": ["bus"],
                    },
                )
            else:
                response = client.post(server, json=event)
        result["ok"] = response.status_code < 400
        if not result["ok"]:
            result["error"] = f"HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        result.update(ok=False, error=type(exc).__name__)
    return result
