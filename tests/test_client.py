import httpx
import pytest

from tmb_cli.client import TmbClient
from tmb_cli.errors import ApiChanged, ApiError, AuthFailed, NetworkError, NotFound, RateLimited

FAKE_ID = "test-id"
FAKE_KEY = "test-secret-key"


def make_client(handler) -> TmbClient:
    return TmbClient(FAKE_ID, FAKE_KEY, transport=httpx.MockTransport(handler))


def test_sends_credentials_as_query_params():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        return httpx.Response(200, json={"ok": True})

    with make_client(handler) as client:
        assert client.bus_arrivals("0001") == {"ok": True}

    assert seen["url"].path == "/v1/itransit/bus/parades/0001"
    assert seen["url"].params["app_id"] == FAKE_ID
    assert seen["url"].params["app_key"] == FAKE_KEY


def test_metro_joins_station_codes():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        return httpx.Response(200, json={})

    with make_client(handler) as client:
        client.metro_arrivals(["123", "115"])

    assert seen["url"].path == "/v1/itransit/metro/estacions"
    assert seen["url"].params["estacions"] == "123,115"
    assert seen["url"].params["app_key"] == FAKE_KEY


def test_metro_requires_a_station():
    with make_client(lambda r: httpx.Response(200, json={})) as client:
        with pytest.raises(ValueError):
            client.metro_arrivals([])


@pytest.mark.parametrize(
    ("status", "error", "exit_code", "retryable"),
    [
        (401, AuthFailed, 3, False),
        (403, AuthFailed, 3, False),
        (404, NotFound, 4, False),
        (429, RateLimited, 5, True),
        (400, ApiError, 5, False),
        (500, ApiError, 5, True),
        (503, ApiError, 5, True),
    ],
)
def test_http_errors_map_to_typed_errors(status, error, exit_code, retryable):
    with make_client(lambda r: httpx.Response(status, text="nope")) as client:
        with pytest.raises(error) as excinfo:
            client.bus_arrivals("0001")
    assert excinfo.value.exit_code == exit_code
    assert excinfo.value.retryable is retryable
    assert FAKE_KEY not in excinfo.value.message


def test_network_failure_is_a_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with make_client(handler) as client:
        with pytest.raises(NetworkError) as excinfo:
            client.bus_arrivals("0001")
    assert excinfo.value.exit_code == 6
    assert excinfo.value.retryable is True


@pytest.mark.parametrize("body", ["<html>", '{"t": NaN}', '{"t": Infinity}', '{"t": 1e400}'])
def test_invalid_or_non_finite_json_means_the_api_changed(body):
    with make_client(lambda r: httpx.Response(200, text=body)) as client:
        with pytest.raises(ApiChanged) as excinfo:
            client.bus_arrivals("0001")
    assert excinfo.value.exit_code == 7
