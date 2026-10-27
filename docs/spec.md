# tmb-cli v1 spec

**Status: agreed 25/10/2026.** Based on the swagger and the captures of 25/10/2026
(`docs/tmb-api.md`). Decisions **D1…D10** were all taken as recommended (Alex, 25/10/2026); each
one keeps its reasoning and the rejected alternative. Vocabulary: AGENTS.md "Language".

## Problem

"¿Me da tiempo a pillar el V15?" needs three things an agent doesn't have: the stop's code, the
user's walking time to it, and live arrivals, without ever seeing the user's API keys. The
official app answers humans; nothing answers agents.

## User stories

1. As a user, I set my TMB keys once in a terminal, so my agent can query TMB without ever seeing
   them.
2. As an agent, I find a stop or station code from a name ("Plaça Catalunya"), so the user never
   has to know codes.
3. As an agent, I get the next arrivals at a stop as compact JSON, so I spend few tokens.
4. As an agent, I filter arrivals by line, so I answer "¿cuándo pasa el V15?" directly.
5. As a user, I save "casa" as my stop plus how many minutes I walk to it, once.
6. As an agent, I answer "¿me da tiempo?" with a yes/no per arrival and when to leave.
7. As an agent, I learn how to use the CLI from the CLI itself (`tmb skills get`).
8. As an agent, I diagnose why something fails (`tmb doctor`) and know whether retrying helps.
9. As a script, I never get stuck on a prompt (`--no-input`).
10. As TMB, I'm cited as the source with the data's update time (licence terms).

## Commands

```text
tmb auth set | status                              (exists)
tmb bus <stop> [--line L]...                       real-time arrivals at a bus stop
tmb metro <station>... [--line L]...               real-time arrivals at metro stations
tmb stops <query> [--bus|--metro] [--limit N]      search the static network by name
tmb fav add <name> <code>... --walk MIN [--metro] | list | remove <name>
tmb next <fav-or-code> [--walk MIN] [--margin MIN] [--metro] [--line L]...  arrivals + make_it / leave_in
tmb doctor                                         credentials, API reachability, cache age
tmb skills get                                     the agent guide (SKILL.md) shipped in the package
```

Global: `--no-input` (exists), `--version`. Every command: JSON on stdout, the error contract in
the README (exit codes 0–7, 130).

### `tmb bus 1103`

```json
{
  "stop": {"code": "1103", "name": "Pl Catalunya - Portal de l'Àngel"},
  "arrivals": [
    {"line": "V15", "destination": "Barceloneta", "minutes": 3, "eta": "2026-10-24T18:06:12+02:00"},
    {"line": "H16", "destination": "Pg. Zona Franca", "minutes": 5, "eta": "2026-10-24T18:08:40+02:00"}
  ],
  "source": "TMB",
  "updated_at": "2026-10-24T18:03:12+02:00"
}
```

(Values made up.) Mapping: `line` ← `nom_linia`, `destination` ← `desti_trajecte`,
`eta` ← `temps_arribada`, `updated_at` ← `timestamp`, both in Europe/Madrid time.
`minutes` = whole minutes between `timestamp` and `temps_arribada` (D1), 0 for a bus already due
(`temps_arribada` before `timestamp`). `arrivals` is one flat list sorted by arrival time, then
line (D2). Stop and station codes must be digits, else `usage` (exit 2) before any request. No buses → `"arrivals": []`, exit 0. `--line` is case-insensitive and
repeatable. Unknown stop: the API answers 200 with `parades: []` (captured). If a real stop with no
buses answers the same (night capture pending), so `not_found` (exit 4) comes from the stops
cache: `parades: []` and a cache that doesn't list the code. Without a cache, `parades: []` gives
`"stop": {"code": …, "name": null}` and empty arrivals. `bus` never downloads the cache itself.

- **D1. Minutes: floor or round?** iBus is precise to the minute. **Decided: floor**: 3 min 50 s
  shows 3, so we never promise more time than there is.
- **D2. Flat list sorted by time, or grouped by line?** **Decided: flat**: the agent reads the first
  item for "what comes next", and `--line` covers "when is the V15".
- **D3. Extra fields?** `id_bus`, `id_sentit`, `transit_namespace` (TMB vs other AMB operator).
  **Decided: leave them out of v1** (tokens); `bus_id` can come back for phase 2.

### `tmb metro 126`

