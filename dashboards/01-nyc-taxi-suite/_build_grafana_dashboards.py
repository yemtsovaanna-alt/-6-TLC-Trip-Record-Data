"""Grafana dashboard JSON generator, v6.

v5: wait-time heatmaps + period tabs on the SVG map.
v6: home KPI board; wait in minutes; Uber/Lyft brand colors; dash-3 filters
    ($taxi_type coverage, $aggregator wait); map coverage + aggregator UI.
"""
import json
import time

DS = {"type": "postgres", "uid": "nyc_taxi_pg"}
MIN_WAIT_N = 50  # keep in sync with _build_map_v2_data.py / _build_zone_wait_tables.py
METRIC_COLOR_LO = "#9BACD8"
METRIC_COLOR_HI = "#F98513"

TAXI_TYPE_COLORS = {"yellow": "#F3C518", "green": "#2E8B57", "fhv": "#4A4A4A", "fhvhv": "#6B4FA0"}
METRO_COLOR = "#0039A6"
BOROUGH_COLORS = {
    "Bronx": "#E15759", "Brooklyn": "#F28E2B", "Manhattan": "#4E79A7",
    "Queens": "#59A14F", "Staten Island": "#B07AA1", "Метро NYC": METRO_COLOR,
}
# Brand palette (team): Uber Green + Lyft Pink; Via/Juno kept for historical series
AGGREGATOR_COLORS = {"Uber": "#06C167", "Lyft": "#FF00BF", "Via": "#00B2A9", "Juno": "#6A0DAD"}
CLUSTER_COLORS = {
    "Утренний коммьютер": METRIC_COLOR_HI, "Вечернее ядро": METRIC_COLOR_LO,
    "Досуговый вечер": "#808183", "Аэропорт (outlier)": "#4A4A4A",
}


def sql_target(sql, ref_id="A", fmt="table"):
    return {"datasource": DS, "rawSql": sql, "rawQuery": True, "format": fmt, "refId": ref_id, "editorMode": "code"}


def panel(id_, title, gridPos, type_, targets, extra=None):
    p = {
        "id": id_, "title": title, "gridPos": gridPos, "type": type_,
        "datasource": DS, "targets": targets,
        "fieldConfig": {"defaults": {"custom": {}}, "overrides": []},
        "options": {},
    }
    if extra:
        p.update(extra)
    return p


def text_panel(id_, gridPos, markdown):
    return panel(id_, "", gridPos, "text", [], extra={
        "options": {"mode": "markdown", "content": markdown}, "transparent": False,
    })


def iframe_panel(id_, gridPos, src, title=""):
    """Custom JS map embed — replaces the old 16-layer geomap. Requires
    [panels] disable_sanitize_html = true in grafana.ini/custom.ini, otherwise
    Grafana's TextPanel strips the <iframe> tag and the panel renders blank."""
    return panel(id_, title, gridPos, "text", [], extra={
        "options": {"mode": "html",
                    "content": f'<iframe src="{src}?v={int(time.time())}" style="width:100%;height:100%;border:0;" title="{title}"></iframe>'},
        "transparent": False,
    })


def value_mappings(color_map):
    return [{"type": "value", "options": {
        k: {"text": k, "color": v, "index": i} for i, (k, v) in enumerate(color_map.items())
    }}]


def color_override_by_name(field_name, color):
    return {"matcher": {"id": "byName", "options": field_name},
            "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}


def _metric_threshold_steps(n: int = 6):
    """Blue→orange steps for Grafana threshold coloring (percentage mode)."""
    lo = tuple(int(METRIC_COLOR_LO[i:i + 2], 16) for i in (1, 3, 5))
    hi = tuple(int(METRIC_COLOR_HI[i:i + 2], 16) for i in (1, 3, 5))
    steps = [{"color": METRIC_COLOR_LO, "value": None}]
    for i in range(1, n):
        t = i / (n - 1)
        rgb = tuple(round(lo[k] + (hi[k] - lo[k]) * t) for k in range(3))
        steps.append({"color": "#%02x%02x%02x" % rgb, "value": round(100 * t)})
    return steps


def metric_color_defaults(unit=None, color=None):
    """Fixed non-aggregator color (default orange #F98513) — no Grafana green."""
    defaults = {
        "color": {"mode": "fixed", "fixedColor": color or METRIC_COLOR_HI},
        "custom": {},
    }
    if unit:
        defaults["unit"] = unit
    return defaults


def timeseries_panel(id_, title, gridPos, sql, unit=None, fmt="time_series", series_colors=None,
                     metric_palette=False, metric_color=None):
    """series_colors: {value_col: {category_value: color}} — the postgres SQL
    datasource names a derived multi-series field '<value_col> <category>',
    e.g. 'trips yellow' or 'share_pct Uber'."""
    extra_field = (
        metric_color_defaults(unit, color=metric_color or METRIC_COLOR_HI) if metric_palette
        else {"custom": {}, **({"unit": unit} if unit else {})}
    )
    overrides = []
    if series_colors:
        for value_col, cmap in series_colors.items():
            for cat, color in cmap.items():
                overrides.append(color_override_by_name(f"{value_col} {cat}", color))
    return panel(id_, title, gridPos, "timeseries", [sql_target(sql, fmt=fmt)],
                 extra={"fieldConfig": {"defaults": extra_field, "overrides": overrides}})


def piechart_panel(id_, title, gridPos, sql, color_map=None):
    field_defaults = {"custom": {}}
    if color_map:
        field_defaults["mappings"] = value_mappings(color_map)
    return panel(id_, title, gridPos, "piechart", [sql_target(sql)], extra={
        "fieldConfig": {"defaults": field_defaults, "overrides": []},
        "options": {
            "reduceOptions": {"values": True, "calcs": [], "fields": ""},
            "pieType": "pie",
            "displayLabels": ["name", "percent"],
            "legend": {"displayMode": "list", "placement": "right", "values": ["value", "percent"]},
        },
    })


def barchart_panel(id_, title, gridPos, sql, series_colors=None, horizontal=True,
                   metric_palette=False, unit=None, metric_color=None):
    """horizontal=True (default): category labels (borough names etc.) read
    left-to-right instead of being crammed/rotated under vertical columns —
    reads noticeably cleaner with few categories, which is every barchart in
    this project's dashboards.

    metric_palette=True → fixed #F98513 (or metric_color) instead of Grafana green.
    """
    overrides = []
    if series_colors:
        for field_name, color in series_colors.items():
            overrides.append(color_override_by_name(field_name, color))
    defaults = (
        metric_color_defaults(unit, color=metric_color or METRIC_COLOR_HI)
        if metric_palette else {"custom": {}}
    )
    if unit and not metric_palette:
        defaults["unit"] = unit
    return panel(id_, title, gridPos, "barchart", [sql_target(sql)], extra={
        "fieldConfig": {"defaults": defaults, "overrides": overrides},
        "options": {
            "orientation": "horizontal" if horizontal else "vertical",
            "showValue": "always", "xTickLabelRotation": 0,
        },
    })


def heatmap_panel(id_, title, gridPos, sql, unit="m", reverse=True, scheme="RdYlGn",
                  wide=False, time_from=None, time_to=None, metric_palette=False):
    """Postgres → Grafana heatmap. wide=True: hour×DOW columns as separate series."""
    fmt = "time_series" if wide else "table"
    if metric_palette:
        # Heatmap only supports named schemes — RdYlBu reversed ≈ cool→warm
        # (exact #9BACD8→#F98513 is applied on map + bar charts via thresholds)
        color_cfg = {
            "mode": "scheme",
            "scheme": "RdYlBu",
            "reverse": True,
            "scale": "linear",
            "steps": 64,
            "fill": METRIC_COLOR_HI,
        }
        field_defaults = {"unit": unit, "custom": {"scaleDistribution": {"type": "linear"}}}
    else:
        color_cfg = {
            "exponent": 0.5, "fill": "dark-orange", "mode": "scheme",
            "reverse": reverse, "scale": "exponential", "scheme": scheme,
            "steps": 64,
        }
        field_defaults = {"unit": unit, "custom": {"scaleDistribution": {"type": "linear"}}}
    p = panel(id_, title, gridPos, "heatmap", [sql_target(sql, fmt=fmt)], extra={
        "fieldConfig": {"defaults": field_defaults, "overrides": []},
        "options": {
            "calculate": False,
            "cellGap": 2,
            "color": color_cfg,
            "exemplars": {"color": "rgba(255,0,255,0.7)"},
            "filterValues": {"le": 1e-9},
            "legend": {"show": True},
            "rowsFrame": {"layout": "auto"},
            "tooltip": {"mode": "single", "yHistogram": False},
            "yAxis": {"axisPlacement": "left", "reverse": False, "unit": unit},
        },
    })
    if time_from:
        p["timeFrom"] = time_from
    if time_to:
        p["timeTo"] = time_to
    return p


def stat_panel(id_, title, gridPos, sql, unit=None, color=None):
    defaults = {"custom": {}}
    if unit:
        defaults["unit"] = unit
    if color:
        defaults["color"] = {"mode": "fixed", "fixedColor": color}
    return panel(id_, title, gridPos, "stat", [sql_target(sql)], extra={
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "value", "graphMode": "none", "textMode": "auto",
        },
    })


