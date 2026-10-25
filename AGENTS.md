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
1. **JSON on stdout, JSON errors on stderr**, exit codes from `errors.py` (0 ok, 1 internal,
   2 usage, 3 credentials, 4 not found, 5 API/rate limit, 6 network, 7 API changed,
   130 interrupted). Never print prose to stdout in JSON mode; prompts go to stderr
   (`typer.prompt(..., err=True)`). Every command runs through `cli._run`, which turns any
   exception into the JSON error (unknown ones by type only).
2. **Credentials are secret.** Never print, log, commit or put `app_id`/`app_key` in error
   messages, fixtures or test names. The request URL contains them: don't echo it.
3. **Tests never hit the network.** Use `httpx.MockTransport`. Real responses go only in
   `captures/` (git-ignored, never committed) and are used to learn the response shape.
   `tests/fixtures/` holds **synthetic** responses: the same structure and field names as a real
   capture, but made-up values (lines like `X1`, stops like `0001`, names like "Destí de prova").
   No real TMB data and no stop that hints where Alex lives: the repo will be public.
4. **Read-only.** Only GET endpoints of the official API at `https://api.tmb.cat/v1/`. Don't use
   third-party backends (e.g. andana.bcn.am) or scrape tmb.cat.
5. **Don't invent API fields.** Shape output only from fields seen in real responses; when unsure,
   ask Alex to run the command and paste (sanitized) output.
6. Small, reviewable changes. Explain briefly what you changed and why: Alex owns the design.

## TMB API notes (verified 23/10/2026; response shapes in `docs/tmb-api.md`)
- Free keys at developer.tmb.cat (create an application). Auth = `app_id` + `app_key` query params;
  without them every endpoint returns 401 "Authentication parameters missing".
- Bus real time: `itransit/bus/parades/{stop_code}`.
- Metro real time: `itransit/metro/estacions?estacions=<code>,<code>`.
- Static network: `transit/linies/{bus|metro}`, `transit/linies/bus/{line}/recs`, …
- Trip planner: `planner/plan`.

From the portal's public swagger (read 24/10/2026; not yet confirmed by a capture):
- All bus stops: `transit/parades` (GeoJSON; `CODI_PARADA`, `NOM_PARADA`, `DESC_PARADA`, …),
  `transit/parades/{code}`, `?filter=FIELD=value`. Metro stations: `transit/estacions`,
  `transit/linies/metro/{line}/estacions`. Static GTFS: `static/datasets/gtfs.zip`.
- Legacy iBus (`stops/{code}`, `lines/{line}/stops/{code}`) is deprecated: don't use it.
- No service-alerts endpoint; only an `alerts` field inside `planner/plan` responses.
- Rate limits: not stated in the swagger, the terms or the app's page in the portal (checked
  25/10/2026). No automatic retries; 429 → `rate_limited`.

Confirmed by captures (25/10/2026, details in `docs/tmb-api.md`): bad keys → 401 (not 403); an
unknown bus stop → 200 with `parades: []` (not 404); `codi_linia` is an int; the real-time metro
`codi_estacio` is `CODI_ESTACIO` of `transit/linies/metro/{line}/estacions` (120 = Plaça de Sants
on L1; Catalunya is 126 on L1 and 326 on L3, one code per line, joined by `CODI_GRUP_ESTACIO`);
undocumented `info_bus.accessibilitat.estat_rampa` on each bus.

Terms (developer.tmb.cat/docs/terms-conditions, read 24/10/2026): free, non-exclusive, worldwide,
indefinite licence to reproduce, distribute and make derived works of the GTFS and API data. We
must **cite the source (TMB) and the date of last update**, **not alter or distort the data**, and
use it only for the application declared when the key was created (users should register their
app as tmb-cli). TMB may change the API, data or terms at any time without notice. Publishing a
client isn't addressed; each user accepts the terms with their own key.

## Language
Use these words in code, output and docs; avoid the alternatives. [wallapop's CONTEXT.md habit]

- **Stop** (parada): a bus stop, identified by its stop code (e.g. `108`). _Avoid_: station.
- **Station** (estació): a metro station, identified by its station code. _Avoid_: stop.
- **Line** (línia): a bus or metro line as TMB names it (`V15`, `H12`, `L3`). _Avoid_: route.
- **Arrival**: one predicted vehicle at a stop or station. `minutes` = minutes from now, `eta` =
  clock time. _Avoid_: departure, prediction (except when talking about iBus accuracy).
- **Destination**: where the arriving vehicle's trip ends, as TMB names it. _Avoid_: direction,
  headsign.
- **Static network**: lines, stops and stations from the `transit/…` endpoints, cached locally.
  **Real time** is the `itransit/…` endpoints, never cached.
- **Favourite**: a local name for a stop or station plus the user's **walk time** (minutes to get
  there). Lives only on the user's machine. _Avoid_: bookmark, saved stop.
