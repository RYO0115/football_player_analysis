# 概要: 解析・予測結果から Substack 投稿用の Markdown 記事を組み立てる。
# 「記事の見た目」をこのモジュールに閉じ込め、publish 側は
# タイトルと本文文字列だけを受け取る構造にする。

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

# *_pct 列名から指標名を取り出す際に取り除く技術的サフィックス。
# 指標そのもの (xg / gls / TklW 等) は列挙せず、命名規則からの機械的な整形のみ行う。
_METRIC_LABEL_SUFFIXES = ("_pct", "_per90")


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


def potential_stars(score: float) -> str:
    """potential_score (0〜100 目安) を 8 段階の★表記に変換する。

    N5 風の個票にある「🌟 ポテンシャル: ★★★★★★★☆」を再現するためのヘルパー。
    """
    filled = max(0, min(8, round(score / 100 * 8)))
    return "★" * filled + "☆" * (8 - filled)


def _metric_label(column: str) -> str:
    """*_pct 列名から指標名を機械的に抽出する。

    指標一覧をコードに列挙しないため、命名規則 (`種別__カテゴリ_指標_per90_pct` 等) から
    技術的サフィックスを取り除いた最後のアンダースコア区切りセグメントを指標名とみなす。
    例: understat__xg_per90_pct → xg / misc__Performance_TklW_per90_pct → TklW
    """
    stripped = column
    for suffix in _METRIC_LABEL_SUFFIXES:
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
    tokens = [t for t in re.split(r"_+", stripped) if t]
    return tokens[-1] if tokens else stripped


# 「強み」として表示すると誤解を招く指標 (高いほど悪い規律系スタッツ) の目印。
# FBref/Understat の列名規約に対する表示上の除外であり、収集・スコア計算には影響しない。
_NEGATIVE_METRIC_MARKERS = ("crd", "card", "fls", "foul", "off", "og", "err")


def _top_pct_metrics(row: pd.Series, n: int = 3) -> list[tuple[str, float]]:
    """行内の *_pct 列のうち値が高い上位 n 件を (指標名, 値) のリストで返す。

    表示品質のため 2 つのフィルタを掛ける:
    - 規律系 (カード・ファウル等) はパーセンタイルが高い=悪いため「強み」から除外
    - 同じ指標名がソース違いで重複する (例 standard と shooting 両方の Gls) ため
      指標名単位で重複排除する
    """
    candidates = [
        (column, value)
        for column, value in row.items()
        if str(column).endswith("_pct") and pd.notna(value)
    ]
    candidates.sort(key=lambda item: item[1], reverse=True)

    result: list[tuple[str, float]] = []
    seen: set[str] = set()
    for column, value in candidates:
        label = _metric_label(column)
        lowered = label.lower()
        if lowered in seen:
            continue
        if any(marker in lowered for marker in _NEGATIVE_METRIC_MARKERS):
            continue
        seen.add(lowered)
        result.append((label, value))
        if len(result) >= n:
            break
    return result


def _format_market_value(value_eur: float) -> str:
    return f"{value_eur / 1_000_000:.2f} M€"


def _build_card(rank: int, row: pd.Series) -> str:
    """選手 1 名分の個票 (N5 風プロフィールカード) を Markdown で組み立てる。

    列は存在するときだけ表示する (Transfermarkt 由来の市場価値・身長は
    データが無いこともある前提で defensive に扱う)。
    """
    lines = [f"### {rank}. {row['player']} ({row['team']})"]
    lines.append(f"- ポジション: {row['position']}")
    if pd.notna(row.get("age")):
        lines.append(f"- 年齢: {int(row['age'])}歳")
    if pd.notna(row.get("minutes")):
        lines.append(f"- 出場時間: {int(row['minutes'])}分")

    height_cm = row.get("transfermarkt__attr_height_cm")
    if pd.notna(height_cm):
        lines.append(f"- 身長: {int(round(float(height_cm)))}cm")

    market_value_eur = row.get("transfermarkt__attr_market_value_eur")
    if pd.notna(market_value_eur):
        lines.append(f"- 市場価値: {_format_market_value(float(market_value_eur))}")

    lines.append(f"- ポテンシャル: {potential_stars(row['potential_score'])}")

    top_metrics = _top_pct_metrics(row)
    if top_metrics:
        metrics_text = "・".join(f"{name} {value:.0f}pct" for name, value in top_metrics)
        lines.append(f"- 強み指標: {metrics_text}")
        lines.append(f"- 💬 {row['position']} ながら {metrics_text} と数値が突出。")

    return "\n".join(lines)


def build_potential_article(
    ranked: pd.DataFrame,
    season: str,
    top_n: int = 20,
    cards_n: int = 5,
) -> Article:
    """potential_score 降順の DataFrame から「次のスーパースター候補」記事を作る。

    ランキング表に加え、上位 cards_n 人分の選手個票 (N5 風プロフィールカード) を
    「## 注目株ピックアップ」セクションとして追加する。
    """
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

    lines += ["", "## 注目株ピックアップ", ""]
    for i, (_, row) in enumerate(top.head(cards_n).iterrows()):
        lines.append(_build_card(i + 1, row))
        lines.append("")

    lines += [
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
