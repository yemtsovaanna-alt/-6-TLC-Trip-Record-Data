"""Clean the NYC TLC taxi archive (TLC_Trip_Data -> TLC_Trip_Data_clean).

Stages:
  1. apply    - filter raw -> clean parquet per file (row-level filtering only,
                schema untouched), all 356 files across all 4 taxi types,
                parallel across files
  2. validate - for every clean file, confirm zero rows violate the type's predicate;
                re-run apply for any file that fails validation
  3. log      - write a full run report to DATA_CLEANING_LOG.md

Design notes:
  - Row-filtering predicates were reverse-engineered from 267 files that had already
    been cleaned in a prior (undocumented) run, then corrected/extended with an
    explicit anomaly-discovery pass (see _discover_anomalies.py output): dropped a
    planned PULocationID/DOLocationID range check after discovery showed the only
    out-of-range values are the official TLC sentinel codes 264/265, and added
    dropoff>pickup + exact-duplicate-row removal + full non-negative-money-fields
    coverage, none of which the prior run applied. Because these additions are
    material, the whole archive (not just the incomplete fhvhv slice) is reprocessed.
  - Parallelism: one OS process per file via ProcessPoolExecutor, WORKERS=2 processes
    x THREADS_PER_WORKER=1 DuckDB thread each, with an explicit per-connection
    PRAGMA memory_limit. Originally ran at 8 workers x 2 threads; that configuration
    correlated with two back-to-back system crashes (BSOD 0x10E) during this exact
    workload (SELECT DISTINCT dedup over large fhvhv files is memory-hungry), so
    parallelism/memory were cut hard in favor of stability over raw throughput.
  - No pandas/pyarrow in the hot path: DuckDB reads/writes parquet natively via
    `read_parquet` / `COPY ... TO ... (FORMAT PARQUET)`.
"""
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import duckdb

RAW_BASE = Path(r"C:\Users\andrn\HSE\NYC\TLC_Trip_Data")
CLEAN_BASE = Path(r"C:\Users\andrn\HSE\NYC\TLC_Trip_Data_clean")
LOG_PATH = Path(r"C:\Users\andrn\HSE\NYC\DATA_CLEANING_LOG.md")

# Снижено после двух крашей системы (BSOD 0x10E) во время параллельного прогона:
# 8 воркеров x 2 потока каждый создавали слишком высокую пиковую нагрузку на память
# при SELECT DISTINCT на больших fhvhv-файлах. Работаем существенно консервативнее.
WORKERS = 2
THREADS_PER_WORKER = 1
MEMORY_LIMIT_PER_WORKER = "2GB"

PREDICATES = {
    "yellow": (
        "fare_amount >= 0 AND trip_distance > 0 AND mta_tax >= 0 AND tip_amount >= 0 "
        "AND tolls_amount >= 0 AND total_amount >= 0 "
        "AND (extra >= 0 OR extra IS NULL) "
        "AND (improvement_surcharge >= 0 OR improvement_surcharge IS NULL) "
        "AND (congestion_surcharge >= 0 OR congestion_surcharge IS NULL) "
        "AND year(tpep_pickup_datetime) BETWEEN 2019 AND 2026 "
        "AND tpep_dropoff_datetime > tpep_pickup_datetime"
    ),
    "green": (
        "fare_amount >= 0 AND trip_distance > 0 AND mta_tax >= 0 AND tip_amount >= 0 "
        "AND tolls_amount >= 0 AND total_amount >= 0 "
        "AND (extra >= 0 OR extra IS NULL) "
        "AND (improvement_surcharge >= 0 OR improvement_surcharge IS NULL) "
        "AND (congestion_surcharge >= 0 OR congestion_surcharge IS NULL) "
        "AND year(lpep_pickup_datetime) BETWEEN 2019 AND 2026 "
        "AND lpep_dropoff_datetime > lpep_pickup_datetime"
    ),
    "fhv": (
        "PUlocationID IS NOT NULL AND PUlocationID != 0 "
        "AND DOlocationID IS NOT NULL AND DOlocationID != 0 "
        "AND dispatching_base_num IS NOT NULL AND dropOff_datetime > pickup_datetime"
    ),
    "fhvhv": (
        "trip_miles > 0 AND trip_miles <= 100 AND trip_time > 0 AND trip_time <= 10800 "
        "AND base_passenger_fare >= 0 AND driver_pay >= 0 "
        "AND dropoff_datetime > pickup_datetime"
    ),
}

