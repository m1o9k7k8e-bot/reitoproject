from __future__ import annotations

import html
import sqlite3
from pathlib import Path

DATA = Path("data")
DOCS = Path("docs")


def esc(x):
    return html.escape("" if x is None else str(x))


def build():
    db = DATA / "reito.sqlite"
    if not db.exists():
        raise SystemExit("data/reito.sqlite not found. Run collector first.")

    DOCS.mkdir(exist_ok=True)
    conn = sqlite3.connect(db)

    latest = conn.execute(
        "SELECT MAX(record_date) FROM daily_records"
    ).fetchone()[0]

    rows = conn.execute("""
      SELECT machine_number,machine_name,flags,big_hits,kakuhen_jitan,max_balls,machine_id
      FROM daily_records
      WHERE record_date=?
      ORDER BY machine_number
    """, (latest,)).fetchall()

    model_count = conn.execute("""
      SELECT COUNT(DISTINCT machine_id)
      FROM daily_records
      WHERE record_date=?
    """, (latest,)).fetchone()[0]

    coverage = conn.execute("""
      SELECT official_units,collected_units,missing_units,model_count,models_with_no_rows
      FROM collection_coverage
      WHERE record_date=?
    """, (latest,)).fetchone()

    if coverage:
        official_units, collected_units, missing_units, listed_models, no_row_models = coverage
    else:
        official_units = None
        collected_units = len(rows)
        missing_units = None
        listed_models = model_count
        no_row_models = 0

    issues = conn.execute("""
      SELECT machine_name,expected_units,page_status
      FROM collection_issues
      WHERE record_date=?
      ORDER BY machine_name
    """, (latest,)).fetchall()

    changes = conn.execute("""
      SELECT change_date,machine_number,old_machine_name,new_machine_name
      FROM machine_changes
      ORDER BY change_date DESC,machine_number
      LIMIT 100
    """).fetchall()

    # This is only a same-day performance index, NOT a prediction.
    maxvals = [r[5] or 0 for r in rows]
    hitvals = [r[3] or 0 for r in rows]
    max_max = max(maxvals or [1]) or 1
    max_hit = max(hitvals or [1]) or 1

    scored = []
    for r in rows:
        score = round(
            100 * (
                0.65 * ((r[5] or 0) / max_max) +
                0.35 * ((r[3] or 0) / max_hit)
            ), 1
        )
        scored.append((*r, score))
    scored.sort(key=lambda x: x[-1], reverse=True)

    table = "\n".join(
        f"<tr><td>{esc(r[0])}</td><td>{esc(r[1])}</td><td>{esc(r[2])}</td>"
        f"<td>{esc(r[3])}</td><td>{esc(r[4])}</td><td>{esc(r[5])}</td>"
        f"<td>{r[-1]}</td></tr>"
        for r in scored
    )

    change_rows = "\n".join(
        f"<tr><td>{esc(c[0])}</td><td>{esc(c[1])}</td>"
        f"<td>{esc(c[2])}</td><td>{esc(c[3])}</td></tr>"
        for c in changes
    ) or '<tr><td colspan="4">まだ入替履歴はありません</td></tr>'

    issue_rows = "\n".join(
        f"<tr><td>{esc(i[0])}</td><td>{esc(i[1])}</td><td>{esc(i[2])}</td></tr>"
        for i in issues
    ) or '<tr><td colspan="3">当日の機種ページ欠損は検出されませんでした</td></tr>'

    official_display = official_units if official_units is not None else "—"
    missing_display = missing_units if missing_units is not None else "—"
    coverage_class = "ok" if (missing_units in (0, None)) else "warn"

    page = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>レイトつくば 4円パチンコ記録</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f5f5f7;color:#1d1d1f}}
main{{max-width:1050px;margin:auto;padding:18px}}
h1{{font-size:25px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.card{{background:white;border-radius:14px;padding:16px;box-shadow:0 1px 5px #0001}}
.big{{font-size:28px;font-weight:700}}
.ok{{color:#167c3a}} .warn{{color:#a45a00}}
table{{width:100%;border-collapse:collapse;background:white}}
th,td{{padding:9px;border-bottom:1px solid #ddd;text-align:left;font-size:13px;vertical-align:top}}
th{{position:sticky;top:0;background:#fff}}
.wrap{{overflow:auto;max-height:68vh;border-radius:12px}}
input{{width:100%;box-sizing:border-box;padding:12px;border:1px solid #ccc;border-radius:10px;margin:8px 0 12px}}
.note{{font-size:12px;color:#666;line-height:1.6}}
.badge{{display:inline-block;padding:3px 7px;border-radius:8px;background:#eee;font-size:11px}}
@media(max-width:650px){{
  .cards{{grid-template-columns:1fr 1fr}}
  th,td{{font-size:12px;padding:7px}}
}}
</style>
</head>
<body><main>

<h1>レイトつくば 4円パチンコ記録</h1>

<div class="cards">
  <div class="card"><div>最新記録日</div><div class="big">{esc(latest)}</div></div>
  <div class="card"><div>公式掲載台数</div><div class="big">{official_display}</div></div>
  <div class="card"><div>取得台数</div><div class="big">{collected_units}</div></div>
  <div class="card"><div>未取得</div><div class="big {coverage_class}">{missing_display}</div></div>
</div>

<p class="note">
一覧ページで確認できた機種数: {listed_models}。
データ行が0件だった機種ページ: {no_row_models}。
「未取得」が0でない日は、公式ページ側の一時的な未掲載・新台切替・HTML形式差などを含む可能性があります。
</p>

<h2>全台一覧</h2>
<p class="note">
「当日実績指数」は当日の公開データ（最大持玉65%＋大当り35%）を相対化しただけの指標です。
勝率・期待値・翌日の当たりやすさを示す予測ではありません。
</p>

<input id="q" placeholder="台番号・機種名で検索">
<div class="wrap">
<table id="tbl">
<thead><tr>
<th>台番号</th><th>機種</th><th>表示</th><th>大当り</th>
<th>確変/時短</th><th>最大持玉</th><th>当日実績指数</th>
</tr></thead>
<tbody>{table}</tbody>
</table>
</div>

<h2>取得診断</h2>
<table>
<thead><tr><th>データ行0件の機種</th><th>一覧上の台数</th><th>状態</th></tr></thead>
<tbody>{issue_rows}</tbody>
</table>

<h2>新装・入替検出</h2>
<table>
<thead><tr><th>日付</th><th>台番号</th><th>旧機種</th><th>新機種</th></tr></thead>
<tbody>{change_rows}</tbody>
</table>

<p class="note">
出典: レイトつくば公式Webの公開台データ。
公式サイトはデータのリアルタイム性・整合性を保証していないため、
本記録も欠損・遅延・一時的不整合を含む可能性があります。
</p>

</main>
<script>
const q=document.getElementById('q');
const rows=[...document.querySelectorAll('#tbl tbody tr')];
q.addEventListener('input',()=>{{
  const s=q.value.toLowerCase();
  rows.forEach(r=>r.style.display=r.innerText.toLowerCase().includes(s)?'':'none');
}});
</script>
</body></html>"""

    (DOCS / "index.html").write_text(page, encoding="utf-8")
    conn.close()


if __name__ == "__main__":
    build()