```json
{
  "stations": [
    {
      "code": "126",
      "name": "Catalunya",
      "arrivals": [
        {"line": "L1", "destination": "Fondo", "track": 1, "minutes": 2, "eta": "2026-10-24T18:05:00+02:00"}
      ]
    }
  ],
  "source": "TMB",
  "updated_at": "2026-10-24T18:03:12+02:00"
}
```

(Values made up, except that 126 is Catalunya on L1: real-time codes are per line, from
`transit/linies/metro/{line}/estacions`; Catalunya on L3 is 326.) The API groups by line; we
regroup by station. `tmb metro 126` gives only L1; to see every line at an interchange, pass all its
codes (`tmb metro 126 326`), which `tmb stops` returns (D10). The real-time response has **no station name**:
`name` comes from the stops cache, `null` if there's no cache yet (`metro` never downloads it:
run `tmb stops` once). Same rules for `minutes`,
sorting and `--line` as `bus`.

### `tmb stops catalunya`

```json
{
  "query": "catalunya",
  "results": [
    {"type": "bus", "code": "1103", "name": "Pl Catalunya - Portal de l'Àngel", "description": "…", "town": "Barcelona"},
    {"type": "metro", "name": "Catalunya", "codes": {"L1": "126", "L3": "326"}}
  ],
  "source": "TMB",
  "updated_at": "2026-10-20T09:00:00+02:00"
}
```

