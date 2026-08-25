# Лог очистки данных TLC_Trip_Data

Запуск: 2026-08-12 17:13:07  
Параллелизм: 2 процессов x 1 DuckDB-потока (на машине с 16 логическими ядрами)  
Общее время выполнения: 40.6 мин

## Правила очистки по типам такси

### yellow
```sql
WHERE fare_amount >= 0 AND trip_distance > 0 AND mta_tax >= 0 AND tip_amount >= 0 AND tolls_amount >= 0 AND total_amount >= 0 AND (extra >= 0 OR extra IS NULL) AND (improvement_surcharge >= 0 OR improvement_surcharge IS NULL) AND (congestion_surcharge >= 0 OR congestion_surcharge IS NULL) AND year(tpep_pickup_datetime) BETWEEN 2019 AND 2026 AND tpep_dropoff_datetime > tpep_pickup_datetime
```
- fare_amount >= 0 — отрицательные тарифы физически невозможны
- trip_distance > 0 — поездка нулевой длины не является поездкой
- mta_tax/tip_amount/tolls_amount/total_amount/extra/improvement_surcharge/congestion_surcharge >= 0 — ни одно денежное поле не может быть отрицательным
- год pickup в [2019, 2026] — отбрасывает мусорные метки времени (напр. 2001, 2088)
- dropoff > pickup — защита от развернутых во времени поездок
- SELECT DISTINCT — удаляет точные дубликаты строк
- PULocationID/DOLocationID вне 1-263 НЕ фильтруются: проверено (см. discovery) — 100% таких значений это 264/265, официальные коды TLC 'Outside NYC'/'Unknown', а не брак данных
- passenger_count = 0 / NULL НЕ фильтруется: как и раньше, это распространенный (до ~8%) пробел в отчетности части вендоров, а не признак поврежденной записи

### green
```sql
WHERE fare_amount >= 0 AND trip_distance > 0 AND mta_tax >= 0 AND tip_amount >= 0 AND tolls_amount >= 0 AND total_amount >= 0 AND (extra >= 0 OR extra IS NULL) AND (improvement_surcharge >= 0 OR improvement_surcharge IS NULL) AND (congestion_surcharge >= 0 OR congestion_surcharge IS NULL) AND year(lpep_pickup_datetime) BETWEEN 2019 AND 2026 AND lpep_dropoff_datetime > lpep_pickup_datetime
```
- те же правила, что и для yellow (идентичная схема тарифов и колонок)

### fhv
```sql
WHERE PUlocationID IS NOT NULL AND PUlocationID != 0 AND DOlocationID IS NOT NULL AND DOlocationID != 0 AND dispatching_base_num IS NOT NULL AND dropOff_datetime > pickup_datetime
```
- PUlocationID/DOlocationID NOT NULL и != 0 — без зоны посадки/высадки запись бесполезна для анализа (0 — тот же брак, что и NULL, встречается редко)
- dispatching_base_num NOT NULL — обязательный идентификатор базы
- dropOff_datetime > pickup_datetime — защита от развернутых во времени поездок
- SELECT DISTINCT — удаляет точные дубликаты строк
- PUlocationID/DOlocationID = 264/265 НЕ фильтруются — официальные коды TLC, не брак

### fhvhv
```sql
WHERE trip_miles > 0 AND trip_miles <= 100 AND trip_time > 0 AND trip_time <= 10800 AND base_passenger_fare >= 0 AND driver_pay >= 0 AND dropoff_datetime > pickup_datetime
```
- trip_miles в (0, 100] — 0 миль или >100 миль за поездку нереалистичны для городского такси
- trip_time в (0, 10800] сек — поездки длиннее 3 часов или нулевой длительности являются браком данных
- base_passenger_fare >= 0, driver_pay >= 0 — денежные поля не могут быть отрицательными
- dropoff > pickup — защита от развернутых во времени поездок
- SELECT DISTINCT — удаляет точные дубликаты строк
- PULocationID/DOLocationID = 264/265 НЕ фильтруются — официальные коды TLC, не брак (tolls/bcf/sales_tax/congestion_surcharge/tips отрицательных значений практически не содержат — отдельный фильтр не требуется)

## Discovery: аномалии, найденные на исходных данных

Числа получены агрегациями по всем raw-файлам соответствующего типа (см. `_discover_anomalies.py`), до применения фильтрации.

### fhv (всего строк: 154,436,750)
| Метрика | Значение |
|---|---|
| pu_null | 82888612.0 |
| do_null | 16966855.0 |
| base_null | 3.0 |
| dropoff_le_pickup | 416.0 |
| pu_invalid | 26059163.0 |
| do_invalid | 19138992.0 |
| bad_year | 0.0 |
| min_pickup | 2019-01-01 00:00:00 |
| max_pickup | 2026-04-30 23:59:49 |

### fhvhv (всего строк: 1,607,275,004)
| Метрика | Значение |
|---|---|
| miles_le0 | 882487.0 |
| miles_gt100 | 155922.0 |
| time_le0 | 22468.0 |
| time_gt3h | 101153.0 |
| fare_lt0 | 1355010.0 |
| pay_lt0 | 21907.0 |
| tolls_lt0 | 0.0 |
| bcf_lt0 | 0.0 |
| salestax_lt0 | 3.0 |
| congestion_lt0 | 0.0 |
| tips_lt0 | 0.0 |
| pu_invalid | 83391.0 |
| do_invalid | 63026724.0 |
| dropoff_le_pickup | 64798.0 |
| bad_year | 0.0 |
| min_pickup | 2019-02-01 00:00:00 |
| max_pickup | 2026-06-30 23:59:59 |

### green (всего строк: 12,233,139)
| Метрика | Значение |
|---|---|
| fare_lt0 | 35396.0 |
| dist_le0 | 419807.0 |
| mta_tax_lt0 | 32097.0 |
| tip_lt0 | 1043.0 |
| tolls_lt0 | 33.0 |
| total_lt0 | 35518.0 |
| extra_lt0 | 14968.0 |
| impsur_lt0 | 33025.0 |
| congestion_lt0 | 289.0 |
| pax_eq0 | 44442.0 |
| pax_gt6 | 1175.0 |
| pax_null | 1864969.0 |
| pu_invalid | 34848.0 |
| do_invalid | 106948.0 |
| pu_null | 0.0 |
| do_null | 0.0 |
| bad_year | 318.0 |
| dropoff_le_pickup | 23619.0 |
| dist_gt200 | 4372.0 |
| min_pickup | 2008-10-21 15:52:05 |
| max_pickup | 2062-08-15 00:00:00 |
| exact_duplicate_groups | 238 |

### yellow (всего строк: 327,009,772)
| Метрика | Значение |
|---|---|
| fare_lt0 | 4731875.0 |
| dist_le0 | 5596543.0 |
| mta_tax_lt0 | 2462357.0 |
| tip_lt0 | 13934.0 |
| tolls_lt0 | 176762.0 |
| total_lt0 | 2736373.0 |
| extra_lt0 | 1273203.0 |
| impsur_lt0 | 2560545.0 |
| congestion_lt0 | 2038576.0 |
| pax_eq0 | 4791766.0 |
| pax_gt6 | 2555.0 |
| pax_null | 25926110.0 |
| pu_invalid | 2659507.0 |
| do_invalid | 3270989.0 |
| pu_null | 0.0 |
| do_null | 0.0 |
| bad_year | 2095.0 |
| dropoff_le_pickup | 1019652.0 |
| dist_gt200 | 8150.0 |
| min_pickup | 2001-01-01 00:02:08 |
| max_pickup | 2098-09-11 02:23:31 |
| exact_duplicate_groups | 12965 |

## Примененная очистка (файлы, обработанные в этом запуске)

