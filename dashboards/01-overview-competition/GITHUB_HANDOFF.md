# taxi_data_2025_2026 — handoff doc

Purpose of this file: give another AI (or a new session) everything needed to (a) understand
the data marts behind the two Grafana dashboards in scope, and (b) safely assemble/push this
repo to GitHub without committing huge raw-data files or secrets.

Repo: NYC TLC "High Volume For-Hire Vehicle" (Uber/Lyft) trip data, Jan 2025 – Apr 2026
(~327M trips). Local stack: DuckDB (ETL) → Postgres (storage) → Grafana (dashboards).

Remote already configured: `git@github.com:yemtsovaanna-alt/taxi_data_2025_2026.git`
Current state: branch `main`, 1 commit ("Initial commit"), tracking that remote.

---

## 1. Pipeline architecture

```
raw parquet (16 files, ~14 GB, NOT in git)
        │  read_parquet(..., union_by_name=true) + DISTINCT
        ▼
   trips              -- deduped raw rows + `provider` column (mapped from hvfhs_license_num)
        │  filter: non-null keys, trip_time>0, fare/miles>=0, dropoff>=pickup
        ▼
   clean_trips         -- sanity-filtered base used by the "fact"-grain marts
        │
        ▼
  ~20 pre-aggregated rollup tables ("витрины"/marts, see §2)
        │  DuckDB postgres extension: ATTACH ... AS pg; CREATE TABLE pg.public.X AS SELECT * FROM X
        ▼
   Postgres (small tables, dashboard-fast)
        │  Grafana panels query Postgres directly via rawSql
        ▼
   Grafana dashboards
```

Orchestration: `etl/run_etl.sh` finds all parquet files (`parquet_extracted/archive/*.parquet`
+ the loose `fhvhv_tripdata_2026-04.parquet`), substitutes them into
`etl/load_taxi_data.sql` (DuckDB SQL script), and runs it. Re-run whenever a new month's
parquet lands. The whole raw-scan step is local-only — only the small mart tables get pushed
to Postgres, which is what makes a lightweight cloud/server deploy possible (see README.md).

Why marts exist at all: 327M raw rows is too slow for interactive Grafana panels. Every mart
below is a `GROUP BY` rollup (daily/monthly/hourly/zone grain) so panels aggregate over
thousands of rows instead of hundreds of millions.

---

## 2. Marts — structure and assembly logic

All defined in `etl/load_taxi_data.sql`, in this order. "Grain" = one row per what.

