---
name: tmb
description: Barcelona buses and metro in real time (TMB, plus AMB's metropolitan buses) with the `tmb` CLI. Use when the user asks when a bus or metro comes, whether they can catch it ("¿me da tiempo?", "¿cuándo pasa el 67?"), when to leave, what's near them, or to be told when to go ("avísame cuando le queden 5 min").
---

# tmb: Barcelona buses and metro, for a personal agent

Every command prints JSON on stdout (errors: one JSON line on stderr, stable exit codes). Always
pass `--no-input`. **Every answer has `say`: a ready-to-send Spanish sentence. Forward it as is**
unless the user asked for something else; the rest of the JSON is there for details.

## First time: learn the user's places

Run `tmb --no-input place list`. If `places` is empty, ask (in one message):
"¿Qué sitios usas a menudo y dónde están? Por ejemplo casa, trabajo, el gimnasio…".
For each place:

1. Turn the address into coordinates with your own tools (maps, search). `tmb` doesn't geocode.
2. `tmb --no-input place add casa 41.4521,2.2410 --label "Carrer X 12, Badalona"`. It picks the
   closest bus stops (TMB and AMB) and metro station and estimates the walk to each.
3. Send its `say` ("He guardado «casa» con 3 paradas: …"). If the user corrects a walk time:
   `tmb --no-input place walk casa <code> <minutes>`.

Names: lowercase, start with a letter (`casa`, `trabajo`, `gym`). Ask again only for new places.

## What they say → one call

| The user says | Run |
|---|---|
| "¿Me da tiempo a pillar el bus de casa?" / "¿cuándo salgo?" | `tmb --no-input next casa` |
| "¿Cuándo pasa el 67?" (no stop said) | `tmb --no-input next 67` (looks in the user's places) |
| "¿Cuándo pasa el V15 por casa?" | `tmb --no-input next casa --line V15` |
| "Estoy en Plaça Catalunya, ¿qué pasa por aquí?" | `tmb --no-input near plaça catalunya` |
| Location shared ("¿qué tengo cerca?") | `tmb --no-input near 41.3870,2.1700` |
| "¿Qué pasa por la parada 1103?" / "¿y el metro en Sants?" | `tmb --no-input next 1103` / `tmb --no-input next sants` |
| "Hoy voy con prisa, tardo 2" | add `--walk 2` to that call |
| "Quiero llegar con margen" | add `--margin 2` |
| "Avísame cuando al 67 le queden 5 min" | `tmb --no-input watch casa --line 67 --minutes 5` (background) |
| "Avísame cuando tenga que salir" | `tmb --no-input watch casa --leave` (background) |

`next` and `watch` take anything: a place, a favourite, a line, a stop code, `lat,lon`, or words.
`resolved` in the answer says what was understood; if it isn't what the user meant, ask.

## Alerts (`watch`)

`watch` waits, checking every 30 s, and **exits** with one event: `due` (`--minutes N`),
`leave_now` (`--leave`, counting the walk) or `timeout` (after `--timeout`, 60 min by default).
Run it **in the background** and message the user its `say` when it ends; on `timeout`, say you
stopped watching. Confirm right away: "Vale, te aviso cuando le queden 5 min al 67."
If you can't run background jobs, schedule yourself a check instead and call `next` then.

## Reading answers

- `arrivals` by time; each has `minutes`, `eta` (Barcelona time), `stop`, `operator`, and with a
  known walk `leave_in` (minutes until they must set off; negative = too late) and `make_it`.
- Mention the walk time you counted when it matters ("contando 4 min andando").
- Empty arrivals = no predictions right now (often at night), not an error.
- `source`: TMB and/or AMB; cite it if you show data to others.
- Real-time data changes every few seconds: ask again rather than reuse an old answer.
- Not covered: Rodalies, FGC, tram. Say so if asked.

## Errors

| Exit | `code` | What to do |
|---|---|---|
| 2 | `usage` | Fix the command (the message says what's wrong). |
| 3 | `missing_credentials`, `auth_failed` | TMB keys missing or wrong: ask the user to run `tmb auth set` in their own terminal, or set `TMB_APP_ID`/`TMB_APP_KEY` as secrets. Never ask for, read, print or pass the keys yourself. AMB-only stops still work. |
| 4 | `not_found` | Unknown place, stop or name: `tmb --no-input stops <words>` to find codes, or ask. |
| 5 | `rate_limited`, `api_error` | If `retryable`, wait a little and retry once. |
| 6 | `network_error` | Retry once; then tell the user TMB or AMB can't be reached. |
| 7 | `api_changed` | TMB or AMB changed their data: tell the user; retrying won't help. |

## Other commands

`tmb stops <words>` (find codes; `--metro`/`--bus`), `tmb bus <code>`, `tmb metro <codes>`,
`tmb place list|remove`, `tmb fav add|list|remove` (older, single-stop favourites), `tmb doctor`
(what's wrong, in one call).

Never read `~/.config/tmb-cli/` files or call the APIs directly: the CLI keeps the keys out of your
context and the answers short.