| Тип | Файл | Было строк | Стало строк | Удалено | % удалено | Время, с |
|---|---|---:|---:|---:|---:|---:|
| fhv | fhv_tripdata_2019-01.parquet | 23,159,064 | 21,330,445 | 1,828,619 | 7.896% | 16.8 |
| fhv | fhv_tripdata_2019-02.parquet | 1,707,650 | 1,701,963 | 5,687 | 0.333% | 0.9 |
| fhv | fhv_tripdata_2019-03.parquet | 1,475,569 | 1,470,794 | 4,775 | 0.324% | 1.0 |
| fhv | fhv_tripdata_2019-04.parquet | 1,937,850 | 1,926,874 | 10,976 | 0.566% | 1.3 |
| fhv | fhv_tripdata_2019-05.parquet | 2,073,045 | 2,067,505 | 5,540 | 0.267% | 1.0 |
| fhv | fhv_tripdata_2019-06.parquet | 2,009,888 | 2,004,682 | 5,206 | 0.259% | 1.0 |
| fhv | fhv_tripdata_2019-07.parquet | 1,947,743 | 1,925,128 | 22,615 | 1.161% | 1.0 |
| fhv | fhv_tripdata_2019-08.parquet | 1,880,408 | 1,815,306 | 65,102 | 3.462% | 1.0 |
| fhv | fhv_tripdata_2019-09.parquet | 1,248,520 | 1,161,655 | 86,865 | 6.957% | 0.6 |
| fhv | fhv_tripdata_2019-10.parquet | 1,897,856 | 1,883,001 | 14,855 | 0.783% | 1.0 |
| fhv | fhv_tripdata_2019-11.parquet | 1,879,487 | 1,862,462 | 17,025 | 0.906% | 1.0 |
| fhv | fhv_tripdata_2019-12.parquet | 2,044,196 | 1,987,564 | 56,632 | 2.77% | 1.1 |
| fhv | fhv_tripdata_2020-01.parquet | 2,028,587 | 1,963,830 | 64,757 | 3.192% | 1.1 |
| fhv | fhv_tripdata_2020-02.parquet | 1,913,495 | 1,685,860 | 227,635 | 11.896% | 1.0 |
| fhv | fhv_tripdata_2020-03.parquet | 1,441,864 | 1,265,303 | 176,561 | 12.245% | 0.7 |
| fhv | fhv_tripdata_2020-04.parquet | 566,426 | 397,975 | 168,451 | 29.739% | 0.3 |
| fhv | fhv_tripdata_2020-05.parquet | 774,970 | 769,841 | 5,129 | 0.662% | 0.5 |
| fhv | fhv_tripdata_2020-06.parquet | 1,011,867 | 1,009,982 | 1,885 | 0.186% | 0.5 |
| fhv | fhv_tripdata_2020-07.parquet | 1,127,489 | 1,124,187 | 3,302 | 0.293% | 0.6 |
| fhv | fhv_tripdata_2020-08.parquet | 1,184,036 | 1,174,352 | 9,684 | 0.818% | 0.8 |
| fhv | fhv_tripdata_2020-09.parquet | 1,271,036 | 1,265,434 | 5,602 | 0.441% | 0.7 |
| fhv | fhv_tripdata_2020-10.parquet | 1,254,734 | 247,680 | 1,007,054 | 80.26% | 0.2 |
| fhv | fhv_tripdata_2020-11.parquet | 1,206,356 | 219,928 | 986,428 | 81.769% | 0.2 |
| fhv | fhv_tripdata_2020-12.parquet | 1,164,605 | 177,183 | 987,422 | 84.786% | 0.2 |
| fhv | fhv_tripdata_2021-01.parquet | 1,154,112 | 184,005 | 970,107 | 84.057% | 0.2 |
| fhv | fhv_tripdata_2021-02.parquet | 1,037,692 | 139,870 | 897,822 | 86.521% | 0.2 |
| fhv | fhv_tripdata_2021-03.parquet | 1,302,665 | 200,077 | 1,102,588 | 84.641% | 0.2 |
| fhv | fhv_tripdata_2021-04.parquet | 1,267,018 | 211,530 | 1,055,488 | 83.305% | 0.2 |
| fhv | fhv_tripdata_2021-05.parquet | 1,263,660 | 209,787 | 1,053,873 | 83.398% | 0.2 |
| fhv | fhv_tripdata_2021-06.parquet | 1,311,346 | 212,426 | 1,098,920 | 83.801% | 0.2 |
| fhv | fhv_tripdata_2021-07.parquet | 1,240,014 | 202,640 | 1,037,374 | 83.658% | 0.2 |
| fhv | fhv_tripdata_2021-08.parquet | 1,203,018 | 204,468 | 998,550 | 83.004% | 0.2 |
| fhv | fhv_tripdata_2021-09.parquet | 1,179,412 | 218,785 | 960,627 | 81.45% | 0.2 |
| fhv | fhv_tripdata_2021-10.parquet | 1,277,393 | 227,591 | 1,049,802 | 82.183% | 0.2 |
| fhv | fhv_tripdata_2021-11.parquet | 1,228,962 | 219,058 | 1,009,904 | 82.175% | 0.2 |
| fhv | fhv_tripdata_2021-12.parquet | 1,339,973 | 325,579 | 1,014,394 | 75.703% | 0.3 |
| fhv | fhv_tripdata_2022-01.parquet | 1,143,691 | 261,364 | 882,327 | 77.147% | 0.2 |
| fhv | fhv_tripdata_2022-02.parquet | 1,251,504 | 271,519 | 979,985 | 78.305% | 0.2 |
| fhv | fhv_tripdata_2022-03.parquet | 1,380,816 | 296,005 | 1,084,811 | 78.563% | 0.2 |
| fhv | fhv_tripdata_2022-04.parquet | 1,246,669 | 311,169 | 935,500 | 75.04% | 0.2 |
| fhv | fhv_tripdata_2022-05.parquet | 1,255,828 | 310,565 | 945,263 | 75.27% | 0.2 |
| fhv | fhv_tripdata_2022-06.parquet | 1,195,414 | 324,977 | 870,437 | 72.815% | 0.2 |
| fhv | fhv_tripdata_2022-07.parquet | 1,159,579 | 291,353 | 868,226 | 74.874% | 0.2 |
| fhv | fhv_tripdata_2022-08.parquet | 1,151,155 | 278,654 | 872,501 | 75.794% | 0.2 |
| fhv | fhv_tripdata_2022-09.parquet | 1,160,493 | 263,320 | 897,173 | 77.31% | 0.2 |
| fhv | fhv_tripdata_2022-10.parquet | 1,174,988 | 272,012 | 902,976 | 76.85% | 0.2 |
| fhv | fhv_tripdata_2022-11.parquet | 1,106,084 | 217,158 | 888,926 | 80.367% | 0.2 |
| fhv | fhv_tripdata_2022-12.parquet | 1,285,443 | 274,629 | 1,010,814 | 78.635% | 0.2 |
| fhv | fhv_tripdata_2023-01.parquet | 1,114,320 | 234,644 | 879,676 | 78.943% | 0.2 |
| fhv | fhv_tripdata_2023-02.parquet | 1,110,797 | 232,923 | 877,874 | 79.031% | 0.2 |
| fhv | fhv_tripdata_2023-03.parquet | 1,328,242 | 283,805 | 1,044,437 | 78.633% | 0.2 |
| fhv | fhv_tripdata_2023-04.parquet | 1,246,479 | 263,289 | 983,190 | 78.877% | 0.2 |
| fhv | fhv_tripdata_2023-05.parquet | 1,385,826 | 319,909 | 1,065,917 | 76.916% | 0.2 |
| fhv | fhv_tripdata_2023-06.parquet | 1,219,445 | 295,342 | 924,103 | 75.781% | 0.2 |
| fhv | fhv_tripdata_2023-07.parquet | 1,370,843 | 316,075 | 1,054,768 | 76.943% | 0.2 |
| fhv | fhv_tripdata_2023-08.parquet | 1,440,352 | 359,884 | 1,080,468 | 75.014% | 0.3 |
| fhv | fhv_tripdata_2023-09.parquet | 1,293,303 | 350,822 | 942,481 | 72.874% | 0.2 |
| fhv | fhv_tripdata_2023-10.parquet | 1,628,438 | 382,534 | 1,245,904 | 76.509% | 0.3 |
| fhv | fhv_tripdata_2023-11.parquet | 1,343,846 | 190,162 | 1,153,684 | 85.849% | 0.2 |
| fhv | fhv_tripdata_2023-12.parquet | 1,376,748 | 232,434 | 1,144,314 | 83.117% | 0.2 |
| fhv | fhv_tripdata_2024-01.parquet | 1,290,116 | 263,066 | 1,027,050 | 79.609% | 0.2 |
| fhv | fhv_tripdata_2024-02.parquet | 1,176,093 | 200,241 | 975,852 | 82.974% | 0.2 |
| fhv | fhv_tripdata_2024-03.parquet | 1,469,352 | 265,847 | 1,203,505 | 81.907% | 0.2 |
| fhv | fhv_tripdata_2024-04.parquet | 1,444,626 | 368,550 | 1,076,076 | 74.488% | 0.3 |
| fhv | fhv_tripdata_2024-05.parquet | 1,352,502 | 264,970 | 1,087,532 | 80.409% | 0.2 |
| fhv | fhv_tripdata_2024-06.parquet | 1,386,539 | 326,072 | 1,060,467 | 76.483% | 0.2 |
| fhv | fhv_tripdata_2024-07.parquet | 1,382,739 | 354,368 | 1,028,371 | 74.372% | 0.2 |
| fhv | fhv_tripdata_2024-08.parquet | 1,484,471 | 233,586 | 1,250,885 | 84.265% | 0.2 |
| fhv | fhv_tripdata_2024-09.parquet | 1,718,375 | 386,806 | 1,331,569 | 77.49% | 0.3 |
| fhv | fhv_tripdata_2024-10.parquet | 1,421,231 | 248,855 | 1,172,376 | 82.49% | 0.2 |
| fhv | fhv_tripdata_2024-11.parquet | 1,591,082 | 323,696 | 1,267,386 | 79.656% | 0.2 |
| fhv | fhv_tripdata_2024-12.parquet | 1,913,200 | 238,503 | 1,674,697 | 87.534% | 0.2 |
| fhv | fhv_tripdata_2025-01.parquet | 1,898,108 | 314,803 | 1,583,305 | 83.415% | 0.2 |
| fhv | fhv_tripdata_2025-02.parquet | 1,578,722 | 302,458 | 1,276,264 | 80.842% | 0.2 |
| fhv | fhv_tripdata_2025-03.parquet | 2,182,992 | 261,698 | 1,921,294 | 88.012% | 0.2 |
| fhv | fhv_tripdata_2025-04.parquet | 1,699,478 | 382,636 | 1,316,842 | 77.485% | 0.3 |
| fhv | fhv_tripdata_2025-05.parquet | 2,210,721 | 452,037 | 1,758,684 | 79.553% | 0.3 |
| fhv | fhv_tripdata_2025-06.parquet | 2,231,731 | 434,438 | 1,797,293 | 80.534% | 0.3 |
| fhv | fhv_tripdata_2025-07.parquet | 2,187,536 | 385,873 | 1,801,663 | 82.36% | 0.3 |
| fhv | fhv_tripdata_2025-08.parquet | 2,256,854 | 359,138 | 1,897,716 | 84.087% | 0.3 |
| fhv | fhv_tripdata_2025-09.parquet | 2,149,292 | 393,697 | 1,755,595 | 81.682% | 0.3 |
| fhv | fhv_tripdata_2025-10.parquet | 2,446,615 | 417,039 | 2,029,576 | 82.954% | 0.3 |
| fhv | fhv_tripdata_2025-11.parquet | 2,278,604 | 383,289 | 1,895,315 | 83.179% | 0.3 |
| fhv | fhv_tripdata_2025-12.parquet | 1,926,891 | 367,345 | 1,559,546 | 80.936% | 0.3 |
| fhv | fhv_tripdata_2026-01.parquet | 1,941,722 | 295,147 | 1,646,575 | 84.8% | 0.3 |
| fhv | fhv_tripdata_2026-02.parquet | 1,948,529 | 155,437 | 1,793,092 | 92.023% | 0.2 |
| fhv | fhv_tripdata_2026-03.parquet | 2,360,690 | 339,313 | 2,021,377 | 85.627% | 0.3 |
| fhv | fhv_tripdata_2026-04.parquet | 2,125,630 | 342,097 | 1,783,533 | 83.906% | 0.3 |
| fhvhv | fhvhv_tripdata_2019-02.parquet | 20,159,102 | 20,072,696 | 86,406 | 0.429% | 53.1 |
| fhvhv | fhvhv_tripdata_2019-03.parquet | 23,864,598 | 23,779,538 | 85,060 | 0.356% | 60.7 |
| fhvhv | fhvhv_tripdata_2019-04.parquet | 21,734,822 | 21,648,526 | 86,296 | 0.397% | 55.4 |
| fhvhv | fhvhv_tripdata_2019-05.parquet | 22,329,247 | 22,261,629 | 67,618 | 0.303% | 54.7 |
| fhvhv | fhvhv_tripdata_2019-06.parquet | 21,001,990 | 20,946,554 | 55,436 | 0.264% | 54.6 |
| fhvhv | fhvhv_tripdata_2019-07.parquet | 20,303,312 | 20,218,414 | 84,898 | 0.418% | 50.5 |
| fhvhv | fhvhv_tripdata_2019-08.parquet | 20,126,113 | 20,079,920 | 46,193 | 0.23% | 51.5 |
| fhvhv | fhvhv_tripdata_2019-09.parquet | 20,069,321 | 19,997,986 | 71,335 | 0.355% | 49.5 |
| fhvhv | fhvhv_tripdata_2019-10.parquet | 21,162,290 | 21,099,724 | 62,566 | 0.296% | 54.7 |
| fhvhv | fhvhv_tripdata_2019-11.parquet | 21,635,568 | 21,567,802 | 67,766 | 0.313% | 55.0 |
| fhvhv | fhvhv_tripdata_2019-12.parquet | 22,243,901 | 21,802,884 | 441,017 | 1.983% | 55.1 |
| fhvhv | fhvhv_tripdata_2020-01.parquet | 20,569,368 | 20,405,910 | 163,458 | 0.795% | 50.4 |
| fhvhv | fhvhv_tripdata_2020-02.parquet | 21,725,100 | 21,682,560 | 42,540 | 0.196% | 52.0 |
| fhvhv | fhvhv_tripdata_2020-03.parquet | 13,392,928 | 13,368,501 | 24,427 | 0.182% | 31.8 |
| fhvhv | fhvhv_tripdata_2020-04.parquet | 4,312,909 | 4,305,586 | 7,323 | 0.17% | 7.4 |
| fhvhv | fhvhv_tripdata_2020-05.parquet | 6,089,999 | 6,078,813 | 11,186 | 0.184% | 14.1 |
| fhvhv | fhvhv_tripdata_2020-06.parquet | 7,555,193 | 7,542,845 | 12,348 | 0.163% | 16.3 |
| fhvhv | fhvhv_tripdata_2020-07.parquet | 9,958,454 | 9,946,799 | 11,655 | 0.117% | 22.9 |
| fhvhv | fhvhv_tripdata_2020-08.parquet | 11,096,852 | 11,085,001 | 11,851 | 0.107% | 25.3 |
| fhvhv | fhvhv_tripdata_2020-09.parquet | 12,106,669 | 12,093,167 | 13,502 | 0.112% | 28.9 |
| fhvhv | fhvhv_tripdata_2020-10.parquet | 13,268,411 | 13,253,642 | 14,769 | 0.111% | 31.1 |
| fhvhv | fhvhv_tripdata_2020-11.parquet | 11,596,865 | 11,578,091 | 18,774 | 0.162% | 27.7 |
| fhvhv | fhvhv_tripdata_2020-12.parquet | 11,637,123 | 11,623,621 | 13,502 | 0.116% | 27.3 |
| fhvhv | fhvhv_tripdata_2021-01.parquet | 11,908,468 | 11,894,758 | 13,710 | 0.115% | 28.9 |
| fhvhv | fhvhv_tripdata_2021-02.parquet | 11,613,942 | 11,598,991 | 14,951 | 0.129% | 27.4 |
| fhvhv | fhvhv_tripdata_2021-03.parquet | 14,227,393 | 14,210,627 | 16,766 | 0.118% | 34.8 |
| fhvhv | fhvhv_tripdata_2021-04.parquet | 14,111,371 | 14,089,746 | 21,625 | 0.153% | 34.7 |
| fhvhv | fhvhv_tripdata_2021-05.parquet | 14,719,171 | 14,693,999 | 25,172 | 0.171% | 36.8 |
| fhvhv | fhvhv_tripdata_2021-06.parquet | 14,961,892 | 14,925,729 | 36,163 | 0.242% | 36.9 |
| fhvhv | fhvhv_tripdata_2021-07.parquet | 15,027,174 | 15,001,447 | 25,727 | 0.171% | 38.8 |
| fhvhv | fhvhv_tripdata_2021-08.parquet | 14,499,696 | 14,475,676 | 24,020 | 0.166% | 38.0 |
| fhvhv | fhvhv_tripdata_2021-09.parquet | 14,886,055 | 14,860,493 | 25,562 | 0.172% | 38.5 |
| fhvhv | fhvhv_tripdata_2021-10.parquet | 16,545,356 | 16,518,945 | 26,411 | 0.16% | 40.9 |
| fhvhv | fhvhv_tripdata_2021-11.parquet | 16,041,639 | 16,005,675 | 35,964 | 0.224% | 40.7 |
| fhvhv | fhvhv_tripdata_2021-12.parquet | 16,054,495 | 16,027,667 | 26,828 | 0.167% | 39.2 |
| fhvhv | fhvhv_tripdata_2022-01.parquet | 14,751,591 | 14,728,593 | 22,998 | 0.156% | 37.0 |
| fhvhv | fhvhv_tripdata_2022-02.parquet | 16,019,283 | 15,996,874 | 22,409 | 0.14% | 40.3 |
| fhvhv | fhvhv_tripdata_2022-03.parquet | 18,453,548 | 18,429,202 | 24,346 | 0.132% | 47.1 |
| fhvhv | fhvhv_tripdata_2022-04.parquet | 17,752,561 | 17,728,112 | 24,449 | 0.138% | 44.8 |
| fhvhv | fhvhv_tripdata_2022-05.parquet | 18,157,335 | 18,127,544 | 29,791 | 0.164% | 46.1 |
| fhvhv | fhvhv_tripdata_2022-06.parquet | 17,780,075 | 17,753,011 | 27,064 | 0.152% | 45.1 |
| fhvhv | fhvhv_tripdata_2022-07.parquet | 17,464,619 | 17,440,545 | 24,074 | 0.138% | 45.0 |
| fhvhv | fhvhv_tripdata_2022-08.parquet | 17,185,687 | 17,158,618 | 27,069 | 0.158% | 43.6 |
| fhvhv | fhvhv_tripdata_2022-09.parquet | 17,793,551 | 17,766,557 | 26,994 | 0.152% | 46.3 |
| fhvhv | fhvhv_tripdata_2022-10.parquet | 19,306,090 | 19,275,439 | 30,651 | 0.159% | 50.3 |
| fhvhv | fhvhv_tripdata_2022-11.parquet | 18,085,896 | 18,053,682 | 32,214 | 0.178% | 48.8 |
| fhvhv | fhvhv_tripdata_2022-12.parquet | 19,665,847 | 19,642,622 | 23,225 | 0.118% | 49.7 |
| fhvhv | fhvhv_tripdata_2023-01.parquet | 18,479,031 | 18,460,108 | 18,923 | 0.102% | 49.0 |
| fhvhv | fhvhv_tripdata_2023-02.parquet | 17,960,971 | 17,942,833 | 18,138 | 0.101% | 47.3 |
| fhvhv | fhvhv_tripdata_2023-03.parquet | 20,413,539 | 20,394,371 | 19,168 | 0.094% | 53.3 |
| fhvhv | fhvhv_tripdata_2023-04.parquet | 19,144,903 | 19,127,930 | 16,973 | 0.089% | 48.8 |
| fhvhv | fhvhv_tripdata_2023-05.parquet | 19,847,676 | 19,835,483 | 12,193 | 0.061% | 51.5 |
| fhvhv | fhvhv_tripdata_2023-06.parquet | 19,366,619 | 19,354,335 | 12,284 | 0.063% | 49.6 |
| fhvhv | fhvhv_tripdata_2023-07.parquet | 19,132,131 | 19,124,910 | 7,221 | 0.038% | 49.7 |
| fhvhv | fhvhv_tripdata_2023-08.parquet | 18,322,150 | 18,313,728 | 8,422 | 0.046% | 46.8 |
| fhvhv | fhvhv_tripdata_2023-09.parquet | 19,851,123 | 19,842,171 | 8,952 | 0.045% | 51.7 |
| fhvhv | fhvhv_tripdata_2023-10.parquet | 20,186,330 | 20,176,585 | 9,745 | 0.048% | 52.5 |
| fhvhv | fhvhv_tripdata_2023-11.parquet | 19,269,250 | 19,253,806 | 15,444 | 0.08% | 50.6 |
| fhvhv | fhvhv_tripdata_2023-12.parquet | 20,516,297 | 20,509,900 | 6,397 | 0.031% | 53.2 |
| fhvhv | fhvhv_tripdata_2024-01.parquet | 19,663,930 | 19,658,222 | 5,708 | 0.029% | 51.5 |
| fhvhv | fhvhv_tripdata_2024-02.parquet | 19,359,148 | 19,345,793 | 13,355 | 0.069% | 51.2 |
| fhvhv | fhvhv_tripdata_2024-03.parquet | 21,280,788 | 21,274,857 | 5,931 | 0.028% | 56.5 |
| fhvhv | fhvhv_tripdata_2024-04.parquet | 19,733,038 | 19,727,911 | 5,127 | 0.026% | 51.6 |
| fhvhv | fhvhv_tripdata_2024-05.parquet | 20,704,538 | 20,699,073 | 5,465 | 0.026% | 54.3 |
| fhvhv | fhvhv_tripdata_2024-06.parquet | 20,123,226 | 20,117,482 | 5,744 | 0.029% | 52.4 |
| fhvhv | fhvhv_tripdata_2024-07.parquet | 19,182,934 | 19,177,088 | 5,846 | 0.03% | 50.9 |
| fhvhv | fhvhv_tripdata_2024-08.parquet | 19,128,392 | 19,122,271 | 6,121 | 0.032% | 49.5 |
| fhvhv | fhvhv_tripdata_2024-09.parquet | 19,209,788 | 19,204,228 | 5,560 | 0.029% | 51.1 |
| fhvhv | fhvhv_tripdata_2024-10.parquet | 20,028,282 | 20,021,476 | 6,806 | 0.034% | 53.3 |
| fhvhv | fhvhv_tripdata_2024-11.parquet | 19,987,533 | 19,970,666 | 16,867 | 0.084% | 51.9 |
| fhvhv | fhvhv_tripdata_2024-12.parquet | 21,068,851 | 21,060,480 | 8,371 | 0.04% | 55.1 |
| fhvhv | fhvhv_tripdata_2025-01.parquet | 20,405,666 | 20,398,660 | 7,006 | 0.034% | 54.5 |
| fhvhv | fhvhv_tripdata_2025-02.parquet | 19,339,461 | 19,334,783 | 4,678 | 0.024% | 50.7 |
| fhvhv | fhvhv_tripdata_2025-03.parquet | 20,536,879 | 20,532,548 | 4,331 | 0.021% | 53.3 |
| fhvhv | fhvhv_tripdata_2025-04.parquet | 19,753,983 | 19,749,524 | 4,459 | 0.023% | 51.5 |
| fhvhv | fhvhv_tripdata_2025-05.parquet | 21,091,193 | 21,085,228 | 5,965 | 0.028% | 55.4 |
| fhvhv | fhvhv_tripdata_2025-06.parquet | 19,868,009 | 19,862,178 | 5,831 | 0.029% | 51.4 |
| fhvhv | fhvhv_tripdata_2025-07.parquet | 19,653,012 | 19,647,109 | 5,903 | 0.03% | 50.5 |
| fhvhv | fhvhv_tripdata_2025-08.parquet | 19,271,461 | 19,265,415 | 6,046 | 0.031% | 50.2 |
| fhvhv | fhvhv_tripdata_2025-09.parquet | 19,434,641 | 19,428,964 | 5,677 | 0.029% | 50.0 |
| fhvhv | fhvhv_tripdata_2025-10.parquet | 21,308,701 | 21,301,952 | 6,749 | 0.032% | 57.1 |
| fhvhv | fhvhv_tripdata_2025-11.parquet | 20,818,240 | 20,799,704 | 18,536 | 0.089% | 56.8 |
| fhvhv | fhvhv_tripdata_2025-12.parquet | 22,108,438 | 22,100,992 | 7,446 | 0.034% | 61.2 |
| fhvhv | fhvhv_tripdata_2026-01.parquet | 20,940,373 | 20,905,776 | 34,597 | 0.165% | 56.0 |
| fhvhv | fhvhv_tripdata_2026-02.parquet | 19,875,686 | 19,867,856 | 7,830 | 0.039% | 53.0 |
| fhvhv | fhvhv_tripdata_2026-03.parquet | 22,058,358 | 22,048,141 | 10,217 | 0.046% | 59.3 |
| fhvhv | fhvhv_tripdata_2026-04.parquet | 20,995,953 | 20,986,950 | 9,003 | 0.043% | 60.8 |
| fhvhv | fhvhv_tripdata_2026-05.parquet | 22,125,744 | 22,112,684 | 13,060 | 0.059% | 70.9 |
| fhvhv | fhvhv_tripdata_2026-06.parquet | 20,775,868 | 20,760,988 | 14,880 | 0.072% | 69.6 |
| green | green_tripdata_2019-01.parquet | 672,105 | 659,174 | 12,931 | 1.924% | 0.9 |
| green | green_tripdata_2019-02.parquet | 615,594 | 603,505 | 12,089 | 1.964% | 0.9 |
| green | green_tripdata_2019-03.parquet | 643,063 | 630,598 | 12,465 | 1.938% | 0.8 |
| green | green_tripdata_2019-04.parquet | 567,852 | 556,957 | 10,895 | 1.919% | 0.7 |
| green | green_tripdata_2019-05.parquet | 545,452 | 534,906 | 10,546 | 1.933% | 0.6 |
| green | green_tripdata_2019-06.parquet | 506,238 | 495,810 | 10,428 | 2.06% | 0.5 |
| green | green_tripdata_2019-07.parquet | 470,743 | 457,783 | 12,960 | 2.753% | 0.5 |
| green | green_tripdata_2019-08.parquet | 449,695 | 434,524 | 15,171 | 3.374% | 0.5 |
| green | green_tripdata_2019-09.parquet | 449,063 | 434,522 | 14,541 | 3.238% | 0.5 |
| green | green_tripdata_2019-10.parquet | 476,386 | 462,144 | 14,242 | 2.99% | 0.5 |
| green | green_tripdata_2019-11.parquet | 449,500 | 419,484 | 30,016 | 6.678% | 0.5 |
| green | green_tripdata_2019-12.parquet | 455,294 | 437,707 | 17,587 | 3.863% | 0.9 |
| green | green_tripdata_2020-01.parquet | 447,770 | 429,588 | 18,182 | 4.061% | 0.8 |
| green | green_tripdata_2020-02.parquet | 398,632 | 384,661 | 13,971 | 3.505% | 0.4 |
| green | green_tripdata_2020-03.parquet | 223,496 | 215,048 | 8,448 | 3.78% | 0.2 |
| green | green_tripdata_2020-04.parquet | 35,644 | 33,775 | 1,869 | 5.244% | 0.0 |
| green | green_tripdata_2020-05.parquet | 57,361 | 54,887 | 2,474 | 4.313% | 0.1 |
| green | green_tripdata_2020-06.parquet | 63,110 | 60,064 | 3,046 | 4.826% | 0.1 |
| green | green_tripdata_2020-07.parquet | 72,258 | 68,262 | 3,996 | 5.53% | 0.1 |
| green | green_tripdata_2020-08.parquet | 81,063 | 76,904 | 4,159 | 5.131% | 0.1 |
| green | green_tripdata_2020-09.parquet | 87,987 | 84,148 | 3,839 | 4.363% | 0.1 |
| green | green_tripdata_2020-10.parquet | 95,120 | 91,313 | 3,807 | 4.002% | 0.1 |
| green | green_tripdata_2020-11.parquet | 88,605 | 85,493 | 3,112 | 3.512% | 0.1 |
| green | green_tripdata_2020-12.parquet | 83,130 | 80,787 | 2,343 | 2.818% | 0.1 |
| green | green_tripdata_2021-01.parquet | 76,518 | 73,877 | 2,641 | 3.451% | 0.1 |
| green | green_tripdata_2021-02.parquet | 64,572 | 62,435 | 2,137 | 3.309% | 0.1 |
| green | green_tripdata_2021-03.parquet | 83,827 | 80,955 | 2,872 | 3.426% | 0.1 |
| green | green_tripdata_2021-04.parquet | 86,941 | 83,310 | 3,631 | 4.176% | 0.1 |
| green | green_tripdata_2021-05.parquet | 88,180 | 84,015 | 4,165 | 4.723% | 0.1 |
| green | green_tripdata_2021-06.parquet | 86,737 | 82,989 | 3,748 | 4.321% | 0.1 |
| green | green_tripdata_2021-07.parquet | 83,691 | 80,148 | 3,543 | 4.233% | 0.1 |
| green | green_tripdata_2021-08.parquet | 83,499 | 80,455 | 3,044 | 3.646% | 0.1 |
| green | green_tripdata_2021-09.parquet | 95,709 | 91,915 | 3,794 | 3.964% | 0.1 |
| green | green_tripdata_2021-10.parquet | 110,891 | 106,406 | 4,485 | 4.045% | 0.1 |
| green | green_tripdata_2021-11.parquet | 108,229 | 104,280 | 3,949 | 3.649% | 0.1 |
| green | green_tripdata_2021-12.parquet | 99,961 | 95,881 | 4,080 | 4.082% | 0.1 |
| green | green_tripdata_2022-01.parquet | 62,495 | 58,764 | 3,731 | 5.97% | 0.1 |
| green | green_tripdata_2022-02.parquet | 69,399 | 65,522 | 3,877 | 5.587% | 0.1 |
| green | green_tripdata_2022-03.parquet | 78,537 | 74,000 | 4,537 | 5.777% | 0.1 |
| green | green_tripdata_2022-04.parquet | 76,136 | 72,083 | 4,053 | 5.323% | 0.1 |
| green | green_tripdata_2022-05.parquet | 76,891 | 72,268 | 4,623 | 6.012% | 0.1 |
| green | green_tripdata_2022-06.parquet | 73,718 | 68,799 | 4,919 | 6.673% | 0.1 |
| green | green_tripdata_2022-07.parquet | 64,192 | 59,660 | 4,532 | 7.06% | 0.1 |
| green | green_tripdata_2022-08.parquet | 65,929 | 61,207 | 4,722 | 7.162% | 0.1 |
| green | green_tripdata_2022-09.parquet | 69,031 | 64,622 | 4,409 | 6.387% | 0.1 |
| green | green_tripdata_2022-10.parquet | 69,322 | 65,285 | 4,037 | 5.824% | 0.1 |
| green | green_tripdata_2022-11.parquet | 62,313 | 58,892 | 3,421 | 5.49% | 0.1 |
| green | green_tripdata_2022-12.parquet | 72,439 | 68,368 | 4,071 | 5.62% | 0.1 |
| green | green_tripdata_2023-01.parquet | 68,211 | 64,746 | 3,465 | 5.08% | 0.1 |
| green | green_tripdata_2023-02.parquet | 64,809 | 61,813 | 2,996 | 4.623% | 0.1 |
| green | green_tripdata_2023-03.parquet | 72,044 | 68,521 | 3,523 | 4.89% | 0.1 |
| green | green_tripdata_2023-04.parquet | 65,392 | 62,181 | 3,211 | 4.91% | 0.1 |
| green | green_tripdata_2023-05.parquet | 69,174 | 65,641 | 3,533 | 5.107% | 0.1 |
| green | green_tripdata_2023-06.parquet | 65,550 | 62,078 | 3,472 | 5.297% | 0.1 |
| green | green_tripdata_2023-07.parquet | 61,343 | 57,881 | 3,462 | 5.644% | 0.1 |
| green | green_tripdata_2023-08.parquet | 60,649 | 57,229 | 3,420 | 5.639% | 0.1 |
| green | green_tripdata_2023-09.parquet | 65,471 | 62,174 | 3,297 | 5.036% | 0.1 |
| green | green_tripdata_2023-10.parquet | 66,177 | 62,408 | 3,769 | 5.695% | 0.1 |
| green | green_tripdata_2023-11.parquet | 64,025 | 60,565 | 3,460 | 5.404% | 0.1 |
| green | green_tripdata_2023-12.parquet | 64,215 | 60,809 | 3,406 | 5.304% | 0.1 |
| green | green_tripdata_2024-01.parquet | 56,551 | 53,558 | 2,993 | 5.293% | 0.1 |
| green | green_tripdata_2024-02.parquet | 53,577 | 50,619 | 2,958 | 5.521% | 0.1 |
| green | green_tripdata_2024-03.parquet | 57,457 | 54,307 | 3,150 | 5.482% | 0.1 |
| green | green_tripdata_2024-04.parquet | 56,471 | 53,141 | 3,330 | 5.897% | 0.1 |
| green | green_tripdata_2024-05.parquet | 61,003 | 57,745 | 3,258 | 5.341% | 0.1 |
| green | green_tripdata_2024-06.parquet | 54,748 | 51,904 | 2,844 | 5.195% | 0.1 |
| green | green_tripdata_2024-07.parquet | 51,837 | 48,729 | 3,108 | 5.996% | 0.1 |
| green | green_tripdata_2024-08.parquet | 51,771 | 48,954 | 2,817 | 5.441% | 0.1 |
| green | green_tripdata_2024-09.parquet | 54,440 | 51,554 | 2,886 | 5.301% | 0.1 |
| green | green_tripdata_2024-10.parquet | 56,147 | 53,441 | 2,706 | 4.819% | 0.1 |
| green | green_tripdata_2024-11.parquet | 52,222 | 49,376 | 2,846 | 5.45% | 0.1 |
| green | green_tripdata_2024-12.parquet | 53,994 | 50,883 | 3,111 | 5.762% | 0.1 |
| green | green_tripdata_2025-01.parquet | 48,326 | 45,554 | 2,772 | 5.736% | 0.1 |
| green | green_tripdata_2025-02.parquet | 46,621 | 43,914 | 2,707 | 5.806% | 0.1 |
| green | green_tripdata_2025-03.parquet | 51,539 | 48,342 | 3,197 | 6.203% | 0.1 |
| green | green_tripdata_2025-04.parquet | 52,132 | 48,818 | 3,314 | 6.357% | 0.1 |
| green | green_tripdata_2025-05.parquet | 55,399 | 52,223 | 3,176 | 5.733% | 0.1 |
| green | green_tripdata_2025-06.parquet | 49,390 | 47,207 | 2,183 | 4.42% | 0.1 |
| green | green_tripdata_2025-07.parquet | 48,205 | 46,617 | 1,588 | 3.294% | 0.1 |
| green | green_tripdata_2025-08.parquet | 46,306 | 44,754 | 1,552 | 3.352% | 0.1 |
| green | green_tripdata_2025-09.parquet | 48,893 | 47,375 | 1,518 | 3.105% | 0.1 |
| green | green_tripdata_2025-10.parquet | 49,416 | 47,734 | 1,682 | 3.404% | 0.1 |
| green | green_tripdata_2025-11.parquet | 46,912 | 45,325 | 1,587 | 3.383% | 0.1 |
| green | green_tripdata_2025-12.parquet | 48,236 | 46,559 | 1,677 | 3.477% | 0.1 |
| green | green_tripdata_2026-01.parquet | 40,272 | 38,909 | 1,363 | 3.384% | 0.1 |
| green | green_tripdata_2026-02.parquet | 37,373 | 35,919 | 1,454 | 3.891% | 0.0 |
| green | green_tripdata_2026-03.parquet | 44,208 | 42,695 | 1,513 | 3.422% | 0.1 |
| green | green_tripdata_2026-04.parquet | 44,238 | 42,550 | 1,688 | 3.816% | 0.1 |
| green | green_tripdata_2026-05.parquet | 44,921 | 43,294 | 1,627 | 3.622% | 0.1 |
| green | green_tripdata_2026-06.parquet | 39,156 | 37,595 | 1,561 | 3.987% | 0.1 |
| yellow | yellow_tripdata_2019-01.parquet | 7,696,617 | 7,634,997 | 61,620 | 0.801% | 12.7 |
| yellow | yellow_tripdata_2019-02.parquet | 7,049,370 | 6,991,060 | 58,310 | 0.827% | 12.0 |
| yellow | yellow_tripdata_2019-03.parquet | 7,866,620 | 7,802,220 | 64,400 | 0.819% | 13.2 |
| yellow | yellow_tripdata_2019-04.parquet | 7,475,949 | 7,414,520 | 61,429 | 0.822% | 12.5 |
| yellow | yellow_tripdata_2019-05.parquet | 7,598,445 | 7,530,309 | 68,136 | 0.897% | 12.0 |
| yellow | yellow_tripdata_2019-06.parquet | 6,971,560 | 6,896,377 | 75,183 | 1.078% | 11.1 |
| yellow | yellow_tripdata_2019-07.parquet | 6,310,419 | 6,231,233 | 79,186 | 1.255% | 10.3 |
| yellow | yellow_tripdata_2019-08.parquet | 6,073,357 | 5,991,136 | 82,221 | 1.354% | 10.0 |
| yellow | yellow_tripdata_2019-09.parquet | 6,567,788 | 6,482,826 | 84,962 | 1.294% | 10.5 |
| yellow | yellow_tripdata_2019-10.parquet | 7,213,891 | 7,127,937 | 85,954 | 1.192% | 11.5 |
| yellow | yellow_tripdata_2019-11.parquet | 6,878,111 | 6,787,239 | 90,872 | 1.321% | 11.1 |
| yellow | yellow_tripdata_2019-12.parquet | 6,896,317 | 6,804,838 | 91,479 | 1.326% | 10.9 |
| yellow | yellow_tripdata_2020-01.parquet | 6,405,008 | 6,305,278 | 99,730 | 1.557% | 10.3 |
| yellow | yellow_tripdata_2020-02.parquet | 6,299,367 | 6,220,880 | 78,487 | 1.246% | 10.2 |
| yellow | yellow_tripdata_2020-03.parquet | 3,007,687 | 2,966,141 | 41,546 | 1.381% | 4.3 |
| yellow | yellow_tripdata_2020-04.parquet | 238,073 | 230,655 | 7,418 | 3.116% | 0.4 |
| yellow | yellow_tripdata_2020-05.parquet | 348,415 | 336,758 | 11,657 | 3.346% | 0.5 |
| yellow | yellow_tripdata_2020-06.parquet | 549,797 | 530,047 | 19,750 | 3.592% | 0.7 |
| yellow | yellow_tripdata_2020-07.parquet | 800,412 | 772,134 | 28,278 | 3.533% | 1.1 |
| yellow | yellow_tripdata_2020-08.parquet | 1,007,286 | 975,045 | 32,241 | 3.201% | 1.4 |
| yellow | yellow_tripdata_2020-09.parquet | 1,341,017 | 1,309,260 | 31,757 | 2.368% | 1.9 |
| yellow | yellow_tripdata_2020-10.parquet | 1,681,132 | 1,644,579 | 36,553 | 2.174% | 2.4 |
| yellow | yellow_tripdata_2020-11.parquet | 1,509,000 | 1,477,922 | 31,078 | 2.06% | 2.1 |
| yellow | yellow_tripdata_2020-12.parquet | 1,461,898 | 1,431,830 | 30,068 | 2.057% | 2.0 |
| yellow | yellow_tripdata_2021-01.parquet | 1,369,769 | 1,337,841 | 31,928 | 2.331% | 1.8 |
| yellow | yellow_tripdata_2021-02.parquet | 1,371,709 | 1,340,129 | 31,580 | 2.302% | 1.9 |
| yellow | yellow_tripdata_2021-03.parquet | 1,925,152 | 1,885,854 | 39,298 | 2.041% | 2.8 |
| yellow | yellow_tripdata_2021-04.parquet | 2,171,187 | 2,127,719 | 43,468 | 2.002% | 3.0 |
| yellow | yellow_tripdata_2021-05.parquet | 2,507,109 | 2,461,454 | 45,655 | 1.821% | 3.5 |
| yellow | yellow_tripdata_2021-06.parquet | 2,834,264 | 2,786,685 | 47,579 | 1.679% | 3.9 |
| yellow | yellow_tripdata_2021-07.parquet | 2,821,746 | 2,770,652 | 51,094 | 1.811% | 4.0 |
| yellow | yellow_tripdata_2021-08.parquet | 2,788,757 | 2,737,439 | 51,318 | 1.84% | 3.9 |
| yellow | yellow_tripdata_2021-09.parquet | 2,963,793 | 2,894,569 | 69,224 | 2.336% | 4.2 |
| yellow | yellow_tripdata_2021-10.parquet | 3,463,504 | 3,406,585 | 56,919 | 1.643% | 5.0 |
| yellow | yellow_tripdata_2021-11.parquet | 3,472,949 | 3,422,874 | 50,075 | 1.442% | 4.9 |
| yellow | yellow_tripdata_2021-12.parquet | 3,214,369 | 3,161,894 | 52,475 | 1.633% | 4.0 |
| yellow | yellow_tripdata_2022-01.parquet | 2,463,931 | 2,421,765 | 42,166 | 1.711% | 2.8 |
| yellow | yellow_tripdata_2022-02.parquet | 2,979,431 | 2,931,648 | 47,783 | 1.604% | 3.5 |
| yellow | yellow_tripdata_2022-03.parquet | 3,627,882 | 3,567,153 | 60,729 | 1.674% | 4.1 |
| yellow | yellow_tripdata_2022-04.parquet | 3,599,920 | 3,540,394 | 59,526 | 1.654% | 4.4 |
| yellow | yellow_tripdata_2022-05.parquet | 3,588,295 | 3,522,732 | 65,563 | 1.827% | 4.5 |
| yellow | yellow_tripdata_2022-06.parquet | 3,558,124 | 3,485,075 | 73,049 | 2.053% | 4.7 |
| yellow | yellow_tripdata_2022-07.parquet | 3,174,394 | 3,108,822 | 65,572 | 2.066% | 4.1 |
| yellow | yellow_tripdata_2022-08.parquet | 3,152,677 | 3,083,220 | 69,457 | 2.203% | 3.9 |
| yellow | yellow_tripdata_2022-09.parquet | 3,183,767 | 3,113,232 | 70,535 | 2.215% | 3.8 |
| yellow | yellow_tripdata_2022-10.parquet | 3,675,411 | 3,589,636 | 85,775 | 2.334% | 4.9 |
| yellow | yellow_tripdata_2022-11.parquet | 3,252,717 | 3,169,870 | 82,847 | 2.547% | 4.7 |
| yellow | yellow_tripdata_2022-12.parquet | 3,399,549 | 3,312,979 | 86,570 | 2.547% | 5.2 |
| yellow | yellow_tripdata_2023-01.parquet | 3,066,766 | 2,998,677 | 68,089 | 2.22% | 4.6 |
| yellow | yellow_tripdata_2023-02.parquet | 2,913,955 | 2,850,646 | 63,309 | 2.173% | 4.0 |
| yellow | yellow_tripdata_2023-03.parquet | 3,403,766 | 3,328,642 | 75,124 | 2.207% | 4.9 |
| yellow | yellow_tripdata_2023-04.parquet | 3,288,250 | 3,221,023 | 67,227 | 2.044% | 4.7 |
| yellow | yellow_tripdata_2023-05.parquet | 3,513,649 | 3,438,068 | 75,581 | 2.151% | 5.0 |
| yellow | yellow_tripdata_2023-06.parquet | 3,307,234 | 3,231,374 | 75,860 | 2.294% | 4.5 |
| yellow | yellow_tripdata_2023-07.parquet | 2,907,108 | 2,829,042 | 78,066 | 2.685% | 4.0 |
| yellow | yellow_tripdata_2023-08.parquet | 2,824,209 | 2,738,128 | 86,081 | 3.048% | 3.9 |
| yellow | yellow_tripdata_2023-09.parquet | 2,846,722 | 2,721,270 | 125,452 | 4.407% | 3.8 |
| yellow | yellow_tripdata_2023-10.parquet | 3,522,285 | 3,366,868 | 155,417 | 4.412% | 4.1 |
| yellow | yellow_tripdata_2023-11.parquet | 3,339,715 | 3,202,955 | 136,760 | 4.095% | 3.8 |
| yellow | yellow_tripdata_2023-12.parquet | 3,376,567 | 3,264,154 | 112,413 | 3.329% | 3.9 |
| yellow | yellow_tripdata_2024-01.parquet | 2,964,624 | 2,869,987 | 94,637 | 3.192% | 3.5 |
| yellow | yellow_tripdata_2024-02.parquet | 3,007,526 | 2,901,799 | 105,727 | 3.515% | 3.9 |
| yellow | yellow_tripdata_2024-03.parquet | 3,582,628 | 3,440,569 | 142,059 | 3.965% | 4.6 |
| yellow | yellow_tripdata_2024-04.parquet | 3,514,289 | 3,414,782 | 99,507 | 2.831% | 4.4 |
| yellow | yellow_tripdata_2024-05.parquet | 3,723,833 | 3,618,280 | 105,553 | 2.835% | 5.0 |
| yellow | yellow_tripdata_2024-06.parquet | 3,539,193 | 3,428,784 | 110,409 | 3.12% | 4.7 |
| yellow | yellow_tripdata_2024-07.parquet | 3,076,903 | 2,974,329 | 102,574 | 3.334% | 4.1 |
| yellow | yellow_tripdata_2024-08.parquet | 2,979,183 | 2,867,740 | 111,443 | 3.741% | 3.9 |
| yellow | yellow_tripdata_2024-09.parquet | 3,633,030 | 3,484,460 | 148,570 | 4.089% | 4.6 |
| yellow | yellow_tripdata_2024-10.parquet | 3,833,771 | 3,682,412 | 151,359 | 3.948% | 4.8 |
| yellow | yellow_tripdata_2024-11.parquet | 3,646,369 | 3,510,514 | 135,855 | 3.726% | 4.7 |
| yellow | yellow_tripdata_2024-12.parquet | 3,668,371 | 3,519,593 | 148,778 | 4.056% | 4.9 |
| yellow | yellow_tripdata_2025-01.parquet | 3,475,226 | 3,253,005 | 222,221 | 6.394% | 4.7 |
| yellow | yellow_tripdata_2025-02.parquet | 3,577,543 | 3,306,817 | 270,726 | 7.567% | 4.5 |
| yellow | yellow_tripdata_2025-03.parquet | 4,145,257 | 3,827,687 | 317,570 | 7.661% | 5.5 |
| yellow | yellow_tripdata_2025-04.parquet | 3,970,553 | 3,672,720 | 297,833 | 7.501% | 5.1 |
| yellow | yellow_tripdata_2025-05.parquet | 4,591,845 | 4,093,325 | 498,520 | 10.857% | 5.7 |
| yellow | yellow_tripdata_2025-06.parquet | 4,322,960 | 3,870,211 | 452,749 | 10.473% | 4.8 |
| yellow | yellow_tripdata_2025-07.parquet | 3,898,963 | 3,495,399 | 403,564 | 10.351% | 3.9 |
| yellow | yellow_tripdata_2025-08.parquet | 3,574,091 | 3,181,548 | 392,543 | 10.983% | 3.4 |
| yellow | yellow_tripdata_2025-09.parquet | 4,251,015 | 3,839,084 | 411,931 | 9.69% | 4.1 |
| yellow | yellow_tripdata_2025-10.parquet | 4,428,699 | 3,944,915 | 483,784 | 10.924% | 4.2 |
| yellow | yellow_tripdata_2025-11.parquet | 4,181,444 | 3,644,918 | 536,526 | 12.831% | 3.8 |
| yellow | yellow_tripdata_2025-12.parquet | 4,305,006 | 4,051,010 | 253,996 | 5.9% | 4.2 |
| yellow | yellow_tripdata_2026-01.parquet | 3,724,889 | 3,518,106 | 206,783 | 5.551% | 3.8 |
| yellow | yellow_tripdata_2026-02.parquet | 3,399,866 | 3,211,742 | 188,124 | 5.533% | 3.7 |
| yellow | yellow_tripdata_2026-03.parquet | 3,952,451 | 3,764,300 | 188,151 | 4.76% | 4.3 |
| yellow | yellow_tripdata_2026-04.parquet | 3,831,240 | 3,675,769 | 155,471 | 4.058% | 4.7 |
| yellow | yellow_tripdata_2026-05.parquet | 4,090,836 | 3,913,696 | 177,140 | 4.33% | 4.7 |

