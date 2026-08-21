from __future__ import annotations

import csv
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

DATA = Path("data")
RAW = DATA / "raw"
DB = DATA / "reito.sqlite"


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def to_int(value: str | None) -> int | None:
    if value is None:
        return None
    text = clean(value)
    if not text or text in {"-", "—", "---"}:
        return None
    m = re.search(r"[0-9][0-9,]*", text)
    return int(m.group(0).replace(",", "")) if m else None


def ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(daily_records)")}
    if "total_start" not in cols:
        conn.execute("ALTER TABLE daily_records ADD COLUMN total_start INTEGER")
    if "total_start_source" not in cols:
        conn.execute("ALTER TABLE daily_records ADD COLUMN total_start_source TEXT")
    conn.commit()


def find_section_table(soup: BeautifulSoup, label: str):
    for tag_name in ("h2", "h3", "h4", "h5", "h6", "dt", "p", "div"):
        for tag in soup.find_all(tag_name):
            if clean(tag.get_text(" ", strip=True)) != label:
                continue
            table = tag.find_next("table")
            if table is not None:
                return table

    node = soup.find(string=lambda s: clean(str(s)) == label if s else False)
    if node is not None and node.parent is not None:
        return node.parent.find_next("table")
    return None


def parse_total_start_from_table(table) -> int | None:
    if table is None:
        return None

    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [clean(x.get_text(" ", strip=True)) for x in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)

    for i, row in enumerate(rows):
        joined = " ".join(row)
        if "累計スタート" not in joined:
            continue
        if i + 1 < len(rows) and rows[i + 1]:
            value = to_int(rows[i + 1][0])
            if value is not None:
                return value

    text = " | ".join(cell for row in rows for cell in row)
    m = re.search(
        r"累計スタート\s*\|\s*最大(?:持玉|得玉).*?\|\s*([0-9,]+|-|—)",
        text,
    )
    return to_int(m.group(1)) if m else None


def parse_saved_detail(path: Path) -> dict[int, int]:
    try:
        html = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        html = path.read_text(encoding="utf-8", errors="replace")

    soup = BeautifulSoup(html, "html.parser")
    out: dict[int, int] = {}
    for offset, label in ((1, "前日"), (2, "前々日")):
        value = parse_total_start_from_table(find_section_table(soup, label))
        if value is not None:
            out[offset] = value
    return out


def export_csv(conn: sqlite3.Connection) -> None:
    path = DATA / "daily_records.csv"
    columns = [
        "record_date",
        "machine_number",
        "machine_id",
        "machine_name",
        "flags",
        "big_hits",
        "kakuhen_jitan",
        "max_balls",
        "total_start",
        "total_start_source",
        "source_day_offset",
        "collected_at",
    ]
    rows = conn.execute(
        """
        SELECT record_date,machine_number,machine_id,machine_name,flags,
               big_hits,kakuhen_jitan,max_balls,total_start,total_start_source,
               source_day_offset,collected_at
        FROM daily_records
        ORDER BY record_date,machine_number
        """
    ).fetchall()

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(rows)


def main() -> None:
    if not DB.exists():
        raise SystemExit("data/reito.sqlite not found")

    conn = sqlite3.connect(DB)
    ensure_columns(conn)

    parsed_files = 0
    values_found = 0
    rows_updated = 0

    if RAW.exists():
        for details_dir in sorted(RAW.glob("????-??-??/details")):
            try:
                source_date = date.fromisoformat(details_dir.parent.name)
            except ValueError:
                continue

            for path in sorted(details_dir.glob("*.html")):
                machine_number = path.stem
                if not re.fullmatch(r"\d{4}", machine_number):
                    continue

                parsed_files += 1
                history = parse_saved_detail(path)

                for offset, total_start in history.items():
                    values_found += 1
                    target_date = str(source_date - timedelta(days=offset))
                    cur = conn.execute(
                        """
                        UPDATE daily_records
                        SET total_start=?, total_start_source=?
                        WHERE record_date=? AND machine_number=?
                          AND (total_start IS NULL OR total_start_source LIKE 'saved_detail_%')
                        """,
                        (
                            total_start,
                            f"saved_detail_{offset}d",
                            target_date,
                            machine_number,
                        ),
                    )
                    rows_updated += cur.rowcount

    conn.commit()
    export_csv(conn)

    coverage = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN total_start IS NOT NULL THEN 1 ELSE 0 END) FROM daily_records"
    ).fetchone()
    conn.close()

    total_rows = coverage[0] or 0
    with_start = coverage[1] or 0
    print(
        f"saved detail files={parsed_files}, values_found={values_found}, "
        f"rows_updated={rows_updated}, total_start_coverage={with_start}/{total_rows}"
    )


if __name__ == "__main__":
    main()