(Values made up, except Catalunya's codes.) Searches a local cache of `transit/parades` plus the
metro stations of each line (13 requests: stops, lines, one per metro line), one result per station
with its per-line codes joined by `CODI_GRUP_ESTACIO` (D10). The cache keeps only codes and names
(~250 KB). The query is all the words given (no quotes needed). Matching ignores case, accents
and punctuation, and spells street types the way TMB
abbreviates them (plaça → pl, avinguda → av, passeig → pg, carretera → ctra). Ranking: a stop
code or an exact name, then name prefix, then every query word starting a word of the name, then
substring of the name, then every query word in name + town, then in name + town + description. Ties: metro, then Barcelona
bus stops, then other towns' (83% of stops are in Barcelona; Alex, 25/10/2026); then the earlier
the query appears in the name; then the name. Bus results carry `town` (`NOM_POBLACIO`) so the
agent can tell two "Av Catalunya" apart. (`transit/parades` seems to list
active stops only; no "not in use" marker was seen.) `updated_at` is TMB's dataset date (`DATA`)
of the cached network. Default `--limit 10`. The stops of a bus stop's lines aren't in
`transit/parades`, so v1 doesn't list lines per bus stop.

- **D10. Metro interchanges in `stops`?** Real-time codes are per line (Catalunya: 126 on L1, 326
  on L3), joined by the group code. **Decided**: one result per station with all its codes,
  `{"type": "metro", "name": "Catalunya", "codes": {"L1": "126", "L3": "326"}}`, so the agent
  passes them all to `tmb metro`. (Rejected: one result per line.)
- **D4. Cache refresh?** **Decided**: download on first use, refresh automatically when older than
  7 days, `tmb stops --refresh` to force it. Stored in `$XDG_CACHE_HOME/tmb-cli/`.

### `tmb fav add casa 1103 --walk 4`, `tmb next casa`

Favourites live in `$XDG_CONFIG_HOME/tmb-cli/favourites.json`, separate from `credentials.json`, so
sharing one never leaks the other. Names: lowercase letters, digits and `-`, starting with a letter
(so a name never looks like a code). A bus favourite has one stop code; a metro favourite can have
several, one per line of an interchange (`tmb fav add feina 126 326 --metro --walk 5`), as
`tmb stops` returns them. `fav add` replaces a favourite with the same name (`"replaced": true`) and,
when the network is cached, rejects unknown codes with `not_found`; it never downloads the cache.

```json
{
  "favourite": {"name": "casa", "type": "bus", "codes": ["1103"], "walk_minutes": 4},
  "stop": {"code": "1103", "name": "Pl Catalunya - Portal de l'Àngel"},
  "arrivals": [
    {"line": "V15", "destination": "Barceloneta", "minutes": 3, "eta": "…", "make_it": false, "leave_in": -1},
    {"line": "V15", "destination": "Barceloneta", "minutes": 11, "eta": "…", "make_it": true, "leave_in": 7}
  ],
  "source": "TMB",
  "updated_at": "…"
}
```

`leave_in` = `minutes - walk_minutes`: when to set off (this is most of the later `leave` idea, for
free). `make_it` = `leave_in >= margin` (D6). `tmb next 1103 --walk 4` works without a favourite
(`"name": null`; `--walk` is required with a code, `--metro` for a station code). `--walk` on a
favourite overrides its walk time for that call. A metro favourite answers like `tmb metro`
(`stations`, each arrival with `make_it` and `leave_in`). `codes` is a list for both types, so the
shape doesn't depend on the type (implementation choice, 25/10/2026).

- **D5. Bus or metro in `fav add`?** **Decided**: bus by default, `--metro` for stations: short and
  explicit. (Alternative: `bus:1103` / `metro:126` prefixes.)
- **D6. Safety margin for `make_it`?** **Decided**: 0 by default, `--margin MIN` to add one. The walk
  time the user gives is already their own estimate.

### `tmb doctor`

```json
{"ok": false, "version": "0.1.0", "checks": [
  {"name": "credentials", "ok": true, "detail": "from file, mode 0600"},
  {"name": "api", "ok": false, "detail": "TMB API rejected the credentials (HTTP 401).", "code": "auth_failed", "exit_code": 3},
  {"name": "cache", "ok": true, "detail": "3 days old, TMB data of 2026-10-24"},
  {"name": "favourites", "ok": true, "detail": "2 saved"}
]}
```

One small authenticated request (real time for stop 1103, validated like `tmb bus`) checks the
keys and the response shape. The JSON goes to stdout even when a check fails; the exit code is the
first failing check's (3 credentials, 5/6/7 API, 2 favourites file), 0 when all pass. A missing or
old cache is not a failure. A credentials file readable by others is reported in `detail` but
doesn't fail.

### `tmb skills get`

Prints `SKILL.md` (shipped inside the package) to stdout as text: the one exception to "JSON on
stdout", because it is documentation for agents. The source is `src/tmb_cli/SKILL.md`; the repo
root has a copy for people browsing GitHub, and a test fails if they differ.

## AMB: the other metropolitan buses (added 25/10/2026)

AMB publishes real time for the metropolitan buses that aren't TMB's (TUSGSAL, Moventis, Monbus,
Avanza, Aerobús…) as open data, without keys (`docs/amb-api.md`). Stop codes are shared with TMB,
so there is no new command: `bus`, `stops`, `fav` and `next` cover both networks.

- **D11. One `tmb bus` for both, or a separate `tmb amb`?** **Decided (Alex, 25/10/2026)**: one
  command. The user and the agent shouldn't need to know who runs a stop.

### `tmb bus <code>` with AMB

```json
{
  "stop": {"code": "0001", "name": "Parada de prova"},
  "arrivals": [
    {"line": "X1", "destination": "Destí de prova", "minutes": 3, "eta": "…", "operator": "TMB"},
    {"line": "Y7", "destination": "Altre destí", "minutes": 5, "eta": "…", "operator": "Operador de prova"}
  ],
  "source": "TMB+AMB",
  "updated_at": "…"
}
```

(Values made up.) Every arrival gets `operator`: `"TMB"` for TMB's data, AMB's `agency_name`
as published ("DIREXIS TUSGSAL", "Moventis"…) for AMB's. Which sources a call asks:

- **AMB** when the AMB stop list (cached, see below) has the code. Its line names and
  destinations come from that cache (`trip_id` → `routes`/`trips`).
- **TMB** unless the stop is AMB-only: in AMB's list and not in TMB's cached list (without TMB's
  list: AMB's id isn't zero-padded, since AMB pads TMB's codes, `001103`). An AMB-only stop needs
  no keys; any other stop without keys is still `missing_credentials`.
- Both answers are merged into one list sorted by time (D2). If TMB's answer lists other
  operators' lines (`transit_namespace: "amb"`) and AMB answered too, those TMB entries are dropped
  so a bus never appears twice; AMB's own feed is the reference for its buses (confirmed at stop
  916, 26/10/2026: same times, and AMB had lines TMB's answer lacked).
- `stop.name`: TMB's `nom_parada`, else AMB's `stop_name`. `not_found` when neither TMB nor
  either cached stop list knows the code.
- `minutes`: from each source's own query time (TMB's `timestamp`, AMB's `header.timestamp`).
- AMB predicts up to ~2 h ahead and keeps some stops a bus already passed. We drop passages more
  than a minute old and keep the next 2 per line and destination, as TMB answers (25/10/2026).

- **D12. `source` and `updated_at` with two sources?** **Decided (implementation choice, for Alex
  to review)**: `source` stays a string, `"TMB"`, `"AMB"` or `"TMB+AMB"`, and `updated_at` is the
  **older** of the two times, so it never claims fresher data than there is. Keeps the shape of
  every v0.1 output.

### AMB cache

`$XDG_CACHE_HOME/tmb-cli/amb.json`, separate from TMB's `network.json` because it expires on its
own schedule: AMB republishes its GTFS every few days with new trip ids. It keeps stops (code, name,
town, in service), lines (`route_id` → name, operator) and trips (`trip_id` → line, headsign).
Refreshed when the feed's `feed_end_date` has passed, when older than 7 days, or once per command
when the real-time feed names a trip at the asked stop that the cache doesn't know (at most hourly,
so a feed with a stray trip id doesn't cost 9 MB per call).

- **D13. Can `tmb bus` download the AMB cache?** **Decided (implementation choice, for Alex to
  review)**: yes, unlike TMB's network cache. Without it AMB arrivals have no line or destination
  (the real-time feed only has trip ids). The first `bus` call, and one every few days, downloads
  8.8 MB; `tmb stops --refresh` refreshes both caches.

### `tmb stops` with AMB

AMB-only stops (not out of service) join the results with `"network": "AMB"`; TMB stops get
`"network": "TMB"`. A shared stop appears once, as TMB's. AMB's `stop_desc` is the stop's kind
("Pal"), so AMB results have `"description": null`; `town` comes from AMB's areas and can be
`null`. `updated_at` is the older of the two datasets' dates.

### `fav`, `next`, `doctor`

`fav add` accepts AMB codes (checked against the AMB cache when present). `next` works unchanged
through `bus`. `doctor` adds an `amb` check (the real-time feed answers and parses) and reports
the AMB cache's age.

## v0.3: agent-native (places, near, say, watch) — 26/10/2026

Personal agents people text (Instinct, Tab, Hermes, OpenClaw, Claude Code on a phone) get one
message at a time ("avísame cuando le queden 5 min al 67", "estoy en Plaça Catalunya, ¿qué pasa?")
and may run checks later on their own. So: **one message = one call**, answers that read well as a
text message, proactive alerts, and a first-time setup that learns the user's places. Decided with
Alex, 26/10/2026: alerts by "wait and exit" first (D14), coordinates come from the agent (D15),
`say` in Spanish (D16).

### Situations it must answer (the bar for v0.3)

| The user says | One call |
|---|---|
| "¿Me da tiempo a pillar el bus de casa?" | `tmb next casa` |
| "¿Cuándo pasa el 67?" | `tmb next 67` (stops of the user's places and favourites that the 67 serves) |
| "Estoy en Plaça Catalunya, ¿qué pasa por aquí?" | `tmb near "plaça catalunya"` |
| (location shared) "¿Qué me pilla cerca?" | `tmb near 41.3870,2.1700` |
| "Avísame cuando al 67 le queden 5 min" | `tmb watch casa --line 67 --minutes 5` (blocks, exits on the event) |
| "Avísame cuando tenga que salir para el 67" | `tmb watch casa --line 67 --leave` |
| First use: "mi casa está en Carrer X, el trabajo en Y" | agent geocodes, then `tmb place add casa 41.45,2.24 --label "Carrer X"` |
| "Tardo 4 min a esa parada, no 6" | `tmb place walk casa 102526 4` |
| Later (v0.4): "¿a qué hora salgo para llegar a las 9 al trabajo?" | `tmb leave trabajo --by 9:00` (TMB `planner/plan`) |

### Targets: anything goes

Every arrivals command takes a **target**, resolved in this order: a place name, a favourite name,
a line name (`67`, `V15`, `L3`: the stops of the user's places/favourites that it serves), a stop
or station code (digits), coordinates (`lat,lon`), else the best `tmb stops` match for the words.
`resolved` in the output says what was understood.

### `say`

Every data answer adds `"say"`: one or two sentences in Spanish, ready to forward as a text
message, built only from the JSON next to it (no invented data). E.g.
`"Sal en 7 min para pillar el 67 de las 11:35 (llegas justo). El de las 11:19 ya no lo pillas."`
The JSON stays the source of truth; `say` is a convenience.

### Places

`$XDG_CONFIG_HOME/tmb-cli/places.json`, next to favourites, only on the user's machine. A place is
a name, coordinates, an optional label (the address as the user said it), and its **stops**: the
nearby TMB/AMB bus stops and metro stations, each with its walk time.

- `tmb place add <name> <lat,lon> [--label TEXT] [--radius 450] [--max 4]` picks the closest stops
  and stations within the radius (at most 3 bus stops and the closest metro station with all its
  lines) from the cached networks, and estimates walk time: straight-line distance × 1.3 (streets
  aren't straight) at 80 m/min, rounded up, at least 1. The answer lists them with `estimated:
  true` so the agent confirms with the user.
- `tmb place walk <place> <code> <minutes>` corrects one stop's walk time (`estimated: false`).
- `tmb place list | remove <name>`.
- `tmb next <place>` merges the arrivals of all its stops; each arrival carries its stop and
  `leave_in`/`make_it` from that stop's walk time.
- Favourites (v0.1) keep working unchanged; a name is looked up as a place first.

### `tmb near <lat,lon | words> [--radius 450] [--limit 4]`

The closest stops and stations (by straight-line distance, walk estimated as above), each with its
next arrivals, in one answer: `{"near": {"lat", "lon", "resolved"}, "stops": [{"type", "name",
"code" | "codes", "distance_m", "walk_minutes", "arrivals": [...]}], "say", "source",
"updated_at"}`. Words resolve to the best matching stop or station's position. Requests: one TMB
call per TMB bus stop (at most 3), one metro call for all stations, one AMB feed.

### `tmb watch <target> [--line L]... (--minutes N | --leave) [--every 30] [--timeout 60]`

Polls every `--every` seconds (min 20) and **exits as soon as the condition holds**, printing one
event; agents run it in the background and message the user when it ends.

- `--minutes N`: the first matching arrival is N minutes away or less → `"event": "due"`.
- `--leave`: tracks the next arrival the user can still catch (`make_it`); fires when its
  `leave_in` reaches 0 → `"event": "leave_now"`.
- `--timeout` minutes without the event → `"event": "timeout"` (exit 0; nothing to alert).
- Output: `{"event", "target", "arrival", "say", "checked": N, "source", "updated_at"}`. Errors
  during polling are retried while `retryable`; others end the watch with the usual JSON error.

### First-time setup (agents)

SKILL.md: if `tmb place list` is empty, the agent asks which places the user goes to (home, work,
gym…) and where they are, geocodes them, runs `tmb place add` for each, reads back the chosen stops
with their walk times and fixes them with `tmb place walk`. Humans can do the same by hand.

## v0.4: routes and when to leave (27/10/2026)

From TMB's trip planner (`planner/plan`, timetables, not real time: `docs/tmb-api.md`).

| The user says | One call |
|---|---|
| "¿Cómo voy a Sagrada Família?" | `tmb route casa sagrada familia` |
| "Tengo que estar en el trabajo a las 9, ¿a qué hora salgo?" | `tmb leave trabajo --by 9:00` |
| "Si salgo ahora, ¿llego a las 18:00 a casa de Laura?" | `tmb leave 41.39,2.15 --by 18:00` (the agent geocodes) |
| "Calcula la ruta y avísame cuando tenga que salir" | `tmb leave trabajo --by 9:00 --wait` (background) |

- **`tmb route <from> <to> [--by HH:MM | --at HH:MM] [--day YYYY-MM-DD]`**: up to 3 options, each
  `{leave_at, leave_in, arrive_at, minutes, walk_minutes, transfers, scheduled: true, legs: [{mode:
  walk|metro|bus|…, line, direction, from, to, from_code, depart, arrive, minutes}]}`. With `--by`
  (arrive by), options that arrive in time, latest departure first; otherwise (leave now or
  `--at`), earliest arrival first. A walk-only option counts like any other.
- **`tmb leave <to> [--from X] [--by HH:MM]`**: the best option only, with `leave_in` (minutes
  from now). `--from` defaults to the place `casa` if it exists; also takes any target that has a
  position (a place, `lat,lon`, a stop or station name).
- **`--wait`** on `leave`: re-plans every 5 min and exits with `"event": "leave_now"` at the
  departure time (or at once if it's already time), like `watch`.
- From and to resolve like other targets but need a position: places, `lat,lon`, stop or station
  names. Addresses: the agent geocodes them.
- Times are Barcelona time. `--by`/`--at` without `--day` mean today, or tomorrow if that time
  has passed. `say` says "según horarios" because the planner isn't real time.

## v0.5: setup, trips, preferences, ambiguity (27/10/2026)

Asked by Alex: the first time, the agent asks everything it needs (and offers trips and alerts);
it never guesses where the user is; when a name could be several places, it asks.

- **Location.** `tmb` runs on the agent's machine and can't see the phone. The agent passes a
  location the user shared (a WhatsApp or iMessage pin carries coordinates) as `lat,lon`, or asks
  "¿dónde estás?" (a street, a stop, a landmark). Never guess.
- **`tmb setup`** returns what is configured and what is missing, in order, each missing item with
  the question to ask (`"next_question"`), so the agent can loop: ask, run the command, call
  `setup` again until `"complete": true`. Items: TMB keys (optional: AMB works without), places
  (at least `casa`), each place's walk times confirmed, trips (optional, offered once), preferences
  (margin, walking pace).
- **Trips** (`trips.json`): `tmb trip add <name> --from <place> --to <place> [--by HH:MM]
  [--days lun-vie]`, `trip list|remove`. `tmb leave <trip>` and `tmb route <trip>` use its from, to
  and `--by` (overridable). `--days` is information for the agent, which schedules its own daily
  check (`tmb leave <trip> --wait` some time before) if the user wants an alert: `tmb` doesn't
  schedule anything.
- **Preferences** (`prefs.json`): `tmb prefs [--margin N] [--pace slow|normal|fast]`. `margin`
  is the default `--margin` of `next`/`watch`; `pace` scales estimated walks (65, 80, 95 m/min;
  only estimates: walks the user set stay as they are).
- **Ambiguity.** When a name resolves through search, `resolved` adds `alternatives` (other good
  matches in other places, with town) and `ambiguous: true` if one of them ranks like the best
  and is more than 500 m away. `say` then starts with "¿Te refieres a X (Barcelona)?" and still
  answers for the best guess; the agent should ask before acting on it (an alert, a route).

## v0.6: notifications (27/10/2026)

For agents that can't run a background job and message the user later, `tmb` can deliver the
alert itself.

- `watch` and `leave --wait` take `--notify TARGET`; `tmb prefs --notify TARGET` sets a default
  (`--notify none` turns it off for one call, `prefs --notify none` clears it).
- Targets: `ntfy:<topic>` (push to the ntfy app, server ntfy.sh), `ntfy:https://host/<topic>`
  (a self-hosted ntfy), `webhook:https://…` (POST of the event JSON).
- ntfy messages use ntfy's JSON publishing (`POST https://host/` with `topic`, `title` "tmb",
  `message` = the event's `say`, `priority` 4, `tags`). Only `due` and `leave_now` notify, not
  `timeout`.
- The event JSON gains `"notified": {"target": "ntfy:<topic>" | "webhook", "ok": bool, "error"?}`.
  A failed notification doesn't fail the command (the alert still prints). Webhook URLs aren't
  echoed (they often carry tokens).
- `tmb notify-test [TARGET]` sends a test message to the target or the default.
- Privacy: on ntfy.sh anyone who knows a topic can read it, and alerts reveal stops and times.
  Topics shorter than 12 characters get a `warning`; SKILL.md tells agents to suggest a long
  random topic.

## Attribution

TMB's and AMB's terms require citing the source and the date of last update. Every data command
adds `"source"` (`"TMB"`, `"AMB"` or `"TMB+AMB"`) and `"updated_at"` (real time: the source's own
time, the older one when there are two; `stops`: the dataset dates). README and SKILL.md credit both.

- **D7. Attribution in every output?** It costs ~15 tokens per call. **Decided: yes**: it's what the
  terms literally ask for, and `updated_at` is useful anyway (the agent knows how fresh data is).

## Times

- **D8. `eta` format?** **Decided**: ISO 8601 with offset in Europe/Madrid
  (`2026-10-24T18:06:12+02:00`): unambiguous, every agent parses it. `minutes` covers the "how long".

## Out of scope for v1

`watch` and notifications, MCP server, `plan` (trip planner), `near` (stops around a point; the API
supports it), Bicing, service alerts (no endpoint), the legacy iBus API, lines per bus stop.

- **D9. `--format pretty` in v1?** **Decided: no**: the official app serves humans better; add it
  after v1 if people ask.
