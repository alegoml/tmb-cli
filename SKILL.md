---
name: tmb
description: Barcelona buses and metro in real time (TMB, plus AMB's metropolitan buses) with the `tmb` CLI. Use when the user asks when a bus or metro comes, whether they can catch it ("¿me da tiempo?", "¿cuándo pasa el 67?"), when to leave, how to get somewhere, what's near them, or to be told when to go ("avísame cuando le queden 5 min").
---

# tmb: Barcelona buses and metro, for a personal agent

The user writes from their phone, in a few words. Make it effortless for them: one short reply,
no codes, no JSON. Every command prints JSON; **every answer has `say`, a ready-to-send Spanish
sentence: forward it as is** unless they asked for something else. Always pass `--no-input`.

## First time (and whenever something is missing): `tmb --no-input setup`

It returns `items` (what's set up), `next_question` (what to ask now) and a `command` hint per item.
Loop until `"complete": true`: ask `next_question` in your own words, run the matching command,
call `setup` again. Ask one or two things per message, not a form. The order:

1. **Home**: "¿Dónde vives?". Turn the address into `lat,lon` with your own tools (`tmb` doesn't
   geocode), then `tmb --no-input place add casa <lat,lon> --label "<address>"`. Send its `say`.
2. **Other places**: work, studies, gym, someone's home… Same command, one name each (lowercase,
   starting with a letter). None: `tmb --no-input setup --done places`.
3. **Walk times**: `setup` asks whether the estimated walks are right. Fix one:
   `tmb --no-input place walk casa <code> <min>`; all fine: `tmb --no-input place confirm casa`.
4. **Trips**: a usual trip at a fixed time? `tmb --no-input trip add trabajo --from casa --to
   trabajo --by 9:00 --days lun-vie`. **Offer a daily alert** for it, and if they want one, schedule
   it yourself on those days (`tmb` doesn't schedule): e.g. 45 min before, run
   `tmb --no-input leave trabajo --wait` in the background and send its `say` when it ends. None:
   `tmb --no-input setup --done trips`.
5. **Preferences**: margin at the stop and walking pace: `tmb --no-input prefs --margin 2 --pace
   slow|normal|fast`. Keep as is: `tmb --no-input setup --done prefs`.
6. **Notifications** (only if you can't message the user on your own; otherwise
   `setup --done notify`): `setup` suggests a long random ntfy topic. The user installs the ntfy
   app and subscribes to it; then `tmb --no-input prefs --notify ntfy:<topic>` and
   `tmb --no-input notify-test` ("¿te ha llegado?"). Every `watch`/`leave --wait` then pushes its
   alert there too. Keep topics long and random: anyone who knows one can read it.
7. **TMB keys** (optional; AMB's metropolitan buses work without): the user creates free keys at
   developer.tmb.cat and runs `tmb auth set` in their own terminal, or puts `TMB_APP_ID` and
   `TMB_APP_KEY` in your secrets. **Never ask for, read, print or pass the keys yourself.**
   Skipped: `tmb --no-input setup --done keys`.

New place or trip later ("apunta el gimnasio, está en …"): just add it; no need to rerun setup.

## Where the user is

`tmb` can't see the phone. If they shared their location (a WhatsApp or iMessage pin carries
coordinates), pass it as `lat,lon`. If they say where they are ("en la parada de la Diagonal con
Balmes", "en el Corte Inglés"), pass the words or geocode them. If you don't know, **ask**
("¿Dónde estás? Puedes mandarme la ubicación"); never guess. "En casa", "en el trabajo": use the
saved place.

## What they say → one call

| The user says | Run |
|---|---|
| "¿Me da tiempo a pillar el bus?" / "¿cuándo salgo?" (at home) | `tmb --no-input next casa` |
| "¿Cuándo pasa el 67?" (no stop said) | `tmb --no-input next 67` (searches their places) |
| "¿Cuándo pasa el V15 por casa?" | `tmb --no-input next casa --line V15` |
| "Estoy en Plaça Catalunya, ¿qué pasa por aquí?" | `tmb --no-input near plaça catalunya` |
| (location pin) "¿qué tengo cerca?" | `tmb --no-input near 41.3870,2.1700` |
| "¿Y el metro en Sants?" / "¿la parada 1103?" | `tmb --no-input next sants` / `tmb --no-input next 1103` |
| "Hoy voy con prisa, tardo 2" | add `--walk 2` to that call |
| "Avísame cuando al 67 le queden 5 min" | `tmb --no-input watch casa --line 67 --minutes 5` (background) |
| "Avísame cuando tenga que salir" | `tmb --no-input watch casa --leave` (background) |
| "¿Cómo voy a Sagrada Família?" | `tmb --no-input route casa "sagrada familia"` |
| "¿Cuándo salgo para el trabajo?" | `tmb --no-input leave trabajo` (a saved trip) |
| "Tengo que estar en X a las 18:00" | `tmb --no-input leave <lat,lon or name> --by 18:00` |
| "Calcula la ruta y avísame cuando salir" | `tmb --no-input leave … --by … --wait` (background) |

`next`, `near` and `watch` take anything: a place, a favourite, a line, a stop code, `lat,lon`,
or words. `route`/`leave` take places, trips, `lat,lon` or stop/station names; quote multi-word
values for `route` and `--from`. `leave` starts from `casa` unless `--from` says otherwise.

## Ambiguous names: ask

If `resolved.ambiguous` is `true` (or `from`/`to` in a route), the name matches another place too
(e.g. "Plaça Catalunya" in Barcelona and in Gavà): `alternatives` lists them with their town and
`say` already asks "si te referías a …, dímelo". **Before an alert or a route, confirm which
one.** Then save it as a place so it isn't ambiguous again.

## Alerts

`watch` and `leave --wait` wait and **exit** with one event: `due`, `leave_now`, or `timeout`.
Run them **in the background**, confirm at once ("Vale, te aviso cuando tengas que salir"), and
send the event's `say` when it ends; on `timeout`, say you stopped watching. If you can't run
background jobs, schedule yourself a check and call `next` or `leave` at that time.
With a notification target (prefs, or `--notify ntfy:<topic>` / `webhook:<url>`), the alert is
also pushed to the phone; the event's `notified` says whether it got through (`ok`), so don't
send it twice, and tell the user if it failed.

## Reading answers

- `arrivals` by time: `minutes`, `eta` (Barcelona time), `stop`, `operator`, and with a known walk
  `leave_in` (minutes until they must set off; negative = too late) and `make_it`.
- Routes are **timetables** (`scheduled: true`, "según horarios"); just before they leave, check
  the first bus or metro with `next`.
- Empty arrivals = no predictions right now (often at night), not an error.
- Not covered: Rodalies, FGC, tram. Say so.

## Errors

| Exit | `code` | What to do |
|---|---|---|
| 2 | `usage` | Fix the command (the message says what's wrong). |
| 3 | `missing_credentials`, `auth_failed` | TMB keys missing or wrong: see setup step 7. AMB-only stops still work. |
| 4 | `not_found` | Unknown place, stop or name: ask the user, or `tmb --no-input stops <words>`. |
| 5 | `rate_limited`, `api_error` | If `retryable`, wait a little and retry once. |
| 6 | `network_error` | Retry once; then tell the user TMB or AMB can't be reached. |
| 7 | `api_changed` | TMB or AMB changed their data: tell the user; retrying won't help. |

Other commands: `tmb stops <words>`, `tmb bus <code>`, `tmb metro <codes>`, `tmb place
list|remove`, `tmb trip list|remove`, `tmb prefs`, `tmb doctor`. Never read `~/.config/tmb-cli/`
or call the APIs directly: the CLI keeps the keys out of your context and the answers short.
