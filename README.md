# レイトつくば 4円パチンコ公開データ記録アプリ

レイトつくば公式Webで公開されている **4円パチンコ** の台データを低頻度で取得し、
日付ごとに保存して、機種入替も追跡する個人研究用プロジェクトです。

## Ver.1でできること

- 4円パチンコの機種一覧を自動検出
- 各機種の当日・前日・前々日の公開データを取得
- 台番号ごとに以下を保存
  - 機種ID / 機種名
  - 大当り回数
  - 確変 / 時短回数
  - 最大持玉
  - NEW / 増台 / オススメ表示
- 同じ台番号の機種IDが変わった場合、新装・入替として自動記録
- SQLite + CSVで長期保存
- iPhone Safariでも見やすい静的Webダッシュボードを生成
- GitHub Actionsで毎日23:30 JST頃に自動収集

## 重要

このアプリは「次に当たる台」を予測するものではありません。
パチンコの抽選結果そのものを過去の当たり履歴から予知することはできません。

今後データが蓄積したら、店の公開データ上の稼働・機種配置・入替・曜日などに
再現性のある偏りが存在するかをバックテストする機能を追加する想定です。

また、公式サイト自身がデータのリアルタイム性・整合性を保証していません。
欠損値や遅延は分析時に考慮してください。

## GitHubで使う手順

1. GitHubで新しい空のリポジトリを作る
2. このフォルダの中身をすべてアップロード
3. GitHubの **Actions** タブで `Collect Reito pachinko data` を開く
4. `Run workflow` を押して初回収集
5. 実行後、`data/` と `docs/index.html` が自動更新される
6. **Settings → Pages → Build and deployment**
7. Sourceを **Deploy from a branch**
8. Branchを `main`、Folderを `/docs` にして保存

これでSafariからダッシュボードを見られます。

## ローカル実行

```bash
pip install -r requirements.txt
python src/collector.py --out data
python src/build_site.py
```

その後 `docs/index.html` をブラウザで開きます。

## データ構造

`daily_records`
- record_date
- machine_number
- machine_id
- machine_name
- flags
- big_hits
- kakuhen_jitan
- max_balls
- source_day_offset
- collected_at

`machine_changes`
- change_date
- machine_number
- old_machine_id
- old_machine_name
- new_machine_id
- new_machine_name

台番号は「場所」、machine_idは「その場所に設置された機種世代」として扱えます。

## 今後のVer.2候補

- 累計スタート等の個別台詳細取得
- 曜日 / 新装後日数 / 機種齢の特徴量
- 台番号の長期傾向と機種固有傾向の分離
- 7日・30日ローリング統計
- ウォークフォワード・バックテスト
- 翌日「候補度」のランキング
- 予測精度とランダム選択の比較