### Сводка по типам (этот запуск)
| Тип | Файлов | Было строк | Стало строк | Удалено | % удалено |
|---|---:|---:|---:|---:|---:|
| fhv | 88 | 154,436,750 | 70,890,303 | 83,546,447 | 54.098% |
| fhvhv | 89 | 1,607,275,004 | 1,604,749,920 | 2,525,084 | 0.157% |
| green | 90 | 12,233,139 | 11,783,821 | 449,318 | 3.673% |
| yellow | 89 | 327,009,772 | 316,243,790 | 10,765,982 | 3.292% |

Это полный пересчет всех 356 файлов архива с нуля (не инкремент), поэтому таблица
выше — это итог по всему `TLC_Trip_Data` целиком, а не только по одному запуску.

### Итог по всему архиву

| Метрика | Значение |
|---|---:|
| Всего строк в raw-архиве | 2,100,954,665 |
| Всего строк после очистки | 2,003,667,834 |
| Удалено строк всего | 97,286,831 (4.631%) |
| Файлов обработано | 356 |
| Размер raw-архива | ~44.13 ГБ |
| Размер очищенного архива | ~51.02 ГБ |

Больше всего строк удаляется у **fhv** (54.1%) — это ожидаемо: у этого типа такси
почти нет полей тарифа/расстояния, а `PUlocationID`/`DOlocationID` перестали
заполняться корректно начиная примерно с 2022 года (в отдельные месяцы 2024–2025
доля NULL доходит до 70–88%, см. таблицу файлов fhv выше). Остальные типы теряют
единицы процентов.

