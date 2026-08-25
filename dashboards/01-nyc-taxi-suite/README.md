# dashboards/01-nyc-taxi-suite/ — основной трек: 7 Grafana-дашбордов по TLC trip data

Данные: NYC TLC Trip Record Data (Yellow, Green, FHV, FHVHV), 2019–2026. Источник:
[официальный сайт NYC TLC](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page).
Очистка описана в [`DATA_CLEANING_LOG.md`](DATA_CLEANING_LOG.md) (правила фильтрации по
типу такси + статистика по каждому обработанному файлу).

## Пайплайн

```
сырые parquet (yellow/green/fhv/fhvhv)
      │  clean_taxi_data.py — построчная фильтрация по правилам из DATA_CLEANING_LOG.md
      ▼
TLC_Trip_Data_clean/ (локально, не в git)
      │  _compute_product_metrics.py, _build_covid_aggregator_tables.py,
      │  _build_zone_wait_tables.py, _zone_clustering.py, _build_event_*.py,
      │  taxi_weather_analysis/causal_*.py, forecast_demand.py, extend_weather.py …
      ▼
~15-20 витрин (см. таблицу ниже, по одной на группу панелей)
      │  _load_postgres_grafana.py — DuckDB → Postgres
      ▼
Postgres (nyc_taxi db)
      │  _build_grafana_dashboards.py — генерирует JSON дашбордов
      ▼
grafana_provisioning/dashboard_json/00..06-*.json  →  Grafana
```

Запуск всего событийного трека одной командой: `_run_event_analysis.py`
(fetch → impact → timelapse → hypothesis → map → Grafana). Пересборка карты ожидания:
`_run_wait_heatmaps.py`. Оркестрация датасорса/провижининга — `grafana_provisioning/`
(`dashboards/dashboards.yaml` — файловый провайдер, `datasources/postgres.yaml` — локальный
Postgres `nyc_taxi`).

## Дашборды

### 00-home
**NYC Taxi — Обзор** (`grafana_provisioning/dashboard_json/00-home.json`, uid `nyc-taxi-home`)
Единая посадочная страница: 4 stat-плитки (среднесуточные поездки за год, медиана ожидания,
оплата водителя в час, доля Uber) + 2 графика (North Star: поездки/день по годам, Guardrail:
ожидание). Витрины: `product_metrics_yearly`, `aggregator_monthly`.

### 01-data-metrics
**NYC Taxi — Данные и продуктовые метрики** (`01-data-metrics.json`, uid `nyc-taxi-data-metrics`)
Продуктовая рамка: 1 North Star (среднесуточные поездки), 3 Guardrail (время ожидания подачи,
почасовая оплата водителя, тариф/милю), 2 Proxy (ликвидность рынка = поездок / активная
зона-час) — динамика по годам + сводная таблица. Фильтр: `$year`.
Витрина: `product_metrics_yearly` — считается `_compute_product_metrics.py`.
Отчет-первоисточник: [`reports/nyc_taxi_product_metrics.html`](reports/nyc_taxi_product_metrics.html).

### 02-weather-metro
**NYC Taxi — Погода, метро, congestion pricing** (`02-weather-metro.json`, uid `nyc-taxi-weather-metro`)
Эффект дождя на поездки (по округам и по терцилям доступности метро), эффект платного
въезда в Manhattan CBD (congestion pricing) год-к-году по поездкам и тарифу, ежедневные
поездки/осадки/райдершип метро (MTA) на одном таймлайне. Фильтр: `$borough`.
Витрины: `daily_citywide`, `weather_effect_by_borough`, `rain_effect_by_subway_tier`,
`congestion_pricing_yoy`. Источники: `taxi_weather_analysis/extend_weather.py` (погода,
Open-Meteo), `fetch_mta_ridership.py` (MTA), `causal_congestion_pricing.py`.
Отчеты: [`reports/nyc_taxi_weather_causal.html`](reports/nyc_taxi_weather_causal.html),
[`reports/nyc_subway_access.html`](reports/nyc_subway_access.html).

### 03-demand-price
**NYC Taxi — Спрос, цена, прогноз** (`03-demand-price.json`, uid `nyc-taxi-demand-price`)
Самый плотный дашборд: карта зон по времени ожидания, heatmap ожидания по часу×дню недели
(с фильтром агрегатора), медианное ожидание по агрегаторам, топ-15 зон с худшей подачей,
зоны «принадлежащие» типу такси, точность прогноза спроса (MAPE), цена→спрос (naive vs IV),
кластеры зон по ритму спроса, влияние удаленности от метро, спрос по округам во времени,
ожидание в аэропортах. Фильтры: `$borough`, `$taxi_type`, `$aggregator`, `$cluster`.
Витрины: `zone_wait_time`, `zone_wait_by_aggregator`, `wait_by_hour_dow_aggregator`,
`zone_dominant_type`, `forecast_results`, `price_elasticity`, `zone_clusters`,
`subway_access`, `daily_by_borough`.
Построители: `_build_zone_wait_tables.py`, `_zone_clustering.py`,
`taxi_weather_analysis/forecast_demand.py`, `causal_price_elasticity.py`,
`causal_subway_access.py`. Также интерактивная кастомная карта зон — см. ниже.
Отчеты: [`reports/nyc_demand_forecast.html`](reports/nyc_demand_forecast.html),
[`reports/nyc_price_elasticity.html`](reports/nyc_price_elasticity.html),
[`reports/nyc_subway_access.html`](reports/nyc_subway_access.html),
[`reports/nyc_zone_clusters.html`](reports/nyc_zone_clusters.html).

