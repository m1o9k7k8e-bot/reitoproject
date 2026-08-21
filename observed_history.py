from __future__ import annotations

import html
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import median

DATA = Path("data")
DOCS = Path("docs")


def esc(value):
    return html.escape("" if value is None else str(value))


def build():
    db = DATA / "reito.sqlite"
    page_path = DOCS / "index.html"
    if not db.exists() or not page_path.exists():
        raise SystemExit("Run collector.py and dashboard builders first.")

    conn = sqlite3.connect(db)
    records = conn.execute(
        """
        SELECT record_date,machine_number,machine_id,machine_name,
               big_hits,kakuhen_jitan,max_balls
        FROM daily_records
        ORDER BY record_date,machine_number
        """
    ).fetchall()
    conn.close()
    if not records:
        return

    by_day = defaultdict(list)
    for r in records:
        by_day[r[0]].append(r)

    inactive_dates = {
        day
        for day, rows in by_day.items()
        if rows and all(r[4] is None and r[5] is None and r[6] is None for r in rows)
    }

    by_machine = defaultdict(list)
    for r in records:
        by_machine[str(r[1])].append(r)

    rows_out = []
    for num, recs in by_machine.items():
        recs = sorted(recs, key=lambda x: x[0])
        latest = recs[-1]
        current_mid = latest[2]

        generation = []
        for r in reversed(recs):
            if r[2] != current_mid:
                break
            generation.append(r)
        generation.reverse()

        usable = [r for r in generation if r[0] not in inactive_dates and r[4] is not None]
        if not usable:
            continue

        hits = [int(r[4]) for r in usable]
        hit_days = sum(1 for x in hits if x > 0)
        hit_day_rate = 100.0 * hit_days / len(hits)
        recent = hits[-7:]
        recent_hit_days = sum(1 for x in recent if x > 0)

        rows_out.append(
            {
                "number": num,
                "machine": latest[3],
                "days": len(hits),
                "hit_days": hit_days,
                "hit_day_rate": hit_day_rate,
                "median_hits": median(hits),
                "recent_n": len(recent),
                "recent_hit_days": recent_hit_days,
            }
        )

    def sort_key(item):
        try:
            return (0, int(item["number"]))
        except Exception:
            return (1, item["number"])

    rows_out.sort(key=sort_key)

    table_rows = "\n".join(
        "<tr>"
        f"<td>{esc(x['number'])}</td>"
        f"<td>{esc(x['machine'])}</td>"
        f"<td>{x['days']}</td>"
        f"<td>{x['hit_days']}/{x['days']} ({x['hit_day_rate']:.1f}%)</td>"
        f"<td>{x['median_hits']:.1f}</td>"
        f"<td>{x['recent_hit_days']}/{x['recent_n']}</td>"
        "</tr>"
        for x in rows_out
    ) or '<tr><td colspan="6">観測実績を計算できるデータがありません</td></tr>'

    section = f"""
<section id="observed-history" style="margin-top:32px">
<h2>台別・観測実績サマリー</h2>
<p class="note">
保存済みの日次実績だけを集計した記述統計です。「大当り記録あり日率」は、その台のデータが取得できた日のうち
大当り回数が1回以上だった日の割合で、1万円以内の初当たり確率や翌日の当たりやすさを表すものではありません。
レイト詳細画面には累計スタートの表示枠がありますが、保存済みHTMLでは数値本体が後読み込みのため残っておらず、
過去の通常回転数を正確に復元できません。このため大当り回数から初当たり確率を逆算していません。
</p>
<div class="wrap" style="max-height:65vh">
<table id="observedTable">
<thead><tr>
<th>台番号</th>
<th>機種</th>
<th>観測日数</th>
<th>大当り記録あり日</th>
<th>1日大当り中央値</th>
<th>直近最大7日・記録あり日</th>
</tr></thead>
<tbody>{table_rows}</tbody>
</table>
</div>
</section>
"""

    page = page_path.read_text(encoding="utf-8")
    marker = '<section id="observed-history"'
    if marker in page:
        start = page.index(marker)
        end = page.index("</section>", start) + len("</section>")
        page = page[:start] + section + page[end:]
    else:
        page = page.replace("</main>", section + "\n</main>", 1)
    page_path.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    build()
