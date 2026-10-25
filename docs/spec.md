# tmb-cli v1 spec

**Status: DRAFT, for Alex to review.** Based on the swagger and the captures of 25/10/2026
(`docs/tmb-api.md`). Open decisions are marked **D1…D9**, each with a recommendation; nothing below them gets
built until Alex picks. Vocabulary: AGENTS.md "Language".

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
tmb fav add <name> <code> --walk MIN [--metro] | list | remove <name>
tmb next <fav-or-code> [--walk MIN] [--line L]...  arrivals + make_it / leave_in
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
`minutes` = whole minutes between `timestamp` and `temps_arribada` (D1). `arrivals` is one flat
list sorted by `eta` (D2). No buses → `"arrivals": []`, exit 0. `--line` is case-insensitive and
repeatable. Unknown stop: the API answers 200 with `parades: []` (captured). If a real stop with no
buses answers the same (night capture pending), `not_found` (exit 4) comes from checking the code
against the stops cache; without a cache, `parades: []` gives `"stop": {"code": …, "name": null}`
and empty arrivals.

- **D1. Minutes: floor or round?** iBus is precise to the minute. *Recommend floor*: 3 min 50 s
  shows 3, so we never promise more time than there is.
- **D2. Flat list sorted by time, or grouped by line?** *Recommend flat*: the agent reads the first
  item for "what comes next", and `--line` covers "when is the V15".
- **D3. Extra fields?** `id_bus`, `id_sentit`, `transit_namespace` (TMB vs other AMB operator).
  *Recommend leaving them out of v1* (tokens); `bus_id` can come back for phase 2.

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
`name` comes from the stops cache, `null` if there's no cache yet. Same rules for `minutes`,
sorting and `--line` as `bus`.

### `tmb stops catalunya`

```json
{
  "query": "catalunya",
  "results": [
    {"type": "bus", "code": "1103", "name": "Pl Catalunya - Portal de l'Àngel", "description": "…"},
    {"type": "metro", "code": "126", "name": "Catalunya", "line": "L1"}
  ],
  "source": "TMB",
  "updated_at": "2026-10-20T09:00:00+02:00"
}
```

(Values made up.) Searches a local cache of `transit/parades` plus the metro stations of each line (one result per
line, because real-time codes are per line: 11 calls, one per metro line). Matching ignores case
and accents, over name and description; exact > prefix > substring. (`transit/parades` seems to list
active stops only; no "not in use" marker was seen.) `updated_at` is TMB's dataset date (`DATA`)
of the cached network. Default `--limit 10`. The stops of a bus stop's lines aren't in
`transit/parades`, so v1 doesn't list lines per bus stop.

- **D10. Metro interchanges in `stops`?** Real-time codes are per line (Catalunya: 126 on L1, 326
  on L3), joined by the group code. *Recommend* one result per station with all its codes,
  `{"type": "metro", "name": "Catalunya", "codes": {"L1": "126", "L3": "326"}}`, so the agent
  passes them all to `tmb metro`. (Alternative: one result per line, as drafted above.)
- **D4. Cache refresh?** *Recommend*: download on first use, refresh automatically when older than
  7 days, `tmb stops --refresh` to force it. Stored in `$XDG_CACHE_HOME/tmb-cli/`.

### `tmb fav add casa 1103 --walk 4`, `tmb next casa`

Favourites live in `$XDG_CONFIG_HOME/tmb-cli/favourites.json`, separate from `credentials.json`, so
sharing one never leaks the other. Names: lowercase letters, digits and `-`.

```json
{
  "favourite": {"name": "casa", "type": "bus", "code": "1103", "walk_minutes": 4},
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
free). `make_it` = `leave_in >= margin` (D6). `tmb next 1103 --walk 4` works without a favourite.

- **D5. Bus or metro in `fav add`?** *Recommend* bus by default, `--metro` for stations: short and
  explicit. (Alternative: `bus:1103` / `metro:126` prefixes.)
- **D6. Safety margin for `make_it`?** *Recommend* 0 by default, `--margin MIN` to add one. The walk
  time the user gives is already their own estimate.

### `tmb doctor`

```json
{"ok": false, "checks": [
  {"name": "credentials", "ok": true, "detail": "from file, mode 0600"},
  {"name": "api", "ok": false, "detail": "TMB API rejected the credentials (HTTP 401).", "code": "auth_failed"},
  {"name": "cache", "ok": true, "detail": "3 days old"}
]}
```

One cheap authenticated request checks the keys. Exit code: the first failing check's (3 for
credentials, 5/6 for the API), 0 when all pass.

### `tmb skills get`

Prints `SKILL.md` (shipped inside the package) to stdout as text: the one exception to "JSON on
stdout", because it is documentation for agents. `SKILL.md` also lives at the repo root.

## Attribution

TMB's terms require citing the source and the date of last update. Every data command adds
`"source": "TMB"` and `"updated_at"` (real time: TMB's `timestamp`; `stops`: the dataset's `DATA`).
README and SKILL.md credit TMB too.

- **D7. Attribution in every output?** It costs ~15 tokens per call. *Recommend yes*: it's what the
  terms literally ask for, and `updated_at` is useful anyway (the agent knows how fresh data is).

## Times

- **D8. `eta` format?** *Recommend* ISO 8601 with offset in Europe/Madrid
  (`2026-10-24T18:06:12+02:00`): unambiguous, every agent parses it. `minutes` covers the "how long".

## Out of scope for v1

`watch` and notifications, MCP server, `plan` (trip planner), `near` (stops around a point; the API
supports it), Bicing, service alerts (no endpoint), the legacy iBus API, lines per bus stop.

- **D9. `--format pretty` in v1?** *Recommend no*: the official app serves humans better; add it
  after v1 if people ask.
