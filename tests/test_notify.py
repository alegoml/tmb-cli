import json

import httpx
import pytest
from test_watch import bus_in, polls  # noqa: F401  (the fixture)
from typer.testing import CliRunner

from tmb_cli import notify
from tmb_cli.cli import app
from tmb_cli.errors import UsageError

runner = CliRunner()
TOPIC = "tmb-prova-x7k2m9q4"  # long enough not to warn
HOOK = "https://hooks.example.invalid/alert?token=secret-hook-token"


class Sent(list):
    """Requests that would have gone out; `handler` sets the server's answer."""

    handler = None


@pytest.fixture
def sent(monkeypatch):
    requests = Sent()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if handler.fail:
            raise httpx.ConnectError("down")
        return httpx.Response(handler.status)

    handler.status, handler.fail = 200, False
    requests.handler = handler
    monkeypatch.setattr(
        notify, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    return requests


def run(*args: str) -> tuple[int, dict, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, json.loads(result.stdout or result.stderr), result.output


def test_targets_parse_label_and_warn():
    assert notify.parse(f"ntfy:{TOPIC}") == ("ntfy", "https://ntfy.sh", TOPIC)
    assert notify.parse("ntfy:https://ntfy.example.invalid/casa-x") == (
        "ntfy",
        "https://ntfy.example.invalid",
        "casa-x",
    )
    assert notify.parse(f"webhook:{HOOK}") == ("webhook", HOOK, "")
    assert notify.label(f"webhook:{HOOK}") == "webhook"
    assert notify.warning("ntfy:bus") and notify.warning(f"ntfy:{TOPIC}") is None
    for bad in ("ntfy:", "ntfy:a/b", "webhook:ftp://x", "telegram:123", "nothing"):
        with pytest.raises(UsageError):
            notify.parse(bad)


def test_watch_pushes_the_alert_to_ntfy(polls, sent):  # noqa: F811
    polls += [bus_in(10), bus_in(4)]
    code, out, _ = run("watch", "0001", "--minutes", "5", "--notify", f"ntfy:{TOPIC}")
    assert (code, out["event"]) == (0, "due")
    assert out["notified"] == {"target": f"ntfy:{TOPIC}", "ok": True}
    request = sent[0]
    assert (request.method, str(request.url)) == ("POST", "https://ntfy.sh/")
    assert json.loads(request.content) == {
        "topic": TOPIC,
        "title": "tmb",
        "message": "El X1 llega en 4 min a Parada de prova.",
        "priority": 4,
        "tags": ["bus"],
    }


def test_webhook_gets_the_event_and_its_url_is_never_echoed(polls, sent):  # noqa: F811
    polls += [bus_in(3)]
    code, out, output = run("watch", "0001", "--minutes", "5", "--notify", f"webhook:{HOOK}")
    assert out["notified"] == {"target": "webhook", "ok": True}
    assert str(sent[0].url) == HOOK
    assert json.loads(sent[0].content)["event"] == "due"
    assert "secret-hook-token" not in output


@pytest.mark.parametrize(
    ("status", "fail", "error"), [(500, False, "HTTP 500"), (200, True, "ConnectError")]
)
def test_a_failed_delivery_is_reported_not_raised(polls, sent, status, fail, error):  # noqa: F811
    sent.handler.status, sent.handler.fail = status, fail
    polls += [bus_in(3)]
    code, out, _ = run("watch", "0001", "--minutes", "5", "--notify", f"ntfy:{TOPIC}")
    assert (code, out["event"]) == (0, "due")
    assert out["notified"]["ok"] is False and out["notified"]["error"] == error


def test_prefs_default_target_none_and_masking(polls, sent):  # noqa: F811
    code, out, output = run("prefs", "--notify", f"webhook:{HOOK}")
    assert out["prefs"]["notify"] == "webhook" and "secret-hook-token" not in output
    polls += [bus_in(3)]
    assert run("watch", "0001", "--minutes", "5")[1]["notified"]["target"] == "webhook"
    assert run("watch", "0001", "--minutes", "5", "--notify", "none")[1]["notified"] is None
    assert run("prefs", "--notify", "ntfy:bus")[1]["warning"].startswith(
        "The ntfy topic `bus` is short"
    )
    assert run("prefs", "--notify", "none")[1]["prefs"]["notify"] is None


def test_a_bad_target_fails_before_watching(polls, sent):  # noqa: F811
    polls += [bus_in(30)]
    code, out, _ = run("watch", "0001", "--minutes", "5", "--notify", "telegram:me")
    assert (code, out["error"]["code"]) == (2, "usage")
    assert sent == []


def test_a_timeout_sends_nothing(polls, sent):  # noqa: F811
    polls += [bus_in(30)]
    code, out, _ = run(
        "watch", "0001", "--minutes", "5", "--timeout", "1", "--notify", f"ntfy:{TOPIC}"
    )
    assert out["event"] == "timeout" and out["notified"] is None
    assert sent == []


def test_notify_test(sent):
    code, out, _ = run("notify-test", f"ntfy:{TOPIC}")
    assert out["notified"]["ok"] is True
    assert json.loads(sent[0].content)["message"].startswith("Las notificaciones de tmb funcionan")
    assert run("notify-test")[1]["error"]["code"] == "usage"  # no target, no default
