# NYC TLC Trip Record Data — дашборды (фото и видео) + витрины

В этом репозитории собрана информация по всем дашбордам, которые были составлены на основе данных NYC TLC.

> **N.B. Дашборды нельзя открыть по ссылке.**
> Дашборды были разработаны в Grafana. В связи с большим объемом данных было принято решение, что каждый участник команды будет локально формировать на своем устройстве витрины данных, необходимые для его раздела проекта. На основе этих витрин затем строились соответствующие дашборды в Grafana.
Поскольку витрины данных хранятся локально, открыть дашборд по ссылке с другого устройства невозможно. Поэтому в данном репозитории представлены изображения и видеозаписи дашбордов.
Для удобства просмотра ниже приведена «Навигация по дашбордам». Рекомендуется знакомиться с дашбордами именно в том порядке, в котором они представлены в "Навигация по дашбордам".


1. Главный дашборд — **NYC FHVHV Taxi Overview** (раздел `01-overview-competition`). Данные FHVHV (Uber/Lyft) взяты из https://disk.yandex.ru/d/p1YAHtu15H2tlA. Рассматриваемый период: 2025-01-01 00:00:00 по 2026-04-30 23:59:59.
2. Дашборд про конкуренцию - **Uber vs Lyft: Competition Overview** (раздел `01-overview-competition`). Данные FHVHV (Uber/Lyft) взяты из https://disk.yandex.ru/d/p1YAHtu15H2tlA. Рассматриваемый период: 2025-01-01 00:00:00 по 2026-04-30 23:59:59.
3. Дашборд про корреляцию между погодой, точками метро и кол-вом поездок - **NYC Taxi — Погода, метро, congestion pricing** (раздел `02-nyc-taxi-suite/`). Источники: taxi_weather_analysis/extend_weather.py (погода, Open-Meteo), fetch_mta_ridership.py (MTA), causal_congestion_pricing.py. Отчеты: reports/nyc_taxi_weather_causal.html, reports/nyc_subway_access.html. Рассматриваемый период: 2019-01-01 по 2026-08-09.
4. Дашборд про прогноз спроса на такси - **NYC Taxi — Спрос, цена, прогноз** (раздел `02-nyc-taxi-suite`). Источники: reports/nyc_demand_forecast.html, reports/nyc_price_elasticity.html, reports/nyc_subway_access.html, reports/nyc_zone_clusters.html. Рассматриваемый период: 2024-2025.
5. Дашборд про эффект COVID - **NYC Taxi — Эффект COVID по типам такси** (раздел `02-nyc-taxi-suite`). Источник: reports/nyc_green_taxi_covid_dowhy.html. Рассматриваемый период: 2019-2025.
6. Дашборд про конкуренцию в разрезе географии - **NYC Taxi — Конкуренция агрегаторов и зоны доминирования** (раздел `02-nyc-taxi-suite`). Рассматриваемый период: 2024.
7. Дашборд про мероприятия и спрос на такси - **NYC Taxi — Мероприятия и спрос на такси** (раздел `02-nyc-taxi-suite`). Рассматриваемый период: 2024-2025.
8. Дашборд про WAV/ARR поездки - **WAV/Accessibility Dashboard** (раздел `03-wav-accessibility`). Данные FHVHV (Uber/Lyft) взяты из https://disk.yandex.ru/d/p1YAHtu15H2tlA. Рассматриваемый период: 2025-01-01 00:00:00 по 2026-04-30 23:59:59.
9. Дашборд про шейринг поездки - **Совместные поездки (Shared rides)** (раздел `04-shared-rides/`). Данные FHVHV (Uber/Lyft) взяты из https://disk.yandex.ru/d/p1YAHtu15H2tlA. Рассматриваемый период: 2025-01-01 00:00:00 по 2026-04-30 23:59:59.



## Навигация по дашбордам

