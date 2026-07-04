# 設計書

最終更新: 2026-07-04 / v0.1.0

## 目的

世界中のフットボール選手のスタッツを収集・解析し、
「今後スーパースターになる選手」の予測記事を Substack に自動投稿する。

## アーキテクチャ

```
src/football_player_analysis/
├── core/                 # 共通基盤 (features から参照される。逆依存禁止)
│   ├── config.py         # Settings / SubstackConfig (.env 読み込み)
│   ├── storage.py        # ParquetStorage (中間データの永続化)
│   └── exceptions.py     # FpaError 階層
├── features/
│   ├── collect/          # 収集: FBrefCollector (soccerdata)
│   ├── analyze/          # 解析: per90 / percentiles / radar
│   ├── predict/          # 予測: PotentialConfig / score_potential
│   ├── report/           # 記事化: Article / build_potential_article
│   └── publish/          # 投稿: SubstackPublisher
├── pipeline.py           # 各フェーズのオーケストレーション
└── cli.py                # argparse サブコマンド (fpa)
```

### 依存方向

```
core ← collect ← analyze ← predict
core ← report ← publish
pipeline → (全 feature)、cli → pipeline
```

- analyze は collect の正規化スキーマ (`META_COLUMNS`) に依存する。
- publish は report の `Article` にのみ依存し、解析結果の中身を知らない。

## モジュール間契約

| フェーズ | 入力 | 出力 |
|---|---|---|
| collect | league, season | META_COLUMNS + `種別__指標` 数値列の DataFrame |
| analyze | collect 出力 | + `*_per90` / `*_pct` / `position_group` 列 |
| predict | analyze 出力 | + `potential_score` 列 (降順ソート済み) |
| report | predict 出力 | `Article` (title / subtitle / body_markdown) |
| publish | `Article` | 保存パス or Substack draft id |

## 主要な設計判断

1. **スタッツ列名を列挙しない**: FBref 側の指標は増減するため、収集は
   「数値列を動的に取り込む」、予測の重みは「列名キーワード一致」で適用する。
   ポジショングループもデータに現れた値をそのまま母集団キーにする。
2. **reader 注入**: soccerdata はネットワーク副作用を持つため、
   `FBrefCollector(reader_factory=...)` で差し替え可能にし、テストは偽 reader で行う。
3. **中間データは Parquet**: 収集 (低頻度・重い) と解析 (高頻度・軽い) を分離し、
   再解析時に再スクレイプしない。リーグ追加はファイル追加だけで済む。
4. **dry_run 既定**: 外部公開 (Substack) は `FPA_DRY_RUN=false` + `--publish-now` の
   二段階で明示しない限り起きない。実投稿でもまず「下書き」作成を既定とする。
5. **予測は契約固定で差し替え可能**: v0 はルールベース。将来 ML 化する際も
   「percentile 付き DataFrame in → potential_score 付き DataFrame out」を維持する。

## スーパースター予測ロードマップ

- v0 (済): 重み付きパーセンタイル × 年齢カーブ (`config/potential.toml`)
- v1: 複数シーズン収集 → 「翌シーズンの市場価値上昇 / Big5 上位クラブ移籍」を
  ラベル化 (Transfermarkt 収集モジュール追加) → 勾配ブースティング等で学習
- v2: Understat / StatsBomb イベントデータで特徴量拡充、リーグ強度補正

## テスト方針

- 全テストはネットワーク不要 (偽 reader / 偽コレクター / dry_run)。
- 契約 (スキーマ・並び順・フィルタ・例外) を検証し、実装詳細に依存しない。
- 実スクレイプの疎通は手動 (`uv run fpa collect ...`) で確認する。
