from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://reitoweb.com/b_moba/doc/"
STORE_ID = "11"
RATE_TYPE = "6"
UA = "ReitoPachinkoResearch/2.4 (+low-frequency personal research collector)"

GET_RETRIES = 6
CONNECT_TIMEOUT = 60
READ_TIMEOUT = 60
MAX_MISSING_UNITS = 5
MIN_COVERAGE_RATIO = 0.98

# 過去日の自動補完設定
BACKFILL_DAYS = 2
BACKFILL_MIN_PARSED_RATIO = 0.85
BACKFILL_MIN_ACTIVE_MACHINES = 5


@dataclass
class MachineModel:
    machine_id: str
    name: str
    flags: str


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def get(session: requests.Session, url: str, retries: int = GET_RETRIES) -> str:
    """GET with exponential backoff."""
    last = None
    for i in range(retries):
        try:
            r = session.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            if i + 1 < retries:
                wait = min(5 * (2 ** i), 120)
                print(
                    f"[WARN] GET failed ({i + 1}/{retries}): {url}: {e}; "
                    f"retrying in {wait}s",
                    flush=True,
                )
                time.sleep(wait)
    raise RuntimeError(f"GET failed after {retries} attempts: {url}: {last}")


def official_total_units(html: str) -> int | None:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)

    # 旧表記
    m = re.search(r"4円パチンコ\s*([0-9,]+)\s*台", text)
    if m:
        return int(m.group(1).replace(",", ""))

    # 店舗ページ側の一般表記にも対応
    m = re.search(r"パチンコ\s*([0-9,]+)\s*台", text)
    return int(m.group(1).replace(",", "")) if m else None


def discover_models(html: str) -> list[MachineModel]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, MachineModel] = {}

    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"])
        p = urlparse(href)
        if not p.path.endswith("/data.php"):
            continue

        q = parse_qs(p.query)
        if q.get("h", [""])[0] != STORE_ID:
            continue
        if q.get("t", [""])[0] != RATE_TYPE:
            continue

        mid = q.get("m", [""])[0]
        if not mid:
            continue

        label = clean(a.get_text(" ", strip=True))
        if not label:
            continue

        flags = [x for x in ("NEW", "増台", "オススメ") if x in label]
        name = label
        for x in ("NEW", "増台", "オススメ"):
            name = name.replace(x, "")
        name = clean(name)

        if name:
            found[mid] = MachineModel(mid, name, ",".join(flags))

    return list(found.values())


def _grab_int(text: str, pattern: str):
    m = re.search(pattern, text)
    return int(m.group(1).replace(",", "")) if m else None


def parse_machine_page(
    html: str,
    expected_machine_id: str,
) -> tuple[list[dict], dict]:
    """Parse same-day machine cards and preserve each detail-page URL."""
    soup = BeautifulSoup(html, "html.parser")

    rows_by_number: dict[str, dict] = {}
    link_numbers: list[str] = []

    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"])
        p = urlparse(href)

        if not (p.path.endswith("/machine.php") or p.path.endswith("/machine2.php")):
            continue

        q = parse_qs(p.query)
        if q.get("h", [""])[0] != STORE_ID:
            continue
        if q.get("t", [""])[0] != RATE_TYPE:
            continue

        mid = q.get("m", [""])[0]
        num = q.get("n", [""])[0]

        if mid != expected_machine_id or not re.fullmatch(r"\d{4}", num):
            continue

        link_numbers.append(num)

        card = a.find_parent(
            "div",
            class_=lambda c: c and "card" in str(c).split(),
        )
        if card is None:
            card = a.parent

        block = clean(card.get_text(" ", strip=True)) if card else ""

        rows_by_number[num] = {
            "machine_number": num,
            "big_hits": _grab_int(block, r"大当\s*([0-9,]+)\s*回"),
            "kakuhen_jitan": _grab_int(
                block,
                r"確変[／/]?\s*時短\s*([0-9,]+)\s*回",
            ),
            "max_balls": _grab_int(block, r"最大持玉\s*([0-9,]+)\s*玉"),
            "detail_url": href,
        }

    rows = list(rows_by_number.values())

    return rows, {
        "page_status": "ok" if rows else "parsed_zero",
        "detail_link_count": len(link_numbers),
        "unique_detail_links": len(set(link_numbers)),
        "parsed_rows": len(rows),
        "duplicate_link_count": len(link_numbers) - len(set(link_numbers)),
    }


