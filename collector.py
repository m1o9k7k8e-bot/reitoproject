from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

BASE = "https://reitoweb.com/b_moba/doc/"
STORE_ID = "11"
RATE_TYPE = "6"
UA = "ReitoPachinkoResearch/2.2 (+low-frequency personal research collector)"

GET_RETRIES = 6
CONNECT_TIMEOUT = 60
READ_TIMEOUT = 60
MAX_MISSING_UNITS = 5
MIN_COVERAGE_RATIO = 0.98


@dataclass
class MachineModel:
    machine_id: str
    name: str
    flags: str


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def get(session: requests.Session, url: str, retries: int = GET_RETRIES) -> str:
    """GET with exponential backoff.

    Connection failures are common enough that a single transient outage should
    not kill the daily snapshot immediately.
    """
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
    m = re.search(r"4åããã³ã³\s*([0-9,]+)\s*å°", text)
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
        if q.get("h", [""])[0] != STORE_ID or q.get("t", [""])[0] != RATE_TYPE:
            continue
        mid = q.get("m", [""])[0]
        if not mid:
            continue

        label = clean(a.get_text(" ", strip=True))
        if not label:
            continue
        flags = [x for x in ("NEW", "å¢å°", "ãªã¹ã¹ã¡") if x in label]
        name = label
        for x in ("NEW", "å¢å°", "ãªã¹ã¹ã¡"):
            name = name.replace(x, "")
        name = clean(name)

        if name:
            found[mid] = MachineModel(mid, name, ",".join(flags))

    return list(found.values())


def _grab_int(text: str, pattern: str):
    m = re.search(pattern, text)
    return int(m.group(1).replace(",", "")) if m else None


