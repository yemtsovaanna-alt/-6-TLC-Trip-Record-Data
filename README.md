# NYC TLC Trip Record Data — аналитика и дашборды

Репозиторий объединяет несколько независимых аналитических треков по данным NYC TLC.
Основной трек (`01-nyc-taxi-suite`, дашборды 1–7) рассматривает все типы поездок —
Yellow/Green/FHV/FHVHV (такси и Uber/Lyft/Via/Juno) — за 2019–2026. Три остальных трека
(дашборды 8–11) сфокусированы на FHVHV (Uber/Lyft) за 2025–2026: доступность поездок
(WAV/AAR), совместные поездки (shared rides) и обзор/конкуренция агрегаторов. Итог
каждого трека — один или несколько **Grafana-дашбордов** поверх Postgres-витрин
("marts"), плюс Jupyter-ноутбуки/скрипты, которыми эти витрины считаются, плюс
статические HTML-отчеты с причинным анализом.

Все треки лежат в [`dashboards/`](dashboards/), по одной папке на трек. Всего в
репозитории **11 дашбордов** в 4 разделах:

## Карта дашбордов

| # | Дашборд | Раздел | О чем | Подробнее |
|---|---|---|---|---|
| 1 | **NYC Taxi — Обзор** (home) | [`01-nyc-taxi-suite/`](dashboards/01-nyc-taxi-suite/README.md) | North Star/Guardrail метрики одним взглядом | [README.md](dashboards/01-nyc-taxi-suite/README.md#00-home) |
| 2 | **NYC Taxi — Данные и продуктовые метрики** | [`01-nyc-taxi-suite/`](dashboards/01-nyc-taxi-suite/README.md) | North Star/Guardrail/Proxy метрики по годам | [README.md](dashboards/01-nyc-taxi-suite/README.md#01-data-metrics) |
| 3 | **NYC Taxi — Погода, метро, congestion pricing** | [`01-nyc-taxi-suite/`](dashboards/01-nyc-taxi-suite/README.md) | Дождь/температура/метро vs спрос, эффект платного въезда в Manhattan CBD | [README.md](dashboards/01-nyc-taxi-suite/README.md#02-weather-metro) |
| 4 | **NYC Taxi — Спрос, цена, прогноз** | [`01-nyc-taxi-suite/`](dashboards/01-nyc-taxi-suite/README.md) | Ожидание по зонам/часам, точность прогноза спроса, эластичность цены | [README.md](dashboards/01-nyc-taxi-suite/README.md#03-demand-price) |
| 5 | **NYC Taxi — Эффект COVID по типам такси** | [`01-nyc-taxi-suite/`](dashboards/01-nyc-taxi-suite/README.md) | Падение и восстановление по типам такси/округам/агрегаторам, 2019=100 | [README.md](dashboards/01-nyc-taxi-suite/README.md#04-covid) |
| 6 | **NYC Taxi — Конкуренция агрегаторов и зоны доминирования** | [`01-nyc-taxi-suite/`](dashboards/01-nyc-taxi-suite/README.md) | Доли рынка Uber/Lyft/Via/Juno по времени, округам, зонам | [README.md](dashboards/01-nyc-taxi-suite/README.md#05-aggregators) |
| 7 | **NYC Taxi — Мероприятия и спрос на такси** | [`01-nyc-taxi-suite/`](dashboards/01-nyc-taxi-suite/README.md) | Всплеск спроса вокруг концертов/матчей, DoWhy-причинность | [README.md](dashboards/01-nyc-taxi-suite/README.md#06-events) |
| 8 | **WAV/Accessibility Dashboard** | [`02-wav-accessibility/`](dashboards/02-wav-accessibility/README.md) | Доступные для колясок поездки (WAV/AAR) — доля, ожидание, экономика | [README.md](dashboards/02-wav-accessibility/README.md) |
| 9 | **Совместные поездки (Shared rides)** | [`03-shared-rides/`](dashboards/03-shared-rides/README.md) | Шеринг Uber/Lyft: кто чаще матчится, когда, где | [README.md](dashboards/03-shared-rides/README.md) |
| 10 | **NYC FHVHV Taxi Overview** | [`04-overview-competition/`](dashboards/04-overview-competition/README.md) | Объем поездок, выручка, комиссия, гео-экономика | [README.md](dashboards/04-overview-competition/README.md) |
| 11 | **Uber vs Lyft: Competition Overview** | [`04-overview-competition/`](dashboards/04-overview-competition/README.md) | Прямое сравнение Uber/Lyft: бронирования, типы поездок, ожидание, surge | [README.md](dashboards/04-overview-competition/README.md) |

Дашборды 1–7 — один живой Grafana-инстанс (`dashboards/01-nyc-taxi-suite/grafana_provisioning/`),
сгенерированный и провижнящийся из этого репозитория. Дашборды 8–9 (WAV, Shared rides) —
витрины и ноутбуки лежат здесь же, сама Grafana-панель к ним не экспортирована (см.
видео/описание в соответствующих разделах). Дашборды 10–11 — это **отдельный
проект-побратим** (`taxi_data_2025_2026`, свой DuckDB→Postgres ETL, не хранится в этом
репо целиком) — здесь лежат только скриншоты/видео финального результата и техническая
справка о нем.

## Структура репозитория

```
.github/
  workflows/ci.yaml         — build/test/deploy (заглушки) + проверка номера задачи в PR
  CODEOWNERS                — обязательные ревьюверы по разделам
  PULL_REQUEST_TEMPLATE.md  — шаблон PR (обязательная ссылка на Issue)
dashboards/
  01-nyc-taxi-suite/        — основной трек: 7 Grafana-дашбордов (было NYC/)
  02-wav-accessibility/     — доступность поездок WAV/AAR (было wav/)
  03-shared-rides/          — совместные поездки Uber/Lyft (было Sharing/)
  04-overview-competition/  — скрины/видео 2 дашбордов проекта-побратима (было Overview+Competition/)
branches.yaml                — политика branch protection для main (декларативно)
review.yaml                  — политика ревью: сколько approve, кто за какой раздел
CONTRIBUTING.md              — процесс разработки: ветки, ревью, CI, связь PR ↔ Issue
README.md                    — этот файл, навигатор по всем 11 дашбордам
```

| Папка | Что внутри |
|---|---|
| [`dashboards/01-nyc-taxi-suite/`](dashboards/01-nyc-taxi-suite/README.md) | Основной трек: очистка сырых TLC-данных → ~20 витрин в Postgres → 7 Grafana-дашбордов, причинные HTML-отчеты, кастомная карта зон, слайды |
| [`dashboards/02-wav-accessibility/`](dashboards/02-wav-accessibility/README.md) | Отдельный трек: доступность поездок для инвалидных колясок (WAV/AAR) — витрины, ноутбуки с проверкой гипотез, запись дашборда |
| [`dashboards/03-shared-rides/`](dashboards/03-shared-rides/README.md) | Отдельный трек: совместные поездки (shared rides) Uber/Lyft — один скрипт-пайплайн, 3 витрины, 3 проверенные гипотезы |
| [`dashboards/04-overview-competition/`](dashboards/04-overview-competition/README.md) | Скриншоты/видео + техническая справка (`GITHUB_HANDOFF.md`) по двум дашбордам из соседнего проекта (`taxi_data_2025_2026`) |

Общий для всех треков сквозной пайплайн: **сырые parquet TLC → очистка (DuckDB) →
агрегированные витрины ("витрины"/marts, `GROUP BY`-роллапы) → Postgres → Grafana /
статический HTML-отчет**. Витрины существуют потому, что сырых поездок — сотни миллионов
(327M yellow, 1.6B fhvhv и т.д., см.
[`DATA_CLEANING_LOG.md`](dashboards/01-nyc-taxi-suite/DATA_CLEANING_LOG.md)) — слишком
много для интерактивных панелей; каждая витрина — это агрегат по дню/месяцу/часу/зоне.

Крупные сырые parquet / TLC dump в git не входят.

## С чего начать человеку со стороны

1. Прочитать этот файл целиком (карта выше) — понять, сколько дашбордов и где что лежит.
2. Открыть README раздела, который интересует конкретно (ссылки в таблице выше) — там
   есть таблица «дашборд → витрины → чем строится».
3. Если нужно воспроизвести витрины — см. раздел «Как пересобрать» в README нужной папки.

## Примечание про диск

Репозиторий живет на внешнем диске с файловой системой **exFAT** — macOS создает на ней
теневые файлы `._*` (AppleDouble) для каждого файла, включая объекты `.git/`. Раз в
несколько сессий они накапливаются и могут повредить индекс git (`non-monotonic index`,
`bad sha1 file` в `git fsck`). Если снова увидите ошибки git fsck — почистите их:
`find . -name '._*' -type f -delete` (безопасно, реальные файлы не задевает).
