# TMB API notes

What we know about the endpoints tmb-cli uses. Source: the public swagger files linked from
<https://developer.tmb.cat/api-docs/v1> (`/assets/api-docs/v1/{ibus,imetro,transit,static,planner}/swagger.json`),
read 24/10/2026. Local copies for reference live in `captures/swagger/` (git-ignored).

**Status:** bus and metro real time, `transit/parades`, `transit/estacions`, `transit/linies/{bus,metro}`
and `transit/linies/metro/{1,3}/estacions` **confirmed by captures on 25/10/2026** (marked ✅ below).
The rest is from the swagger only. Where the swagger and a capture disagree, the capture wins
(AGENTS.md rule 5).

## Auth

`app_id` and `app_key` as query parameters on every call. Without them the API answers
**401** `Authentication failed. Authentication parameters missing` (checked 24/10/2026 on
`transit/parades/1103` and `static/datasets/gtfs.zip`). ✅ With a wrong key it also answers **401**,
body `Authentication failed. Invalid credentials` (the swagger says 403). We map 401 and 403 to
`auth_failed`.

Rate limits: not shown on the application's page in the portal either (checked 25/10/2026).

## Real time: bus (`itransit/bus/parades/{codi_parada}`) ✅

Predictions are based on the bus's last known position, "with a maximum precision of one minute".

```text
timestamp                    int   query time, epoch milliseconds
parades[]
  codi_parada                str   "1103"
  nom_parada                 str   "Pl Catalunya - Portal de l'Àngel"
  linies_trajectes[]               one entry per route of a line serving the stop
    id_operador              int   2
    transit_namespace        str   "bus" = TMB line, "amb" = another AMB operator's line
    codi_linia               int   215     internal code (✅ int; the swagger says str)
    nom_linia                str   "V15"   the name people know
    id_sentit                int   1 = outbound (anada), 2 = return (tornada)
    codi_trajecte            str   "2151"
    desti_trajecte           str   "Barceloneta"   destination
    propers_busos[]                one or more upcoming buses, sorted by time within the route
      temps_arribada         int   predicted arrival, epoch milliseconds (whole seconds: ...000)
      id_bus                 int   vehicle id, "if available"
      info_bus                     ✅ not in the swagger
        accessibilitat
          estat_rampa        str   "SENSE_INCIDENCIA" (ramp status)
```

No minutes field: minutes = `temps_arribada - timestamp`, in our own code. `nom_parada` matches
`NOM_PARADA` in `transit/parades`.

✅ **Unknown stop** (`999999`): HTTP 200 with `{"timestamp": …, "parades": []}`, not 404.
Not yet captured: a real stop with no buses (e.g. at night). If that also gives `parades: []`, the
only way to answer `not_found` is to check the code against the cached `transit/parades`.

## Real time: metro (`itransit/metro/estacions?estacions=<code>,<code>`) ✅

Predictions refresh "no less often than every 10–15 seconds". Grouped by **line**, not by station:

```text
timestamp                    int   query time, epoch milliseconds
linies[]
  codi_linia                 int   1
  nom_linia                  str   "L1"
  codi_familia, nom_familia  int, str   1, "Metro"
  color_linia                str   "CE1126"
  estacions[]                      the queried stations on this line, one entry per track
    codi_via                 int   track 1 or 2
    id_sentit                int   1 = outbound, 2 = return
    codi_estacio             int   120
    linies_trajectes[]
      codi_linia, nom_linia, color_linia
      codi_trajecte          str   "0011"
      desti_trajecte         str   "Fondo"
      propers_trens[]
        temps_arribada       int   predicted arrival, epoch milliseconds
        codi_servei          str   "121"   service code shown on the front of the train
```

**No station name** in the response: names have to come from the static network. ✅ Station `120`
on L1 is **Plaça de Sants** (not Catalunya, which is `126` on L1): two entries, one per track
(`codi_via` 1 → Fondo, 2 → Hospital de Bellvitge), two trains each. `codi_linia` is an int at both
levels. `temps_arribada` has whole seconds.

## Static network (`transit/…`)

GeoJSON `FeatureCollection`s ✅: top level `type`, `features`, `totalFeatures`, `numberMatched`,
`numberReturned`, `timeStamp` (ISO 8601 UTC, when the server built the response), `crs`. Each
feature has `id`, `geometry` (Point or MultiLineString, EPSG:4326) and `properties`; every
`properties` has `DATA` (`"2026-10-24Z"`, the dataset's date: our "date of last update" for
attribution). No paging seen: `numberReturned` equals `numberMatched` even for 2708 stops.
Filters (swagger, not tried yet): `…/{code}` for one element, `?filter=FIELD=value`,
`?srsName=EPSG:XXXX`.

