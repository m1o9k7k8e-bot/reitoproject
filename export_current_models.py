from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

DATA = Path("data")


def main():
    db = DATA / "reito.sqlite"
    if not db.exists():
        raise SystemExit("data/reito.sqlite not found")

    conn = sqlite3.connect(db)
    latest = conn.execute("SELECT MAX(record_date) FROM daily_records").fetchone()[0]
    rows = conn.execute(
        """
        SELECT DISTINCT machine_id, machine_name
        FROM daily_records
        WHERE record_date = ?
        ORDER BY CAST(machine_id AS INTEGER), machine_name
        """,
        (latest,),
    ).fetchall()
    conn.close()

    out = DATA / "current_models.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["record_date", "machine_id", "machine_name"])
        for machine_id, machine_name in rows:
            writer.writerow([latest, machine_id, machine_name])

    print(f"wrote {len(rows)} current models to {out}")


if __name__ == "__main__":
    main()