def stat_trend_panel(id_, title, gridPos, sql, unit=None, color=None):
    """Stat KPI with YoY arrow (showPercentChange on annual time series)."""
    defaults = metric_color_defaults(unit, color=color or METRIC_COLOR_HI)
    return panel(id_, title, gridPos, "stat", [sql_target(sql, fmt="time_series")], extra={
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "value", "graphMode": "none", "textMode": "auto",
            "wideLayout": True, "showPercentChange": True,
            "percentChangeColorMode": "standard",
        },
    })


def significance_table(id_, title, gridPos, sql, pvalue_col="p_value"):
    return panel(id_, title, gridPos, "table", [sql_target(sql)], extra={
        "fieldConfig": {
            "defaults": {"custom": {"cellOptions": {"type": "auto"}}},
            "overrides": [{
                "matcher": {"id": "byName", "options": pvalue_col},
                "properties": [
                    {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
                    {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                        {"color": METRIC_COLOR_HI, "value": None},
                        {"color": "semi-dark-red", "value": 0.05},
                    ]}},
                    {"id": "custom.width", "value": 110},
                ],
            }],
        },
    })


def annotations_block():
    return {"list": [{
        "datasource": DS, "enable": False, "iconColor": "red", "name": "Ключевые события",
        "target": {"rawSql": 'SELECT event_time AS "time", title AS text, tags FROM dashboard_events ORDER BY 1',
                   "format": "table"},
        "mappings": {},
    }]}


def query_variable(name, label, sql, multi=True, include_all=True, all_value=None):
    """Grafana multi-value vars: use ${name:sqlstring} in SQL IN (...) clauses.
    Without :sqlstring, selecting All expands to the bare word All and breaks SQL."""
    v = {
        "name": name, "label": label, "type": "query", "datasource": DS,
        "query": sql, "definition": sql,
        "refresh": 1, "multi": multi, "includeAll": include_all,
        "current": {}, "sort": 1,
    }
    if all_value is not None:
        v["allValue"] = all_value
    return v


# Postgres has no median(); use ordered-set aggregate.
def _pg_median(col: str) -> str:
    return f"(percentile_cont(0.5) WITHIN GROUP (ORDER BY {col}))"


VAR_BOROUGH = query_variable("borough", "Округ", "SELECT DISTINCT borough FROM daily_by_borough ORDER BY borough")
VAR_TAXI_TYPE = query_variable("taxi_type", "Тип такси / покрытие",
                               "SELECT DISTINCT dominant_type AS taxi_type FROM zone_dominant_type ORDER BY 1")
VAR_TAXI_TYPE_COVID = query_variable("taxi_type", "Тип такси",
                                     "SELECT DISTINCT taxi_type FROM monthly_by_type ORDER BY taxi_type")
VAR_AGGREGATOR = query_variable("aggregator", "Агрегатор",
                                "SELECT DISTINCT aggregator FROM wait_by_hour_dow_aggregator ORDER BY aggregator")
VAR_AGGREGATOR_SHARE = query_variable("aggregator", "Агрегатор",
                                      "SELECT DISTINCT aggregator FROM aggregator_monthly ORDER BY aggregator")
VAR_YEAR = query_variable("year", "Год", "SELECT DISTINCT year FROM product_metrics_yearly ORDER BY year")
VAR_CLUSTER = query_variable("cluster", "Кластер зоны",
                             "SELECT DISTINCT cluster_label FROM zone_clusters ORDER BY cluster_label")

DASH_LINKS = [
    {"type": "dashboards", "asDropdown": True, "title": "NYC Taxi", "keepTime": True,
     "includeVars": True, "targetBlank": False},
]


def dashboard(title, uid, panels, tags, variables=None):
    return {
        "id": None, "uid": uid, "title": title, "tags": tags,
        "timezone": "browser", "schemaVersion": 40, "version": 6,
        "refresh": "", "time": {"from": "now-7y", "to": "now"},
        "panels": panels, "links": DASH_LINKS, "editable": True,
        "annotations": annotations_block(),
        "templating": {"list": variables or []},
    }


