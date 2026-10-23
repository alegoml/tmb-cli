"""Typed errors. Each one maps to a stable `code` and process exit code.

Exit codes (keep them stable, agents rely on them):
    0  ok
    2  bad usage (handled by Typer)
    3  missing or rejected credentials
    4  not found (unknown stop/station)
    5  TMB API or network failure
"""


class TmbError(Exception):
    code = "error"
    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        error = {"code": self.code, "message": self.message}
        if self.hint:
            error["hint"] = self.hint
        return {"error": error}


class MissingCredentials(TmbError):
    code = "missing_credentials"
    exit_code = 3


class AuthFailed(TmbError):
    code = "auth_failed"
    exit_code = 3


class NotFound(TmbError):
    code = "not_found"
    exit_code = 4


class ApiError(TmbError):
    code = "api_error"
    exit_code = 5


class NetworkError(TmbError):
    code = "network_error"
    exit_code = 5