| # | Дашборд | Раздел | О чем | Ответственный | Подробнее |
|---|---|---|---|---|---|
| 1 | **NYC FHVHV Taxi Overview** (основной дашборд репозитория) | [`01-overview-competition/`](dashboards/01-overview-competition/README.md) | Объем поездок, выручка, комиссия, гео-экономика | [@yemtsovaanna-alt](https://github.com/yemtsovaanna-alt) | [README.md](dashboards/01-overview-competition/README.md) |
| 2 | **Uber vs Lyft: Competition Overview** | [`01-overview-competition/`](dashboards/01-overview-competition/README.md) | Прямое сравнение Uber/Lyft: бронирования, типы поездок, ожидание, surge | [@yemtsovaanna-alt](https://github.com/yemtsovaanna-alt) | [README.md](dashboards/01-overview-competition/README.md) |
| 3 | **NYC Taxi — Погода, метро, congestion pricing** | [`02-nyc-taxi-suite/`](dashboards/02-nyc-taxi-suite/README.md) | Дождь/температура/метро vs спрос, эффект платного въезда в Manhattan CBD | [@ddandreev2003](https://github.com/ddandreev2003) | [README.md](dashboards/02-nyc-taxi-suite/README.md#02-weather-metro) |
| 4 | **NYC Taxi — Спрос, цена, прогноз** | [`02-nyc-taxi-suite/`](dashboards/02-nyc-taxi-suite/README.md) | Ожидание по зонам/часам, точность прогноза спроса, эластичность цены | [@ddandreev2003](https://github.com/ddandreev2003) | [README.md](dashboards/02-nyc-taxi-suite/README.md#03-demand-price) |
| 5 | **NYC Taxi — Эффект COVID по типам такси** | [`02-nyc-taxi-suite/`](dashboards/02-nyc-taxi-suite/README.md) | Падение и восстановление по типам такси/округам/агрегаторам, 2019=100 | [@ddandreev2003](https://github.com/ddandreev2003) | [README.md](dashboards/02-nyc-taxi-suite/README.md#04-covid) |
| 6 | **NYC Taxi — Конкуренция агрегаторов и зоны доминирования** | [`02-nyc-taxi-suite/`](dashboards/02-nyc-taxi-suite/README.md) | Доли рынка Uber/Lyft/Via/Juno по времени, округам, зонам | [@ddandreev2003](https://github.com/ddandreev2003) | [README.md](dashboards/02-nyc-taxi-suite/README.md#05-aggregators) |
| 7 | **NYC Taxi — Мероприятия и спрос на такси** | [`02-nyc-taxi-suite/`](dashboards/02-nyc-taxi-suite/README.md) | Всплеск спроса вокруг концертов/матчей, DoWhy-причинность | [@ddandreev2003](https://github.com/ddandreev2003) | [README.md](dashboards/02-nyc-taxi-suite/README.md#06-events) |
| 8 | **WAV/Accessibility Dashboard** | [`03-wav-accessibility/`](dashboards/03-wav-accessibility/README.md) | Доступные для колясок поездки (WAV/AAR) — доля, ожидание, экономика | [@annamyaktinova](https://github.com/annamyaktinova) | [README.md](dashboards/03-wav-accessibility/README.md) |
| 9 | **Совместные поездки (Shared rides)** | [`04-shared-rides/`](dashboards/04-shared-rides/README.md) | Шеринг Uber/Lyft: кто чаще матчится, когда, где | [@SigmaMalia](https://github.com/SigmaMalia) | [README.md](dashboards/04-shared-rides/README.md) |

### Что из этого реально живет в репозитории

Не все 9 дашбордов представлены здесь одинаково полно:

| Дашборды | Что здесь есть |
|---|---|
| 1–2 (NYC FHVHV Overview, Uber vs Lyft) | Фото/видео готового результата и техническая справка о его устройстве ([`GITHUB_HANDOFF.md`](dashboards/01-overview-competition/GITHUB_HANDOFF.md)). Сами дашборды строит отдельный проект-побратим `taxi_data_2025_2026` (свой DuckDB→Postgres ETL), который в этом репозитории не хранится целиком |
| 3–7 (`02-nyc-taxi-suite`) | Полностью: репозиторий сам генерирует и провижнит живой Grafana-инстанс (`dashboards/02-nyc-taxi-suite/grafana_provisioning/`) |
| 8–9 (WAV, Shared rides) | Витрины и ноутбуки, которыми дашборд обоснован, — здесь. Сама Grafana-панель как JSON не экспортирована; посмотреть, как она выглядит, — по видео/описанию в README раздела |

## Структура репозитория

```
.github/
  workflows/ci.yaml         — build/test/deploy (заглушки) + проверка номера задачи в PR
  CODEOWNERS                — обязательные ревьюверы по разделам
  PULL_REQUEST_TEMPLATE.md  — шаблон PR (обязательная ссылка на Issue)
dashboards/
  02-nyc-taxi-suite/        — география + погода
  03-wav-accessibility/     — доступность поездок WAV/AAR 
  04-shared-rides/          — совместные поездки Uber/Lyft 
  01-overview-competition/  — главный дашборд + конкуренция
branches.yaml               — политика branch protection для main (декларативно)
review.yaml                 — политика ревью: сколько approve, кто за какой раздел
CONTRIBUTING.md             — процесс разработки: ветки, ревью, CI, связь PR ↔ Issue
README.md                   — этот файл, навигатор по всем 9 дашбордам
```

| Папка | Что внутри |
|---|---|
| [`dashboards/02-nyc-taxi-suite/`](dashboards/02-nyc-taxi-suite/README.md) | Основной трек: очистка сырых TLC-данных → ~20 витрин в Postgres → 7 Grafana-дашбордов, причинные HTML-отчеты, кастомная карта зон, слайды |
| [`dashboards/03-wav-accessibility/`](dashboards/03-wav-accessibility/README.md) | Отдельный трек: доступность поездок для инвалидных колясок (WAV/AAR) — витрины, ноутбуки с проверкой гипотез, запись дашборда |
| [`dashboards/04-shared-rides/`](dashboards/04-shared-rides/README.md) | Отдельный трек: совместные поездки (shared rides) Uber/Lyft — один скрипт-пайплайн, 3 витрины, 3 проверенные гипотезы |
| [`dashboards/01-overview-competition/`](dashboards/01-overview-competition/README.md) | Скриншоты/видео + техническая справка (`GITHUB_HANDOFF.md`) по основному дашборду и дашборду с конкуренцией (`taxi_data_2025_2026`) |

### Сквозной пайплайн

Общий для всех треков:

```
сырые parquet TLC → очистка (DuckDB) → витрины (marts, GROUP BY-роллапы) → Postgres → Grafana / статический HTML-отчет
```

Витрины нужны потому, что сырых поездок — сотни миллионов (327M yellow, 1.6B fhvhv и
т.д., см. [`DATA_CLEANING_LOG.md`](dashboards/02-nyc-taxi-suite/DATA_CLEANING_LOG.md)) —
слишком много, чтобы строить интерактивные панели напрямую по ним. Каждая витрина —
заранее посчитанный агрегат по дню/месяцу/часу/зоне.

Крупные сырые parquet и другие TLC dump-ы в репозиторий не входят — здесь только код,
который их обрабатывает, и уже посчитанные витрины/отчеты.

## С чего начать человеку со стороны

1. Прочитать этот файл целиком (карта выше) — понять, сколько дашбордов и где что лежит.
2. Открыть README раздела, который интересует конкретно (ссылки в таблице выше) — там
   есть таблица «дашборд → витрины → чем строится».
3. Если нужно воспроизвести витрины — см. раздел «Как пересобрать» в README нужной папки.

## Примечание про диск

Репозиторий живет на внешнем диске с файловой системой **exFAT**. Это важно из-за одной
особенности:

- **Причина:** на exFAT macOS создает теневые файлы `._*` (AppleDouble) для каждого
  файла, включая объекты `.git/`.
- **Симптом:** раз в несколько сессий такие файлы накапливаются и могут повредить индекс
  git — `git fsck` начинает ругаться `non-monotonic index` или `bad sha1 file`.
- **Починка:** если увидите такие ошибки, удалите теневые файлы —
  `find . -name '._*' -type f -delete`. Это безопасно: реальные файлы не задевает,
  трогает только служебный мусор exFAT.
