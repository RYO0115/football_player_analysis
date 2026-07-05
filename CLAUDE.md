# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

世界中のフットボール選手スタッツを収集・解析し、「次のスーパースター候補」記事を生成して
Substack に自動投稿するパイプライン。最終目標は市場価値上昇を教師ラベルにした ML 予測 (docs/design.md のロードマップ参照)。
Python 開発の共通規約は `.claude/skills/python-dev-workflow` に従う (uv / core-features 構成 / テスト必須 / ハードコード禁止原則)。

## よく使うコマンド

```bash
uv sync                                  # 環境構築
uv run pytest -q                         # 全テスト (ネットワーク不要・数秒で完走)
uv run pytest tests/test_predict.py -q   # 単一ファイル
uv run pytest -k "profile" -q            # キーワード指定

# パイプライン (fpa CLI)。リーグ ID は soccerdata 表記、シーズンは "2526" 形式
uv run fpa collect --league "GER-Bundesliga" --season 2526 [--source fbref|understat|transfermarkt]
uv run fpa merge   --league "GER-Bundesliga" --season 2526 --secondary understat   # → 仮想ソース "merged"
uv run fpa merge   --league "GER-Bundesliga" --season 2526 --source merged --secondary transfermarkt
uv run fpa analyze --league "GER-Bundesliga" --season 2526 --source merged --pool all  # pool: league|all
uv run fpa predict --source merged --top 20
uv run fpa run     --league "..." --season 2526              # 収集→解析→予測→記事→投稿の一括実行

uv run marimo edit notebooks/data_explorer.py   # データ探索ノートブック (要: merged の analyze 済みデータ)
uv run bump-my-version bump minor               # 機能追加後のバージョン更新 (自動 commit + tag)
```

## アーキテクチャ (詳細は docs/design.md)

`core ← collect ← analyze ← predict` / `core ← report ← publish`、`pipeline.py` が全フェーズを束ね `cli.py` が argparse で公開する。
フェーズ間はすべて **DataFrame 契約**で接続され、中間データは `data/{raw|analyzed}_player_season_{source}/{league}_{season}.parquet` に永続化される。

- **正規化スキーマ**: 全コレクターは `META_COLUMNS` (player/team/league/season/position/age/minutes) + `種別__指標` 形式の数値列を返す (collect/base.py)。スタッツ列は動的に取り込み、コード側で列名を列挙しない
- **SOURCES レジストリ** (collect/__init__.py): fbref / understat / transfermarkt。新ソースは 1 エントリ追加で CLI から使える。`merged` はコレクターを持たない**仮想ソース**で、`merge_sources` (unidecode による選手名正規化の左結合) が生成する
- **`__attr_` 列規約**: 市場価値・身長など per-90 換算が無意味な静的属性は `種別__attr_指標` と命名し、to_per90 が換算対象から除外する
- **予測** (predict/potential.py): `config/potential.toml` の重みキーワード × ポジション内パーセンタイル × 年齢カーブ。`[profiles.<グループ名>.metric_weights]` でポジション別重み (前方一致・最長キー優先、未一致は既定へフォールバック)。適用結果は `applied_profile` 列
- **選手評価の方法論** (docs/analyst_methods.md): レーダーは `config/radar.toml` の**ポジション別テンプレート**、次元スコア `dim_*` (0-100、同ポジション内) は `config/dimensions.toml`、守備カウントは `team_possession` データがあれば **PAdj** (`*_padj` 列に置換)。fbref の collect がポゼッションも自動保存する。ポジション⇔設定キーの照合は `core/matching.py` の最長前方一致
- **テスト方針**: ネットワーク副作用は全て注入可能 (FBref/Understat は reader_factory、Transfermarkt は fetcher)。テストは偽データのみで、実スクレイプの疎通は手動確認

## データソースの重要な前提 (再調査不要)

- **FBref** (soccerdata 経由): 2025-01 の Opta 契約解消で xG・プログレッシブ・passing/defense/possession は**消失済み**。取得可能な stat_type は standard/shooting/keeper/playing_time/misc の 5 種のみ (未対応種別は WARNING でスキップ = 正常動作)。Cloudflare 対策で Selenium が起動し、初回は chromedriver がダウンロードされる
- **Understat**: xG/npxG/xA/xGChain/xGBuildup の供給源。**年齢を提供しない** (age は NA、FBref との merge で補完)。対応は欧州 5 大リーグ + ロシア。ポジションは空白区切り表記 ("D M S")
- **Transfermarkt**: 自前スクレイパー (requests + BeautifulSoup、UA 明示・3 秒間隔・5xx は指数バックオフ)。対応リーグは `config/transfermarkt_leagues.toml` で管理。minutes は NA
- **Substack**: 公式 API 無し。python-substack (メール/パスワード認証、環境変数のみ) を使用。**dry_run が既定**で、実投稿は `FPA_DRY_RUN=false` + 即時公開はさらに `--publish-now` の二段階

## 変更時の注意

- 機能変更にはテスト追加が必須。完了前に `uv run pytest -q` 全 green を確認
- ドキュメント (README.md / docs/design.md) は同じコミットで更新し、機能追加後は bump-my-version で minor を上げる
- コメント・ドキュメント・コミットメッセージは日本語
