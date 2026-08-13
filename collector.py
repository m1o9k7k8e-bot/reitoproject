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
UA = "ReitoPachinkoResearch/1.0 (+low-frequency personal research collector)"


@dataclass
class MachineModel:
    machine_id: str
    name: str
    flags: str


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
        flags = ",".join(x for x in ("NEW", "増台", "オススメ") if x in label)
        name = label
        for x in ("NEW", "増台", "オススメ"):
            name = name.replace(x, "")
        name = clean(name)
        if name:
            found[mid] = MachineModel(mid, name, flags)
    return list(found.values())


def parse_machine_page(html: str, fallback_name: str) -> tuple[str, list[dict]]:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find(["h1", "h2", "h3"])
    name = clean(heading.get_text(" ", strip=True)) if heading else fallback_name
    for x in ("NEW", "増台", "オススメ"):
        name = name.replace(x, "")
    name = clean(name) or fallback_name

    text = soup.get_text("\n", strip=True)
    matches = list(re.finditer(r"(?m)^\s*(\d{4})\s*番台\s*$", text))
    rows = []
    for i, m in enumerate(matches):
        number = m.group(1)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[m.end():end]
        # Stop if we have reached the common footer/category links.
        block = block.split("1000／46枚S", 1)[0]

        def grab(pattern):
            mm = re.search(pattern, block)
            return int(mm.group(1).replace(",", "")) if mm else None

        rows.append({
            "machine_number": number,
            "big_hits": grab(r"大当\s*([0-9,]+)\s*回"),
            "kakuhen_jitan": grab(r"確変[／/]時短\s*([0-9,]+)\s*回"),
            "max_balls": grab(r"最大持玉\s*([0-9,]+)\s*玉"),
        })
    return name, rows


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
    session.headers.update({"User-Agent": UA, "Accept-Language": "ja-JP,ja;q=0.9"})

    index_url = f"{BASE}data.php?h={STORE_ID}&t={RATE_TYPE}"
    index_html = get(session, index_url)
    models = discover_models(index_html)
    if not models:
        raise RuntimeError("No machine models found; site structure may have changed.")

    conn = sqlite3.connect(db_path)
    init_db(conn)

    today = date.today()
    summary = {"collected_on": str(today), "models": len(models), "pages": 0, "records": 0}

    for day_offset in (0, 1, 2):
        record_date = str(today - timedelta(days=day_offset))
        day_raw = raw_dir / record_date
        day_raw.mkdir(parents=True, exist_ok=True)

        for idx, model in enumerate(models):
            url = f"{BASE}data.php?h={STORE_ID}&m={model.machine_id}&t={RATE_TYPE}"
            if day_offset:
                url += f"&d={day_offset}"
            html = get(session, url)
            summary["pages"] += 1
            (day_raw / f"{model.machine_id}_d{day_offset}.html").write_text(
                html, encoding="utf-8"
            )
            parsed_name, rows = parse_machine_page(html, model.name)
            for row in rows:
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
                    record_date, row["machine_number"], model.machine_id, parsed_name,
                    model.flags, row["big_hits"], row["kakuhen_jitan"], row["max_balls"],
                    day_offset
                ))
                summary["records"] += 1
            conn.commit()
            if sleep_sec:
                time.sleep(sleep_sec)

        detect_changes(conn, record_date)
        conn.commit()

    # Export CSV for transparency / easy analysis.
    with open(out_dir / "daily_records.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["record_date","machine_number","machine_id","machine_name","flags",
                    "big_hits","kakuhen_jitan","max_balls","source_day_offset","collected_at"])
        w.writerows(conn.execute("""
            SELECT record_date,machine_number,machine_id,machine_name,flags,
                   big_hits,kakuhen_jitan,max_balls,source_day_offset,collected_at
            FROM daily_records ORDER BY record_date,machine_number
        """))

    (out_dir / "last_run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    conn.close()
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--sleep", type=float, default=0.35,
                    help="seconds between machine-model page requests")
    args = ap.parse_args()
    print(json.dumps(collect(Path(args.out), args.sleep), ensure_ascii=False, indent=2))
