# AGENTS.md — tmb-cli

Instructions for coding agents (Claude Code, Codex, …) working in this repo.
The maintainer is Alex (@alegoml). **Talk to him in Spanish**; code, comments, commits and docs
stay in English.

## What this is
An unofficial, JSON-first CLI for TMB (Barcelona) real-time bus and metro arrivals, built so that
coding agents can answer things like "¿me da tiempo a pillar el V15?". Inspired by
`Microck/wallapop-cli` and `luisgonzaleznf/vodafone-cli`. Private repo until v1, then public.

## Stack and layout
- Python 3.12+, uv, Typer (CLI), httpx (HTTP), pytest, ruff.
- `src/tmb_cli/cli.py` commands · `client.py` TMB API client · `config.py` credentials ·
  `errors.py` typed errors + exit codes · `output.py` JSON to stdout/stderr.
- `tests/` offline tests only.

## Commands
```bash
uv sync
uv run tmb --help
uv run pytest
uv run ruff check . && uv run ruff format .
```

## Rules
1. **JSON on stdout, JSON errors on stderr**, exit codes from `errors.py` (0 ok, 2 usage,
   3 credentials, 4 not found, 5 API/network). Never print prose to stdout in JSON mode.
2. **Credentials are secret.** Never print, log, commit or put `app_id`/`app_key` in error
   messages, fixtures or test names. The request URL contains them: don't echo it.
3. **Tests never hit the network.** Use `httpx.MockTransport`. Fixtures captured from the real API
   must be sanitized (no keys) before they go in `tests/fixtures/`. Raw captures go in `captures/`
   (git-ignored).
4. **Read-only.** Only GET endpoints of the official API at `https://api.tmb.cat/v1/`. Don't use
   third-party backends (e.g. andana.bcn.am) or scrape tmb.cat.
5. **Don't invent API fields.** Shape output only from fields seen in real responses; when unsure,
   ask Alex to run the command and paste (sanitized) output.
6. Small, reviewable changes. Explain briefly what you changed and why: Alex owns the design.

## TMB API notes (verified 23/10/2026)
- Free keys at developer.tmb.cat (create an application). Auth = `app_id` + `app_key` query params;
  without them every endpoint returns 401 "Authentication parameters missing".
- Bus real time: `itransit/bus/parades/{stop_code}`.
- Metro real time: `itransit/metro/estacions?estacions=<code>,<code>`.
- Static network: `transit/linies/{bus|metro}`, `transit/linies/bus/{line}/recs`, …
- Trip planner: `planner/plan`.
- Rate limits / terms: unknown until Alex logs into the portal. Record them here.

## Positioning
The TMB API is public and simple, so an agent could `curl` it directly. The CLI earns its place by
doing what an agent can't do well alone: keep the keys out of the agent's context, resolve stop
names to codes, return compact output (fewer tokens than the raw payload), and remember state
(favourites, walking time). Pitch: "your agent knows your stop, how long you take to get there, and
never sees your keys". Prior art to acknowledge in the README/post: `ibus-mcp` (MCP server, bus
only), `pytmb` and `tmb` (Python libraries), Home Assistant's TMB integration.

## Roadmap to v1 (keep this list up to date)
- [x] Skeleton: auth set/status, `bus <stop>`, `metro <stations…>` (raw payload), error mapping, tests
- [ ] Capture one real bus + metro response, sanitize, add as fixtures
- [ ] Compact, stable output: `{stop, arrivals: [{line, destination, minutes, eta}]}`; `--line` filter
- [ ] `tmb stops <name>`: search stops/stations by name → codes (cache the static network locally)
- [ ] Favourites with walking time: `tmb fav add casa 108 --walk 4`, `tmb next casa` → per arrival
      `make_it: true/false` (answers "¿me da tiempo?")
- [ ] `SKILL.md` so agents know how to use the CLI
- [ ] Check TMB terms of use (publishing a client is allowed?) and rate limits; record them above
- [ ] `--format pretty` for humans (low priority: the official app beats us for humans)
- [ ] `uv tool install` from GitHub, README demo (3-step key signup), 15 s human-vs-agent video →
      go public + post

Later (not v1), roughly by value: `watch` with notifications (ntfy/webhook), `plan A B` via
`planner/plan`, service alerts (if the API exposes them), `leave` ("¿cuándo salgo?"), Bicing
availability, train positions per line, MCP server, phase 2 ML (log iBus predictions vs actual
arrivals; check first whether actual arrivals can be observed at all).

Possible sibling project with the same pattern: Datadis (own electricity consumption) + PVPC prices.