# ===========================================================================
# Dashboard 0: Home / KPI hub
# ===========================================================================
d0_intro = f"""## NYC Taxi — обзор

Метрики без агрегатора: `{METRIC_COLOR_LO}` → `{METRIC_COLOR_HI}` · Uber `#06C167` · Lyft `#FF00BF` · wait: FHVHV 2024.

| Доска | О чем |
|-------|--------|
| [Метрики](/d/nyc-taxi-data-metrics) | North Star, wait, оплата водителя |
| [Погода / метро](/d/nyc-taxi-weather-metro) | Дождь, congestion pricing |
| [Спрос / wait-карта](/d/nyc-taxi-demand-price) | Карта зон, теплокарты ожидания, фильтры |
| [COVID](/d/nyc-taxi-covid) | Восстановление + почему green не ожил |
| [Агрегаторы](/d/nyc-taxi-aggregators) | Uber vs Lyft, зоны доминирования |
| [Мероприятия](/d/nyc-taxi-events) | NFL, NBA, MLB, марафон → всплески такси |

KPI ниже — последний год + стрелка год-к-году (сравнение с предыдущим годом в ряду)."""

_UBER_SHARE_YR_SQL = """
WITH yr AS (
  SELECT extract(year FROM month)::int AS yr, aggregator, sum(trips) AS trips
  FROM aggregator_monthly GROUP BY 1, 2
),
tot AS (SELECT yr, sum(trips) AS total FROM yr GROUP BY 1)
SELECT make_date(y.yr, 1, 1) AS time, round(100.0 * y.trips / t.total, 1) AS uber_share
FROM yr y JOIN tot t ON t.yr = y.yr
WHERE y.aggregator = 'Uber' ORDER BY y.yr
"""

d0_panels = [
    text_panel(0, {"x": 0, "y": 0, "w": 24, "h": 7}, d0_intro),
    stat_trend_panel(1, "Среднесуточные поездки (последний год)", {"x": 0, "y": 7, "w": 6, "h": 5},
                     'SELECT make_date(year::int,1,1) AS time, avg_daily_trips '
                     "FROM product_metrics_yearly ORDER BY year",
                     unit="short"),
    stat_trend_panel(2, "Медиана ожидания, мин", {"x": 6, "y": 7, "w": 6, "h": 5},
                     'SELECT make_date(year::int,1,1) AS time, '
                     "round((med_wait_sec/60.0)::numeric, 2) AS med_wait_min "
                     "FROM product_metrics_yearly ORDER BY year",
                     unit="m"),
    stat_trend_panel(3, "Оплата водителя, $/час", {"x": 12, "y": 7, "w": 6, "h": 5},
                     'SELECT make_date(year::int,1,1) AS time, med_hourly_pay '
                     "FROM product_metrics_yearly ORDER BY year",
                     unit="currencyUSD"),
    stat_trend_panel(4, "Доля Uber, %", {"x": 18, "y": 7, "w": 6, "h": 5},
                     _UBER_SHARE_YR_SQL.strip(), unit="percent", color="#06C167"),
    timeseries_panel(5, "North Star: поездки/день по годам", {"x": 0, "y": 12, "w": 12, "h": 8},
                      'SELECT make_date(year::int,1,1) AS "time", avg_daily_trips FROM product_metrics_yearly ORDER BY year',
                      unit="short", metric_palette=True),
    timeseries_panel(6, "Guardrail: ожидание, мин", {"x": 12, "y": 12, "w": 12, "h": 8},
                      'SELECT make_date(year::int,1,1) AS "time", '
                      "round((med_wait_sec/60.0)::numeric,2) AS med_wait_min "
                      "FROM product_metrics_yearly ORDER BY year",
                      unit="m", metric_palette=True),
]
dash0 = dashboard("NYC Taxi — Обзор", "nyc-taxi-home", d0_panels, ["nyc-taxi"])

# ===========================================================================
# Dashboard 1: Данные и продуктовые метрики
# ===========================================================================
d1_intro = """## Вопрос: здоров ли рынок такси год к году, и не в ущерб ли водителям/райдерам?

**North Star** (`avg_daily_trips`) — растет ли объем реально доставляемой ценности.
**Guardrail** (время ожидания, оплата водителя) — не растет ли North Star за счет того,
что кто-то из сторон рынка страдает. **Proxy** (тариф/милю, ликвидность) — быстрые опережающие
сигналы дисбаланса, которые двигаются раньше, чем North Star успевает отреагировать.

**Короткий ответ:** рынок восстанавливается после провала COVID (2020: −51% к 2019), но к 2025
все еще на −20% от пика 2019. При этом guardrail-ы держатся здорово — ожидание стабильно
(4-5 мин), оплата водителя растет (+29% за 7 лет, эффект минимального тарифа TLC с 2023) —
рост не идет за счет водителей."""

d1_panels = [
    text_panel(0, {"x": 0, "y": 0, "w": 24, "h": 6}, d1_intro),
    timeseries_panel(1, "North Star: среднесуточные поездки по годам", {"x": 0, "y": 6, "w": 12, "h": 8},
                      "SELECT make_date(year::int,1,1) AS \"time\", avg_daily_trips FROM product_metrics_yearly ORDER BY year",
                      unit="short", metric_palette=True),
    timeseries_panel(2, "Guardrail: время ожидания подачи, мин", {"x": 12, "y": 6, "w": 12, "h": 8},
                      "SELECT make_date(year::int,1,1) AS \"time\", "
                      "round((med_wait_sec/60.0)::numeric,2) AS med_wait_min "
                      "FROM product_metrics_yearly ORDER BY year",
                      unit="m", metric_palette=True),
    timeseries_panel(3, "Guardrail: почасовая оплата водителя, $", {"x": 0, "y": 14, "w": 12, "h": 8},
                      "SELECT make_date(year::int,1,1) AS \"time\", med_hourly_pay FROM product_metrics_yearly ORDER BY year",
                      unit="currencyUSD", metric_palette=True),
    timeseries_panel(4, "Proxy: тариф за милю, $", {"x": 12, "y": 14, "w": 12, "h": 8},
                      "SELECT make_date(year::int,1,1) AS \"time\", med_fare_per_mile FROM product_metrics_yearly ORDER BY year",
                      unit="currencyUSD", metric_palette=True),
    timeseries_panel(5, "Proxy: ликвидность рынка (поездок / активная зона-час)", {"x": 0, "y": 22, "w": 12, "h": 8},
                      "SELECT make_date(year::int,1,1) AS \"time\", avg_trips_per_active_zone_hour FROM product_metrics_yearly ORDER BY year",
                      unit="short", metric_palette=True),
    panel(6, "Таблица метрик по годам", {"x": 12, "y": 22, "w": 12, "h": 8}, "table",
          [sql_target("SELECT * FROM product_metrics_yearly WHERE year IN (${year:sqlstring}) ORDER BY year")]),
]
dash1 = dashboard("NYC Taxi — Данные и продуктовые метрики", "nyc-taxi-data-metrics", d1_panels, ["nyc-taxi"],
                   variables=[VAR_YEAR])

