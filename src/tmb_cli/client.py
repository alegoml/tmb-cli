"""Thin HTTP client for the official TMB API (https://api.tmb.cat/v1).

Only read endpoints. Every request carries app_id/app_key as query parameters,
which is what the TMB API expects. Error messages never echo the request URL,
because it contains the credentials.
"""

import httpx

from tmb_cli.errors import ApiError, AuthFailed, NetworkError, NotFound

BASE_URL = "https://api.tmb.cat/v1/"
DEFAULT_TIMEOUT = 10.0


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
            raise ApiError("TMB API rate limit reached (HTTP 429). Try again later.")
        if status >= 400:
            raise ApiError(f"TMB API returned HTTP {status}.")

        try:
            return response.json()
        except ValueError:
            raise ApiError("TMB API returned a response that is not JSON.") from None

    # --- real-time arrivals -------------------------------------------------
    # The output is the raw API payload for now. Shape it into our own stable
    # JSON once we have looked at real responses (see AGENTS.md roadmap).

    def bus_arrivals(self, stop_code: str) -> dict:
        return self.get(f"itransit/bus/parades/{stop_code}")

    def metro_arrivals(self, station_codes: list[str]) -> dict:
        if not station_codes:
            raise ValueError("At least one station code is required.")
        return self.get("itransit/metro/estacions", params={"estacions": ",".join(station_codes)})
