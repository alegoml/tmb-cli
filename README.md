# tmb-cli

Unofficial command-line client for **TMB** (Transports Metropolitans de Barcelona): real-time bus and
metro arrivals from your terminal. Output is JSON, so shell pipelines (`jq`) and coding agents
(Claude Code, Codex, Hermes…) can use it directly.

> **Status: work in progress (v0.1).** Commands return the raw TMB payload for now; a stable,
> documented JSON shape comes next. Not affiliated with or endorsed by TMB.

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- A free TMB API key: sign in at [developer.tmb.cat](https://developer.tmb.cat/), create an
  application and copy its `app_id` and `app_key`.

## Install (from source)

```bash
git clone <repo-url> tmb-cli && cd tmb-cli
uv sync
uv run tmb --help
uv tool install --editable .   # optional: put `tmb` on your PATH
```

## Credentials

```bash
tmb auth set       # prompts for app_id and app_key (hidden), saved to ~/.config/tmb-cli/credentials.json (0600)
tmb auth status    # offline check; never prints the key
```

Environment variables `TMB_APP_ID` and `TMB_APP_KEY` take precedence over the file.

## Usage

```bash
tmb bus 1103             # next buses at stop 1103 (Pl Catalunya)
tmb metro 126 326        # next trains at Catalunya, L1 and L3 (codes are per line)
tmb bus 1103 | jq .
```

Errors are printed to stderr as one line of JSON, with stable exit codes:

```json
{"error": {"code": "rate_limited", "message": "…", "exit_code": 5, "retryable": true, "hint": "…"}}
```

| Exit code | `code` | Meaning |
|---|---|---|
| 0 | | OK |
| 1 | `internal` | Unexpected error (only the exception type is reported) |
| 2 | `usage` | Bad usage, cancelled prompt, or a prompt was needed under `--no-input` |
| 3 | `missing_credentials`, `auth_failed` | Missing, unreadable or rejected credentials |
| 4 | `not_found` | Unknown stop or station |
| 5 | `api_error`, `rate_limited` | TMB API error or rate limit |
| 6 | `network_error` | Network failure or timeout |
| 7 | `api_changed` | Unexpected response shape: the TMB API probably changed |
| 130 | `interrupted` | Interrupted (Ctrl-C) |

`retryable: true` means trying again later may work (rate limit, TMB 5xx, network); `false` means
retrying won't help until something changes.

Argument errors caught by the parser itself (a missing stop code, an unknown option) are still
printed as plain text, with exit code 2.

Scripts and agents should pass `--no-input` (or set `TMB_NO_INPUT=1`) so the CLI never waits for a
prompt.

## Development

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Tests never call the real API (they use `httpx.MockTransport`).

## Disclaimer

This project is not affiliated with or endorsed by Transports Metropolitans de Barcelona. It uses
TMB's public developer API with your own credentials; you are responsible for complying with its
terms of use.

## License

[MIT](LICENSE)