# ===========================================================================
# Dashboard 2: Погода, метро, congestion pricing
# ===========================================================================
d2_intro = """## Вопрос: влияет ли погода на спрос такси, через какой канал, и что сделал congestion pricing?

**Короткий ответ:** дождь увеличивает спрос на такси (+1.44% на 10мм осадков, город в целом),
но эффект сильно неравномерен — сильнее всего в Манхэттене (+2.11%, значимо), исчезает на
Статен-Айленде (+0.23%, **не значимо**, p=0.46). Субституция с метро реальна, но только там,
где метро физически рядом (+1.77% в ближних к метро зонах против +0.33% в дальних, не значимо).
Congestion pricing (с 5 января 2025) уронил такси-спрос в Манхэттене на 9 процентных пунктов
относительно тренда — единственный округ, где объем упал год-к-году, на фоне роста везде
остальные.

**Осторожно:** таблицы ниже показывают p-value — красная заливка значит эффект статистически
не отличим от нуля, не интерпретируйте такие цифры как реальный эффект."""

d2_panels = [
    text_panel(0, {"x": 0, "y": 0, "w": 24, "h": 7}, d2_intro),
    significance_table(1, "Эффект дождя на поездки по округам", {"x": 0, "y": 7, "w": 12, "h": 9},
                        "SELECT borough, pct_per_10mm_rain, p_value, n_days FROM weather_effect_by_borough "
                        "WHERE borough IN (${borough:sqlstring}) ORDER BY pct_per_10mm_rain DESC"),
    significance_table(2, "Эффект дождя по доступности метро (терцили)", {"x": 12, "y": 7, "w": 12, "h": 9},
                        "SELECT tier, pct_per_10mm_rain, p_value, n_zones FROM rain_effect_by_subway_tier ORDER BY pct_per_10mm_rain DESC"),
    barchart_panel(3, "Congestion pricing: поездки год-к-году, %", {"x": 0, "y": 16, "w": 12, "h": 8},
                   "SELECT borough, yoy_pct FROM congestion_pricing_yoy WHERE borough IN (${borough:sqlstring}) ORDER BY yoy_pct",
                   metric_palette=True),
    barchart_panel(4, "Congestion pricing: тариф год-к-году, %", {"x": 12, "y": 16, "w": 12, "h": 8},
                   "SELECT borough, fare_yoy_pct FROM congestion_pricing_yoy WHERE borough IN (${borough:sqlstring}) ORDER BY fare_yoy_pct DESC",
                   metric_palette=True),
    timeseries_panel(5, "Ежедневные поездки, весь период", {"x": 0, "y": 24, "w": 24, "h": 7},
                      'SELECT date AS "time", trips FROM daily_citywide ORDER BY date', unit="short",
                      metric_palette=True),
    timeseries_panel(6, "Осадки, мм/день", {"x": 0, "y": 31, "w": 12, "h": 7},
                      'SELECT date AS "time", prcp_mm FROM daily_citywide ORDER BY date', unit="lengthmm",
                      metric_palette=True),
    timeseries_panel(7, "Ежедневный райдершип метро (MTA)", {"x": 12, "y": 31, "w": 12, "h": 7},
                      'SELECT date AS "time", subway_ridership FROM daily_citywide ORDER BY date', unit="short",
                      metric_palette=True, metric_color=METRIC_COLOR_LO),
]
dash2 = dashboard("NYC Taxi — Погода, метро, congestion pricing", "nyc-taxi-weather-metro", d2_panels, ["nyc-taxi"],
                   variables=[VAR_BOROUGH])

# ===========================================================================
# Dashboard 3: Спрос, цена, прогноз + wait filters
# ===========================================================================
# Postgres: round(float, int) does NOT exist — always cast to numeric.
# Grafana multi-vars: use ${var:sqlstring} so All → 'a','b' not bare All.
d3_intro = """## Спрос, цена и ожидание подачи

Фильтры сверху: **округ**, **тип покрытия** (dominant taxi type), **агрегатор** (Uber/Lyft), **кластер**.
Wait считается только по FHVHV (`request→pickup`); yellow/green timestamp запроса не отдают.
На карте чекбоксы покрытия гасят чужие зоны; wait внутри — все равно FHVHV."""

WAIT_HEATMAP_SQL = """
SELECT
  (date_trunc('day', $__timeTo()::timestamptz) + hour * INTERVAL '1 hour') AS "time",
  round((sum(med_wait_sec * n_trips) FILTER (WHERE dow=0) / nullif(sum(n_trips) FILTER (WHERE dow=0), 0) / 60.0)::numeric, 2) AS "Пн",
  round((sum(med_wait_sec * n_trips) FILTER (WHERE dow=1) / nullif(sum(n_trips) FILTER (WHERE dow=1), 0) / 60.0)::numeric, 2) AS "Вт",
  round((sum(med_wait_sec * n_trips) FILTER (WHERE dow=2) / nullif(sum(n_trips) FILTER (WHERE dow=2), 0) / 60.0)::numeric, 2) AS "Ср",
  round((sum(med_wait_sec * n_trips) FILTER (WHERE dow=3) / nullif(sum(n_trips) FILTER (WHERE dow=3), 0) / 60.0)::numeric, 2) AS "Чт",
  round((sum(med_wait_sec * n_trips) FILTER (WHERE dow=4) / nullif(sum(n_trips) FILTER (WHERE dow=4), 0) / 60.0)::numeric, 2) AS "Пт",
  round((sum(med_wait_sec * n_trips) FILTER (WHERE dow=5) / nullif(sum(n_trips) FILTER (WHERE dow=5), 0) / 60.0)::numeric, 2) AS "Сб",
  round((sum(med_wait_sec * n_trips) FILTER (WHERE dow=6) / nullif(sum(n_trips) FILTER (WHERE dow=6), 0) / 60.0)::numeric, 2) AS "Вс"
FROM wait_by_hour_dow_aggregator
WHERE aggregator IN (${aggregator:sqlstring})
GROUP BY hour
ORDER BY hour
"""