def _to_int_or_none(s: str | None) -> int | None:
    if s is None:
        return None
    s = clean(s)
    if not s or s in {"-", "—", "---"}:
        return None
    m = re.search(r"[0-9][0-9,]*", s)
    return int(m.group(0).replace(",", "")) if m else None


def _find_section_table(soup: BeautifulSoup, label: str):
    """Find the first table belonging to a heading/text node such as 前日/前々日."""
    # Heading tags are preferred.
    for tag_name in ("h2", "h3", "h4", "h5", "h6", "dt", "p", "div"):
        for tag in soup.find_all(tag_name):
            if clean(tag.get_text(" ", strip=True)) == label:
                table = tag.find_next("table")
                if table is not None:
                    # Do not accidentally jump beyond the next previous-day heading.
                    blocker = tag.find_next(
                        lambda t: getattr(t, "name", None) in
                        {"h2", "h3", "h4", "h5", "h6", "dt", "p", "div"}
                        and clean(t.get_text(" ", strip=True)) in {"前日", "前々日"}
                        and clean(t.get_text(" ", strip=True)) != label
                    )
                    if blocker is None or table.sourceline is None or blocker.sourceline is None:
                        return table
                    if table.sourceline < blocker.sourceline:
                        return table

    # Fallback: exact text node then next table.
    node = soup.find(string=lambda s: clean(str(s)) == label if s else False)
    if node is not None:
        parent = node.parent
        if parent is not None:
            return parent.find_next("table")
    return None


def _parse_previous_table(table) -> dict | None:
    if table is None:
        return None

    # Normalize each row separately first.
    rows = []
    for tr in table.find_all("tr"):
        cells = [
            clean(x.get_text(" ", strip=True))
            for x in tr.find_all(["th", "td"])
        ]
        if cells:
            rows.append(cells)

    flat = [x for row in rows for x in row]
    text = " | ".join(flat)

    # Preferred: derive values from table row positions.
    big_hits = None
    kakuhen = None
    max_balls = None

    for i, row in enumerate(rows):
        joined = " ".join(row)

        if "大当" in joined and ("確変" in joined or "時短" in joined):
            # Usually the next row contains the values for those headers.
            if i + 1 < len(rows):
                vals = rows[i + 1]
                if len(vals) >= 1:
                    big_hits = _to_int_or_none(vals[0])
                if len(vals) >= 2:
                    kakuhen = _to_int_or_none(vals[1])

        if "累計スタート" in joined and ("最大持玉" in joined or "最大得玉" in joined):
            if i + 1 < len(rows):
                vals = rows[i + 1]
                if len(vals) >= 2:
                    max_balls = _to_int_or_none(vals[1])

    # Fallback for compressed/nonstandard table markup.
    if big_hits is None and kakuhen is None:
        m = re.search(
            r"大当り?\s*\|\s*確変(?:／?時短|時短).*?"
            r"\|\s*([0-9,]+|-|—)\s*\|\s*([0-9,]+|-|—)",
            text,
        )
        if m:
            big_hits = _to_int_or_none(m.group(1))
            kakuhen = _to_int_or_none(m.group(2))

    if max_balls is None:
        m = re.search(
            r"累計スタート\s*\|\s*最大(?:持玉|得玉).*?"
            r"\|\s*([0-9,]+|-|—)\s*\|\s*([0-9,]+|-|—)",
            text,
        )
        if m:
            max_balls = _to_int_or_none(m.group(2))

    # A section that exists but has only dashes is not usable backfill.
    if big_hits is None and kakuhen is None and max_balls is None:
        return None

    return {
        "big_hits": big_hits,
        "kakuhen_jitan": kakuhen,
        "max_balls": max_balls,
    }


