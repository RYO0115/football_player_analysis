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
│   ├── collect/          # 収集: FBref/Understat/Transfermarkt Collector / merge_sources
│   ├── analyze/          # 解析: per90 / percentiles / radar / radar_axes (軸選択)
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
- merge (collect 内の純粋関数 `merge_sources`) は 2 つの正規化 DataFrame を
  選手名で結合するだけで、コレクター実装には依存しない。

## モジュール間契約

| フェーズ | 入力 | 出力 |
|---|---|---|
| collect | league, season | META_COLUMNS + `種別__指標` 数値列の DataFrame (fbref は別途 `team_possession` も保存) |
| merge | primary/secondary の collect 出力 2 枚 | primary 基準に secondary のスタッツ列を左結合した DataFrame (`source="merged"`) |
| analyze | collect / merge 出力 | + `*_padj` (ポゼッション調整、possession があれば) / `*_per90` / `*_pct` / `position_group` / `dim_*` (次元スコア 0-100) 列 |
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
6. **"merged" は仮想ソース**: 複数ソース結合結果はコレクターを持たない仮想
   ソース名 `merged` の raw データとして保存する。source を保存先の接尾辞に
   使う既存の仕組み (`raw_player_season_{source}`) にそのまま乗るため、analyze/
   predict は無変更で `--source merged` を扱える。コレクターを持たないソースが
   混ざるため、`Pipeline.collector` は Optional とし、CLI は `SOURCES.get(source)`
   で実コレクターのあるソースのときだけ生成する (collect/run は実ソースのみ許可)。
   選手名の表記揺れ (アクセント有無) は `normalize_player_name` (unidecode) で吸収。
7. **アナリスト手法の採用 (詳細は docs/analyst_methods.md)**: レーダー軸は
   `config/radar.toml` の**ポジション別テンプレート** (StatsBomb 流、position_group と
   `core.matching.match_longest_prefix` で解決)。選手の総合像は `config/dimensions.toml`
   による**次元スコア dim_\* (0-100、同ポジション内)** (smarterscout 流)。守備カウントは
   `team_possession` データがあるとき **PAdj (× 50/相手ポゼッション%)** に置き換えられ、
   列名は `*_padj` になる (キーワード照合の二重一致を防ぐため生列は残さない)。
   母集団は既定でリーグ内、`fpa analyze --pool all` で全リーグ統合 (FBref の競技グループ相当)。
8. **`__attr_` 静的属性列の規約**: 市場価値・身長のように「累積スタッツではなく
   選手固有の静的属性」を表す列は `種別__attr_指標` の形にする (`base.is_attr_column`)。
   per-90 換算 (`to_per90`) はこの印を持つ列を対象外にして値をそのまま残す (市場価値を
   出場時間で割っても無意味なため)。merge は `__` を含む通常のスタッツ列として自然に
   取り込むので、規約はこの列名だけで閉じ、merge/predict 側の変更を要さない。
   Transfermarkt は soccerdata 非対応のため requests + BeautifulSoup で直接スクレイプ
   するが、FBref と同じく「ネットワーク関数 (url -> html) を注入可能」にしてテストは
   偽 HTML で行う。対応リーグ (soccerdata ID → TM の slug/競技 ID) は
   `config/transfermarkt_leagues.toml` で管理し、コードに埋め込まない。

## スーパースター予測ロードマップ

- v0 (済): 重み付きパーセンタイル × 年齢カーブ (`config/potential.toml`)。
  ポジショングループ別の重みプロファイル (`[profiles.<名前>.metric_weights]`)
  に対応し、ボランチ型・DF型の若手が攻撃寄り既定重みで過小評価される問題を
  是正 (`applied_profile` 列で適用プロファイルを確認可能)。
- v1: **Understat コレクター追加で xG/npxG/xA を補完**
  (2025-01 の Opta 契約解消で FBref から高度スタッツが消失したため優先度高)
- v2: **Transfermarkt コレクター追加で市場価値・身長を収集** (`--source transfermarkt`)。
  まず選手個票への表示に使い、次段で複数シーズン収集 → 「翌シーズンの市場価値上昇 /
  Big5 上位クラブ移籍」をラベル化 → 勾配ブースティング等で学習へ発展させる
- v3: StatsBomb イベントデータで特徴量拡充、リーグ強度補正 (smarterscout のベンチマーク換算相当)
- v4: PCA + k-means による**ロールクラスタリング** (「Box-to-Box」「Advanced Creator」等の
  データ駆動ロールを母集団にする。scikit-learn 依存追加込み)

## テスト方針

- 全テストはネットワーク不要 (偽 reader / 偽コレクター / dry_run)。
- 契約 (スキーマ・並び順・フィルタ・例外) を検証し、実装詳細に依存しない。
- 実スクレイプの疎通は手動 (`uv run fpa collect ...`) で確認する。
