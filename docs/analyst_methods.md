# 著名アナリストの選手評価手法と本リポジトリでの対応

最終更新: 2026-07-05 / v0.2.0

「ポジション・特性ごとに見るべき指標が変わる」問題に対する業界標準の手法調査と、
football_player_analysis での実装対応をまとめる。

## 調査まとめ

### 1. StatsBomb / Ted Knutson — ポジション別レーダーテンプレート

出典: [Understanding StatsBomb Radars](https://blogarchive.statsbomb.com/articles/soccer/understanding-statsbomb-radars/) /
[Revisiting Radars](https://blogarchive.statsbomb.com/articles/soccer/revisiting-radars/)

- 主要 5 ポジション (CB / FB / MF / AM・W / ST) ごとに**別のレーダーテンプレート** (各 10〜12 指標) を用意する。
  「DF に 1 試合 8 本のシュートを期待するのは馬鹿げているし、ロナウドに 5 タックルを期待するのも馬鹿げている」
- すべて per-90 換算。境界は**同ポジション母集団 (欧州 5 大リーグ×複数シーズン) の上位/下位 5%** (約 ±2σ)
- 守備指標は **PAdj (ポゼッション調整)**: 保持率の高いチームの守備者は守備機会が少ないことを補正
- 指標は「品質系 (良し悪しを測る)」と「スタイル系 (プレー様式を示すだけ)」を意図的に混在させ、
  レーダーは採点表ではなく**選手のプロファイル理解の道具**と位置づける

テンプレート例 (StatsBomb の指標 → 本リポジトリで取得可能な対応指標):

| ポジション | StatsBomb の主な軸 | 本リポジトリで使える対応 |
|---|---|---|
| CB | PAdj タックル/インターセプト、空中戦、パス成功率、xGBuildup | TklW / Int / xg_buildup / (空中戦・パス系は現状データ無し) |
| MF | ディープ前進、xG アシスト、PAdj 守備、ドリブル | xg_buildup / xg_chain / xa / key_passes / TklW / Int |
| AM・W / ST | xG、シュート、ボックス内タッチ、xG/シュート | np_xg / Gls / SoT / shots / xa |

### 2. FBref Scouting Reports — カテゴリ別パーセンタイル

出典: [Scouting Reports Explained](https://fbref.com/en/about/scouting-reports-explained)

- 直近 365 日・**同ポジション・同競技グループ**の母集団に対するパーセンタイルで表示
- 指標は **Attacking / Possession / Defending** のカテゴリに分けて提示する
- パーセンタイル = 「未満の選手割合」と「以下の選手割合」の平均

### 3. smarterscout (Dan Altman) — 次元別レーティング 0-99

出典: [smarterscout FAQ](https://smarterscout.com/faq)

- 選手を単一の総合点ではなく**次元別レーティング**で表す:
  攻撃出力 (保持中の xGF 貢献) / ボール前進 / ボール保持 / 守備量 (機会あたり) × 守備質 (xGA 影響)
- 各次元を **0-99 スケール**に正規化し、リーグ強度差はベンチマークリーグへの換算で補正

### 4. PAdj (ポゼッション調整守備スタッツ)

出典: [Wyscout Glossary](https://dataglossary.wyscout.com/p_adj/) /
[StatsBomb: Introducing Possession-Adjusted Player Stats](https://blogarchive.statsbomb.com/articles/soccer/introducing-possession-adjusted-player-stats/)

- `PAdj スタッツ = 生スタッツ × 50 / 相手ポゼッション%`
- 例: 保持率 60% のチームの CB が 10 タックル → PAdj では 12.5 タックル相当
- チームレベルでこの調整をすると被シュート・失点との相関が大きく向上する

### 5. ロールクラスタリング (将来)

出典: [Stats Perform: Clustering Playing Styles](https://www.statsperform.com/resource/clustering-playing-styles-in-the-modern-day-full-back/) 他

- PCA + k-means で「Box-to-Box」「Advanced Creator」のような**データ駆動ロール**に分類し、
  同ロール内で比較する。ポジション表記より実際のプレー内容に即した母集団を作れる
- 本リポジトリでは v-next (scikit-learn 依存追加込み) として docs/design.md のロードマップに記載

## 本リポジトリでの実装対応

| 手法 | 実装 |
|---|---|
| ポジション別テンプレート | `config/radar.toml` の `[templates.<ポジション接頭辞>]`。position_group と前方一致 (最長優先) で解決し、未定義は既定 categories にフォールバック |
| カテゴリ別パーセンタイル表示 | 選手個票の「強み指標」をカテゴリ別に表示 (radar.toml のカテゴリ定義を共用) |
| 次元スコア 0-100 | `config/dimensions.toml` + `analyze/dimensions.py`。次元 = 一致した *_pct 列の重み付き平均 → position_group 内で再パーセンタイル化した `dim_*` 列 |
| 比較母集団 | 既定はリーグ内。`fpa analyze --pool all` で全リーグ統合母集団 (FBref の競技グループに相当) |
| PAdj | FBref チームスタッツの Poss が取得可能なら `stat × 50/(100−Poss)`。不可ならチーム内シェア近似 (docs に限界明記) |

## 限界と注意

- 2025-01 の Opta 契約解消で FBref からパス成功率・プログレッシブ・空中戦・プレッシャー等が消失しており、
  StatsBomb テンプレートの完全再現は不可能。取得可能な指標の範囲でテンプレートを構成している
- リーグ強度補正 (smarterscout のベンチマーク換算) は未実装。リーグ横断母集団では「リーグの格」は無視される
- レーダーは採点表ではない (スタイル系指標を含む)。順位付けには potential_score / dim_* を使う