def parse_detail_history(html: str) -> dict[int, dict]:
    """Return {1: previous-day data, 2: two-days-ago data} when available."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[int, dict] = {}

    for offset, label in ((1, "前日"), (2, "前々日")):
        parsed = _parse_previous_table(_find_section_table(soup, label))
        if parsed is not None:
            out[offset] = parsed

    return out


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS daily_records (
      record_date TEXT NOT NULL,
      machine_number TEXT NOT NULL,
      machine_id TEXT NOT NULL,
      machine_name TEXT NOT NULL,
      flags TEXT DEFAULT '',
      big_hits INTEGER,
      kakuhen_jitan INTEGER,
      max_balls INTEGER,
      source_day_offset INTEGER NOT NULL DEFAULT 0,
      collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (record_date, machine_number)
    );

    CREATE TABLE IF NOT EXISTS machine_changes (
      change_date TEXT NOT NULL,
      machine_number TEXT NOT NULL,
      old_machine_id TEXT,
      old_machine_name TEXT,
      new_machine_id TEXT NOT NULL,
      new_machine_name TEXT NOT NULL,
      PRIMARY KEY (change_date, machine_number, new_machine_id)
    );

    CREATE TABLE IF NOT EXISTS collection_coverage (
      record_date TEXT PRIMARY KEY,
      official_units INTEGER,
      collected_units INTEGER NOT NULL,
      missing_units INTEGER,
      model_count INTEGER NOT NULL,
      models_with_no_rows INTEGER NOT NULL,
      detail_links INTEGER DEFAULT 0,
      unique_detail_links INTEGER DEFAULT 0,
      duplicate_links INTEGER DEFAULT 0,
      collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS backfill_log (
      target_date TEXT NOT NULL,
      source_run_date TEXT NOT NULL,
      source_day_offset INTEGER NOT NULL,
      parsed_units INTEGER NOT NULL,
      active_units INTEGER NOT NULL,
      applied_units INTEGER NOT NULL,
      status TEXT NOT NULL,
      collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (target_date, source_run_date, source_day_offset)
    );
    """)


def remove_unreliable_seed_history(conn: sqlite3.Connection):
    # v1/v2でdata.phpにd=1/d=2を付けた擬似履歴だけを削除する。
    # v2.4の詳細ページ由来のoffset 1/2は信頼できるため削除しない。
    conn.execute("""
        DELETE FROM daily_records
        WHERE source_day_offset > 0
          AND collected_at < '2026-08-19 00:00:00'
    """)
    conn.execute("""
        DELETE FROM collection_coverage
        WHERE record_date NOT IN (
          SELECT DISTINCT record_date FROM daily_records
        )
    """)
    conn.commit()


def detect_changes(conn: sqlite3.Connection, target_date: str):
    prev = conn.execute(
        "SELECT MAX(record_date) FROM daily_records WHERE record_date < ?",
        (target_date,),
    ).fetchone()[0]

    if not prev:
        return

    current = {
        r[0]: r[1:]
        for r in conn.execute(
            """
            SELECT machine_number,machine_id,machine_name
            FROM daily_records
            WHERE record_date=?
            """,
            (target_date,),
        )
    }

    previous = {
        r[0]: r[1:]
        for r in conn.execute(
            """
            SELECT machine_number,machine_id,machine_name
            FROM daily_records
            WHERE record_date=?
            """,
            (prev,),
        )
    }

    for num, (new_id, new_name) in current.items():
        if num in previous:
            old_id, old_name = previous[num]
            if old_id != new_id:
                conn.execute("""
                    INSERT OR IGNORE INTO machine_changes
                    (
                      change_date,machine_number,
                      old_machine_id,old_machine_name,
                      new_machine_id,new_machine_name
                    )
                    VALUES (?,?,?,?,?,?)
                """, (
                    target_date,
                    num,
                    old_id,
                    old_name,
                    new_id,
                    new_name,
                ))


def _date_needs_backfill(conn: sqlite3.Connection, target_date: str) -> bool:
    row = conn.execute("""
        SELECT
          COUNT(*) AS n,
          SUM(
            CASE
              WHEN big_hits IS NOT NULL
                OR kakuhen_jitan IS NOT NULL
                OR max_balls IS NOT NULL
              THEN 1 ELSE 0
            END
          ) AS n_with_values
        FROM daily_records
        WHERE record_date=?
    """, (target_date,)).fetchone()

    n = row[0] or 0
    n_with_values = row[1] or 0

    # Missing entirely, or effectively an all-blank snapshot.
    if n == 0:
        return True
    return n_with_values < max(5, int(n * 0.10))