d3_panels = [
    text_panel(0, {"x": 0, "y": 0, "w": 24, "h": 4}, d3_intro),
    iframe_panel(1, {"x": 0, "y": 4, "w": 24, "h": 22}, "public/nyc_map/index.html",
                 title="Где и когда дольше всего ждать машину? (карта зон)"),
    heatmap_panel(10,
                  "В какие часы и дни недели дольше ждать? (мин, фильтр агрегатора)",
                  {"x": 0, "y": 26, "w": 12, "h": 10}, WAIT_HEATMAP_SQL, unit="m",
                  wide=True, time_from="now/d", reverse=False, metric_palette=True),
    barchart_panel(12, "У кого из агрегаторов дольше медианное ожидание?",
                   {"x": 12, "y": 26, "w": 12, "h": 10},
                   # String field required by Grafana bar chart; wide cols → brand colors
                   f"SELECT 'ожидание' AS metric, "
                   f"round((sum(med_wait_sec * n_trips) FILTER (WHERE aggregator='Uber')/"
                   f"nullif(sum(n_trips) FILTER (WHERE aggregator='Uber'),0)/60.0)::numeric,2) AS \"Uber\", "
                   f"round((sum(med_wait_sec * n_trips) FILTER (WHERE aggregator='Lyft')/"
                   f"nullif(sum(n_trips) FILTER (WHERE aggregator='Lyft'),0)/60.0)::numeric,2) AS \"Lyft\", "
                   f"round((sum(med_wait_sec * n_trips) FILTER (WHERE aggregator='Via')/"
                   f"nullif(sum(n_trips) FILTER (WHERE aggregator='Via'),0)/60.0)::numeric,2) AS \"Via\", "
                   f"round((sum(med_wait_sec * n_trips) FILTER (WHERE aggregator='Juno')/"
                   f"nullif(sum(n_trips) FILTER (WHERE aggregator='Juno'),0)/60.0)::numeric,2) AS \"Juno\" "
                   f"FROM zone_wait_by_aggregator "
                   f"WHERE aggregator IN (${{aggregator:sqlstring}}) AND n_trips >= {MIN_WAIT_N}",
                   series_colors=AGGREGATOR_COLORS),
    barchart_panel(11, "В каких зонах покрытия хуже всего с подачей? (топ-15, мин)",
                   {"x": 0, "y": 36, "w": 14, "h": 10},
                   f"SELECT sa.zone_name, "
                   f"round((sum(zwa.med_wait_sec * zwa.n_trips)/nullif(sum(zwa.n_trips),0)/60.0)::numeric,2) AS med_wait_min "
                   f"FROM zone_wait_by_aggregator zwa "
                   f"JOIN subway_access sa ON sa.\"LocationID\" = zwa.zone "
                   f"JOIN zone_dominant_type zdt ON zdt.zone = zwa.zone "
                   f"WHERE zwa.aggregator IN (${{aggregator:sqlstring}}) AND zwa.n_trips >= {MIN_WAIT_N} "
                   f"AND sa.borough IN (${{borough:sqlstring}}) "
                   f"AND zdt.dominant_type IN (${{taxi_type:sqlstring}}) "
                   f"GROUP BY sa.zone_name "
                   f"ORDER BY med_wait_min DESC NULLS LAST LIMIT 15",
                   metric_palette=True),
    panel(13, "Какие зоны «принадлежат» выбранному типу такси?",
          {"x": 14, "y": 36, "w": 10, "h": 10}, "table",
          [sql_target(
              "SELECT zone_name, borough, dominant_type, "
              "round(dominant_share_pct::numeric,1) AS share_pct, "
              "round(yellow::numeric,0) AS yellow, round(green::numeric,0) AS green, "
              "round(fhvhv::numeric,0) AS fhvhv, round(fhv::numeric,0) AS fhv "
              "FROM zone_dominant_type "
              "WHERE dominant_type IN (${taxi_type:sqlstring}) "
              "AND borough IN (${borough:sqlstring}) "
              "ORDER BY dominant_share_pct DESC LIMIT 30")]),
    barchart_panel(2, "Насколько точен прогноз спроса? (MAPE %)",
                   {"x": 0, "y": 46, "w": 12, "h": 8},
                   "SELECT model, mape_pct FROM forecast_results ORDER BY mape_pct DESC",
                   metric_palette=True),
    significance_table(3, "Как цена влияет на спрос? (naive vs IV)",
                        {"x": 12, "y": 46, "w": 12, "h": 8},
                        "SELECT method, estimate, p_value, note FROM price_elasticity", pvalue_col="p_value"),
    piechart_panel(4, "Какие ритмы спроса бывают у зон?",
                   {"x": 0, "y": 54, "w": 8, "h": 8},
                   "SELECT cluster_label, count(*) AS n_zones FROM zone_clusters "
                   "WHERE cluster_label IN (${cluster:sqlstring}) "
                   "AND borough IN (${borough:sqlstring}) GROUP BY cluster_label",
                   color_map=CLUSTER_COLORS),
    panel(5, "Далеко от метро = меньше поездок?",
          {"x": 8, "y": 54, "w": 16, "h": 8}, "table",
          [sql_target(
              "SELECT zone_name, borough, dist_to_subway_m, annual_trips, fare_per_mile, avg_trip_miles "
              "FROM subway_access WHERE borough IN (${borough:sqlstring}) "
              "ORDER BY dist_to_subway_m")]),
    timeseries_panel(6, "Как менялся спрос по округам во времени?",
                      {"x": 0, "y": 62, "w": 24, "h": 8},
                      'SELECT date AS "time", borough, trips FROM daily_by_borough '
                      "WHERE borough IN (${borough:sqlstring}) ORDER BY date",
                      unit="short"),
    panel(8, "На каких аэропортах дольше ждать такси? (2024, мин)",
          {"x": 0, "y": 70, "w": 24, "h": 8}, "table",
          [sql_target(
              "SELECT sa.zone_name, sa.annual_trips, "
              "round((zw.med_wait_sec/60.0)::numeric, 2) AS med_wait_min, "
              "zw.n_trips, "
              "round(sa.fare_per_mile::numeric, 2) AS fare_per_mile "
              "FROM subway_access sa "
              "LEFT JOIN zone_wait_time zw ON zw.zone = sa.\"LocationID\" "
              "WHERE sa.zone_name IN ('JFK Airport','LaGuardia Airport') "
              "ORDER BY med_wait_min DESC NULLS LAST")]),
]
dash3 = dashboard("NYC Taxi — Спрос, цена, прогноз", "nyc-taxi-demand-price", d3_panels, ["nyc-taxi"],
                   variables=[VAR_BOROUGH, VAR_TAXI_TYPE, VAR_AGGREGATOR, VAR_CLUSTER])

