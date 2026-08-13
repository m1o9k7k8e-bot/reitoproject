from __future__ import annotations
import html
import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DATA = Path("data")
DOCS = Path("docs")


def esc(x):
    return html.escape("" if x is None else str(x))


def weekday_jp(d):
    names = ["月", "火", "水", "木", "金", "土", "日"]
    return names[datetime.strptime(d, "%Y-%m-%d").weekday()]


def avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def build():
    db = DATA / "reito.sqlite"
    if not db.exists():
        raise SystemExit("data/reito.sqlite not found. Run collector first.")
    DOCS.mkdir(exist_ok=True)

    conn = sqlite3.connect(db)
    latest = conn.execute("SELECT MAX(record_date) FROM daily_records").fetchone()[0]

    rows = conn.execute("""
      SELECT machine_number,machine_name,flags,big_hits,kakuhen_jitan,max_balls,machine_id
      FROM daily_records WHERE record_date=? ORDER BY machine_number
    """, (latest,)).fetchall()

    coverage = conn.execute("""
      SELECT official_units,collected_units,missing_units,model_count,models_with_no_rows,
             detail_links,unique_detail_links,duplicate_links
      FROM collection_coverage WHERE record_date=?
    """, (latest,)).fetchone()

    if coverage:
        (official_units,collected_units,missing_units,listed_models,no_row_models,
         detail_links,unique_detail_links,duplicate_links) = coverage
    else:
        official_units = None
        collected_units = len(rows)
        missing_units = None
        listed_models = conn.execute(
            "SELECT COUNT(DISTINCT machine_id) FROM daily_records WHERE record_date=?", (latest,)
        ).fetchone()[0]
        no_row_models = detail_links = unique_detail_links = duplicate_links = 0

    changes = conn.execute("""
      SELECT change_date,machine_number,old_machine_name,new_machine_name
      FROM machine_changes ORDER BY change_date DESC,machine_number LIMIT 100
    """).fetchall()

    all_records = conn.execute("""
      SELECT record_date,machine_number,machine_id,machine_name,flags,big_hits,kakuhen_jitan,max_balls
      FROM daily_records ORDER BY record_date,machine_number
    """).fetchall()

    # Current-day score
    maxvals = [r[5] or 0 for r in rows]
    hitvals = [r[3] or 0 for r in rows]
    max_max = max(maxvals or [1]) or 1
    max_hit = max(hitvals or [1]) or 1

    scored = []
    for r in rows:
        score = round(100 * (
            0.65 * ((r[5] or 0) / max_max) +
            0.35 * ((r[3] or 0) / max_hit)
        ), 1)
        scored.append((*r, score))
    scored.sort(key=lambda x: x[-1], reverse=True)

    # History cache by machine number
    histories = defaultdict(list)
    for rec in all_records:
        histories[rec[1]].append(rec)

    table = "\n".join(
        f'<tr data-num="{esc(r[0])}" onclick="showHistory(\'{esc(r[0])}\')" class="clickrow">'
        f"<td>{esc(r[0])}</td><td>{esc(r[1])}</td><td>{esc(r[2])}</td>"
        f"<td>{esc(r[3])}</td><td>{esc(r[4])}</td><td>{esc(r[5])}</td><td>{r[-1]}</td></tr>"
        for r in scored
    )

    history_payload = {}
    for num, recs in histories.items():
        recs = sorted(recs, key=lambda x: x[0])
        latest_rec = recs[-1]
        last7 = recs[-7:]
        last30 = recs[-30:]
        by_weekday = defaultdict(list)
        for rr in recs:
            by_weekday[weekday_jp(rr[0])].append(rr)

        # current generation start date
        current_mid = latest_rec[2]
        generation = []
        for rr in reversed(recs):
            if rr[2] != current_mid:
                break
            generation.append(rr)
        generation = list(reversed(generation))

        history_payload[num] = {
            "number": num,
            "current_machine": latest_rec[3],
            "current_machine_id": latest_rec[2],
            "generation_start": generation[0][0] if generation else latest_rec[0],
            "generation_days": len(generation),
            "records": [
                {
                    "date": rr[0],
                    "weekday": weekday_jp(rr[0]),
                    "machine": rr[3],
                    "machine_id": rr[2],
                    "flags": rr[4],
                    "big_hits": rr[5],
                    "kakuhen_jitan": rr[6],
                    "max_balls": rr[7],
                } for rr in recs[-60:]
            ],
            "avg7": {
                "big_hits": avg([x[5] for x in last7]),
                "kakuhen_jitan": avg([x[6] for x in last7]),
                "max_balls": avg([x[7] for x in last7]),
            },
            "avg30": {
                "big_hits": avg([x[5] for x in last30]),
                "kakuhen_jitan": avg([x[6] for x in last30]),
                "max_balls": avg([x[7] for x in last30]),
            },
            "weekday": {
                wd: {
                    "count": len(v),
                    "big_hits": avg([x[5] for x in v]),
                    "max_balls": avg([x[7] for x in v]),
                }
                for wd, v in by_weekday.items()
            }
        }

    change_rows = "\n".join(
        f"<tr><td>{esc(c[0])}</td><td>{esc(c[1])}</td><td>{esc(c[2])}</td><td>{esc(c[3])}</td></tr>"
        for c in changes
    ) or '<tr><td colspan="4">まだ入替履歴はありません</td></tr>'

    official_display = official_units if official_units is not None else "—"
    missing_display = missing_units if missing_units is not None else "—"
    coverage_class = "ok" if missing_units in (0, None) else "warn"

    page = f"""<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>レイトつくば 4円パチンコ分析</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f5f5f7;color:#1d1d1f}}
main{{max-width:1050px;margin:auto;padding:18px}} h1{{font-size:25px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.card{{background:white;border-radius:14px;padding:16px;box-shadow:0 1px 5px #0001}}
.big{{font-size:28px;font-weight:700}} .ok{{color:#167c3a}} .warn{{color:#a45a00}}
table{{width:100%;border-collapse:collapse;background:white}}
th,td{{padding:9px;border-bottom:1px solid #ddd;text-align:left;font-size:13px;vertical-align:top}}
th{{position:sticky;top:0;background:#fff}} .wrap{{overflow:auto;max-height:68vh;border-radius:12px}}
input{{width:100%;box-sizing:border-box;padding:12px;border:1px solid #ccc;border-radius:10px;margin:8px 0 12px}}
.note{{font-size:12px;color:#666;line-height:1.6}}
.clickrow{{cursor:pointer}}
.drawer{{position:fixed;left:0;right:0;bottom:0;background:#fff;border-radius:18px 18px 0 0;box-shadow:0 -8px 30px #0003;max-height:82vh;overflow:auto;padding:18px;display:none;z-index:20}}
.drawer.open{{display:block}}
.drawer h2{{margin-top:0}}
.closebtn{{float:right;border:0;background:#eee;border-radius:999px;width:36px;height:36px;font-size:20px}}
.mini{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.mini .card{{padding:12px}}
.histtable th,.histtable td{{font-size:12px}}
@media(max-width:650px){{.cards{{grid-template-columns:1fr 1fr}} th,td{{font-size:12px;padding:7px}} .mini{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main>

<h1>レイトつくば 4円パチンコ分析</h1>
<div class="cards">
<div class="card"><div>最新記録日</div><div class="big">{esc(latest)}</div></div>
<div class="card"><div>公式掲載台数</div><div class="big">{official_display}</div></div>
<div class="card"><div>取得台数</div><div class="big">{collected_units}</div></div>
<div class="card"><div>未取得</div><div class="big {coverage_class}">{missing_display}</div></div>
</div>

<p class="note">
機種数 {listed_models} ／ 詳細リンク検出 {detail_links}件 ／ ユニーク詳細リンク {unique_detail_links}件 ／ 重複リンク {duplicate_links}件。
</p>

<h2>全台一覧</h2>
<p class="note">
台番号をタップすると、その設置位置の履歴・7日/30日平均・曜日別傾向を表示します。
「当日実績指数」は当日の公開値の相対指標で、翌日の当たりやすさや期待値の予測ではありません。
</p>
<input id="q" placeholder="台番号・機種名で検索">
<div class="wrap"><table id="tbl">
<thead><tr><th>台番号</th><th>機種</th><th>表示</th><th>大当り</th><th>確変/時短</th><th>最大持玉</th><th>当日実績指数</th></tr></thead>
<tbody>{table}</tbody></table></div>

<h2>新装・入替検出</h2>
<table><thead><tr><th>日付</th><th>台番号</th><th>旧機種</th><th>新機種</th></tr></thead>
<tbody>{change_rows}</tbody></table>

<p class="note">出典: レイトつくば公式Web公開台データ。公開元の更新遅延や一時的不整合を含む可能性があります。</p>
</main>

<div id="drawer" class="drawer">
<button class="closebtn" onclick="closeHistory()">×</button>
<div id="drawerContent"></div>
</div>

<script>
const HIST={json.dumps(history_payload, ensure_ascii=False)};
const q=document.getElementById('q'), rows=[...document.querySelectorAll('#tbl tbody tr')];
q.addEventListener('input',()=>{{const s=q.value.toLowerCase();rows.forEach(r=>r.style.display=r.innerText.toLowerCase().includes(s)?'':'none')}});

function v(x){{return x===null||x===undefined?'—':x}}
function showHistory(num){{
  const h=HIST[num]; if(!h) return;
  const wdOrder=['月','火','水','木','金','土','日'];
  const wdRows=wdOrder.filter(w=>h.weekday[w]).map(w=>{{
    const d=h.weekday[w];
    return `<tr><td>${{w}}</td><td>${{d.count}}</td><td>${{v(d.big_hits)}}</td><td>${{v(d.max_balls)}}</td></tr>`;
  }}).join('');
  const recRows=[...h.records].reverse().map(r=>`
    <tr><td>${{r.date}}(${{r.weekday}})</td><td>${{r.machine}}</td><td>${{v(r.big_hits)}}</td><td>${{v(r.kakuhen_jitan)}}</td><td>${{v(r.max_balls)}}</td></tr>
  `).join('');
  document.getElementById('drawerContent').innerHTML=`
    <h2>${{h.number}}番台</h2>
    <p><b>現在:</b> ${{h.current_machine}}</p>
    <p class="note">現機種世代の推定開始日: ${{h.generation_start}} ／ 保存日数: ${{h.generation_days}}日</p>
    <div class="mini">
      <div class="card"><div>7日平均 大当り</div><div class="big">${{v(h.avg7.big_hits)}}</div></div>
      <div class="card"><div>7日平均 最大持玉</div><div class="big">${{v(h.avg7.max_balls)}}</div></div>
      <div class="card"><div>30日平均 大当り</div><div class="big">${{v(h.avg30.big_hits)}}</div></div>
      <div class="card"><div>30日平均 最大持玉</div><div class="big">${{v(h.avg30.max_balls)}}</div></div>
    </div>
    <h3>曜日別傾向</h3>
    <table><thead><tr><th>曜日</th><th>日数</th><th>平均大当り</th><th>平均最大持玉</th></tr></thead><tbody>${{wdRows}}</tbody></table>
    <h3>日別履歴</h3>
    <table class="histtable"><thead><tr><th>日付</th><th>機種</th><th>大当り</th><th>確変/時短</th><th>最大持玉</th></tr></thead><tbody>${{recRows}}</tbody></table>
  `;
  document.getElementById('drawer').classList.add('open');
}}
function closeHistory(){{document.getElementById('drawer').classList.remove('open')}}
</script>
</body></html>"""

    (DOCS / "index.html").write_text(page, encoding="utf-8")
    conn.close()

if __name__ == "__main__":
    build()
