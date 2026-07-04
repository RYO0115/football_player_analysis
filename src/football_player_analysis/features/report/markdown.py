# 概要: 解析・予測結果から Substack 投稿用の Markdown 記事を組み立てる。
# 「記事の見た目」をこのモジュールに閉じ込め、publish 側は
# タイトルと本文文字列だけを受け取る構造にする。

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Article:
    """投稿 1 本分の成果物。"""

    title: str
    subtitle: str
    body_markdown: str


def _format_row(rank: int, row: pd.Series) -> str:
    return (
        f"| {rank} | {row['player']} | {row['team']} ({row['league']}) "
        f"| {row['position']} | {int(row['age'])} | {int(row['minutes'])} "
        f"| {row['potential_score']:.1f} |"
    )


def build_potential_article(
    ranked: pd.DataFrame,
    season: str,
    top_n: int = 20,
) -> Article:
    """potential_score 降順の DataFrame から「次のスーパースター候補」記事を作る。"""
    top = ranked.head(top_n)

    lines = [
        f"今シーズン ({season}) の出場データをもとに、ポジション別パーセンタイルを "
        "攻撃貢献・前進性・創造性で重み付けし、年齢カーブを掛け合わせて "
        "「スーパースター潜在能力スコア」を算出しました。",
        "",
        "| 順位 | 選手 | 所属 | Pos | 年齢 | 出場(分) | スコア |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [_format_row(i + 1, row) for i, (_, row) in enumerate(top.iterrows())]
    lines += [
        "",
        "### 手法",
        "- データ: FBref の選手シーズンスタッツ (リーグごとに提供される全統計種別)",
        "- 正規化: 90 分あたり換算 → ポジショングループ内パーセンタイル",
        "- スコア: 重み付きパーセンタイル平均 × 年齢係数 (若いほど高い)",
        "",
        "*本記事は自動生成パイプラインによって作成されています。*",
    ]

    return Article(
        title=f"次のスーパースター候補 Top {min(top_n, len(top))} — {season}",
        subtitle="データで探す、ブレイク前夜の若手たち",
        body_markdown="\n".join(lines),
    )
