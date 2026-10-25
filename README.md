# tmb-cli

Unofficial command-line client for Barcelona's real-time bus and metro arrivals: **TMB**
(Transports Metropolitans de Barcelona: Barcelona's buses and metro) and **AMB**'s metropolitan
buses run by other operators (TUSGSAL, Moventis, Monbus, Aerobús…). Output is JSON, so shell
pipelines (`jq`) and coding agents (Claude Code, Codex, Hermes…) can use it directly.

> Not affiliated with or endorsed by TMB or AMB. Data: TMB's open API and AMB's open data,
> credited in every response (`source`, `updated_at`).

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- A free TMB API key, for TMB's buses and the metro: sign in at
  [developer.tmb.cat](https://developer.tmb.cat/), create an application and copy its `app_id` and
  `app_key`. AMB's buses need no key.

## Install

```bash
uv tool install git+https://github.com/alegoml/tmb-cli@v0.1.0
```

Or with the script, which does the same after checking that uv is there (read it first):

```bash
curl -LsSf https://raw.githubusercontent.com/alegoml/tmb-cli/main/install.sh | sh
```

From a clone, for development:

```bash
git clone https://github.com/alegoml/tmb-cli && cd tmb-cli
uv sync
uv run tmb --help
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
tmb bus 1103 --line V15  # only the V15 (case-insensitive, repeatable)
tmb metro 126 326        # next trains at Catalunya, L1 and L3 (codes are per line)
tmb stops catalunya      # find stop and station codes by name
tmb fav add casa 1103 --walk 4   # save a stop with your walk time to it
tmb next casa            # next buses + whether you make it: "¿me da tiempo?"
```

```json
{
  "stop": {"code": "1103", "name": "Pl Catalunya - Portal de l'Àngel"},
  "arrivals": [
    {"line": "V15", "destination": "Barceloneta", "minutes": 5, "eta": "2026-10-25T09:48:39+01:00", "operator": "TMB"},
    {"line": "H16", "destination": "Fòrum Campus Besòs", "minutes": 7, "eta": "2026-10-25T09:50:05+01:00", "operator": "TMB"}
  ],
  "source": "TMB",
  "updated_at": "2026-10-25T09:42:54+01:00"
}
```

`minutes` is rounded down (3 min 50 s shows 3) and `eta` is Barcelona time. Arrivals are the next
two per line and destination. `metro` returns `stations`, each with its `arrivals` (plus `track`)
and the station's `name` once the network is cached. Data: `source`, as of `updated_at`.

`tmb bus` covers both networks with the same stop codes: at a stop TMB and AMB share it merges
both (`"source": "TMB+AMB"`, each arrival with its `operator`); an AMB-only stop (e.g. in
Badalona) needs no TMB key. AMB's line names come from its GTFS, cached in
`~/.cache/tmb-cli/amb.json` (a ~9 MB download the first time and every few days, when AMB
republishes it).

`tmb stops <words>` searches bus stops and metro stations by name, street or town, ignoring case
and accents (no quotes needed), in TMB's and AMB's networks (`"network": "TMB"` or `"AMB"`). A metro
station lists one code per line (`"codes": {"L1": "126", "L3": "326"}`): pass them all to
`tmb metro`. The first run downloads the static network (13 requests) to
`~/.cache/tmb-cli/network.json`; it refreshes weekly, or now with `--refresh`.

`tmb next casa` adds to each arrival `leave_in` (minutes until you must set off: `minutes` minus
your walk time) and `make_it` (`leave_in` ≥ `--margin`, 0 by default). Favourites live only on your
machine, in `~/.config/tmb-cli/favourites.json`. A metro favourite can hold every line of an
interchange: `tmb fav add feina 126 326 --metro --walk 5`.

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

Scripts and agents should pass `--no-input` (anywhere: `tmb --no-input bus 1103` and
`tmb bus 1103 --no-input` both work) or set `TMB_NO_INPUT=1`, so the CLI never waits for a prompt.

## Using it from a coding agent

The point of `tmb` is that your agent (Claude Code, Codex, …) can answer "¿me da tiempo a pillar
el V15?" without ever seeing your TMB keys, and remembers your stop and how long you take to get
there.

1. **You** set the keys once, in your own terminal (not through the agent): `tmb auth set`.
2. Give your agent the guide. It ships with the CLI:
   ```bash
   tmb skills get                                   # print it
   mkdir -p ~/.claude/skills/tmb && tmb skills get > ~/.claude/skills/tmb/SKILL.md   # Claude Code
   ```
   For other agents, point them at `tmb skills get` or paste it into their instructions
   (`AGENTS.md`).
3. Ask: "guarda mi parada de casa, la 1103, tardo 4 minutos" → `tmb fav add casa 1103 --walk 4`.
   Then "¿me da tiempo?" → `tmb --no-input next casa`.

Why a CLI and not raw `curl` against the API: the keys stay out of the agent's context (and out of
its logs), stop names resolve to codes (`tmb stops`), the output is compact (a fraction of the raw
payload's tokens), favourites and walk times persist between sessions, and failures come as typed
JSON with exit codes the agent can act on. `tmb doctor` checks the keys, API access, the stops
cache and the favourites file in one call.

## Development

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Tests never call the real API (they use `httpx.MockTransport`).

## Data and attribution

Data:

- **Transports Metropolitans de Barcelona (TMB)**, from its open developer API
  ([developer.tmb.cat](https://developer.tmb.cat/)), under TMB's
  [terms of use](https://developer.tmb.cat/docs/terms-conditions).
- **Àrea Metropolitana de Barcelona (AMB)**, from its open data (GTFS and GTFS-Realtime of the
  metropolitan buses, publisher AMB Informació), under AMB's
  [terms of use](https://www.amb.cat/web/area-metropolitana/dades-obertes/condicions-d-us)
  (Llei 37/2007).

Both ask to cite the source together with the date of the last update, and not to alter the data.
`tmb` does that in every response: `source` (`"TMB"`, `"AMB"` or `"TMB+AMB"`) and `updated_at`
(the source's own time for real time, the older one when there are two; the dataset dates for the
stops list). `minutes`, `leave_in` and `make_it` are computed from the sources' times; names,
lines and destinations are passed through as published.

Each user gets their own TMB key and accepts TMB's terms. Register the application as `tmb-cli`. TMB
may change the API or its terms without notice; if a response stops matching, `tmb` fails with
`api_changed` (exit 7) instead of guessing.

## Disclaimer

This project is not affiliated with or endorsed by Transports Metropolitans de Barcelona or the
Àrea Metropolitana de Barcelona. It uses TMB's public developer API with your own credentials and
AMB's open data; you are responsible for complying with their terms of use.

## License

[MIT](LICENSE)
