from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

BASE = "https://reitoweb.com/b_moba/doc/"
STORE_ID = "11"
RATE_TYPE = "6"  # 4円パチンコ
UA = "ReitoPachinkoResearch/1.1 (+low-frequency personal research collector)"


@dataclass
class MachineModel:
    machine_id: str
    name: str
    flags: str
    expected_units: int | None = None


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def get(session: requests.Session, url: str, retries: int = 3) -> str:
    last = None
    for i in range(retries):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"GET failed: {url}: {last}")


def official_total_units(html: str) -> int | None:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = re.search(r"4円パチンコ\s*([0-9,]+)\s*台", text)
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

        flags_list = []
        for flag in ("NEW", "増台", "オススメ"):
            if flag in label:
                flags_list.append(flag)

        # 一覧ページのアンカーテキストを正式機種名として使う。
        # "NEW増台ｅ○○" のような連結表記にも対応。
        name = label
        for flag in ("NEW", "増台", "オススメ"):
            name = name.replace(flag, "")
        name = clean(name)

        # 親要素に "(4 台)" 等があれば参考値として保存。
        expected_units = None
        parent_text = clean(a.parent.get_text(" ", strip=True)) if a.parent else ""
        m_units = re.search(r"[\(（]\s*([0-9,]+)\s*台\s*[\)）]", parent_text)
        if m_units:
            expected_units = int(m_units.group(1).replace(",", ""))

        if name:
            found[mid] = MachineModel(
                machine_id=mid,
                name=name,
                flags=",".join(flags_list),
                expected_units=expected_units,
            )

    return list(found.values())


def parse_machine_page(html: str) -> tuple[list[dict], str]:
    """Return rows and page status. Machine name is intentionally NOT parsed here."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    if "当日分のデータが見つかりませんでした" in text:
        page_status = "no_data"
    else:
        page_status = "ok"

    matches = list(re.finditer(r"(?m)^\s*(\d{4})\s*番台\s*$", text))
    rows = []

    for i, m in enumerate(matches):
        number = m.group(1)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[m.end():end]

        # Footer/rate-category area is not part of this machine block.
        for marker in ("1000／46枚S", "4円パチンコ", "レイトグループ"):
            block = block.split(marker, 1)[0]

        def grab(pattern):
            mm = re.search(pattern, block)
            return int(mm.group(1).replace(",", "")) if mm else None

        rows.append({
            "machine_number": number,
            "big_hits": grab(r"大当\s*([0-9,]+)\s*回"),
            "kakuhen_jitan": grab(r"確変[／/]\s*時短\s*([0-9,]+)\s*回"),
            "max_balls": grab(r"最大持玉\s*([0-9,]+)\s*玉"),
        })

    if not rows and page_status == "ok":
        page_status = "parsed_zero"

    return rows, page_status


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
      collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS collection_issues (
      record_date TEXT NOT NULL,
      machine_id TEXT NOT NULL,
      machine_name TEXT NOT NULL,
      expected_units INTEGER,
      page_status TEXT NOT NULL,
      PRIMARY KEY (record_date, machine_id)
    );
    """)


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


def collect(out_dir: Path, sleep_sec: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(exist_ok=True)
    db_path = out_dir / "reito.sqlite"

    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "ja-JP,ja;q=0.9",
    })

    index_url = f"{BASE}data.php?h={STORE_ID}&t={RATE_TYPE}"
    index_html = get(session, index_url)
    models = discover_models(index_html)
    official_units = official_total_units(index_html)

    if not models:
        raise RuntimeError("No machine models found; site structure may have changed.")

    conn = sqlite3.connect(db_path)
    init_db(conn)

    today = date.today()
    summary = {
        "collected_on": str(today),
        "official_units": official_units,
        "models": len(models),
        "pages": 0,
        "records_processed": 0,
        "coverage": {},
    }

    # Save the index itself too.
    (raw_dir / f"index_{today}.html").write_text(index_html, encoding="utf-8")

    for day_offset in (0, 1, 2):
        record_date = str(today - timedelta(days=day_offset))
        day_raw = raw_dir / record_date
        day_raw.mkdir(parents=True, exist_ok=True)

        conn.execute("DELETE FROM collection_issues WHERE record_date=?", (record_date,))
        no_row_models = 0

        for model in models:
            url = f"{BASE}data.php?h={STORE_ID}&m={model.machine_id}&t={RATE_TYPE}"
            if day_offset:
                url += f"&d={day_offset}"

            html = get(session, url)
            summary["pages"] += 1
            (day_raw / f"{model.machine_id}_d{day_offset}.html").write_text(
                html, encoding="utf-8"
            )

            rows, page_status = parse_machine_page(html)

            if not rows:
                no_row_models += 1
                conn.execute("""
                    INSERT OR REPLACE INTO collection_issues
                    (record_date,machine_id,machine_name,expected_units,page_status)
                    VALUES (?,?,?,?,?)
                """, (
                    record_date, model.machine_id, model.name,
                    model.expected_units, page_status
                ))

            for row in rows:
                # IMPORTANT: always use name from the machine-list page.
                conn.execute("""
                INSERT INTO daily_records
                (record_date,machine_number,machine_id,machine_name,flags,
                 big_hits,kakuhen_jitan,max_balls,source_day_offset)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(record_date,machine_number) DO UPDATE SET
                  machine_id=excluded.machine_id,
                  machine_name=excluded.machine_name,
                  flags=excluded.flags,
                  big_hits=excluded.big_hits,
                  kakuhen_jitan=excluded.kakuhen_jitan,
                  max_balls=excluded.max_balls,
                  source_day_offset=MIN(daily_records.source_day_offset, excluded.source_day_offset),
                  collected_at=CURRENT_TIMESTAMP
                """, (
                    record_date, row["machine_number"], model.machine_id, model.name,
                    model.flags, row["big_hits"], row["kakuhen_jitan"],
                    row["max_balls"], day_offset
                ))
                summary["records_processed"] += 1

            conn.commit()
            if sleep_sec:
                time.sleep(sleep_sec)

        detect_changes(conn, record_date)

        collected_units = conn.execute(
            "SELECT COUNT(*) FROM daily_records WHERE record_date=?", (record_date,)
        ).fetchone()[0]

        # Official total is current-day information. For prior days it is only a reference.
        official_for_day = official_units if day_offset == 0 else None
        missing_units = (
            max(official_units - collected_units, 0)
            if day_offset == 0 and official_units is not None
            else None
        )

        conn.execute("""
            INSERT OR REPLACE INTO collection_coverage
            (record_date,official_units,collected_units,missing_units,
             model_count,models_with_no_rows,collected_at)
            VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
        """, (
            record_date, official_for_day, collected_units, missing_units,
            len(models), no_row_models
        ))
        conn.commit()

        summary["coverage"][record_date] = {
            "official_units": official_for_day,
            "collected_units": collected_units,
            "missing_units": missing_units,
            "models_with_no_rows": no_row_models,
        }

    # Export main records.
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

    # Export diagnostics.
    with open(out_dir / "collection_issues.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["record_date","machine_id","machine_name","expected_units","page_status"])
        w.writerows(conn.execute("""
            SELECT record_date,machine_id,machine_name,expected_units,page_status
            FROM collection_issues ORDER BY record_date,machine_name
        """))

    (out_dir / "last_run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    conn.close()
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument(
        "--sleep", type=float, default=0.35,
        help="seconds between machine-model page requests"
    )
    args = ap.parse_args()
    print(json.dumps(
        collect(Path(args.out), args.sleep),
        ensure_ascii=False, indent=2
    ))
