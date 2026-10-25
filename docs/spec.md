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
(~250 KB). Matching ignores case, accents and punctuation, and spells street types the way TMB
abbreviates them (plaça → pl, avinguda → av, passeig → pg, carretera → ctra). Ranking: a stop
code or an exact name, then name prefix, then every query word starting a word of the name, then
substring of the name, then every query word in name + description. Ties: metro, then Barcelona
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

## Attribution

TMB's terms require citing the source and the date of last update. Every data command adds
`"source": "TMB"` and `"updated_at"` (real time: TMB's `timestamp`; `stops`: the dataset's `DATA`).
README and SKILL.md credit TMB too.

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
