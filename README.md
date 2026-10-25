# PL Watch ・ ネタバレなし観戦ノート

プレミアリーグを「後から観る」人のためのサイトです。
スタメン・フォーメーション・ベンチ・欠場者だけを表示し、**スコア・得点者・順位は一切取得しません。**

- 表示: `index.html`（PC・スマホ両対応、GitHub Pages で公開）
- データ更新: `scripts/update.py`（GitHub Actions が1時間ごとに自動実行）
- データ元: ESPN（日程・スタメン）、プレミアリーグ公式（選手写真）

---

## 画面の使い方

| 場所 | 意味 |
|---|---|
| 次に観る試合 | まだ「観た」にしていない一番古い試合。スタメン・ベンチ・欠場者が見られます |
| その後の試合 | ロック中。上の試合を「観た」にすると順に解放されます |
| 今後の日程 | まだ始まっていない試合。キックオフ約1時間前からスタメンが出ます |
| 観た試合 | 「観た」にした試合。いつでも見返せます |
| ⚙ 設定 | ロックのオン/オフ、観た記録のリセット |

「観た」の記録はブラウザ（localStorage）に保存されます。スマホとPCで別々に記録されます。

### なぜロックするのか

次の試合のスタメンを見ると「あの選手がいない → 前の試合で怪我した？」のように展開が推測できてしまうためです。
気にしない場合は設定でロックをオフにできます。

---

## 欠場理由を書く（absences.json）

欠場者は「選手名鑑 − 当日のメンバー」で自動検出しますが、理由までは自動で取れません。
`absences.json` に書くと表示されます。

```json
{
  "man-utd": [
    { "name": "Mazraoui", "type": "負傷", "reason": "ハムストリング", "from": "2026-10-01", "until": "2026-11-15" },
    { "name": "Bruno Fernandes", "type": "出場停止", "reason": "累積警告" }
  ]
}
```

- `name` は英語表記。姓だけでも一致します
- `from` / `until` は省略可。書くとその期間の試合にだけ適用されます
- 保存して GitHub に push すると、次回の自動更新から反映されます（過去の試合には再生成時のみ反映）

---

## チームを追加する（teams.json）

```json
{
  "id": "arsenal",
  "name": "Arsenal",
  "shortName": "アーセナル",
  "league": "eng.1",
  "leagueName": "プレミアリーグ",
  "espnTeamId": "359",
  "plTeamId": 1,
  "color": "#ef0107"
}
```

- `espnTeamId`: ESPN のチームページ URL `espn.com/soccer/team/_/id/359/arsenal` の数字
- `plTeamId`: premierleague.com のクラブ ID（主なチーム: Arsenal 1, Aston Villa 2, Chelsea 4, Everton 7, Liverpool 10, Man City 11, Man Utd 12, Newcastle 23, Tottenham 21, West Ham 25）
- `color`: チームカラー（タブやボタンの色に使われます）

---

## GitHub Pages で公開する手順

1. GitHub に新しいリポジトリを作る（Public 推奨。Private だと Pages に有料プランが必要）
2. このフォルダを push する
3. push をきっかけに **Actions** の `update-and-deploy` が走り、GitHub Pages が自動で有効化・公開されます
4. 数分後 `https://<ユーザー名>.github.io/<リポジトリ名>/` で見られます（URL は Actions の実行結果にも表示されます）

以降は毎時7分（UTC）にデータ更新と再公開が自動で行われます。費用はかかりません。

うまくいかないときは **Settings → Actions → General → Workflow permissions** が
`Read and write permissions` になっているか確認してください。

---

## PC でローカル表示する

`serve.bat` をダブルクリックすると http://localhost:8787 が開きます
（`index.html` を直接ダブルクリックすると、ブラウザの制限でデータが読み込めません）。

手動でデータを更新するには:

```bash
python scripts/update.py
```

---

## ネタバレ防止の仕組み（技術メモ）

- `update.py` は取得した JSON から必要な項目だけを手で詰め直す「ホワイトリスト方式」
- 書き出す直前に `score` `winner` `goals` などの禁止ワードが含まれていないか検査し、含まれていれば書き込みを中止
- 交代が実際に行われたか・何分に行われたかも保存しない（展開の推測を防ぐため）
- 外部サイトへのリンクは置かない
