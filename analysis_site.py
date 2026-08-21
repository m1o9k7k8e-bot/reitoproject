from __future__ import annotations

import html
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

DATA = Path("data")
DOCS = Path("docs")


def esc(value):
    return html.escape("" if value is None else str(value))


def weekday_jp(value: str):
    names = ["月", "火", "水", "木", "金", "土", "日"]
    return names[datetime.strptime(value, "%Y-%m-%d").weekday()]


def safe_mean(values):
    vals = [v for v in values if v is not None]
    return mean(vals) if vals else None


def fmt(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f}"


def build():
    db = DATA / "reito.sqlite"
    page_path = DOCS / "index.html"
    if not db.exists() or not page_path.exists():
        raise SystemExit("Run collector.py and build_site.py first.")

    conn = sqlite3.connect(db)
    records = conn.execute("""
        SELECT record_date,machine_number,machine_id,machine_name,flags,
               big_hits,kakuhen_jitan,max_balls
        FROM daily_records
        ORDER BY record_date,machine_number
    """).fetchall()
    conn.close()

    if not records:
        return

    by_day = defaultdict(list)
    for r in records:
        by_day[r[0]].append(r)

    inactive_dates = {
        day
        for day, rows in by_day.items()
        if rows and all(r[5] is None and r[6] is None and r[7] is None for r in rows)
    }
    active_dates = sorted(d for d in by_day if d not in inactive_dates)

    weekday_rows = defaultdict(list)
    for day in active_dates:
        weekday_rows[weekday_jp(day)].extend(by_day[day])

    weekday_order = ["月", "火", "水", "木", "金", "土", "日"]
    weekday_table = []
    for wd in weekday_order:
        rows = weekday_rows.get(wd, [])
        if not rows:
            continue
        dates = {r[0] for r in rows}
        weekday_table.append(
            "<tr>"
            f"<td>{wd}</td>"
            f"<td>{len(dates)}</td>"
            f"<td>{fmt(safe_mean([r[5] for r in rows]))}</td>"
            f"<td>{fmt(safe_mean([r[7] for r in rows]))}</td>"
            "</tr>"
        )

    daily_metrics = []
    for day in active_dates:
        rows = by_day[day]
        daily_metrics.append({
            "date": day,
            "weekday": weekday_jp(day),
            "avg_hits": safe_mean([r[5] for r in rows]),
            "avg_balls": safe_mean([r[7] for r in rows]),
            "units": len(rows),
        })

    # Walk-forward validation of store-wide weekday effect only.
    # This evaluates whether same-weekday aggregate history has predictive
    # value for the store-wide daily average. It never ranks individual machines.
    bt = []
    for i, cur in enumerate(daily_metrics):
        if i < 3 or cur["avg_balls"] is None:
            continue
        past = daily_metrics[:i]
        past_same = [x["avg_balls"] for x in past if x["weekday"] == cur["weekday"] and x["avg_balls"] is not None]
        past_all = [x["avg_balls"] for x in past if x["avg_balls"] is not None]
        if not past_all:
            continue
        weekday_pred = safe_mean(past_same) if past_same else safe_mean(past_all)
        baseline_pred = safe_mean(past_all)
        bt.append({
            "date": cur["date"],
            "actual": cur["avg_balls"],
            "weekday_pred": weekday_pred,
            "baseline_pred": baseline_pred,
            "weekday_abs_error": abs(cur["avg_balls"] - weekday_pred),
            "baseline_abs_error": abs(cur["avg_balls"] - baseline_pred),
        })

    weekday_mae = safe_mean([x["weekday_abs_error"] for x in bt])
    baseline_mae = safe_mean([x["baseline_abs_error"] for x in bt])
    improvement = None
    if weekday_mae is not None and baseline_mae not in (None, 0):
        improvement = 100 * (baseline_mae - weekday_mae) / baseline_mae

    recent_bt = "\n".join(
        "<tr>"
        f"<td>{esc(x['date'])}</td>"
        f"<td>{fmt(x['actual'])}</td>"
        f"<td>{fmt(x['weekday_pred'])}</td>"
        f"<td>{fmt(x['baseline_pred'])}</td>"
        "</tr>"
        for x in bt[-14:]
    ) or '<tr><td colspan="4">検証に必要な日数がまだ不足しています</td></tr>'

    changes = 0
    try:
        conn = sqlite3.connect(db)
        changes = conn.execute("SELECT COUNT(*) FROM machine_changes").fetchone()[0]
        conn.close()
    except Exception:
        pass

    section = f"""
<section id="historical-validation" style="margin-top:32px">
<h2>店舗全体の履歴分析・再現性検証</h2>
<p class="note">
このセクションは、公開済みの過去データを使って店舗全体の曜日差やデータ安定性を検証するものです。
個別台の当選確率、期待値、翌日の推奨台を示すものではありません。
</p>
<div class="cards">
  <div class="card"><div>統計採用日</div><div class="big">{len(active_dates)}</div></div>
  <div class="card"><div>休業/未更新候補</div><div class="big">{len(inactive_dates)}</div></div>
  <div class="card"><div>入替検出</div><div class="big">{changes}</div></div>
  <div class="card"><div>検証日数</div><div class="big">{len(bt)}</div></div>
</div>

<h3>曜日別・店舗全体平均</h3>
<div class="wrap" style="max-height:none">
<table>
<thead><tr><th>曜日</th><th>日数</th><th>平均大当り</th><th>平均最大持玉</th></tr></thead>
<tbody>{''.join(weekday_table)}</tbody>
</table>
</div>

<h3>ウォークフォワード再現性検証</h3>
<p class="note">
各日について、その日より前のデータだけを使い「同じ曜日の店舗全体平均」を推定し、
単純な全曜日平均と誤差を比較します。未来データは計算に使いません。
</p>
<div class="cards">
  <div class="card"><div>同曜日モデル MAE</div><div class="big">{fmt(weekday_mae)}</div></div>
  <div class="card"><div>単純平均 MAE</div><div class="big">{fmt(baseline_mae)}</div></div>
  <div class="card"><div>誤差改善率</div><div class="big">{fmt(improvement)}%</div></div>
</div>
<div class="wrap" style="max-height:50vh">
<table>
<thead><tr><th>日付</th><th>実績 平均最大持玉</th><th>同曜日推定</th><th>単純平均推定</th></tr></thead>
<tbody>{recent_bt}</tbody>
</table>
</div>
</section>
"""

    page = page_path.read_text(encoding="utf-8")
    marker = '<section id="historical-validation"'
    if marker in page:
        start = page.index(marker)
        end = page.index("</section>", start) + len("</section>")
        page = page[:start] + section + page[end:]
    else:
        page = page.replace("</main>", section + "\n</main>", 1)
    page_path.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    build()