- **make_it**: whether the user can catch an arrival from a favourite (`minutes` ≥ walk time);
  the exact rule is defined in `docs/spec.md`.

## Positioning
The TMB API is public and simple, so an agent could `curl` it directly. The CLI earns its place by
doing what an agent can't do well alone: keep the keys out of the agent's context, resolve stop
names to codes, return compact output (fewer tokens than the raw payload), and remember state
(favourites, walking time). Pitch: "your agent knows your stop, how long you take to get there, and
never sees your keys". Prior art to acknowledge in the README/post: `ibus-mcp` (MCP server, bus
only), `pytmb` and `tmb` (Python libraries), Home Assistant's TMB integration.

## Roadmap to v1 (keep this list up to date)
Habits borrowed from `luisgonzaleznf/vodafone-cli` and `Microck/wallapop-cli` are noted in brackets.

1. - [x] Skeleton: auth set/status, `bus <stop>`, `metro <stations…>` (raw payload), error mapping
2. - [x] Error contract: exit codes 1/6/7/130, `retryable`, catch-all by type only, prompts on
     stderr, `--no-input`, strict JSON [both]
   - [x] CI: ruff + pytest on GitHub Actions (runs once the repo is on GitHub)
3. - [x] Tooling: opt-in live tests (`TMB_LIVE=1`) and `scripts/capture.py` writing to `captures/`
     [vodafone]
   - [x] Alex ran the first captures (25/10/2026): bus stop, unknown stop, metro station, static
     network
   - [ ] Pending capture: a stop with no buses (night); synthetic fixtures updated to the confirmed shape in `tests/fixtures/`
4. - [x] `docs/tmb-api.md`: response shapes from the public swagger (to confirm with captures)
   - [x] `docs/spec.md` draft: v1 commands, JSON shapes, user stories, decisions D1–D9 [wallapop]
   - [ ] Alex picks D1–D10; spec updated after the captures. No new commands before that
5. - [ ] Pydantic `Wire*` models (only fields we read, unknown ignored; mismatch → `api_changed`)
     and output models (our stable contract) [vodafone]; compact `bus`/`metro`; `--line` filter
6. - [ ] `tmb stops <name>`: search stops/stations by name → codes (cache the static network locally)
7. - [ ] Favourites with walking time: `tmb fav add casa 108 --walk 4`, `tmb next casa` → per arrival
     `make_it: true/false` (answers "¿me da tiempo?")
8. - [ ] Agents: `SKILL.md` + `tmb skills get` (the skill ships inside the package) [wallapop];
     `tmb doctor` (credentials, connectivity, cache age) [wallapop]; README "Using it from a coding
     agent" section [vodafone]
9. - [ ] Release: TMB attribution in README (and in the output if the spec decides so); rate limits
     from Alex's portal page;
     `source-exclude` for secrets in the build, pinned `uv tool install …@vX.Y.Z` + `install.sh`,
     a packaging test that pins agree, `RELEASING.md` [vodafone]; README demo (3-step key signup),
     15 s human-vs-agent video → go public + post
   - [ ] `--format pretty` for humans (low priority: the official app beats us for humans)

Later (not v1), roughly by value: `watch` with notifications, modelled as Watch → Check → Event →
Sink (ntfy/webhook/exec) [wallapop]; `plan A B` via `planner/plan`; service alerts (if the API
exposes them); `leave` ("¿cuándo salgo?"); Bicing availability; MCP server as a thin wrapper that
runs each command and returns its JSON verbatim, plus `tmb mcp install claude-code` [wallapop];
prefilled GitHub issue link on `api_changed` [wallapop]; Homebrew tap [vodafone]; train positions
per line; phase 2 ML (log iBus predictions vs actual arrivals; check first whether actual arrivals
can be observed at all).

Not borrowed on purpose (we don't need them: two static keys, small command surface): session
engine/encrypted vault, profiles, proxy, file locks, noun-verb command tree, docs site, npm wrapper.

Possible sibling project with the same pattern: Datadis (own electricity consumption) + PVPC prices.