| Table | Grain | Built from | What it's for |
|---|---|---|---|
| `zones` | 1 row / LocationID | `taxi_zone_lookup.csv` | borough/zone name lookup |
| `trips` | 1 row / trip (deduped) | raw parquet, `DISTINCT`, +`provider` derived from `hvfhs_license_num` | base table, not exposed to Grafana |
| `clean_trips` | 1 row / valid trip | `trips` minus garbage rows (null keys, non-positive time, negative fare/miles, dropoff<pickup) | base for fact-grain marts (WAV, shared, segment) |
| `trips_daily` | day × provider | `trips` | core rollup: counts, avg fare/driver pay/miles/time, tips, CBD fee %, shared/WAV %. Feeds most top-line KPIs on both dashboards |
| `trips_cbd_daily` | day × provider | `trips` where `cbd_congestion_fee>0` | same shape as above, restricted to Manhattan congestion-zone trips |
| `trips_hourly_dow` | hour × day-of-week | `trips`, aggregated over the whole dataset | source for the pivoted heatmap below |
| `trips_heatmap` | day-of-week (hour columns pivoted) | `PIVOT trips_hourly_dow` | ready-to-render heatmap table, but **not** time-range-filterable |
| `trips_hourly_dow_daily` | calendar day × hour | `trips` | same signal as above but keyed by actual date, so Grafana's time-range picker works (day-of-week computed at query time) |
| `trips_by_zone` | month × pickup zone | `trips` JOIN `zones` on `PULocationID` | zone-level economics, monthly grain |
| `trips_by_zone_daily` | day × pickup zone | same as above, daily grain | lets `$__timeFilter` work for arbitrary (non-month-aligned) ranges |
| `trips_by_zone_do` | month × **dropoff** zone | `trips` JOIN `zones` on `DOLocationID` | destination-side economics (where drivers get stranded) |
| `zone_centroids` | 1 row / zone | NYC Open Data GeoJSON via DuckDB `spatial` extension | lat/lon for Geomap panels |
| `weather_daily` | 1 row / day | Open-Meteo historical API (Central Park), fetched once, cached in `etl/nyc_weather.json` | correlate demand/fare with rain/temperature |
| `benchmarks` | 1 row / entity | **hand-entered**, not derived from trip data | NYC take-rate (22.9%) vs. Uber (25.4%) / Lyft (33.5%) reported figures — explicitly flagged non-apples-to-apples (global company revenue/bookings vs. NYC-only fare-driver_pay split) |
| `trips_monthly_provider` | month × provider | `trips` | monthly trip count, avg fare/driver pay, take-rate % |
| `wav_hourly_zone` | hour × provider × pickup zone | `clean_trips`, split into inclusive / ordinary_wav / ordinary_regular | wheelchair-accessible-vehicle segmentation |
| `wav_wait_fact` | 1 row / trip (WAV-relevant) | `clean_trips` where `request_datetime` present | row-level wait time (can't pre-aggregate percentiles) |
| `mart_shared_daily` | day × provider (Uber/Lyft only) | `clean_trips`, cut by `shared_request_flag`×`shared_match_flag` | shared-ride economics: match rate, fare/duration/pay solo vs. shared |
| `mart_shared_zone` | day × provider × zone | `clean_trips` JOIN `zones` | same shared-ride signal broken out by pickup zone |
| `mart_segment_daily` | day × provider × segment (wav/shared/regular) | `clean_trips` | revenue split by business segment: gross bookings, driver pay, platform take |
| `wait_hourly_provider` | hour × day-of-week × provider × group (citywide/JFK/LGA) | `clean_trips` where `request_datetime`&`on_scene_datetime` present | pre-aggregated wait-time stats (avg/median/p90/variance) — feeds the "who waits longer" panels |
| `significance_tests` | 1 row / hypothesis | **hand-computed offline** (scipy, full 327M rows) in `hypothesis_center_vs_edge_pricing.ipynb` §15–16, pasted in as literal values | Welch t-test / DiD results on wait-time and rush-hour surge gaps between Lyft and Uber |
| `surge_hourly_provider` | hour × day-of-week × provider | `clean_trips`, 2–5 mile trips only (Uber/Lyft only) | fare-per-mile by hour, distance-band-controlled, for surge comparison |
| **`mile_bin_pricing`** | provider × distance bin | **⚠️ referenced by the dashboard, not created anywhere in `load_taxi_data.sql`** | see gap note below |

At the end, every mart is pushed into Postgres via
`ATTACH '...' AS pg (TYPE POSTGRES); CREATE OR REPLACE TABLE pg.public.X AS SELECT * FROM X;`
for each table, then `DETACH pg`.

### ⚠️ Known gap: `mile_bin_pricing`
`grafana/dashboards/financial-overview.json` has two panels ("Take Rate by Trip Distance",
"Fare per Mile by Trip Distance") that query a table `mile_bin_pricing` (provider, mile_bin,
mile_bin_order, take_rate_pct, fare_per_mile). This table does **not** exist in
`etl/load_taxi_data.sql`, so `run_etl.sh` never creates or refreshes it in Postgres. The only
place this logic exists is as ad-hoc pandas code in `hypothesis_center_vs_edge_pricing.ipynb`
(binning by `trip_miles`, computing `fare_per_mile`/`take_rate` per provider × bin), which was
apparently pasted into Postgres by hand at some point and never persisted back into the ETL
script. **On a fresh deploy (fresh Postgres, running only `run_etl.sh`), those two panels will
error** — table doesn't exist. Fix: either add a `CREATE TABLE mile_bin_pricing AS ...` mart to
`load_taxi_data.sql` (mirroring the notebook's binning logic) and push it like the others, or
document it as a manual one-off load.

---

## 3. Dashboard → mart mapping (the two dashboards in scope)

### A. "NYC FHVHV Taxi Overview" — `grafana/dashboards/taxi-overview.json` (uid `taxi-overview`)
General trip-volume/economics/geography overview (closest match to "HVFHV Trip Records
Overview").

| Panel | Marts used |
|---|---|
| Trip Count / Provider Commission / Driver Pay / Passenger Fare (YoY stats) | `trips_daily` |
| Daily Trip Volume by Provider | `trips_daily` |
| Passenger Fare vs Driver Pay vs Commission | `trips_daily` |
| Top 20 Pickup Zones | `trips_by_zone_daily` |
| Trips by Hour × Day-of-Week | `trips_hourly_dow_daily` |
| Take Rate % by Month | `trips_monthly_provider` |
| Trip Share by Provider | `trips_daily` |
| Gross Bookings YTD YoY | `trips_monthly_provider` |
| Take Rate Benchmark vs public companies | `benchmarks` |
| Revenue & Driver Pay per Mile | `trips_daily` |
| Driver Effective Hourly Rate | `trips_daily` |
| Airports vs Rest of City economics | `trips_by_zone` |
| Revenue Concentration — Top 10 Zones / Top 10 Zones Share | `trips_by_zone` |
| Daily Trips vs Precipitation / Corr: Rain vs Trips | `trips_daily` JOIN `weather_daily` |
| Avg Fare vs Max Temperature / Corr: Temp vs Fare | `trips_daily` JOIN `weather_daily` |
| Pickup/Dropoff Zones — Driver $/Hour (Geomap) | `trips_by_zone` / `trips_by_zone_do` JOIN `zone_centroids` |

**Conclusions this dashboard encodes:** NYC's blended platform take rate (~22.9%) sits below
both Uber's (25.4%) and Lyft's (33.5%) globally-reported take rates — but the `benchmarks`
comment explicitly warns this is not apples-to-apples (different scope/methodology). Zone/geo
panels surface driver $/hour by pickup and dropoff location as an equity/productivity view.

### B. "Uber vs Lyft: Competition Overview" — `grafana/dashboards/financial-overview.json` (uid `financial-overview`)
Head-to-head Uber vs. Lyft comparison. Has a `$provider` template variable
(`Uber` / `Lyft` / `Uber+Lyft`) used across most panels' `WHERE` clauses.

| Row | Panel | Marts used |
|---|---|---|
| Fares/Commission/Trips | Total Gross Bookings, Total Commission, Commission Share of Fare, Driver Pay (YoY), Trip Count, Provider Share of Trips (stats) | `trips_daily` |
| | What the Rider Actually Pays — Fee Breakdown | `trips_daily` (fare, tolls, bcf, sales_tax, congestion fees) |
| | Daily Gross Bookings by Provider / Gross Bookings Share / Provider Share of Trips Over Time | `trips_daily` |
| Ride Type Breakdown | Platform Take by Ride Type (+ over time), Trip Count by Segment × Provider, Ride Type Summary/Breakdown tables | `mart_segment_daily` |
| Wait Time | Wait time gap (Lyft−Uber), Average wait time by hour of day, Wait time citywide vs airports | `wait_hourly_provider` |
| Distance-Based Pricing | Take Rate by Trip Distance, Fare per Mile by Trip Distance | **`mile_bin_pricing` — missing from ETL, see gap above** |

**Conclusions this dashboard encodes** (from `significance_tests`, computed offline in the
hypothesis notebook and hand-pasted into the mart):
- Citywide, Lyft's average wait time is ~13.4s longer than Uber's (Welch t-test, effectively
  p≈0 at this sample size, but Cohen's d=0.07 — a small effect).
- At JFK and LGA the direction **reverses**: Uber waits ~60s / ~54s longer than Lyft.
- The citywide Lyft-vs-Uber wait gap concentrates in rush hours (diff-in-diff: Lyft +10.9s in
  rush vs. its own off-peak; Uber −2.2s).
- Rush-hour surge (fare/mile, 2–5mi trips): both providers surge, but Lyft surges more
  relatively than Uber, on both weekdays and weekends (diff-in-diff tests).

---

## 4. What should and shouldn't go into the GitHub repo

Large/duplicate data files must **not** be committed (GitHub hard-caps individual files at
100MB, and a multi-GB repo is unusable to clone). The project's own README already flags some
of these as redundant copies.

| Path | Size | Git status now | Recommendation |
|---|---|---|---|
| `archive-2026-08-08_16-14-34.zip` | 6.9 GB | untracked | **exclude** — README calls it a redundant copy of the same data, unused by ETL |
| `parquet_extracted/archive/*.parquet` (15 files) | 7.0 GB | untracked | **exclude** — raw ETL input, regenerate/re-download instead of committing |
| `fhvhv_tripdata_2026-04.parquet` | 486 MB | untracked | **exclude** — same reason, current month's raw data |
| `.tmp/` | 54 GB(!) | untracked, **not yet in .gitignore** | **exclude**, add to `.gitignore` |
| `.venv/` | — | untracked, **not yet in .gitignore** | **exclude**, add to `.gitignore` (only `.env`/`.env.*` are currently ignored, not the venv itself) |
| `.idea/` | 2.3 MB | untracked, not in .gitignore | **exclude**, add to `.gitignore` |
| `grafana.zip` | 256 KB | untracked | likely a stale export duplicate of `grafana/` — verify contents before deciding, probably exclude |
| `.env`, `.env.server` | — | correctly ignored via `.env`/`.env.*` pattern | **never commit** — contain Postgres/Grafana credentials |
| `parquet_extracted/taxi_zone_lookup.csv` | 256 KB | staged | **include** — small, required by ETL (zone name lookup) |
| `etl/` (SQL, shell, weather JSON, zones GeoJSON) | 5.3 MB | untracked | **include** — this is the ETL logic itself |
| `scripts/sync_dashboards.sh` | — | untracked | **include** — pulls live dashboard JSON back into the repo |
| `grafana/` (dashboards JSON + provisioning) | 4.8 MB | untracked | **include** — dashboard definitions are the actual deliverable |
| `docker-compose.yml`, `docker-compose.server.yml` | — | untracked | **include** |
| `README.md` | — | modified | **include** |
| `eda.ipynb`, `hypothesis_center_vs_edge_pricing.ipynb` | 2.0 MB / 1.3 MB | staged / untracked | **include** — analysis notebooks, reasonably sized |
| `.gitignore` | — | untracked (needs the additions above) | **include** |

### Suggested `.gitignore` additions
```
.venv/
.idea/
.tmp/
archive-2026-08-08_16-14-34.zip
fhvhv_tripdata_2026-04.parquet
parquet_extracted/archive/
```
(and `grafana.zip` too, once confirmed redundant against `grafana/`)

---

## 5. Notes for whoever pushes this

- Don't `git add -A` blindly — the untracked list above includes a 54GB scratch dir and ~14GB
  of raw parquet that must never enter git history (even one bad commit bloats the repo
  permanently; a later `.gitignore` add won't undo it).
- `.env` / `.env.server` contain live credentials — confirm they're excluded before any push,
  don't just trust `.gitignore` blindly (verify with `git status` / `git check-ignore`).
- The repo already has a configured `origin` remote (see top of this file) — no need to create
  a new GitHub repo, just get the working tree clean and push to `main`.
