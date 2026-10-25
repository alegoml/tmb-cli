# AMB open data notes

What we know about AMB's (Àrea Metropolitana de Barcelona) open data, which covers the
metropolitan buses that are **not** TMB's: TUSGSAL, Moventis, Monbus, Soler i Sauret, Avanza,
Aerobús… Checked against real downloads on 25/10/2026 (copies in `captures/amb/`, git-ignored).

Sources: the [AMB open data catalogue](http://www.amb.cat/web/area-metropolitana/dades-obertes/cataleg-opendata)
("Servei GTFS Real time autobusos" and "Informació de companyies, línies i recorreguts"), its
[terms of use](https://www.amb.cat/web/area-metropolitana/dades-obertes/condicions-d-us), and the
[Mobility Database entry](https://mobilitydatabase.org/feeds/gtfs/mdb-892).

## Access and terms

- **No keys, no registration.** Plain HTTPS GETs; httpx's default User-Agent works.
- No JSON API for real time: the only real-time source is a **GTFS-Realtime protobuf** feed. (AMB
  also has a SOAP service for static data behind a request form; we don't need it.)
- Licence: "Autorització segons Llei 37/2007" (publisher "AMB Informació"). Same duties as TMB's:
  **cite the source (AMB)**, **don't alter or distort the data**, **state the date of the last
  update**. Commercial and non-commercial reuse allowed.

## Real time: `https://www.ambmobilitat.cat/transit/trips-updates/trips.bin` ✅

GTFS-Realtime 1.0 `FeedMessage`, refreshed **every 30 s**, ~280 KB, **the whole network** (no
per-stop query). `last-modified` and `etag` headers, no `cache-control`.

```text
header.timestamp                       epoch seconds of the feed
entity[]                               ~650, all trip_update (no vehicle positions, no alerts)
  trip_update.trip.trip_id             "129.20.1.1.12"  → trips.txt
  trip_update.trip.start_time/date     "12:55:00", "20261025"
  trip_update.vehicle.id / label       "9510", "4276"
  trip_update.stop_time_update[]       the trip's remaining stops
    stop_sequence                      9
    stop_id                            "102722", or zero-padded "000852" (see stops)
    arrival.time / departure.time      epoch seconds (absolute, never a `delay`)
    schedule_relationship              0 SCHEDULED; 1 SKIPPED (no time: ignore)
```

On 25/10/2026: 8920 stop time updates, 8768 with `arrival.time`, 0 with `delay`, 152 `SKIPPED`
without times. Predictions reach ~2 h ahead (up to 11 per stop), and 52 were already in the past
(18 by more than 5 min: stops a bus had passed). Every RT `trip_id` was in the static `trips.txt`. Because times are absolute,
**`stop_times.txt` is never needed**.

## Static network: `https://www.ambmobilitat.cat/OpenData/google_transit.zip` ✅

GTFS Schedule, 8.8 MB zipped, 60 MB unzipped (48.5 MB `stop_times.txt`, 9.6 MB `shapes.txt`:
both unused). `feed_info.txt` gives a short validity window (`feed_start_date` 20261025,
`feed_end_date` 20261030): the zip is republished every few days and trip ids change with it.

What we read (≈4 MB, straight from the zip):

- **`agency.txt`**: 11 operators, `agency_id` → `agency_name` ("DIREXIS TUSGSAL", "Moventis",
  "Monbus (Aerobús)", …). No TMB.
- **`routes.txt`**: 140 lines, all `route_type` 3 (bus). `route_id` → `agency_id`,
  `route_short_name` ("B24", "L77", "A1"; unique), `route_long_name`.
- **`trips.txt`**: ~32 400 trips. `trip_id` → `route_id`, `trip_headsign` (destination, never
  empty), `direction_id`.
- **`stops.txt`**: 4970 stops. `stop_id` (6 digits, zero-padded), `stop_code` (= `stop_id` without
  leading zeros, for all 4970), `stop_name`, `stop_desc` (the stop's kind: "Pal", "Marquesina";
  not a description), lat/lon, `wheelchair_boarding`, `out_of_service` (102 are `1`).
- **`areas.txt`** + **`stop_areas.txt`**: town per stop (INE code → name, e.g. 08015 Badalona) for
  3608 of 4970 stops. `areas.txt` has a space after the comma in its header and trailing tabs in
  some names: strip them.

## TMB and AMB share stop codes

`stop_code` is TMB's stop code for TMB stops: AMB's `001103` / `1103` is "Pl Catalunya - Portal
de l'Àngel", same as TMB's 1103. 1419 of TMB's 2708 stops are in AMB's GTFS (zero-padded ids); the
other AMB stops (e.g. Badalona's `1xxxxx`) are AMB-only. So **one code space**: `tmb bus <code>`
can ask both sources and merge.

On 25/10/2026, 436 TMB stops had AMB arrivals in the feed (e.g. 916, 917, 91). Open: TMB's real
time also lists other operators' lines at its stops (`transit_namespace: "amb"`); not seen yet in a
capture. If both list the same bus, we keep AMB's (the operator's own feed) and drop TMB's `amb`
entries. Needs a TMB capture of a shared stop such as 916.
