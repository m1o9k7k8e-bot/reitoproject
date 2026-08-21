from __future__ import annotations

import html
import sqlite3
from collections import defaultdict
from pathlib import Path

DATA = Path("data")
DOCS = Path("docs")
SECTION_ID = "manual-review-candidates"


def esc(value):
    return html.escape("" if value is None else str(value))


def build():
    db = DATA / "reito.sqlite"
    page_path = DOCS / "index.html"
    if not db.exists() or not page_path.exists():
        raise SystemExit("Run collector.py and dashboard builders first.")

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_records)")}
    total_start_expr = "total_start" if "total_start" in cols else "NULL AS total_start"
    rows = conn.execute(
        f"""
        SELECT record_date,machine_number,machine_id,machine_name,
               big_hits,kakuhen_jitan,max_balls,{total_start_expr},collected_at
        FROM daily_records
        ORDER BY record_date,machine_number
        """
    ).fetchall()
    conn.close()

    by_machine = defaultdict(list)
    for r in rows:
        by_machine[str(r[1])].append(r)

    candidates = []
    for number, recs in by_machine.items():
        recs = sorted(recs, key=lambda r: (r[0], r[8] or ""))
        latest = recs[-1]
        current_mid = latest[2]

        generation = []
        for r in reversed(recs):
            if r[2] != current_mid:
                break
            generation.append(r)
        generation.reverse()

        usable = [r for r in generation if r[4] is not None or r[6] is not None]
        if not usable:
            continue

        ambiguous = [
            r for r in usable
            if (r[4] or 0) == 0 and (r[6] or 0) > 0
        ]
        sparse = [
            r for r in usable
            if r[4] is not None and r[4] <= 1 and (r[6] or 0) > 0
        ]
        if not ambiguous:
            continue

        latest_usable = usable[-1]
        latest_ambiguous = (latest_usable[4] or 0) == 0 and (latest_usable[6] or 0) > 0
        saved_total = latest_usable[7]

        candidates.append(
            {
                "number": number,
                "machine": latest[3],
                "observations": len(usable),
                "ambiguous_count": len(ambiguous),
                "sparse_count": len(sparse),
                "latest_date": latest_usable[0],
                "latest_hits": latest_usable[4],
                "latest_max_balls": latest_usable[6],
                "latest_total_start": saved_total,
                "latest_ambiguous": latest_ambiguous,
            }
        )

    # This is a data-review priority, not a gambling-performance ranking.
    candidates.sort(
        key=lambda x: (
            -int(x["latest_ambiguous"]),
            -x["ambiguous_count"],
            -x["sparse_count"],
            int(x["number"]) if x["number"].isdigit() else 999999,
        )
    )
    candidates = candidates[:10]

    parts = []
    for i, x in enumerate(candidates, start=1):
        total_text = "未取得" if x["latest_total_start"] is None else f"{int(x['latest_total_start']):,}"
        reason = (
            "最新スナップショットも0回＋持玉値あり"
            if x["latest_ambiguous"]
            else f"過去スナップショットで0回＋持玉値ありが{x['ambiguous_count']}回"
        )
        parts.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td><strong>{esc(x['number'])}</strong></td>"
            f"<td>{esc(x['machine'])}</td>"
            f"<td>{x['ambiguous_count']}/{x['observations']}</td>"
            f"<td>{esc(x['latest_date'])}</td>"
            f"<td>{'—' if x['latest_hits'] is None else int(x['latest_hits'])}</td>"
            f"<td>{'—' if x['latest_max_balls'] is None else f'{int(x['latest_max_balls']):,}'}</td>"
            f"<td>{esc(total_text)}</td>"
            f"<td>{esc(reason)}</td>"
            "</tr>"
        )

    table_rows = "\n".join(parts) or (
        '<tr><td colspan="9">現在、累計スタートを優先確認する候補はありません</td></tr>'
    )

    section = f"""
<section id="{SECTION_ID}" style="margin-top:32px">
<h2>累計スタート・手動確認候補</h2>
<p class="note">
この表は「打つべき台」や「そろそろ当たる台」の順位ではありません。
保存済みスナップショットの中で、大当り0回なのに最大持玉などに値があり、未稼働なのか実際に回された台なのかを
累計スタートで確認するとデータ解釈が改善する台を、確認作業用に最大10台まで並べています。
途中経過のスナップショットも含むため、「0回観測」は1日確定実績を意味しません。
手動で累計スタートを確認した場合は、その日付・台番号・累計スタートを記録すると後の分析に利用できます。
</p>
<div class="wrap" style="max-height:55vh">
<table id="manualReviewTable">
<thead><tr>
<th>確認順</th>
<th>台番号</th>
<th>機種</th>
<th>0回＋持玉値あり観測</th>
<th>最新観測日</th>
<th>最新大当り</th>
<th>最新最大持玉</th>
<th>累計スタート</th>
<th>確認理由</th>
</tr></thead>
<tbody>{table_rows}</tbody>
</table>
</div>
</section>
"""

    page = page_path.read_text(encoding="utf-8")
    marker = f'<section id="{SECTION_ID}"'
    if marker in page:
        start = page.index(marker)
        end = page.index("</section>", start) + len("</section>")
        page = page[:start] + section + page[end:]
    else:
        observed_marker = '<section id="observed-history"'
        if observed_marker in page:
            page = page.replace(observed_marker, section + "\n" + observed_marker, 1)
        else:
            page = page.replace("</main>", section + "\n</main>", 1)
    page_path.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    build()
