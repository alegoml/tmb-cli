"""Thin HTTP client for the official TMB API (https://api.tmb.cat/v1).

Only read endpoints. Every request carries app_id/app_key as query parameters,
which is what the TMB API expects. Error messages never echo the request URL,
because it contains the credentials.
"""

import math

import httpx

from tmb_cli.errors import ApiChanged, ApiError, AuthFailed, NetworkError, NotFound, RateLimited

BASE_URL = "https://api.tmb.cat/v1/"
DEFAULT_TIMEOUT = 10.0


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-finite number {name}")  # NaN / Infinity, which json accepts by default


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):  # e.g. 1e400
        raise ValueError(f"non-finite number {text}")
    return value


class TmbClient:
    def __init__(
        self,
        app_id: str,
        app_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,  # injected in tests
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            params={"app_id": app_id, "app_key": app_key},
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def __enter__(self) -> "TmbClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def get(self, path: str, params: dict | None = None) -> dict:
        try:
            response = self._http.get(path, params=params)
        except httpx.TimeoutException:
            raise NetworkError("TMB API timed out.") from None
        except httpx.HTTPError as exc:
            raise NetworkError(f"Could not reach the TMB API ({type(exc).__name__}).") from None

        status = response.status_code
        if status in (401, 403):
            raise AuthFailed(
                f"TMB API rejected the credentials (HTTP {status}).",
                hint="Check them with `tmb auth status` or set new ones with `tmb auth set`.",
            )
        if status == 404:
            raise NotFound(f"Nothing found at `{path}` (HTTP 404).")
        if status == 429:
            raise RateLimited(
                "TMB API rate limit reached (HTTP 429).", hint="Wait a while before retrying."
            )
        if status >= 500:
            raise ApiError(f"TMB API returned HTTP {status}.", retryable=True)
        if status >= 400:
            raise ApiError(f"TMB API returned HTTP {status}.")

        try:
            # Strict JSON: NaN/Infinity are not JSON and must never reach our output.
            return response.json(parse_constant=_reject_constant, parse_float=_finite_float)
        except ValueError:
            raise ApiChanged(
                "TMB API returned a response that is not valid JSON.",
                hint="The TMB API may have changed; please open an issue.",
            ) from None

    # --- real-time arrivals -------------------------------------------------
    # Raw payloads; `arrivals.py` validates them and shapes our output.

    def bus_arrivals(self, stop_code: str) -> dict:
        return self.get(f"itransit/bus/parades/{stop_code}")

    def metro_arrivals(self, station_codes: list[str]) -> dict:
        if not station_codes:
            raise ValueError("At least one station code is required.")
        return self.get("itransit/metro/estacions", params={"estacions": ",".join(station_codes)})

    # --- static network (cached by `network.py`) ------------------------------

    def bus_stops(self) -> dict:
        return self.get("transit/parades")

    def metro_lines(self) -> dict:
        return self.get("transit/linies/metro")

    def metro_line_stations(self, line_code: int) -> dict:
        return self.get(f"transit/linies/metro/{line_code}/estacions")


AMB_BASE_URL = "https://www.ambmobilitat.cat/"


class AmbClient:
    """AMB open data: the GTFS-Realtime feed and the GTFS zip, no credentials (docs/amb-api.md)."""

    def __init__(
        self,
        *,
        base_url: str = AMB_BASE_URL,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,  # injected in tests
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def __enter__(self) -> "AmbClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.close()

    def _get(self, path: str) -> bytes:
        try:
            response = self._http.get(path)
        except httpx.TimeoutException:
            raise NetworkError("AMB open data timed out.") from None
        except httpx.HTTPError as exc:
            raise NetworkError(f"Could not reach AMB open data ({type(exc).__name__}).") from None
        status = response.status_code
        if status == 429:
            raise RateLimited("AMB rate limit reached (HTTP 429).", hint="Wait before retrying.")
        if status >= 500:
            raise ApiError(f"AMB open data returned HTTP {status}.", retryable=True)
        if status >= 400:  # a moved or removed feed, not something the user can fix
            raise ApiChanged(
                f"AMB open data returned HTTP {status} for `{path}`.",
                hint="AMB may have moved its open data; please open an issue.",
            )
        return response.content

    def realtime(self) -> bytes:
        """GTFS-Realtime trip updates for the whole AMB network (~280 KB, refreshed every 30 s)."""
        return self._get("transit/trips-updates/trips.bin")

    def gtfs(self) -> bytes:
        """The static network as a GTFS zip (~9 MB)."""
        return self._get("OpenData/google_transit.zip")