def parse_machine_page(html: str, expected_machine_id: str) -> tuple[list[dict], dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows_by_number: dict[str, dict] = {}
    link_numbers: list[str] = []

    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"])
        p = urlparse(href)
        if not p.path.endswith("/machine.php"):
            continue
        q = parse_qs(p.query)
        if q.get("h", [""])[0] != STORE_ID or q.get("t", [""])[0] != RATE_TYPE:
            continue
        mid = q.get("m", [""])[0]
        num = q.get("n", [""])[0]
        if mid != expected_machine_id or not re.fullmatch(r"\d{4}", num):
            continue

        link_numbers.append(num)
        card = a.find_parent("div", class_=lambda c: c and "card" in str(c).split())
        if card is None:
            card = a.parent
        block = clean(card.get_text(" ", strip=True)) if card else ""

        rows_by_number[num] = {
            "machine_number": num,
            "big_hits": _grab_int(block, r"å¤§å½\s*([0-9,]+)\s*å"),
            "kakuhen_jitan": _grab_int(block, r"ç¢ºå¤[ï¼/]\s*æç­\s*([0-9,]+)\s*å"),
            "max_balls": _grab_int(block, r"æå¤§æç\s*([0-9,]+)\s*ç"),
        }

    rows = list(rows_by_number.values())
    status = "ok" if rows else "parsed_zero"
    return rows, {
        "page_status": status,
        "detail_link_count": len(link_numbers),
        "unique_detail_links": len(set(link_numbers)),
        "parsed_rows": len(rows),
        "duplicate_link_count": len(link_numbers) - len(set(link_numbers)),
    }


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
    """)


def remove_unreliable_seed_history(conn: sqlite3.Connection):
    conn.execute("DELETE FROM daily_records WHERE source_day_offset > 0")
    conn.execute("""
        DELETE FROM collection_coverage
        WHERE record_date NOT IN (SELECT DISTINCT record_date FROM daily_records)
    """)
    conn.commit()


def detect_changes(conn: sqlite3.Connection, target_date: str):
    prev = conn.execute(
        "SELECT MAX(record_date) FROM daily_records WHERE record_date < ?", (target_date,)
    ).fetchone()[0]
    if not prev:
        return

    current = {
        r[0]: r[1:] for r in conn.execute(
            "SELECT machine_number,machine_id,machine_name FROM daily_records WHERE record_date=?",
            (target_date,)
        )
    }
    previous = {
        r[0]: r[1:] for r in conn.execute(
            "SELECT machine_number,machine_id,machine_name FROM daily_records WHERE record_date=?",
            (prev,)
        )
    }
    for num, (new_id, new_name) in current.items():
        if num in previous:
            old_id, old_name = previous[num]
            if old_id != new_id:
                conn.execute("""
                INSERT OR IGNORE INTO machine_changes
                (change_date,machine_number,old_machine_id,old_machine_name,new_machine_id,new_machine_name)
                VALUES (?,?,?,?,?,?)
                """, (target_date, num, old_id, old_name, new_id, new_name))


def _write_exports(conn: sqlite3.Connection, out_dir: Path, summary: dict):
    with open(out_dir / "daily_records.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "record_date","machine_number","machine_id","machine_name","flags",
            "big_hits","kakuhen_jitan","max_balls","source_day_offset","collected_at"
        ])
        w.writerows(conn.execute("""
            SELECT record_date,machine_number,machine_id,machine_name,flags,
                   big_hits,kakuhen_jitan,max_balls,source_day_offset,collected_at
            FROM daily_records ORDER BY record_date,machine_number
        """))

    (out_dir / "last_run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
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
        raise RuntimeError("No machine models found; site structure may have changed.")

    conn = sqlite3.connect(db_path)
    init_db(conn)
    remove_unreliable_seed_history(conn)

    today = date.today()
    record_date = str(today)
    day_raw = raw_dir / record_date
    day_raw.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"index_{today}.html").write_text(index_html, encoding="utf-8")

    total_links = total_unique_links = total_duplicate_links = 0
    no_row_models = 0
    records_processed = 0
    model_errors: list[dict] = []

    # One run is one transaction. If coverage is insufficient, rollback so that
    # an earlier successful snapshot from the same day is never damaged.
    conn.execute("BEGIN")

    try:
        for model in models:
            url = f"{BASE}data.php?h={STORE_ID}&m={model.machine_id}&t={RATE_TYPE}"
            try:
                page = get(session, url)
            except Exception as e:
                model_errors.append({
                    "machine_id": model.machine_id,
                    "machine_name": model.name,
                    "error": str(e),
                })
                print(f"[ERROR] model fetch failed: {model.machine_id} {model.name}: {e}", flush=True)
                continue

            (day_raw / f"{model.machine_id}_d0.html").write_text(page, encoding="utf-8")
            rows, diag = parse_machine_page(page, model.machine_id)
            total_links += diag["detail_link_count"]
            total_unique_links += diag["unique_detail_links"]
            total_duplicate_links += diag["duplicate_link_count"]

            if not rows:
                no_row_models += 1

            for row in rows:
                conn.execute("""
                INSERT INTO daily_records
                (record_date,machine_number,machine_id,machine_name,flags,
                 big_hits,kakuhen_jitan,max_balls,source_day_offset)
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
                    record_date, row["machine_number"], model.machine_id, model.name,
                    model.flags, row["big_hits"], row["kakuhen_jitan"], row["max_balls"]
                ))
                records_processed += 1

            if sleep_sec:
                time.sleep(sleep_sec)

        collected_units = conn.execute(
            "SELECT COUNT(*) FROM daily_records WHERE record_date=?", (record_date,)
        ).fetchone()[0]

        missing_units = (
            max(official_units - collected_units, 0)
            if official_units is not None else None
        )
        coverage_ratio = (
            collected_units / official_units
            if official_units not in (None, 0) else None
        )

        if official_units is not None:
            too_many_missing = missing_units is not None and missing_units > MAX_MISSING_UNITS
            too_low_ratio = coverage_ratio is not None and coverage_ratio < MIN_COVERAGE_RATIO
            if too_many_missing or too_low_ratio:
                raise RuntimeError(
                    "Incomplete snapshot rejected: "
                    f"official={official_units}, collected={collected_units}, "
                    f"missing={missing_units}, coverage={coverage_ratio:.3%}, "
                    f"model_errors={len(model_errors)}"
                )

        detect_changes(conn, record_date)

        conn.execute("""
            INSERT OR REPLACE INTO collection_coverage
            (record_date,official_units,collected_units,missing_units,model_count,
             models_with_no_rows,detail_links,unique_detail_links,duplicate_links,collected_at)
            VALUES (?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        """, (
            record_date, official_units, collected_units, missing_units, len(models),
            no_row_models, total_links, total_unique_links, total_duplicate_links
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        conn.close()
        raise

    summary = {
        "version": "2.2",
        "collected_on": record_date,
        "official_units": official_units,
        "collected_units": collected_units,
        "missing_units": missing_units,
        "coverage_ratio": coverage_ratio,
        "models": len(models),
        "model_errors": len(model_errors),
        "detail_links": total_links,
        "records_processed": records_processed,
        "note": (
            "Only real same-day snapshots are stored. "
            "A run is committed only when coverage passes quality checks."
        ),
    }

    _write_exports(conn, out_dir, summary)
    conn.close()
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--sleep", type=float, default=0.35)
    args = ap.parse_args()
    print(json.dumps(collect(Path(args.out), args.sleep), ensure_ascii=False, indent=2))