# ===========================================================================
# Dashboard 4: Эффект COVID (+ green recovery narrative)
# ===========================================================================
d4_intro = """## Вопрос: как COVID ударил по типам такси — и правда ли, что он «убил» green?

**Короткий ответ:** COVID был общим шоком, а не уникальной причиной смерти green.
В 2020 yellow и green упали почти одинаково (~до 29% и 27% от 2019). К 2025 пути
разошлись: apps (FHVHV) уже выше доковидного уровня (~104%), yellow около половины (~53%),
green — около **9%**. Ниже — индекс (янв 2019 = 100), абсолютные объемы, дно кризиса,
KPI восстановления и разбор, почему популяция green не вернулась."""

_d4_recovery_sql = (
    "WITH t AS ("
    "  SELECT taxi_type,"
    "    sum(CASE WHEN month >= '2019-01-01' AND month < '2020-01-01' THEN trips END) AS t2019,"
    "    sum(CASE WHEN month >= '2025-01-01' AND month < '2026-01-01' THEN trips END) AS t2025"
    "  FROM monthly_by_type GROUP BY taxi_type"
    ") SELECT round((100.0 * t2025 / nullif(t2019,0))::numeric, 1) AS recovery_pct "
    "FROM t WHERE taxi_type = '{tt}'"
)

d4_causes = """## Почему green не восстановил популяцию

COVID обнулил спрос у всех сразу. Дальше рынок разъехался по разным «рельсам».
Желтые такси частично ожили там, где у них есть плотный спрос: Manhattan CBD и аэропорты.
Приложения (Uber/Lyft) вернули плотность водителей через диспетчеризацию, ETA и оплату в app —
и к 2025 уже превысили уровень 2019. Green остался в той же нише, где apps сильнее всего:
outer boroughs, street-hail, без права брать пассажиров с улицы в CBD и на аэропортах.

Отсюда цепочка: меньше выгодных поездок → ниже дневной заработок (~$114 → ~$52 по прессе) →
водители уходят (пик ~7.5k в 2015 → ~0.5k к 2026) → еще меньше машин на улице → еще слабее
street-hail. Пилоты TLC без доступа к dense demand не чинят эту экономику.

**DoWhy / TWFE (зона×год):** у yellow рост доли apps внутри зоны сильно связан с падением
поездок (каннибализация). У green прямой эффект apps слабее и менее стабилен — главный
эмпирический факт не «один ATE», а асимметрия recovery **9% vs 104%**. Зоны, где apps уже
доминировали в 2019, к 2025 восстановили green хуже (кросс-секция, p ≪ 0.001).

**Uber / Lyft:** take ~28–30% mobility bookings у Uber (US share ~76%); Lyft #2 (~24% US,
~26% NYC), ниже take в отчетности из‑за net accounting. Вместе — дуополия ~75%+ for-hire.
Apps монетизируют matching и pricing power; green — только meter на урезанной карте.
Пока apps держат density в boroughs, street-hail green проигрывает по convenience даже
после отступления COVID.

Полный отчет: `reports/nyc_green_taxi_covid_dowhy.html`."""

COVID_INDEX_TS_SQL = """
SELECT month AS "time", taxi_type, index_jan2019_100
FROM monthly_by_type_indexed
WHERE taxi_type IN (${taxi_type:sqlstring})
UNION ALL
SELECT month AS "time", 'Метро NYC' AS taxi_type, index_jan2019_100
FROM monthly_recovery_indexed
WHERE series = 'Метро NYC'
ORDER BY 1, 2
"""

COVID_RECOVERY_MONTHLY_SQL = """
SELECT month AS "time", series,
  round(index_jan2019_100::numeric, 1) AS recovery_idx
FROM monthly_recovery_indexed
WHERE series = 'Метро NYC' OR series IN (${borough:sqlstring})
ORDER BY month, series
"""

COVID_RECOVERY_YEARLY_SQL = """
SELECT make_date(year::int, 1, 1) AS "time", series,
  round(index_jan2019_100::numeric, 1) AS recovery_idx
FROM yearly_recovery_indexed
WHERE series = 'Метро NYC' OR series IN (${borough:sqlstring})
ORDER BY year, series
"""

COVID_AGG_MONTHLY_SQL = """
SELECT month AS "time", aggregator,
  round(index_jan2019_100::numeric, 1) AS recovery_idx
FROM aggregator_monthly_indexed
WHERE aggregator IN (${aggregator:sqlstring})
ORDER BY month, aggregator
"""

COVID_AGG_YEARLY_SQL = """
SELECT make_date(year::int, 1, 1) AS "time", aggregator,
  round(index_jan2019_100::numeric, 1) AS recovery_idx
FROM yearly_aggregator_indexed
WHERE aggregator IN (${aggregator:sqlstring})
ORDER BY year, aggregator
"""

d4_panels = [
    text_panel(0, {"x": 0, "y": 0, "w": 24, "h": 6}, d4_intro),
    stat_panel(10, "Green 2025 vs 2019", {"x": 0, "y": 6, "w": 8, "h": 4},
               _d4_recovery_sql.format(tt="green"), unit="percent", color="#2E8B57"),
    stat_panel(11, "Yellow 2025 vs 2019", {"x": 8, "y": 6, "w": 8, "h": 4},
               _d4_recovery_sql.format(tt="yellow"), unit="percent", color="#F3C518"),
    stat_panel(12, "FHVHV (apps) 2025 vs 2019", {"x": 16, "y": 6, "w": 8, "h": 4},
               _d4_recovery_sql.format(tt="fhvhv"), unit="percent", color="#6B4FA0"),
    timeseries_panel(1,
                      "Кто сильнее упал и кто быстрее восстановился? "
                      "(индекс: такси янв 2019 = 100, метро март 2020 = 100)",
                      {"x": 0, "y": 10, "w": 24, "h": 11},
                      COVID_INDEX_TS_SQL,
                      unit="short",
                      series_colors={"index_jan2019_100": {**TAXI_TYPE_COLORS, "Метро NYC": METRO_COLOR}}),
    timeseries_panel(2, "Сколько поездок в месяц у каждого типа такси? (абсолютные числа, не индекс)",
                      {"x": 0, "y": 21, "w": 24, "h": 11},
                      'SELECT month AS "time", taxi_type, trips FROM monthly_by_type '
                      'WHERE taxi_type IN (${taxi_type:sqlstring}) ORDER BY month',
                      unit="short", series_colors={"trips": TAXI_TYPE_COLORS}),
    timeseries_panel(20,
                     "Восстановление по месяцам: округа + метро (индекс янв 2019 = 100, метро март 2020 = 100)",
                     {"x": 0, "y": 32, "w": 12, "h": 10}, COVID_RECOVERY_MONTHLY_SQL,
                     unit="percent", series_colors={"recovery_idx": BOROUGH_COLORS}),
    timeseries_panel(21,
                     "Восстановление агрегаторов по месяцам (индекс янв 2019 = 100)",
                     {"x": 12, "y": 32, "w": 12, "h": 10}, COVID_AGG_MONTHLY_SQL,
                     unit="percent", series_colors={"recovery_idx": AGGREGATOR_COLORS}),
    timeseries_panel(22,
                     "Восстановление по годам: округа + метро (индекс 2019 = 100, метро март 2020 = 100)",
                     {"x": 0, "y": 42, "w": 12, "h": 10}, COVID_RECOVERY_YEARLY_SQL,
                     unit="percent", series_colors={"recovery_idx": BOROUGH_COLORS}),
    timeseries_panel(23,
                     "Восстановление агрегаторов по годам (индекс 2019 = 100)",
                     {"x": 12, "y": 42, "w": 12, "h": 10}, COVID_AGG_YEARLY_SQL,
                     unit="percent", series_colors={"recovery_idx": AGGREGATOR_COLORS}),
    panel(3, "Когда было дно COVID по каждому типу?", {"x": 0, "y": 52, "w": 24, "h": 7}, "table",
          [sql_target(
              "SELECT taxi_type, min(index_jan2019_100) AS min_index_pct, "
              "(array_agg(month ORDER BY index_jan2019_100 ASC))[1] AS bottom_month "
              "FROM monthly_by_type_indexed WHERE month < '2021-01-01' "
              "AND taxi_type IN (${taxi_type:sqlstring}) "
              "GROUP BY taxi_type ORDER BY min_index_pct")]),
    text_panel(4, {"x": 0, "y": 59, "w": 24, "h": 16}, d4_causes),
]
dash4 = dashboard("NYC Taxi — Эффект COVID по типам такси", "nyc-taxi-covid", d4_panels, ["nyc-taxi"],
                   variables=[VAR_TAXI_TYPE_COVID, VAR_BOROUGH, VAR_AGGREGATOR_SHARE])

