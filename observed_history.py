from __future__ import annotations

import html
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, time, timezone
from pathlib import Path
from statistics import mean, median, pstdev
from zoneinfo import ZoneInfo

DATA = Path("data")
DOCS = Path("docs")
JST = ZoneInfo("Asia/Tokyo")
STORE_CLOSE = time(22, 45)


def esc(value):
    return html.escape("" if value is None else str(value))


def wilson_interval(successes: int, total: int, z: float = 1.96):
    """Wilson 95% interval for an observed end-of-day binary proportion."""
    if total <= 0:
        return None, None
    p = successes / total
    z2 = z * z
    denom = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) / total) + (z2 / (4 * total * total))) / denom
    return 100.0 * max(0.0, center - margin), 100.0 * min(1.0, center + margin)


def percentile(values, p: float):
    vals = sorted(values)
    if not vals:
        return None
    if len(vals) == 1:
        return float(vals[0])
    pos = (len(vals) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(vals[lo])
    weight = pos - lo
    return vals[lo] * (1.0 - weight) + vals[hi] * weight


def is_end_of_day_record(record_date: str, source_day_offset: int, collected_at: str) -> bool:
    """Return True only when a row can reasonably be treated as a completed day.

    Backfilled rows (offset > 0) are parsed from the site's previous-day sections and
    are treated as completed-day observations. Same-day rows are accepted only when
    the snapshot was collected after the store closes (22:45 JST) on record_date.
    SQLite CURRENT_TIMESTAMP is UTC, so collected_at is converted to JST explicitly.
    """
    if int(source_day_offset or 0) > 0:
        return True
    try:
        stamp = datetime.strptime(collected_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        local = stamp.astimezone(JST)
        target = datetime.strptime(record_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return local.date() == target and local.time() >= STORE_CLOSE


def build():
    db = DATA / "reito.sqlite"
    page_path = DOCS / "index.html"
    if not db.exists() or not page_path.exists():
        raise SystemExit("Run collector.py and dashboard builders first.")

    conn = sqlite3.connect(db)
    records = conn.execute(
        """
        SELECT record_date,machine_number,machine_id,machine_name,
               big_hits,kakuhen_jitan,max_balls,source_day_offset,collected_at
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

    qualified_dates = {
        day
        for day, rows in by_day.items()
        if any(is_end_of_day_record(r[0], r[7], r[8]) for r in rows)
    }

    by_machine = defaultdict(list)
    for r in records:
        by_machine[str(r[1])].append(r)

    rows_out = []
    model_units = defaultdict(list)

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

        usable = [
            r
            for r in generation
            if r[0] not in inactive_dates
            and r[0] in qualified_dates
            and is_end_of_day_record(r[0], r[7], r[8])
            and r[4] is not None
        ]
        if not usable:
            continue

        hits = [int(r[4]) for r in usable]
        hit_days = sum(1 for x in hits if x > 0)
        hit_day_rate = 100.0 * hit_days / len(hits)
        ci_low, ci_high = wilson_interval(hit_days, len(hits))
        recent = hits[-7:]
        recent_hit_days = sum(1 for x in recent if x > 0)

        rows_out.append(
            {
                "number": num,
                "machine_id": current_mid,
                "machine": latest[3],
                "days": len(hits),
                "hit_days": hit_days,
                "hit_day_rate": hit_day_rate,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "median_hits": median(hits),
                "recent_n": len(recent),
                "recent_hit_days": recent_hit_days,
            }
        )

        model_key = (str(current_mid), latest[3])
        model_units[model_key].append({"number": num, "hits": hits})

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
        f"<td>{x['hit_days']}/{x['days']} ({x['hit_day_rate']:.1f}%)"
        f"<br><small>95%区間 {x['ci_low']:.1f}–{x['ci_high']:.1f}%</small></td>"
        f"<td>{x['median_hits']:.1f}</td>"
        f"<td>{x['recent_hit_days']}/{x['recent_n']}</td>"
        "</tr>"
        for x in rows_out
    ) or '<tr><td colspan="6">閉店後の確定スナップショットがまだ十分ありません</td></tr>'

    model_rows_data = []
    for (_mid, machine_name), units in model_units.items():
        all_hits = [value for unit in units for value in unit["hits"]]
        if not all_hits:
            continue
        hit_days = sum(1 for x in all_hits if x > 0)
        rate = 100.0 * hit_days / len(all_hits)
        ci_low, ci_high = wilson_interval(hit_days, len(all_hits))
        q1 = percentile(all_hits, 0.25)
        q3 = percentile(all_hits, 0.75)
        unit_means = [mean(unit["hits"]) for unit in units if unit["hits"]]
        unit_cv = None
        if len(unit_means) >= 2:
            m = mean(unit_means)
            if m != 0:
                unit_cv = 100.0 * pstdev(unit_means) / abs(m)

        model_rows_data.append(
            {
                "machine": machine_name,
                "units": len(units),
                "unit_days": len(all_hits),
                "hit_days": hit_days,
                "rate": rate,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "mean_hits": mean(all_hits),
                "median_hits": median(all_hits),
                "q1": q1,
                "q3": q3,
                "unit_cv": unit_cv,
            }
        )

    model_rows_data.sort(key=lambda x: (-x["units"], x["machine"]))

    model_parts = []
    for x in model_rows_data:
        cv_text = "—" if x["unit_cv"] is None else f"{x['unit_cv']:.1f}%"
        model_parts.append(
            "<tr>"
            f"<td>{esc(x['machine'])}</td>"
            f"<td>{x['units']}</td>"
            f"<td>{x['unit_days']}</td>"
            f"<td>{x['hit_days']}/{x['unit_days']} ({x['rate']:.1f}%)"
            f"<br><small>95%区間 {x['ci_low']:.1f}–{x['ci_high']:.1f}%</small></td>"
            f"<td>{x['mean_hits']:.1f}</td>"
            f"<td>{x['median_hits']:.1f}</td>"
            f"<td>{x['q1']:.1f}–{x['q3']:.1f}</td>"
            f"<td>{cv_text}</td>"
            "</tr>"
        )
    model_table_rows = "\n".join(model_parts) or '<tr><td colspan="8">閉店後の確定スナップショットがまだ十分ありません</td></tr>'

    qualified_text = "、".join(sorted(qualified_dates)) if qualified_dates else "なし"

    section = f"""
<section id="observed-history" style="margin-top:32px">
<h2>台別・閉店後実績サマリー</h2>
<p class="note">
日中の途中経過を1日分の実績と誤認しないよう、日次統計には原則として閉店時刻22:45以降に取得した当日スナップショットだけを使用します。
信頼できる前日・前々日バックフィルがある場合はそれも確定日として採用します。現在の採用日: {esc(qualified_text)}。
「大当り記録あり日率」は採用できた確定日のうち大当り回数が1回以上だった日の割合で、翌日の当たりやすさを表すものではありません。
通常回転数・累計スタートが保存されていないため、大当り回数から初当たり確率や「そろそろ当たる」を逆算していません。
</p>
<div class="wrap" style="max-height:65vh">
<table id="observedTable">
<thead><tr>
<th>台番号</th>
<th>機種</th>
<th>確定観測日数</th>
<th>大当り記録あり日</th>
<th>1日大当り中央値</th>
<th>直近最大7確定日・記録あり日</th>
</tr></thead>
<tbody>{table_rows}</tbody>
</table>
</div>

<h3>機種別・閉店後実績ばらつき統計</h3>
<p class="note">
同一機種について、閉店後に確定した「台×日」だけをまとめています。IQRは1日大当り回数の中央50%範囲です。
「台別平均CV」は各台の1日平均大当り回数のばらつきを平均値に対する割合で示す記述指標です。
稼働量や通常回転数が不明なので、設定・釘・勝率・期待値の差とは解釈できません。
</p>
<div class="wrap" style="max-height:65vh">
<table id="modelObservedTable">
<thead><tr>
<th>機種</th>
<th>現在台数</th>
<th>確定観測台日</th>
<th>大当り記録あり台日</th>
<th>1日平均</th>
<th>1日中央値</th>
<th>IQR</th>
<th>台別平均CV</th>
</tr></thead>
<tbody>{model_table_rows}</tbody>
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
