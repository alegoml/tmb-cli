"""Typed errors. Each one maps to a stable `code`, process exit code and `retryable` flag.

Exit codes (keep them stable, agents rely on them):
    0    ok
    1    unexpected internal error
    2    bad usage (bad arguments, cancelled prompt, prompt needed under --no-input)
    3    missing, unreadable or rejected credentials
    4    not found (unknown stop/station)
    5    TMB API error or rate limit
    6    network failure or timeout
    7    TMB API changed (unexpected response shape)
    130  interrupted (Ctrl-C)
"""


class TmbError(Exception):
    code = "internal"
    exit_code = 1
    retryable = False

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        error = {
            "code": self.code,
            "message": self.message,
            "exit_code": self.exit_code,
            "retryable": self.retryable,
        }
        if self.hint:
            error["hint"] = self.hint
        return {"error": error}


class UsageError(TmbError):
    code = "usage"
    exit_code = 2


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

    def __init__(self, message: str, *, hint: str | None = None, retryable: bool = False) -> None:
        super().__init__(message, hint=hint)
        self.retryable = retryable


class RateLimited(ApiError):
    code = "rate_limited"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint, retryable=True)


class NetworkError(TmbError):
    code = "network_error"
    exit_code = 6
    retryable = True


class ApiChanged(TmbError):
    code = "api_changed"
    exit_code = 7


class Interrupted(TmbError):
    code = "interrupted"
    exit_code = 130