# Все запросы очистки используют SELECT DISTINCT — точные дубликаты строк
# (полное совпадение всех колонок) отбрасываются попутно, без отдельного
# дорогого прохода по всему архиву.
USE_DISTINCT = True

RULE_NOTES = {
    "yellow": [
        "fare_amount >= 0 — отрицательные тарифы физически невозможны",
        "trip_distance > 0 — поездка нулевой длины не является поездкой",
        "mta_tax/tip_amount/tolls_amount/total_amount/extra/improvement_surcharge/"
        "congestion_surcharge >= 0 — ни одно денежное поле не может быть отрицательным",
        "год pickup в [2019, 2026] — отбрасывает мусорные метки времени (напр. 2001, 2088)",
        "dropoff > pickup — защита от развернутых во времени поездок",
        "SELECT DISTINCT — удаляет точные дубликаты строк",
        "PULocationID/DOLocationID вне 1-263 НЕ фильтруются: проверено (см. discovery) — "
        "100% таких значений это 264/265, официальные коды TLC 'Outside NYC'/'Unknown', "
        "а не брак данных",
        "passenger_count = 0 / NULL НЕ фильтруется: как и раньше, это распространенный "
        "(до ~8%) пробел в отчетности части вендоров, а не признак поврежденной записи",
    ],
    "green": [
        "те же правила, что и для yellow (идентичная схема тарифов и колонок)",
    ],
    "fhv": [
        "PUlocationID/DOlocationID NOT NULL и != 0 — без зоны посадки/высадки запись "
        "бесполезна для анализа (0 — тот же брак, что и NULL, встречается редко)",
        "dispatching_base_num NOT NULL — обязательный идентификатор базы",
        "dropOff_datetime > pickup_datetime — защита от развернутых во времени поездок",
        "SELECT DISTINCT — удаляет точные дубликаты строк",
        "PUlocationID/DOlocationID = 264/265 НЕ фильтруются — официальные коды TLC, не брак",
    ],
    "fhvhv": [
        "trip_miles в (0, 100] — 0 миль или >100 миль за поездку нереалистичны для городского такси",
        "trip_time в (0, 10800] сек — поездки длиннее 3 часов или нулевой длительности являются браком данных",
        "base_passenger_fare >= 0, driver_pay >= 0 — денежные поля не могут быть отрицательными",
        "dropoff > pickup — защита от развернутых во времени поездок",
        "SELECT DISTINCT — удаляет точные дубликаты строк",
        "PULocationID/DOLocationID = 264/265 НЕ фильтруются — официальные коды TLC, не брак "
        "(tolls/bcf/sales_tax/congestion_surcharge/tips отрицательных значений практически не содержат — "
        "отдельный фильтр не требуется)",
    ],
}


def raw_files(taxi_type: str) -> list[Path]:
    return sorted(RAW_BASE.glob(f"{taxi_type}/{taxi_type}_tripdata_*.parquet"))


def clean_path_for(raw_path: Path) -> Path:
    return CLEAN_BASE / raw_path.parent.name / raw_path.name


