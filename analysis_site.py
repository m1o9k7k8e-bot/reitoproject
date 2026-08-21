from __future__ import annotations

import csv
import html
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev

DATA = Path("data")
DOCS = Path("docs")
SPECS = Path("machine_specs.csv")


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


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def pct_distance(a, b):
    if a is None or b is None:
        return 0.0
    return abs(a - b) / max(abs(b), 1.0)


def load_specs():
    specs = {}
    if not SPECS.exists():
        return specs
    with SPECS.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                mid = str(int(row.get("machine_id", "")))
            except (TypeError, ValueError):
                continue
            specs[mid] = row
    return specs


def spec_cell(spec):
    if not spec:
        return '<span title="公表値を型式照合できていません">未登録</span>'

    lines = []
    normal = spec.get("normal_odds", "").strip()
    right = spec.get("right_odds", "").strip()
    entry = spec.get("entry_rate", "").strip()
    cont = spec.get("continuation_rate", "").strip()
    upper = spec.get("upper_rate", "").strip()
    note = spec.get("note", "").strip()
    source = spec.get("source_url", "").strip()

    if normal:
        lines.append(f"<b>通常 {esc(normal)}</b>")
    if right:
        lines.append(f"右/ST {esc(right)}")
    rates = []
    if entry:
        rates.append(f"突入 {esc(entry)}")
    if cont:
        rates.append(f"継続 {esc(cont)}")
    if upper:
        rates.append(f"上位 {esc(upper)}")
    if rates:
        lines.append(" / ".join(rates))
    if note:
        lines.append(f'<small>{esc(note)}</small>')
    if source:
        lines.append(
            f'<a href="{esc(source)}" target="_blank" rel="noopener noreferrer">出典</a>'
        )
    return "<br>".join(lines) if lines else "未登録"


def normal_denominator(spec):
    """Extract the first published 1/N denominator from the normal-odds text."""
    if not spec:
        return None
    text = spec.get("normal_odds", "").strip()
    m = re.search(r"1\s*/\s*([0-9]+(?:\.[0-9]+)?)", text)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    return value if value > 1 else None


def hit_probability(denominator, spins):
    if denominator is None or spins <= 0:
        return None
    return 100.0 * (1.0 - (1.0 - 1.0 / denominator) ** spins)


def budget_probability_cell(spec):
    """Neutral theoretical first-hit probabilities for a fixed 10,000-yen budget.

    No actual machine rotation rate is inferred. Three illustrative rotation-rate
    scenarios are shown instead: 12, 15, and 18 spins per 1,000 yen.
    """
    denominator = normal_denominator(spec)
    if denominator is None:
        return '<span title="通常時の固定1/N確率として算出できない機種です">算出対象外</span>'

    scenarios = []
    for spins_per_1000 in (12, 15, 18):
        spins = spins_per_1000 * 10
        prob = hit_probability(denominator, spins)
        scenarios.append(f"{spins_per_1000}回/k: {prob:.1f}%")
    return "<br>".join(scenarios)


