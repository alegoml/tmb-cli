import httpx
import pytest

from tmb_cli.client import TmbClient
from tmb_cli.errors import ApiError, AuthFailed, NetworkError, NotFound

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
        assert client.bus_arrivals("108") == {"ok": True}

    assert seen["url"].path == "/v1/itransit/bus/parades/108"
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
    ("status", "error"),
    [(401, AuthFailed), (403, AuthFailed), (404, NotFound), (429, ApiError), (500, ApiError)],
)
def test_http_errors_map_to_typed_errors(status, error):
    with make_client(lambda r: httpx.Response(status, text="nope")) as client:
        with pytest.raises(error) as excinfo:
            client.bus_arrivals("108")
    assert FAKE_KEY not in excinfo.value.message


def test_network_failure_is_a_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with make_client(handler) as client:
        with pytest.raises(NetworkError):
            client.bus_arrivals("108")


def test_non_json_response_is_an_api_error():
    with make_client(lambda r: httpx.Response(200, text="<html>")) as client:
        with pytest.raises(ApiError):
            client.bus_arrivals("108")