def _existing_identity(
    conn: sqlite3.Connection,
    target_date: str,
    machine_number: str,
) -> tuple[str, str, str] | None:
    row = conn.execute("""
        SELECT machine_id,machine_name,flags
        FROM daily_records
        WHERE record_date=? AND machine_number=?
    """, (target_date, machine_number)).fetchone()
    return tuple(row) if row else None


def apply_backfill(
    conn: sqlite3.Connection,
    run_date,
    detail_sources: list[dict],
    wanted_offsets: set[int],
    session: requests.Session,
    raw_dir: Path,
    sleep_sec: float,
) -> dict:
    """Recover missing prior-day data from each machine detail page."""
    results = {}

    if not wanted_offsets:
        return results

    candidates: dict[int, list[dict]] = {
        offset: []
        for offset in wanted_offsets
    }

    detail_errors = 0
    parsed_pages = 0

    detail_raw_dir = raw_dir / str(run_date) / "details"
    detail_raw_dir.mkdir(parents=True, exist_ok=True)

    for i, source in enumerate(detail_sources, start=1):
        try:
            html = get(session, source["detail_url"])
            parsed_pages += 1

            # Keep the raw detail HTML so a future parser can be improved
            # without hitting the live site again.
            (detail_raw_dir / f'{source["machine_number"]}.html').write_text(
                html,
                encoding="utf-8",
            )

            history = parse_detail_history(html)

            for offset in wanted_offsets:
                rec = history.get(offset)
                if rec is None:
                    continue

                candidates[offset].append({
                    **source,
                    **rec,
                })

        except Exception as e:
            detail_errors += 1
            print(
                f'[WARN] detail fetch failed '
                f'{source["machine_number"]}: {e}',
                flush=True,
            )

        if sleep_sec:
            time.sleep(max(sleep_sec, 0.15))

        if i % 50 == 0:
            print(
                f"[INFO] detail backfill progress: {i}/{len(detail_sources)}",
                flush=True,
            )

    total_sources = max(len(detail_sources), 1)

    for offset in sorted(wanted_offsets):
        target_date = str(run_date - timedelta(days=offset))
        rows = candidates[offset]

        parsed_ratio = len(rows) / total_sources
        active_units = sum(
            1
            for r in rows
            if (r["big_hits"] or 0) > 0
            or (r["kakuhen_jitan"] or 0) > 0
            or (r["max_balls"] or 0) > 0
        )

        # Store-wide guard against a closed/unpublished day.
        accepted = (
            parsed_ratio >= BACKFILL_MIN_PARSED_RATIO
            and active_units >= BACKFILL_MIN_ACTIVE_MACHINES
        )

        applied = 0

        if accepted:
            for r in rows:
                existing = _existing_identity(
                    conn,
                    target_date,
                    r["machine_number"],
                )

                if existing:
                    machine_id, machine_name, flags = existing
                else:
                    # If there is no row at all, use the current identity.
                    # This is safe for ordinary missed days; machine-change
                    # detection remains available when neighboring snapshots exist.
                    machine_id = r["machine_id"]
                    machine_name = r["machine_name"]
                    flags = r["flags"]

                # Never overwrite a historical row that already has real values.
                has_values = conn.execute("""
                    SELECT 1
                    FROM daily_records
                    WHERE record_date=?
                      AND machine_number=?
                      AND (
                        big_hits IS NOT NULL
                        OR kakuhen_jitan IS NOT NULL
                        OR max_balls IS NOT NULL
                      )
                """, (target_date, r["machine_number"])).fetchone()

                if has_values:
                    continue

                conn.execute("""
                    INSERT INTO daily_records
                    (
                      record_date,machine_number,machine_id,machine_name,flags,
                      big_hits,kakuhen_jitan,max_balls,source_day_offset
                    )
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(record_date,machine_number) DO UPDATE SET
                      machine_id=excluded.machine_id,
                      machine_name=excluded.machine_name,
                      flags=excluded.flags,
                      big_hits=excluded.big_hits,
                      kakuhen_jitan=excluded.kakuhen_jitan,
                      max_balls=excluded.max_balls,
                      source_day_offset=excluded.source_day_offset,
                      collected_at=CURRENT_TIMESTAMP
                """, (
                    target_date,
                    r["machine_number"],
                    machine_id,
                    machine_name,
                    flags,
                    r["big_hits"],
                    r["kakuhen_jitan"],
                    r["max_balls"],
                    offset,
                ))
                applied += 1

            conn.execute("""
                INSERT OR REPLACE INTO collection_coverage
                (
                  record_date,official_units,collected_units,missing_units,
                  model_count,models_with_no_rows,
                  detail_links,unique_detail_links,duplicate_links,collected_at
                )
                SELECT
                  ?,
                  NULL,
                  COUNT(*),
                  NULL,
                  COUNT(DISTINCT machine_id),
                  0,
                  COUNT(*),
                  COUNT(*),
                  0,
                  CURRENT_TIMESTAMP
                FROM daily_records
                WHERE record_date=?
            """, (target_date, target_date))

        status = "applied" if accepted else "rejected_quality_guard"

        conn.execute("""
            INSERT OR REPLACE INTO backfill_log
            (
              target_date,source_run_date,source_day_offset,
              parsed_units,active_units,applied_units,status,collected_at
            )
            VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        """, (
            target_date,
            str(run_date),
            offset,
            len(rows),
            active_units,
            applied,
            status,
        ))

        results[str(offset)] = {
            "target_date": target_date,
            "parsed_units": len(rows),
            "parsed_ratio": round(parsed_ratio, 4),
            "active_units": active_units,
            "applied_units": applied,
            "status": status,
        }

    results["detail_pages_fetched"] = parsed_pages
    results["detail_errors"] = detail_errors
    return results


