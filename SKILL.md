---
name: tmb
description: Real-time TMB (Barcelona) bus and metro arrivals with the `tmb` CLI. Use when the user asks when a bus or metro comes, whether they can catch it ("¿me da tiempo?", "¿cuándo pasa el V15?"), when to leave, or for a stop or station code.
---

# tmb: Barcelona bus and metro arrivals

`tmb` answers from TMB's official API. Every command prints JSON on stdout; errors are one line of
JSON on stderr with a stable exit code. Always pass `--no-input`, so it never waits for a prompt.

## Which command

| The user asks | Run |
|---|---|
| "¿Me da tiempo a pillar el bus de casa?" | `tmb --no-input next casa` |
| "¿Cuándo pasa el V15 por mi parada?" | `tmb --no-input next casa --line V15` |
| Next buses at a stop | `tmb --no-input bus 1103` |
| Next trains at a station | `tmb --no-input metro 126 326` |
| A stop or station code from a name | `tmb --no-input stops "plaça catalunya"` |
| Their saved places | `tmb --no-input fav list` |
| Something fails | `tmb --no-input doctor` |

Start with `tmb --no-input fav list`: the user may already have a favourite (e.g. `casa`, `feina`)
with their walk time.

## Answering "¿me da tiempo?"

`tmb next <favourite>` adds to each arrival:

- `leave_in`: minutes until the user must set off (`minutes` minus their walk time). Negative
  means it's too late for that one.
- `make_it`: `true` if they can catch it (`leave_in` ≥ `--margin`, 0 by default).

Answer with the first arrival where `make_it` is `true`, say when to leave, and **always say the
walk time you counted** (`favourite.walk_minutes`) and the stop, so the user can correct it:
"Contando 4 min andando hasta Pl Catalunya: el V15 de las 18:06 no lo pillas; el siguiente pasa en
11 min, sal en 7." Use `--margin 2` if the user wants spare time.

The walk time is the user's, never yours:

- If the user gives a different time for today ("hoy voy con prisa, tardo 2"), pass `--walk 2`
  for that call; it doesn't change the favourite. To change it for good, `fav add` the same name
  again with the new `--walk` (it replaces the old one).
- Without a favourite, `tmb next 1103 --walk 4` works too (`--metro` for a station code), but
  **ask how many minutes they walk** first: don't guess a number. Offer to save it as a favourite.

## Saving a favourite

Ask the user for the stop (name or code) and how many minutes they walk to it, then:

1. Find the code: `tmb --no-input stops <words>` (name, street or town). Bus results have `code`
   and `town`; metro results have `codes`, one per line (`{"L1": "126", "L3": "326"}`). If several
   match, ask. No results can mean the stop belongs to another operator (e.g. most buses in
   Badalona are TUSGSAL's): `tmb` only covers TMB's network, so say so and suggest a nearby metro
   station or a TMB stop instead.
2. Save it: `tmb --no-input fav add casa 1103 --walk 4`, or for a station with all its lines
   `tmb --no-input fav add feina 126 326 --metro --walk 5`. Names: lowercase, start with a letter.

## Output

- `minutes`: whole minutes from TMB's query time, rounded down (3 min 50 s is 3). `eta`: arrival
  time in Barcelona time, ISO 8601.
- `arrivals` is sorted by time. An empty list means TMB has no prediction right now (e.g. at
  night), not an error.
- Metro arrivals carry `track` (1 or 2, the two directions). Real-time station codes are per line:
  pass every code of an interchange to see all its lines.
- `source` and `updated_at`: TMB's data and when it was produced. Mention that it comes from TMB
  if you show the data to others.
- Real-time data changes every few seconds: run the command again rather than reusing an old
  answer.

## Errors

| Exit | `code` | What to do |
|---|---|---|
| 2 | `usage` | Fix the command (the message says what's wrong). |
| 3 | `missing_credentials`, `auth_failed` | Ask the user to run `tmb auth set` **in their own terminal**. Never ask for, read, print or pass the keys yourself. |
| 4 | `not_found` | Unknown stop, station or favourite, or another operator's stop (TMB has no data for those): search with `tmb stops`, or check `tmb fav list`. |
| 5 | `rate_limited`, `api_error` | If `retryable` is `true`, wait a little and retry once. |
| 6 | `network_error` | Retry once; then tell the user TMB can't be reached. |
| 7 | `api_changed` | TMB changed its API: tell the user; retrying won't help. |

## Don't

- Don't read `~/.config/tmb-cli/credentials.json` or ask for `app_id`/`app_key`.
- Don't call `api.tmb.cat` directly: the CLI keeps the keys out of your context and the output
  small.
- Don't guess codes: look them up with `tmb stops`.