Очищенный архив (51.02 ГБ) немного больше raw (44.13 ГБ), несмотря на меньшее число
строк — сжатие ZSTD уровня по умолчанию у DuckDB не полностью повторяет эффективность
исходных writer'ов TLC (GZIP для yellow/green/fhv, тюнингованный ZSTD для fhvhv).
Протестирован ZSTD level 19: экономия ~5% размера ценой ~6-кратного увеличения
времени записи (39.6с → 230.3с на характерный fhvhv-файл) — решено не применять,
разница в 51 → ~48 ГБ не стоит +2.5 часов к общему времени прогона при 39 ГБ
свободного места на диске.

## Валидация всех файлов в TLC_Trip_Data_clean

Проверено файлов: 356. Нарушений правил: 0. Ошибок чтения: 0.

## Погода: расширение на весь период архива

Источник: NOAA GHCN Daily Summaries, станция Central Park NY (`USW00094728`),
endpoint `https://www.ncei.noaa.gov/access/services/data/v1`. Ранее данные были
только за 2024 год (`taxi_weather_analysis/weather_daily_2024.csv`).

Скрипт `taxi_weather_analysis/extend_weather.py` запрашивает NOAA параллельно —
по одному HTTP-запросу на календарный год (`ThreadPoolExecutor`, сеть, поэтому
потоки, а не процессы) — и склеивает результат.

