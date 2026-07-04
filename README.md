# football-player-analysis

世界中のフットボール選手の詳細スタッツを収集・解析し、
「次にスーパースターになりそうな若手」ランキング記事を生成して
Substack に投稿するまでを自動化するパイプライン。

最終更新: 2026-07-04 / v0.1.0

## パイプライン全体像

```
collect (FBref via soccerdata)
   ↓ data/raw_player_season/*.parquet
analyze (per-90 換算 + ポジション内パーセンタイル)
   ↓ data/analyzed_player_season/*.parquet
predict (潜在能力スコア: 重み付きパーセンタイル × 年齢カーブ)
   ↓ ランキング DataFrame
report (Markdown 記事生成)
   ↓ Article
publish (Substack 下書き投稿 / dry_run 時はローカル .md 出力)
```

## セットアップ

```bash
uv sync
cp .env.example .env   # Substack 認証情報などを設定
```

## 使い方

```bash
# 1. 収集 (リーグは複数指定可。ID は soccerdata の表記)
# 注: passing/defense/possession 等の詳細統計は "Big 5 European Leagues Combined"
#     指定時のみ提供。単一リーグ指定では standard/shooting 等に自動フォールバックする。
uv run fpa collect --league "Big 5 European Leagues Combined" --season 2425

# 2. 解析 (per-90 + パーセンタイル)
uv run fpa analyze --league "ENG-Premier League" --season 2425

# 3. 予測 (スーパースター候補ランキング表示)
uv run fpa predict --top 20

# 一括実行 (収集→解析→予測→記事生成→投稿)
uv run fpa run --league "ENG-Premier League" --league "ESP-La Liga" --season 2425
```

- 既定は **dry_run** (`FPA_DRY_RUN=true`): 記事は `data/output/*.md` に保存されるだけで外部投稿しない。
- `FPA_DRY_RUN=false` にすると Substack に**下書き**として投稿する。即時公開は `--publish-now` を明示した場合のみ。

## 定期実行 (自動化)

cron / launchd から `uv run fpa run ...` を叩くだけで全フェーズが回る。例 (毎週月曜 9:00):

```
0 9 * * 1 cd /path/to/football_player_analysis && uv run fpa run --league "ENG-Premier League" --season 2526
```

## データソースの選定 (調査結果)

| ソース | 手段 | 採用 | 理由 |
|---|---|---|---|
| FBref | [soccerdata](https://github.com/probberechts/soccerdata) | ✅ v0 主データ | xG・プログレッシブ系まで揃う最も網羅的な無料ソース。Big5 以外のリーグも対応 |
| Understat | soccerdata | 将来 | xG の別ソースとして検証用 |
| Sofascore / WhoScored | soccerdata | 将来 | レーティング・詳細イベント |
| Transfermarkt | 別スクレイパー | 将来 | 市場価値 = ML の教師ラベル候補 |
| StatsBomb Open Data | 公式無料 | 将来 | イベントデータでの深掘り分析 |

Substack は公式 API が無いため、非公式の [python-substack](https://github.com/ma2za/python-substack) を採用
(メール/パスワード認証・下書き作成・公開まで可能)。

## スーパースター予測 (v0 → 将来)

- **v0 (実装済み)**: `config/potential.toml` の重み × ポジション内パーセンタイル × 年齢カーブによるスコアリング。
  重み・年齢帯・最低出場時間はすべて TOML で調整可能。
- **将来 (設計済み)**: 過去シーズンのスタッツを特徴量、翌シーズン以降の市場価値上昇 (Transfermarkt) や
  ビッグクラブ移籍を教師ラベルにした学習モデルへ差し替える。`score_potential` と同じ
  「DataFrame in → potential_score 付き DataFrame out」の契約を守れば無変更で載せ替えられる。

## 開発

```bash
uv run pytest        # 全テスト (ネットワーク不要)
```

設計詳細は [docs/design.md](docs/design.md) を参照。