# ===========================================================================
# Dashboard 5: Конкуренция агрегаторов и зоны доминирования
# ===========================================================================
d5_intro = """## Вопрос: это реальная конкуренция агрегаторов, или рынок консолидировался?

**Короткий ответ:** рынок сжался с 4 игроков до фактической дуополии Uber/Lyft — Juno ушел
в ноябре 2019, Via — в октябре 2021 (аннотации на графике ниже). С тех пор Uber держит
устойчиво ~74% рынка **равномерно по всем округам** (73-78%, разброс минимальный), Lyft — ~26%.
Доминирование по зонам еще жестче: Uber — доминирующий агрегатор в 259 из 262 зон; три зоны,
где формально побеждает Lyft (Rikers Island, Governor's Island, кладбище Saint Michaels) —
статистический шум на почти нулевых объемах, не реальные рыночные позиции. По типам такси
картина похожая: fhvhv (Uber+Lyft+...) доминирует в 259 из 263 зон, yellow и fhv делят
оставшиеся 4. Цвета — фирменные: Uber Green `#06C167`, Lyft Pink `#FF00BF`, Via бирюзовый, Juno фиолетовый."""

d5_panels = [
    text_panel(0, {"x": 0, "y": 0, "w": 24, "h": 8}, d5_intro),
    timeseries_panel(1, "Как делится рынок между агрегаторами во времени?",
                      {"x": 0, "y": 8, "w": 24, "h": 10},
                      'SELECT month AS "time", aggregator, share_pct FROM aggregator_monthly '
                      'WHERE aggregator IN (${aggregator:sqlstring}) ORDER BY month',
                      unit="percent", series_colors={"share_pct": AGGREGATOR_COLORS}),
    barchart_panel(2, "Одинакова ли доля Uber/Lyft по округам?",
                   {"x": 0, "y": 18, "w": 12, "h": 9},
                   "SELECT borough, "
                   "max(CASE WHEN aggregator='Uber' THEN share_pct END) AS \"Uber\", "
                   "max(CASE WHEN aggregator='Lyft' THEN share_pct END) AS \"Lyft\" "
                   "FROM aggregator_by_borough_2024 WHERE borough IN (${borough:sqlstring}) "
                   "GROUP BY borough ORDER BY borough",
                   series_colors=AGGREGATOR_COLORS),
    piechart_panel(3, "Кто доминирует в зонах по типу такси?",
                   {"x": 12, "y": 18, "w": 12, "h": 9},
                   "SELECT dominant_type, count(*) AS n_zones FROM zone_dominant_type "
                   "WHERE borough IN (${borough:sqlstring}) GROUP BY dominant_type",
                   color_map=TAXI_TYPE_COLORS),
    piechart_panel(4, "Кто доминирует в зонах среди агрегаторов?",
                   {"x": 0, "y": 27, "w": 12, "h": 9},
                   "SELECT dominant_aggregator, count(*) AS n_zones FROM zone_dominant_aggregator "
                   "WHERE borough IN (${borough:sqlstring}) GROUP BY dominant_aggregator",
                   color_map=AGGREGATOR_COLORS),
    panel(5, "Где НЕ доминирует Uber / fhvhv?",
          {"x": 12, "y": 27, "w": 12, "h": 9}, "table",
          [sql_target(
              "SELECT zone_name, borough, dominant_aggregator, round(dominant_share_pct::numeric,1) AS share_pct "
              "FROM zone_dominant_aggregator WHERE dominant_aggregator != 'Uber' "
              "AND borough IN (${borough:sqlstring}) "
              "UNION ALL "
              "SELECT zone_name, borough, dominant_type, round(dominant_share_pct::numeric,1) "
              "FROM zone_dominant_type WHERE dominant_type != 'fhvhv' "
              "AND borough IN (${borough:sqlstring}) "
              "ORDER BY share_pct DESC")]),
]
dash5 = dashboard("NYC Taxi — Конкуренция агрегаторов и зоны доминирования", "nyc-taxi-aggregators", d5_panels, ["nyc-taxi"],
                   variables=[VAR_AGGREGATOR_SHARE, VAR_BOROUGH])

# ===========================================================================
# Dashboard 6: Массовые мероприятия → такси
# ===========================================================================
VAR_EVENT_TYPE = query_variable("event_type", "Тип события",
                                "SELECT DISTINCT event_type FROM event_impact ORDER BY 1")