def _write_exports(conn: sqlite3.Connection, out_dir: Path, summary: dict):
    with open(
        out_dir / "daily_records.csv",
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        w = csv.writer(f)
        w.writerow([
            "record_date",
            "machine_number",
            "machine_id",
            "machine_name",
            "flags",
            "big_hits",
            "kakuhen_jitan",
            "max_balls",
            "source_day_offset",
            "collected_at",
        ])
        w.writerows(conn.execute("""
            SELECT
              record_date,machine_number,machine_id,machine_name,flags,
              big_hits,kakuhen_jitan,max_balls,source_day_offset,collected_at
            FROM daily_records
            ORDER BY record_date,machine_number
        """))

    (out_dir / "last_run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def collect(out_dir: Path, sleep_sec: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    db_path = out_dir / "reito.sqlite"

    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "ja-JP,ja;q=0.9",
        "Connection": "close",
    })

    index_url = f"{BASE}data.php?h={STORE_ID}&t={RATE_TYPE}"
    index_html = get(session, index_url)
    models = discover_models(index_html)
    official_units = official_total_units(index_html)

    if not models:
        raise RuntimeError(
            "No machine models found; site structure may have changed."
        )

    conn = sqlite3.connect(db_path)
    init_db(conn)
    remove_unreliable_seed_history(conn)

    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    record_date = str(today)

    day_raw = raw_dir / record_date
    day_raw.mkdir(parents=True, exist_ok=True)

    (raw_dir / f"index_{today}.html").write_text(
        index_html,
        encoding="utf-8",
    )

    total_links = 0
    total_unique_links = 0
    total_duplicate_links = 0
    no_row_models = 0
    records_processed = 0
    model_errors: list[dict] = []
    detail_sources: list[dict] = []

    conn.execute("BEGIN")

    try:
        for model in models:
            url = (
                f"{BASE}data.php?"
                f"h={STORE_ID}&m={model.machine_id}&t={RATE_TYPE}"
            )

            try:
                page = get(session, url)
            except Exception as e:
                model_errors.append({
                    "machine_id": model.machine_id,
                    "machine_name": model.name,
                    "error": str(e),
                })
                print(
                    f"[ERROR] model fetch failed: "
                    f"{model.machine_id} {model.name}: {e}",
                    flush=True,
                )
                continue

            (day_raw / f"{model.machine_id}_d0.html").write_text(
                page,
                encoding="utf-8",
            )

            rows, diag = parse_machine_page(
                page,
                model.machine_id,
            )

            total_links += diag["detail_link_count"]
            total_unique_links += diag["unique_detail_links"]
            total_duplicate_links += diag["duplicate_link_count"]

            if not rows:
                no_row_models += 1

            for row in rows:
                conn.execute("""
                    INSERT INTO daily_records
                    (
                      record_date,machine_number,machine_id,machine_name,flags,
                      big_hits,kakuhen_jitan,max_balls,source_day_offset
                    )
                    VALUES (?,?,?,?,?,?,?,?,0)
                    ON CONFLICT(record_date,machine_number) DO UPDATE SET
                      machine_id=excluded.machine_id,
                      machine_name=excluded.machine_name,
                      flags=excluded.flags,
                      big_hits=excluded.big_hits,
                      kakuhen_jitan=excluded.kakuhen_jitan,
                      max_balls=excluded.max_balls,
                      source_day_offset=0,
                      collected_at=CURRENT_TIMESTAMP
                """, (
                    record_date,
                    row["machine_number"],
                    model.machine_id,
                    model.name,
                    model.flags,
                    row["big_hits"],
                    row["kakuhen_jitan"],
                    row["max_balls"],
                ))

                detail_sources.append({
                    "machine_number": row["machine_number"],
                    "machine_id": model.machine_id,
                    "machine_name": model.name,
                    "flags": model.flags,
                    "detail_url": row["detail_url"],
                })

                records_processed += 1

            if sleep_sec:
                time.sleep(sleep_sec)

        collected_units = conn.execute(
            """
            SELECT COUNT(*)
            FROM daily_records
            WHERE record_date=?
            """,
            (record_date,),
        ).fetchone()[0]

        missing_units = (
            max(official_units - collected_units, 0)
            if official_units is not None
            else None
        )

        coverage_ratio = (
            collected_units / official_units
            if official_units not in (None, 0)
            else None
        )

        if official_units is not None:
            too_many_missing = (
                missing_units is not None
                and missing_units > MAX_MISSING_UNITS
            )
            too_low_ratio = (
                coverage_ratio is not None
                and coverage_ratio < MIN_COVERAGE_RATIO
            )

            if too_many_missing or too_low_ratio:
                raise RuntimeError(
                    "Incomplete snapshot rejected: "
                    f"official={official_units}, "
                    f"collected={collected_units}, "
                    f"missing={missing_units}, "
                    f"coverage={coverage_ratio:.3%}, "
                    f"model_errors={len(model_errors)}"
                )

        detect_changes(conn, record_date)

        conn.execute("""
            INSERT OR REPLACE INTO collection_coverage
            (
              record_date,official_units,collected_units,missing_units,
              model_count,models_with_no_rows,
              detail_links,unique_detail_links,duplicate_links,collected_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        """, (
            record_date,
            official_units,
            collected_units,
            missing_units,
            len(models),
            no_row_models,
            total_links,
            total_unique_links,
            total_duplicate_links,
        ))

        # Only hit all detail pages when a prior date actually needs repair.
        wanted_offsets = {
            offset
            for offset in range(1, BACKFILL_DAYS + 1)
            if _date_needs_backfill(
                conn,
                str(today - timedelta(days=offset)),
            )
        }

        backfill = apply_backfill(
            conn=conn,
            run_date=today,
            detail_sources=detail_sources,
            wanted_offsets=wanted_offsets,
            session=session,
            raw_dir=raw_dir,
            sleep_sec=sleep_sec,
        )

        # Re-run change detection for repaired neighboring dates.
        for offset in sorted(wanted_offsets, reverse=True):
            detect_changes(
                conn,
                str(today - timedelta(days=offset)),
            )
        detect_changes(conn, record_date)

        conn.commit()

    except Exception:
        conn.rollback()
        conn.close()
        raise

    summary = {
        "version": "2.4",
        "collected_on": record_date,
        "official_units": official_units,
        "collected_units": collected_units,
        "missing_units": missing_units,
        "coverage_ratio": coverage_ratio,
        "models": len(models),
        "model_errors": len(model_errors),
        "detail_links": total_links,
        "records_processed": records_processed,
        "backfill": backfill,
        "note": (
            "Same-day snapshots use JST. "
            "If yesterday/the day before is missing or all-blank, "
            "machine detail pages are used to recover 前日/前々日 data. "
            "Existing historical rows with real values are never overwritten."
        ),
    }

    _write_exports(
        conn,
        out_dir,
        summary,
    )

    conn.close()
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default="data",
    )
    ap.add_argument(
        "--sleep",
        type=float,
        default=0.35,
    )
    args = ap.parse_args()

    print(
        json.dumps(
            collect(
                Path(args.out),
                args.sleep,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
