from __future__ import annotations

import csv
from pathlib import Path

BASE = Path("machine_specs.csv")
EXTRA = Path("machine_specs_extra.csv")
FIELDS = [
    "machine_id",
    "machine_name",
    "normal_odds",
    "right_odds",
    "entry_rate",
    "continuation_rate",
    "upper_rate",
    "source_url",
    "verified_at",
    "note",
]


def load(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    merged = {}
    for row in load(BASE) + load(EXTRA):
        try:
            key = str(int(row.get("machine_id", "")))
        except (TypeError, ValueError):
            continue
        merged[key] = {field: row.get(field, "") for field in FIELDS}

    ordered = sorted(merged.values(), key=lambda r: int(r["machine_id"]))
    with BASE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(ordered)

    print(f"Merged {len(ordered)} machine specification rows into {BASE}")


if __name__ == "__main__":
    main()
