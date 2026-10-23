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
tmb bus 108              # next buses at stop 108
tmb metro 123 115        # next trains at metro stations 123 and 115
tmb bus 108 | jq .
```

Errors are printed to stderr as JSON (`{"error": {"code": ..., "message": ..., "hint": ...}}`) with
stable exit codes:

| Exit code | Meaning |
|---|---|
| 0 | OK |
| 2 | Bad usage |
| 3 | Missing or rejected credentials |
| 4 | Not found |
| 5 | TMB API or network failure |

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
