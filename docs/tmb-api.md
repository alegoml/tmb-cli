# TMB API notes

What we know about the endpoints tmb-cli uses. Source: the public swagger files linked from
<https://developer.tmb.cat/api-docs/v1> (`/assets/api-docs/v1/{ibus,imetro,transit,static,planner}/swagger.json`),
read 24/10/2026. Local copies for reference live in `captures/swagger/` (git-ignored).

**Status: documented, not yet confirmed by a real capture.** The swagger has known
inconsistencies (see "Gotchas"), so the `Wire*` models must be checked against `captures/` before
we rely on them (AGENTS.md rule 5).

## Auth

`app_id` and `app_key` as query parameters on every call. Without them the API answers
**401** `Authentication failed. Authentication parameters missing` (checked 24/10/2026 on
`transit/parades/1103` and `static/datasets/gtfs.zip`). The swagger documents **403**
`Authentication failed` for bad credentials. We map both to `auth_failed`.

## Real time: bus (`itransit/bus/parades/{codi_parada}`)

Predictions are based on the bus's last known position, "with a maximum precision of one minute".

```text
timestamp                    int   query time, epoch milliseconds
parades[]
  codi_parada                str   "108"
  nom_parada                 str   "Pl Espanya - FGC"
  linies_trajectes[]               one entry per route of a line serving the stop
    id_operador              int   2
    transit_namespace        str   "bus" = TMB line, "amb" = another AMB operator's line
    codi_linia               str   "212"   internal code
    nom_linia                str   "H12"   the name people know
    id_sentit                int   1 = outbound (anada), 2 = return (tornada)
    codi_trajecte            str   "2121"
    desti_trajecte           str   "Gornal"   destination
    propers_busos[]
      temps_arribada         int   predicted arrival, epoch milliseconds
      id_bus                 int   vehicle id, "if available"
```

No minutes field: minutes = `temps_arribada - timestamp`, in our own code.

Not documented: what an unknown stop returns (404? empty `parades`?) and what a stop with no
buses returns. Both need a capture.

## Real time: metro (`itransit/metro/estacions?estacions=<code>,<code>`)

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
        codi_servei          str   "120"   service code shown on the front of the train
```

**No station name** in the response: names have to come from the static network.

## Static network (`transit/…`)

GeoJSON `FeatureCollection`s (`features[].properties`, `geometry` in EPSG:4326, `totalFeatures`).
Filters: `…/{code}` for one element, `?filter=FIELD=value` on properties, `?srsName=EPSG:XXXX`.

- **`transit/parades`**: all bus stops. Properties include `CODI_PARADA` (number), `NOM_PARADA`,
  `DESC_PARADA`, `ADRECA`, `NOM_VIA`, `NOM_PROPERA_VIA`, `NOM_DISTRICTE`, `NOM_POBLACIO`,
  `ID_POBLACIO` (748 = Barcelona), `CODI_INTERC`/`NOM_INTERC`, `TIPIFICACIO_PARADA`
  (N normal, P provisional, X not in use), `DATA_INICI`/`DATA_FI`. **No list of lines per stop.**
- **`transit/estacions`**: metro stations grouped (one per interchange): `CODI_GRUP_ESTACIO`
  (e.g. 6660315), `ID_ESTACIO`, `NOM_ESTACIO`, `PICTO` (e.g. "L3"), `ID_TIPUS_ESTAT`.
- **`transit/linies/metro/{line}/estacions`**: stations of one line: `CODI_ESTACIO` ("alternative
  code", e.g. 220), `CODI_ESTACIO_LINIA`, `CODI_GRUP_ESTACIO`, `NOM_ESTACIO`, `NOM_LINIA`,
  `DESTI_SERVEI`, `ID_TIPUS_ACCESSIBILITAT`, `ID_TIPUS_ESTAT`, …
- **`transit/linies/bus`**, **`transit/linies/metro`**: lines (`CODI_LINIA`, `NOM_LINIA`,
  `DESC_LINIA`, colours, calendar…).
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

- Metro `LiniaTrajecte.codi_linia` is typed `string` in the schema but the example shows `1`
  (an int). Accept both.
- The real-time metro `codi_estacio` (e.g. 120) most likely matches `CODI_ESTACIO` from
  `transit/linies/metro/{line}/estacions` (L1 → 1xx, L2 → 2xx…), **not** `CODI_GRUP_ESTACIO`.
  To confirm with captures.
- Static `CODI_PARADA` is a **number**; real-time `codi_parada` is a **string**. Normalise to string.