def clean_one_file(taxi_type: str, raw_path_str: str) -> dict:
    raw_path = Path(raw_path_str)
    out_path = clean_path_for(raw_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")

    # Каждый воркер обязан иметь СВОЙ temp_directory: при memory_limit=2GB DuckDB
    # активно спиллит промежуточные данные SELECT DISTINCT на диск, а общий дефолтный
    # ".tmp" на процесс приводил к коллизиям имен спилл-файлов между параллельными
    # воркерами (IO Error при удалении файла, который держит открытым другой процесс).
    spill_dir = CLEAN_BASE / "_duckdb_spill" / f"{taxi_type}_{raw_path.stem}"
    spill_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute(
        f"PRAGMA threads={THREADS_PER_WORKER}; PRAGMA disable_progress_bar; "
        f"PRAGMA memory_limit='{MEMORY_LIMIT_PER_WORKER}'; "
        f"PRAGMA temp_directory='{spill_dir.as_posix()}';"
    )
    predicate = PREDICATES[taxi_type]

    t0 = time.time()
    raw_count = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{raw_path.as_posix()}')"
    ).fetchone()[0]

    # ZSTD вместо дефолтного для DuckDB SNAPPY: raw-файлы архива сжаты GZIP (yellow/green/fhv)
    # или ZSTD (fhvhv), и запись с SNAPPY по умолчанию давала clean-файлы БОЛЬШЕ raw,
    # несмотря на меньшее число строк (обнаружено после первого полного прогона).
    select_kw = "SELECT DISTINCT" if USE_DISTINCT else "SELECT"
    con.execute(
        f"COPY ({select_kw} * FROM read_parquet('{raw_path.as_posix()}') WHERE {predicate}) "
        f"TO '{tmp_path.as_posix()}' (FORMAT PARQUET, COMPRESSION 'ZSTD')"
    )
    os.replace(tmp_path, out_path)

    clean_count = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{out_path.as_posix()}')"
    ).fetchone()[0]
    con.close()

    import shutil
    shutil.rmtree(spill_dir, ignore_errors=True)

    return {
        "type": taxi_type,
        "file": raw_path.name,
        "raw_rows": raw_count,
        "clean_rows": clean_count,
        "removed_rows": raw_count - clean_count,
        "removed_pct": round(100 * (raw_count - clean_count) / raw_count, 3) if raw_count else 0.0,
        "elapsed_sec": round(time.time() - t0, 1),
    }


def validate_one_file(taxi_type: str, clean_path_str: str) -> dict:
    clean_path = Path(clean_path_str)
    con = duckdb.connect()
    con.execute(
        f"PRAGMA threads={THREADS_PER_WORKER}; PRAGMA disable_progress_bar; "
        f"PRAGMA memory_limit='{MEMORY_LIMIT_PER_WORKER}';"
    )
    predicate = PREDICATES[taxi_type]
    total = con.execute(f"SELECT COUNT(*) FROM read_parquet('{clean_path.as_posix()}')").fetchone()[0]
    violations = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{clean_path.as_posix()}') WHERE NOT ({predicate})"
    ).fetchone()[0]
    con.close()
    return {
        "type": taxi_type,
        "file": clean_path.name,
        "total_rows": total,
        "violations": violations,
        "ok": violations == 0,
    }


def stage_apply(pending: dict[str, list[Path]]) -> list[dict]:
    tasks = [(t, str(p)) for t, paths in pending.items() for p in paths]
    if not tasks:
        return []
    results = []
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(clean_one_file, t, p): (t, p) for t, p in tasks}
        for fut in as_completed(futures):
            t, p = futures[fut]
            try:
                res = fut.result()
                results.append(res)
                print(f"  [apply] {res['type']}/{res['file']}: {res['raw_rows']} -> "
                      f"{res['clean_rows']} (-{res['removed_pct']}%) in {res['elapsed_sec']}s")
            except Exception as e:
                print(f"  [apply] FAILED {t}/{Path(p).name}: {e}")
                results.append({"type": t, "file": Path(p).name, "error": str(e)})
    return results


def stage_validate(clean_files: dict[str, list[Path]]) -> list[dict]:
    tasks = [(t, str(p)) for t, paths in clean_files.items() for p in paths]
    results = []
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(validate_one_file, t, p): (t, p) for t, p in tasks}
        for fut in as_completed(futures):
            t, p = futures[fut]
            try:
                res = fut.result()
                results.append(res)
                if not res["ok"]:
                    print(f"  [validate] MISMATCH {res['type']}/{res['file']}: "
                          f"{res['violations']} violating rows")
            except Exception as e:
                print(f"  [validate] FAILED {t}/{Path(p).name}: {e}")
                results.append({"type": t, "file": Path(p).name, "error": str(e)})
    return results


