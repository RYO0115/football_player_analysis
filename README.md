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
# 注: 2025-01 の Opta 契約解消以降、FBref からは xG・プログレッシブ・
#     passing/defense/possession 等の高度スタッツが消失しており、
#     現在取得できるのは standard/shooting/keeper/playing_time/misc の 5 種別。
#     未提供種別を指定した場合は WARNING を出してスキップする (正常動作)。
uv run fpa collect --league "ENG-Premier League" --season 2425

# 2. (任意) 2 ソースを選手名で結合し xG 系を補完
#    FBref (age・基本スタッツ) を primary、Understat (xG 系) を secondary として
#    選手名で結合し、"merged" ソースとして保存する。事前に両ソースの collect が必要。
uv run fpa collect --league "ENG-Premier League" --season 2425 --source understat
uv run fpa merge --league "ENG-Premier League" --season 2425 --secondary understat
# 以降は --source merged で解析・予測できる
#   uv run fpa analyze --league "ENG-Premier League" --season 2425 --source merged
#   uv run fpa predict --source merged --top 20

# 3. 解析 (per-90 + パーセンタイル)
uv run fpa analyze --league "ENG-Premier League" --season 2425

# 4. 予測 (スーパースター候補ランキング表示)
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
| FBref | [soccerdata](https://github.com/probberechts/soccerdata) | ✅ v0 主データ | 基本スタッツ (ゴール/アシスト/シュート/守備アクション等) を世界中のリーグで取得可能。※2025-01 の Opta 契約解消で xG 等の高度スタッツは消失 |
| Understat | soccerdata | ✅ v1 (xG 補完) | FBref から消えた xG/npxG/xA/xGChain/xGBuildup を補完 (`--source understat`)。対応は欧州 5 大リーグ + ロシア。年齢は提供されない |
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