- **`transit/parades`** ✅: all bus stops, 2708 features (~2.7 MB), one per `CODI_PARADA` (int, no
  duplicates; real time uses a string). Properties: `ID_PARADA`, `CODI_PARADA`, `NOM_PARADA`,
  `DESC_PARADA`, `ADRECA`, `NOM_VIA`, `NOM_PROPERA_VIA`, `ID_DISTRICTE`/`NOM_DISTRICTE`,
  `ID_POBLACIO` (748 = Barcelona)/`NOM_POBLACIO`, `CODI_INTERC`/`NOM_INTERC`, `NOM_TIPUS_PARADA`,
  `NOM_TIPUS_SIMPLE_PARADA`, `DESC_TIPUS_PARADA`, `TIPIFICACIO_PARADA`, `PUNTS_PARADA`, `DATA`.
  `TIPIFICACIO_PARADA` values seen: only `N` and `NXB` (the swagger's N/P/X doesn't match; meaning
  of `NXB` unknown). The endpoint's feature ids say `PARADES_ACTIVES`: probably active stops only.
  **No list of lines per stop.** Not seen: `DATA_INICI`/`DATA_FI`.
- **`transit/estacions`** ✅: 140 grouped stations (one per interchange). Properties: only
  `ID_ESTACIO`, `CODI_GRUP_ESTACIO`, `NOM_ESTACIO`, `PICTO` (lines, e.g. `"L1L3"`), `DATA`.
  Catalunya: `ID_ESTACIO` 126, `CODI_GRUP_ESTACIO` 6660126, `PICTO` `"L1L3"`: the group takes the
  code of one of its lines, so it doesn't give the other lines' codes.
- **`transit/linies/metro/{line}/estacions`** ✅ (`{line}` = `CODI_LINIA`): stations of one line,
  one feature per station (L1: 30, codes 111–140). Properties: `ID_ESTACIO_LINIA`,
  `CODI_ESTACIO_LINIA`, `ID_GRUP_ESTACIO`, `CODI_GRUP_ESTACIO`, `ID_ESTACIO`, `CODI_ESTACIO`,
  `NOM_ESTACIO`, `ORDRE_ESTACIO`, `ID_LINIA`, `CODI_LINIA`, `NOM_LINIA`, `ORDRE_LINIA`,
  `ID_TIPUS_SERVEI`, `DESC_SERVEI`, `ORIGEN_SERVEI`, `DESTI_SERVEI`, `ID_TIPUS_ACCESSIBILITAT`,
  `NOM_TIPUS_ACCESSIBILITAT`, `ID_TIPUS_ESTAT`, `NOM_TIPUS_ESTAT`, `DATA_INAUGURACIO`, `DATA`,
  `COLOR_LINIA`, `PICTO`, `PICTO_GRUP`. On L1 `CODI_ESTACIO` == `CODI_ESTACIO_LINIA` for all
  stations, and it is the real-time `codi_estacio` (120 = Plaça de Sants in both).
  There is no endpoint for every line's stations at once: one call per metro line.
- **`transit/linies/metro`** ✅: 11 lines; `CODI_LINIA` → `NOM_LINIA`: 1 L1, 2 L2, 3 L3, 4 L4,
  5 L5, 11 L11, 91 L9S, 94 L9N, 101 L10S, 104 L10N, 99 FM (funicular). So station codes are not
  always "line digit + 2 digits"; take them from the per-line endpoint, never compute them.
- **`transit/linies/bus`** ✅: 114 lines (~1.8 MB with geometry). `CODI_LINIA` (int) →
  `NOM_LINIA` (e.g. 215 → `V15`), `DESC_LINIA` (`"Barceloneta / Av. Tibidabo"`), `ORIGEN_LINIA`,
  `DESTI_LINIA`, `NOM_FAMILIA` (Convencionals, Verticals, Horitzontals, Diagonals, Proximitat,
  XPRESBus, Llançadores, Bus a la Demanda, BusTuristic), operator, calendar, colours.
- **`transit/linies/bus/{line}/parades`**: stops of one line, in order (`ParadaRec`).
- **`transit/elements/superficie/{tipus}/{lon}/{lat}/{dist}`**: elements near a point
  (1 stations, 2 stops, 3 accesses, 4 interchanges), `dist` in metres. Enables a future `near`.
- **`static/datasets/gtfs.zip`**: the whole network as GTFS (also needs keys).

## Other

- **`planner/plan`**: trip planner; its responses carry an `alerts` field (`LocalizedAlert`). There
  is **no** service-alerts endpoint.
- **Legacy iBus** (documented at `/api-docs/v1/ibus_legacy`): deprecated by TMB ("will
  disappear"). Don't use it.
- **Rate limits**: not documented anywhere public.

## Gotchas

- `codi_linia` is an **int** in both real-time responses (bus and metro), though the swagger
  types it as a string in places. Accept both.
- ✅ The real-time metro `codi_estacio` is `CODI_ESTACIO` from
  `transit/linies/metro/{line}/estacions`, **not** `CODI_GRUP_ESTACIO` (checked on L1).
  ✅ **Each line has its own code at an interchange**: Catalunya is 126 on L1 and 326 on L3, and
  real time for `126` returns only L1 trains. What ties them together is `CODI_GRUP_ESTACIO`
  (6660126 for both), which is also the key of `transit/estacions`. So "Catalunya, all lines" =
  every `CODI_ESTACIO` with that group = `?estacions=126,326`.
- Static `CODI_PARADA` is a **number**; real-time `codi_parada` is a **string**. Normalise to string.
- Bad credentials give 401, not the swagger's 403.
- An unknown bus stop gives 200 with an empty `parades`, not 404.