### 04-covid
**NYC Taxi — Эффект COVID по типам такси** (`04-covid.json`, uid `nyc-taxi-covid`)
Индексированное (янв 2019 = 100, метро — март 2020 = 100) сравнение падения/восстановления
Green/Yellow/FHVHV к 2025 году, абсолютные объемы по месяцам, восстановление по округам и по
агрегаторам (помесячно и погодично), таблица «когда было дно COVID по каждому типу».
Фильтры: `$taxi_type`, `$borough`, `$aggregator`.
Витрины: `monthly_by_type`, `monthly_by_type_indexed`, `monthly_recovery_indexed`,
`yearly_recovery_indexed`, `aggregator_monthly_indexed`, `yearly_aggregator_indexed`.
Построитель: `_build_covid_aggregator_tables.py`, причинность —
`taxi_weather_analysis/causal_green_covid_dowhy.py`.
Отчет: [`reports/nyc_green_taxi_covid_dowhy.html`](reports/nyc_green_taxi_covid_dowhy.html).

### 05-aggregators
**NYC Taxi — Конкуренция агрегаторов и зоны доминирования** (`05-aggregators.json`, uid `nyc-taxi-aggregators`)
Динамика долей рынка агрегаторов, доля Uber/Lyft по округам, кто доминирует в зоне по типу
такси / по агрегатору, таблица зон, где Uber/FHVHV **не** доминирует. Фильтры: `$aggregator`,
`$borough`. Витрины: `aggregator_monthly`, `aggregator_by_borough_2024`,
`zone_dominant_type`, `zone_dominant_aggregator`. Построитель: `_build_covid_aggregator_tables.py`.

### 06-events
**NYC Taxi — Мероприятия и спрос на такси** (`06-events.json`, uid `nyc-taxi-events`)
Причинный анализ (DoWhy): влияет ли удаленность события от метро и ценовой тир площадки на
всплеск спроса (lift) до/после мероприятия. ATE + p-value по двум факторам, таймлапс событий
на карте, разбивка всплеска по типу события (NFL/NBA/MLB/marathon/US Open/концерты), топ-20
событий по величине всплеска. Фильтр: `$event_type`.
Витрины: `event_impact`, `event_hypothesis`, `event_hypothesis_venue`, `event_dowhy_results`
(+ исходники в [`events/`](events/): `nyc_events.csv`, `venues.csv`, `curated_concerts.csv`).
Построители: `_fetch_nyc_events.py` → `_build_event_impact.py` → `_build_event_timelapse.py`
→ `_build_event_hypothesis.py`, причинность — `taxi_weather_analysis/causal_event_taxi_dowhy.py`.
Одна команда для всего: `_run_event_analysis.py`.
Отчет: [`reports/nyc_event_taxi_dowhy.html`](reports/nyc_event_taxi_dowhy.html).

## Кастомная карта зон (используется дашбордом 03)

`grafana_provisioning/nyc_map/index.html` — самописная (не Grafana Geomap) интерактивная
карта 263 таксомоторных зон NYC: режим ожидания (табы по периодам + фильтр агрегатора
Uber/Lyft/Via/Juno/все), режим покрытия (доминирующий тип такси по зоне), слои линий метро
по официальным цветам MTA (`grafana_provisioning/geojson/subway_*.geojson`, нарезаны
`_build_subway_line_groups.py`, т.к. категориальная раскраска по полю в Grafana Geomap
оказалась ненадежной). Собирается в 2 шага: `_build_map_v2_data.py` (вся тяжелая
геопространственная работа/расчет цвета в Python/DuckDB → один JSON) →
`_build_map_v2_artifact.py` (HTML вокруг JSON). Таймлапс почасового спроса добавляет
`_build_zone_timelapse.py`. Более ранние/альтернативные версии карты в корне этой папки:
`nyc_taxi_zones_map.html`, `nyc_taxi_flow_map.html` (маршруты A* по дорожной сети —
`route_flows.py` + `_build_graph_from_pbf.py` + `_prepare_map_svg.py`, отчет
[`reports/nyc_taxi_flows.html`](reports/nyc_taxi_flows.html)).

## Слайды

[`slides/`](slides/) — готовая презентация выводов трека (карта погоды, эффект событий,
карта зон, разбор конкретного случая MSG 2022-12-07, схема A/B-теста), собирается
`slides/_render_slides.py` + вспомогательные `_render_*.py`.

## Как пересобрать витрины

Полного `run_all.sh` в этом разделе нет — витрины собираются точечно нужным скриптом
(см. таблицу дашбордов выше) либо через `_run_event_analysis.py` /
`_run_wait_heatmaps.py` для соответствующих групп. Все `_build_*`/`_run_*`/`_compute_*`
скрипты читают из локально очищенных parquet (`clean_taxi_data.py`) и пишут в Postgres
через `_load_postgres_grafana.py` / DuckDB `postgres` extension. Требуются: DuckDB,
Postgres, Python (duckdb, pandas, geopandas/pyogrio для карты, dowhy/statsmodels/scipy
для причинных ноутбуков).

## Ноутбуки

- [`data_exploration.ipynb`](data_exploration.ipynb) — первичный разведочный анализ.
- [`fhvhv_anomalies.ipynb`](fhvhv_anomalies.ipynb) — разбор аномалий в сырых FHVHV-данных.
- [`taxi_weather_analysis/NYC_taxi_weather_analysis.ipynb`](taxi_weather_analysis/NYC_taxi_weather_analysis.ipynb) — сводный ноутбук причинных тестов (погода/COVID/агрегаторы/цена/метро), из которого получены `causal_*.py`.