| Метрика | Значение |
|---|---|
| Период | 2019-01-01 … 2026-08-09 |
| Дней получено | 2,778 |
| Пропущенных дней внутри периода | 0 |
| Ошибок запросов | 0 |
| Время выполнения (8 запросов параллельно) | 12.2 с |
| Результат | `taxi_weather_analysis/weather_daily_2019_2026.csv` |

Колонки идентичны исходному `weather_daily_2024.csv` (`date, prcp_mm, snow_mm,
snwd_mm, tmax_c, tmin_c, awnd_ms, wsf5_ms`), значения сверены на пересекающихся
датах 2024 года и совпадают. Старый файл `weather_daily_2024.csv` не удален и
не изменен — остается валидным подмножеством нового.

## Инциденты в ходе выполнения

Первая версия пайплайна (`WORKERS=8`, `THREADS_PER_WORKER=2`, без ограничения
памяти на DuckDB-соединение) дважды подряд привела к аварийной перезагрузке
системы во время обработки fhvhv (BSOD `0x0000010E`, VIDEO_MEMORY_MANAGEMENT_INTERNAL,
дампы в `C:\WINDOWS\Minidumps\`, оба раза ~13 минут после старта тяжелой части
прогона). Прямой причиной падения именно видеоподсистемы предположительно стало
давление на системную память от восьми параллельных `SELECT DISTINCT` по большим
fhvhv-файлам без верхнего предела памяти на DuckDB-соединение.

Меры, примененные после этого:
1. `WORKERS` снижен с 8 до 2, `THREADS_PER_WORKER` с 2 до 1.
2. Добавлен явный `PRAGMA memory_limit='2GB'` на каждое DuckDB-соединение —
   вместо бесконтрольного роста потребления памяти DuckDB спиллит на диск.
3. После этого обнаружился следующий, уже некритичный баг: спилл-файлы двух
   параллельных воркеров писались в общий относительный `.tmp`-каталог и
   конфликтовали по именам (`IO Error: Failed to delete file`) — один из дочерних
   процессов падал, что каскадно роняло все еще не выполненные задачи в этом
   пуле. Исправлено выдачей каждому воркеру собственного `temp_directory`
   (`TLC_Trip_Data_clean/_duckdb_spill/<тип>_<файл>/`, удаляется по завершении
   файла).
4. Отдельно обнаружено и исправлено побитое чтение: один clean-файл
   (`fhvhv_tripdata_2019-02.parquet`), переживший первый краш, оказался поврежден
   ("No magic bytes found at end of file") — переживший rename файл, чьи данные,
   по всей видимости, не успели сброситься на диск при жесткой перезагрузке.
   Добавлена дешевая проверка читаемости footer'а каждого уже существующего
   clean-файла перед тем, как считать его готовым (см. `is_valid_parquet` в
   `clean_taxi_data.py`) — битые файлы теперь автоматически пересоздаются
   при повторном запуске, а не остаются незамеченными.
5. Отдельно (не связано с крашами) обнаружено, что запись без явного указания
   кодека давала clean-файлы БОЛЬШЕ raw, несмотря на меньшее число строк —
   DuckDB по умолчанию пишет parquet со SNAPPY, тогда как исходные файлы архива
   сжаты GZIP/ZSTD. Добавлен явный `COMPRESSION 'ZSTD'` в `COPY ... TO`, архив
   пересчитан заново целиком (см. "Итог по всему архиву" выше).

После всех исправлений финальный полный прогон (пересчет всех 356 файлов с нуля)
прошел за 40.6 минут без единого сбоя и без перезагрузок системы.