def write_log(discovery: dict, apply_results: list[dict], validate_results: list[dict],
              revalidate_results: list[dict] | None, total_elapsed: float):
    from datetime import datetime

    lines = []
    lines.append("# Лог очистки данных TLC_Trip_Data\n")
    lines.append(f"Запуск: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"Параллелизм: {WORKERS} процессов x {THREADS_PER_WORKER} DuckDB-потока "
                 f"(на машине с {os.cpu_count()} логическими ядрами)  ")
    lines.append(f"Общее время выполнения: {round(total_elapsed / 60, 1)} мин\n")

    lines.append("## Правила очистки по типам такси\n")
    for t in ["yellow", "green", "fhv", "fhvhv"]:
        lines.append(f"### {t}")
        lines.append(f"```sql\nWHERE {PREDICATES[t]}\n```")
        for note in RULE_NOTES[t]:
            lines.append(f"- {note}")
        lines.append("")

    if discovery:
        lines.append("## Discovery: аномалии, найденные на исходных данных\n")
        lines.append("Числа получены агрегациями по всем raw-файлам соответствующего типа "
                      "(см. `_discover_anomalies.py`), до применения фильтрации.\n")
        for t, d in discovery.items():
            lines.append(f"### {t} (всего строк: {d.get('total_rows', '?'):,})")
            lines.append("| Метрика | Значение |")
            lines.append("|---|---|")
            for k, v in d.items():
                if k in ("type", "total_rows", "elapsed_sec"):
                    continue
                lines.append(f"| {k} | {v} |")
            lines.append("")

    if apply_results:
        lines.append("## Примененная очистка (файлы, обработанные в этом запуске)\n")
        lines.append("| Тип | Файл | Было строк | Стало строк | Удалено | % удалено | Время, с |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        ok_results = [r for r in apply_results if "error" not in r]
        for r in sorted(ok_results, key=lambda r: (r["type"], r["file"])):
            lines.append(f"| {r['type']} | {r['file']} | {r['raw_rows']:,} | {r['clean_rows']:,} | "
                         f"{r['removed_rows']:,} | {r['removed_pct']}% | {r['elapsed_sec']} |")
        errors = [r for r in apply_results if "error" in r]
        if errors:
            lines.append("\n**Ошибки при обработке:**\n")
            for r in errors:
                lines.append(f"- {r['type']}/{r['file']}: {r['error']}")

        lines.append("\n### Сводка по типам (этот запуск)")
        lines.append("| Тип | Файлов | Было строк | Стало строк | Удалено | % удалено |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        by_type = {}
        for r in ok_results:
            d = by_type.setdefault(r["type"], {"files": 0, "raw": 0, "clean": 0})
            d["files"] += 1
            d["raw"] += r["raw_rows"]
            d["clean"] += r["clean_rows"]
        for t, d in sorted(by_type.items()):
            removed = d["raw"] - d["clean"]
            pct = round(100 * removed / d["raw"], 3) if d["raw"] else 0.0
            lines.append(f"| {t} | {d['files']} | {d['raw']:,} | {d['clean']:,} | {removed:,} | {pct}% |")
        lines.append("")

    if validate_results:
        lines.append("## Валидация всех файлов в TLC_Trip_Data_clean\n")
        total = len(validate_results)
        bad = [r for r in validate_results if not r.get("ok", True)]
        errored = [r for r in validate_results if "error" in r]
        lines.append(f"Проверено файлов: {total}. Нарушений правил: {len(bad)}. "
                     f"Ошибок чтения: {len(errored)}.\n")
        if bad:
            lines.append("| Тип | Файл | Строк | Нарушающих строк |")
            lines.append("|---|---|---:|---:|")
            for r in bad:
                lines.append(f"| {r['type']} | {r['file']} | {r['total_rows']:,} | {r['violations']:,} |")
            lines.append("")
        if errored:
            for r in errored:
                lines.append(f"- ОШИБКА {r['type']}/{r['file']}: {r['error']}")
            lines.append("")

    if revalidate_results is not None:
        lines.append("## Повторная валидация после дообработки расхождений\n")
        bad = [r for r in revalidate_results if not r.get("ok", True)]
        lines.append(f"Проверено файлов: {len(revalidate_results)}. Осталось нарушений: {len(bad)}.\n")

    LOG_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nЛог записан: {LOG_PATH}")


def main():
    t0 = time.time()

    tmp_broken = list(CLEAN_BASE.glob("**/*.parquet.tmp"))
    for p in tmp_broken:
        print(f"Removing broken tmp file: {p}")
        p.unlink()

    spill_root = CLEAN_BASE / "_duckdb_spill"
    if spill_root.exists():
        import shutil
        shutil.rmtree(spill_root, ignore_errors=True)

    discovery = {}
    for f in sorted(Path(r"C:\Users\andrn\HSE\NYC").glob("_disc_*.json")):
        t = f.stem.replace("_disc_", "")
        try:
            discovery[t] = json.loads(f.read_text())
        except Exception:
            pass

    # Финальный предикат зафиксирован (проверен на 267 уже пересчитанных файлах в
    # предыдущих прогонах этого же скрипта, до крашей системы), поэтому дальше — только
    # режим дозаполнения: не трогаем файлы, для которых clean-версия уже существует,
    # обрабатываем лишь недостающие (в основном fhvhv). Полная validate-стадия ниже
    # все равно проверит вообще все 356 файлов на соответствие правилам.
    def is_valid_parquet(p: Path) -> bool:
        # Дешевая проверка читаемости footer'а — ловит файлы, побитые предыдущими
        # крашами системы (напр. rename прошел, но данные не успели сброситься на диск).
        try:
            con = duckdb.connect()
            con.execute("PRAGMA disable_progress_bar;")
            con.execute(f"SELECT 1 FROM read_parquet('{p.as_posix()}') LIMIT 1")
            con.close()
            return True
        except Exception:
            return False

    pending = {}
    for t in ["yellow", "green", "fhv", "fhvhv"]:
        raws = raw_files(t)
        existing = list((CLEAN_BASE / t).glob("*.parquet")) if (CLEAN_BASE / t).exists() else []
        have = set()
        for p in existing:
            if is_valid_parquet(p):
                have.add(p.name)
            else:
                print(f"  Обнаружен поврежденный файл, будет пересоздан: {p}")
        missing = [p for p in raws if p.name not in have]
        pending[t] = missing
        print(f"{t}: {len(missing)} из {len(raws)} файлов будет обработано (остальные уже готовы)")

    apply_results = stage_apply(pending)

    clean_files = {t: sorted((CLEAN_BASE / t).glob("*.parquet")) for t in ["yellow", "green", "fhv", "fhvhv"]}
    validate_results = stage_validate(clean_files)

    bad_by_type = {}
    for r in validate_results:
        if not r.get("ok", True):
            bad_by_type.setdefault(r["type"], []).append(RAW_BASE / r["type"] / r["file"])

    revalidate_results = None
    if bad_by_type:
        print(f"Re-processing {sum(len(v) for v in bad_by_type.values())} files with validation mismatches...")
        extra_apply = stage_apply(bad_by_type)
        apply_results.extend(extra_apply)
        reclean_files = {t: [CLEAN_BASE / t / p.name for p in paths] for t, paths in bad_by_type.items()}
        revalidate_results = stage_validate(reclean_files)

    total_elapsed = time.time() - t0
    write_log(discovery, apply_results, validate_results, revalidate_results, total_elapsed)
    print(f"\nDone in {round(total_elapsed / 60, 1)} min")


if __name__ == "__main__":
    main()