d6_intro = """## Как массовые мероприятия влияют на такси?

**Метод:** для каждого события сравниваем поездки FHVHV (Uber/Lyft) в зонах стадиона/арены
с **базой того же дня недели и тех же часов** в дни без событий.

| Окно | Что меряем | Интерпретация |
|------|------------|---------------|
| **−2…0 ч** до начала | dropoff в зону | **Приезд** зрителей |
| **0…+3 ч** | pickup + dropoff | **Во время** события |
| **+3…+5 ч** после | pickup из зоны | **Разъезд** после финала |

**Гипотеза (DoWhy):** чем **дороже** (`price_tier`) и чем **дальше от метро** (`log_dist_m`),
тем сильнее разъезд на такси. Полный отчет: `reports/nyc_event_taxi_dowhy.html`.

**Источники событий:** NFL/NBA/MLB/MLS (расписания), концерты (MSG/Barclays/Yankee/Citi),
парады и перекрытия (Thanksgiving, St Patrick's, NYE, Pride).

**Карта:** режим **«События ▶»** → площадка → таймлапс pickup/час с авто-зумом."""

d6_panels = [
    text_panel(0, {"x": 0, "y": 0, "w": 24, "h": 5}, d6_intro),
    stat_panel(30, "DoWhy: dist→lift (ATE pp/ln m)", {"x": 0, "y": 5, "w": 6, "h": 4},
               "SELECT round(ate::numeric, 2) FROM event_dowhy_results WHERE model='dist_to_metro'",
               color=METRIC_COLOR_LO),
    stat_panel(31, "DoWhy p-value (dist)", {"x": 6, "y": 5, "w": 6, "h": 4},
               "SELECT round(p_value::numeric, 4) FROM event_dowhy_results WHERE model='dist_to_metro'",
               color=METRIC_COLOR_LO),
    stat_panel(32, "DoWhy: price tier→lift", {"x": 12, "y": 5, "w": 6, "h": 4},
               "SELECT round(ate::numeric, 2) FROM event_dowhy_results WHERE model='price_tier'",
               unit="percent", color=METRIC_COLOR_HI),
    stat_panel(33, "DoWhy p-value (price)", {"x": 18, "y": 5, "w": 6, "h": 4},
               "SELECT round(p_value::numeric, 4) FROM event_dowhy_results WHERE model='price_tier'",
               color=METRIC_COLOR_HI),
    iframe_panel(1, {"x": 0, "y": 9, "w": 24, "h": 16}, "public/nyc_map/index.html",
                 title="Таймлапс событий: lift pickup (режим «События ▶»)"),
    stat_panel(1, "Средний всплеск разъезда (post PU)", {"x": 0, "y": 25, "w": 6, "h": 4},
               "SELECT round(avg(post_pu_lift_pct)::numeric, 1) FROM event_impact "
               "WHERE event_type IN (${event_type:sqlstring})", unit="percent", color=METRIC_COLOR_HI),
    stat_panel(2, "Средний всплеск приезда (pre DO)", {"x": 6, "y": 25, "w": 6, "h": 4},
               "SELECT round(avg(pre_do_lift_pct)::numeric, 1) FROM event_impact "
               "WHERE event_type IN (${event_type:sqlstring})", unit="percent", color=METRIC_COLOR_LO),
    stat_panel(3, "Событий в выборке", {"x": 12, "y": 25, "w": 6, "h": 4},
               "SELECT count(*) FROM event_impact WHERE event_type IN (${event_type:sqlstring})",
               color=METRIC_COLOR_LO),
    stat_panel(4, "ρ: price_tier → разъезд", {"x": 18, "y": 25, "w": 6, "h": 4},
               "SELECT round(corr(price_tier, post_pu_lift_pct)::numeric, 2) FROM event_hypothesis",
               color=METRIC_COLOR_HI),
    barchart_panel(10, "Гипотеза: разъезд vs price tier (медиана по площадке)",
                   {"x": 0, "y": 29, "w": 12, "h": 9},
                   f"SELECT price_tier::text AS tier, "
                   f"round({_pg_median('post_pu_lift')}::numeric, 1) AS post_pu_lift "
                   "FROM event_hypothesis_venue GROUP BY price_tier ORDER BY price_tier",
                   metric_palette=True),
    barchart_panel(11, "Гипотеза: разъезд vs расстояние до метро (по площадкам)",
                   {"x": 12, "y": 29, "w": 12, "h": 9},
                   "SELECT name, post_pu_lift FROM event_hypothesis_venue "
                   "ORDER BY dist_to_subway_m DESC",
                   metric_palette=True),
    barchart_panel(12, "Всплеск разъезда после события по типу (медиана, % к базе)",
                   {"x": 0, "y": 38, "w": 12, "h": 9},
                   f"SELECT event_type, round({_pg_median('post_pu_lift_pct')}::numeric, 1) AS post_pu_lift "
                   "FROM event_impact GROUP BY event_type ORDER BY post_pu_lift DESC",
                   metric_palette=True),
    barchart_panel(13, "Всплеск приезда до события по типу (медиана, % к базе)",
                   {"x": 12, "y": 38, "w": 12, "h": 9},
                   f"SELECT event_type, round({_pg_median('pre_do_lift_pct')}::numeric, 1) AS pre_do_lift "
                   "FROM event_impact GROUP BY event_type ORDER BY pre_do_lift DESC",
                   metric_palette=True),
    barchart_panel(20, "Разъезд после события: топ-20 (post PU lift, %)",
                   {"x": 0, "y": 47, "w": 24, "h": 10},
                   "SELECT left(title, 40) || ' (' || date::text || ')' AS event, "
                   "post_pu_lift_pct AS lift_pct "
                   "FROM event_impact WHERE event_type IN (${event_type:sqlstring}) "
                   "ORDER BY post_pu_lift_pct DESC LIMIT 20",
                   metric_palette=True),
    panel(21, "Топ событий + гипотеза (price tier, метро)", {"x": 0, "y": 57, "w": 24, "h": 12}, "table",
          [sql_target(
              "SELECT h.date, h.event_type, h.title, h.venue_name, h.price_tier, "
              "round(h.dist_to_subway_m::numeric, 0) AS metro_m, "
              "h.pre_do_lift_pct AS \"приезд %\", h.post_pu_lift_pct AS \"разъезд %\" "
              "FROM event_hypothesis h "
              "WHERE h.event_type IN (${event_type:sqlstring}) "
              "ORDER BY h.post_pu_lift_pct DESC LIMIT 30")]),
]
dash6 = dashboard("NYC Taxi — Мероприятия и спрос на такси", "nyc-taxi-events", d6_panels, ["nyc-taxi"],
                   variables=[VAR_EVENT_TYPE])

# ===========================================================================
out_dir = r"C:\Users\andrn\HSE\NYC\grafana_provisioning\dashboard_json"
files = [
    ("00-home.json", dash0),
    ("01-data-metrics.json", dash1), ("02-weather-metro.json", dash2), ("03-demand-price.json", dash3),
    ("04-covid.json", dash4), ("05-aggregators.json", dash5), ("06-events.json", dash6),
]
for name, d in files:
    with open(f"{out_dir}\\{name}", "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    print("wrote", name)