def build():
    db = DATA / "reito.sqlite"
    page_path = DOCS / "index.html"
    if not db.exists() or not page_path.exists():
        raise SystemExit("Run collector.py and build_site.py first.")

    conn = sqlite3.connect(db)
    records = conn.execute(
        """
        SELECT record_date,machine_number,machine_id,machine_name,flags,
               big_hits,kakuhen_jitan,max_balls
        FROM daily_records
        ORDER BY record_date,machine_number
        """
    ).fetchall()
    conn.close()
    if not records:
        return

    specs = load_specs()

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

    weekday_table = []
    for wd in ["月", "火", "水", "木", "金", "土", "日"]:
        rows = weekday_rows.get(wd, [])
        if not rows:
            continue
        weekday_table.append(
            "<tr>"
            f"<td>{wd}</td>"
            f"<td>{len({r[0] for r in rows})}</td>"
            f"<td>{fmt(safe_mean([r[5] for r in rows]))}</td>"
            f"<td>{fmt(safe_mean([r[7] for r in rows]))}</td>"
            "</tr>"
        )

    daily_metrics = []
    for day in active_dates:
        rows = by_day[day]
        daily_metrics.append(
            {
                "date": day,
                "weekday": weekday_jp(day),
                "avg_balls": safe_mean([r[7] for r in rows]),
            }
        )

    bt = []
    for i, cur in enumerate(daily_metrics):
        if i < 3 or cur["avg_balls"] is None:
            continue
        past = daily_metrics[:i]
        past_same = [
            x["avg_balls"]
            for x in past
            if x["weekday"] == cur["weekday"] and x["avg_balls"] is not None
        ]
        past_all = [x["avg_balls"] for x in past if x["avg_balls"] is not None]
        if not past_all:
            continue
        weekday_pred = safe_mean(past_same) if past_same else safe_mean(past_all)
        baseline_pred = safe_mean(past_all)
        bt.append(
            {
                "date": cur["date"],
                "actual": cur["avg_balls"],
                "weekday_pred": weekday_pred,
                "baseline_pred": baseline_pred,
                "weekday_abs_error": abs(cur["avg_balls"] - weekday_pred),
                "baseline_abs_error": abs(cur["avg_balls"] - baseline_pred),
            }
        )

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

    by_machine = defaultdict(list)
    for r in records:
        by_machine[str(r[1])].append(r)

    latest_date = max(by_day)
    latest_weekday = weekday_jp(latest_date)
    machine_features = []

    for num, recs in by_machine.items():
        recs = sorted(recs, key=lambda x: x[0])
        latest_rec = recs[-1]
        current_mid = latest_rec[2]

        generation = []
        for rr in reversed(recs):
            if rr[2] != current_mid:
                break
            generation.append(rr)
        generation.reverse()
        usable = [rr for rr in generation if rr[0] not in inactive_dates]
        if not usable:
            continue

        last7 = usable[-7:]
        last30 = usable[-30:]
        same_wd = [rr for rr in usable if weekday_jp(rr[0]) == latest_weekday]

        avg7_balls = safe_mean([rr[7] for rr in last7])
        avg30_balls = safe_mean([rr[7] for rr in last30])
        wd_balls = safe_mean([rr[7] for rr in same_wd])
        avg7_hits = safe_mean([rr[5] for rr in last7])
        avg30_hits = safe_mean([rr[5] for rr in last30])

        ball_vals = [rr[7] for rr in last30 if rr[7] is not None]
        cv = 0.0
        if len(ball_vals) >= 2:
            m = mean(ball_vals)
            if m:
                cv = pstdev(ball_vals) / abs(m)

        score = clamp(
            100
            * (
                0.35 * min(pct_distance(avg7_balls, avg30_balls), 1.0)
                + 0.20 * min(pct_distance(wd_balls, avg30_balls), 1.0)
                + 0.20 * min(pct_distance(avg7_hits, avg30_hits), 1.0)
                + 0.15 * (min(cv, 2.0) / 2.0)
                + 0.10 * (min(len(usable), 30) / 30.0)
            )
        )

        machine_features.append(
            {
                "number": num,
                "machine_id": str(current_mid),
                "machine": latest_rec[3],
                "days": len(usable),
                "avg7_balls": avg7_balls,
                "avg30_balls": avg30_balls,
                "weekday_balls": wd_balls,
                "avg7_hits": avg7_hits,
                "score": round(score, 1),
            }
        )

    def machine_sort_key(item):
        try:
            return (0, int(item["number"]))
        except Exception:
            return (1, item["number"])

    machine_features.sort(key=machine_sort_key)

    current_types = {x["machine_id"] for x in machine_features}
    registered_types = len(current_types & set(specs))

    machine_rows = "\n".join(
        "<tr>"
        f"<td>{esc(x['number'])}</td>"
        f"<td>{esc(x['machine'])}</td>"
        f"<td>{spec_cell(specs.get(x['machine_id']))}</td>"
        f"<td>{budget_probability_cell(specs.get(x['machine_id']))}</td>"
        f"<td data-sort=\"{x['days']}\">{x['days']}</td>"
        f"<td data-sort=\"{'' if x['avg7_balls'] is None else x['avg7_balls']}\">{fmt(x['avg7_balls'])}</td>"
        f"<td data-sort=\"{'' if x['avg30_balls'] is None else x['avg30_balls']}\">{fmt(x['avg30_balls'])}</td>"
        f"<td data-sort=\"{'' if x['weekday_balls'] is None else x['weekday_balls']}\">{fmt(x['weekday_balls'])}</td>"
        f"<td data-sort=\"{'' if x['avg7_hits'] is None else x['avg7_hits']}\">{fmt(x['avg7_hits'])}</td>"
        f"<td data-sort=\"{x['score']}\"><b>{x['score']:.1f}</b></td>"
        "</tr>"
        for x in machine_features
    ) or '<tr><td colspan="10">台別履歴を計算できるデータがありません</td></tr>'

    section = f"""
<section id="historical-validation" style="margin-top:32px">
<h2>店舗全体の履歴分析・再現性検証</h2>
<p class="note">
公開済みの過去データを使った履歴分析です。公表スペックは型式ごとの仕様値で、店舗の実績値とは別物です。
履歴特徴スコアも勝率・期待値・翌日の当たりやすさを示すものではありません。
</p>
<div class="cards">
  <div class="card"><div>統計採用日</div><div class="big">{len(active_dates)}</div></div>
  <div class="card"><div>休業/未更新候補</div><div class="big">{len(inactive_dates)}</div></div>
  <div class="card"><div>入替検出</div><div class="big">{changes}</div></div>
  <div class="card"><div>公表スペック登録</div><div class="big">{registered_types}/{len(current_types)}</div></div>
</div>

<h3>台別・履歴特徴スコア ＋ 公表スペック</h3>
<p class="note">
「公表スペック」には型式を照合できた機種だけ、通常時確率・右打ち/ST中確率・RUSH/ST突入率・継続率を表示します。
「1万円 初当たり理論確率」は、公表された通常時1/N確率から、1,000円あたり12回・15回・18回回せると仮定した場合に、
合計1万円までに初当たりを1回以上引く理論確率を示します。実際の回転率・釘・交換条件・遊タイム・RUSH等は反映しません。
羽根モノなど固定の通常時1/Nとして扱えない機種は「算出対象外」とします。この列は推奨順位には使用しません。
</p>
<div class="wrap" style="max-height:65vh">
<table id="featureTable">
<thead><tr>
<th onclick="sortFeatureTable(0,false)">台番号 ↕</th>
<th onclick="sortFeatureTable(1,false)">機種 ↕</th>
<th>公表スペック</th>
<th>1万円 初当たり理論確率</th>
<th onclick="sortFeatureTable(4,true)">採用日数 ↕</th>
<th onclick="sortFeatureTable(5,true)">7日平均持玉 ↕</th>
<th onclick="sortFeatureTable(6,true)">30日平均持玉 ↕</th>
<th onclick="sortFeatureTable(7,true)">{latest_weekday}曜平均持玉 ↕</th>
<th onclick="sortFeatureTable(8,true)">7日平均大当り ↕</th>
<th onclick="sortFeatureTable(9,true)">履歴特徴スコア ↕</th>
</tr></thead>
<tbody>{machine_rows}</tbody>
</table>
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
各日について、その日より前のデータだけを使い「同じ曜日の店舗全体平均」を推定し、単純な全曜日平均と誤差を比較します。
未来データは計算に使いません。
</p>
<div class="cards">
  <div class="card"><div>検証日数</div><div class="big">{len(bt)}</div></div>
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
<script>
let featureSortDir = {{}};
function sortFeatureTable(col, numeric) {{
  const table = document.getElementById('featureTable');
  if (!table) return;
  const body = table.tBodies[0];
  const rows = Array.from(body.rows);
  const asc = !(featureSortDir[col] ?? false);
  featureSortDir[col] = asc;
  rows.sort((a,b) => {{
    let av = a.cells[col].dataset.sort ?? a.cells[col].innerText.trim();
    let bv = b.cells[col].dataset.sort ?? b.cells[col].innerText.trim();
    if (numeric) {{
      av = parseFloat(av); bv = parseFloat(bv);
      if (Number.isNaN(av)) av = -Infinity;
      if (Number.isNaN(bv)) bv = -Infinity;
      return asc ? av-bv : bv-av;
    }}
    return asc ? av.localeCompare(bv, 'ja', {{numeric:true}}) : bv.localeCompare(av, 'ja', {{numeric:true}});
  }});
  rows.forEach(r => body.appendChild(r));
}}
</script>
"""

    page = page_path.read_text(encoding="utf-8")
    marker = '<section id="historical-validation"'
    if marker in page:
        start = page.index(marker)
        end = page.index("</section>", start) + len("</section>")
        after = page[end:]
        script_marker = "<script>\nlet featureSortDir = {}"
        if script_marker in after[:3000]:
            s = after.index(script_marker)
            e = after.index("</script>", s) + len("</script>")
            after = after[:s] + after[e:]
        page = page[:start] + section + after
    else:
        page = page.replace("</main>", section + "\n</main>", 1)
    page_path.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    build()
