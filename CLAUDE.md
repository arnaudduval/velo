# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Setup environment variables (required before running):**
```bash
source env.sh
```

**Run the development server:**
```bash
python manage.py runserver
```

**Database migrations:**
```bash
python manage.py makemigrations
python manage.py migrate
```

**Django shell:**
```bash
python manage.py shell
```

There are no tests currently (centcols/tests.py is empty).

## Architecture

Django project named `velo` with a single app `centcols`. The app URL prefix is `/centcols/`.

### Key design: Activity processing pipeline

`Activity` (defined in `centcols/activity.py`, not `models.py`) is a Django model that goes through a multi-step processing pipeline tracked by boolean flags:

| Flag | What it means |
|------|--------------|
| `detailsHandled` | Detailed polyline fetched from Strava |
| `colsHandled` | Mountain passes searched and linked |
| `streamsHandled` | Time-series data (power, altitude…) fetched |
| `cp_curveHandled` | Critical power curve computed |
| `tilesHandled` | Visited map tiles identified |

The main entry points into this pipeline are:
- `Activity.update()` — full refresh from Strava API
- `Activity.scan()` → fetches polyline → `do_check_passes()`
- `Activity.get_streams()` → saves streams as pickle+base64 numpy arrays
- `Activity.compute_cp_curve()` → sliding window max-power over streams
- `Activity.do_check_tiles(zoom)` → visited OSM tiles at given zoom

### Other models (centcols/models.py)

- `Gear` — bike/equipment synced from Strava, with `fetch_gear_details()` classmethod
- `GearMaintenanceManager` — maintenance records with periodicity (km, hours, months)
- `Col` — mountain pass (from OSM), linked to activities via M2M `Activity.climbs`
- `Tile` — OSM map tile (zoom/x/y), linked via M2M `Activity.visited_tiles`
- `Stream` — time-series metric (watts, altitude, time…), FK to Activity, data stored as `base64(pickle(numpy_array))`

### Services layer

`services/strava_service.py` wraps the `stravatools.StravaApp` third-party library. All Strava API calls go through `StravaService`. Rate limit handling uses `tenacity` retries (wait 900s for activity fetches, 180s for streams/lists).

### Bulk operations

`centcols/actions.py` — `retrieve_and_save_activities(before, after, scan=False)` pages through Strava API and upserts activities. The `scan=False` default means detailed processing is deferred.

`centcols/passes.py` — `retrieve_and_save_passes(min_lat, min_lon, max_lat, max_lon)` imports mountain passes from OSM via `osmtools.get_pass_from_osm()`.

The maintenance views at `/centcols/maintenance/<1-9>/` are admin batch operations (re-scan, recompute CP curves, rebuild tiles, etc.).

### JSON API endpoints

Views return GeoJSON/Chart.js-compatible JSON for the frontend maps and charts:
- `/centcols/track_json/<id>/` — detailed polyline
- `/centcols/visited_tiles_json/<id>/` — visited tiles as polygons
- `/centcols/cp_curve_json/<id>/` — CP curve as `{x: seconds, y: watts}` points
- `/centcols/time_streams_json/<id>/` — power and altitude streams

### Environment variables

Three Strava credentials are required (set via `env.sh`):
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_ACCESS_TOKEN`

### Storage format for binary data

Streams use `base64(pickle(numpy_array))` stored in `BinaryField`.  
CP curves use `numpy.save()` format stored in `BinaryField` (deserialize with `np.load(BytesIO(...))`).  
These two formats are **not interchangeable** — streams use pickle, CP curves use npy.
