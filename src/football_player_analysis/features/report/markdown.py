# 概要: 解析・予測結果から Substack 投稿用の Markdown 記事を組み立てる。
# 「記事の見た目」をこのモジュールに閉じ込め、publish 側は
# タイトルと本文文字列だけを受け取る構造にする。

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from football_player_analysis.features.analyze.radar_axes import metric_label


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
    """*_pct 列名から表示用の指標名を抽出する。

    ラベル規則 (PAdj マーカーや np_xg の保持) を analyze 側と揃えるため、
    radar_axes.metric_label に委譲する。
    """
    return metric_label(column)


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


def card_heading(rank: int, row: pd.Series) -> str:
    """個票の見出し行 (順位・選手名・所属) を返す。

    レーダーと並べる際に見出しだけ独立配置できるよう本文と分離している。
    """
    return f"### {rank}. {row['player']} ({row['team']})"


def card_body(row: pd.Series) -> str:
    """個票の本文 (ポジション以下の箇条書き) を Markdown で組み立てる。

    列は存在するときだけ表示する (Transfermarkt 由来の市場価値・身長は
    データが無いこともある前提で defensive に扱う)。
    """
    lines = [f"- ポジション: {row['position']}"]
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

    # 次元スコア (smarterscout 流の 0-100)。dim_* 列があるときだけ表示する
    dims = [
        (str(c).removeprefix("dim_"), row[c])
        for c in row.index
        if str(c).startswith("dim_") and pd.notna(row[c])
    ]
    if dims:
        dims_text = " / ".join(f"{name} {value:.0f}" for name, value in dims)
        lines.append(f"- 次元スコア (同ポジション内): {dims_text}")

    top_metrics = _top_pct_metrics(row)
    if top_metrics:
        metrics_text = "・".join(f"{name} {value:.0f}pct" for name, value in top_metrics)
        lines.append(f"- 強み指標: {metrics_text}")
        lines.append(f"- 💬 {row['position']} ながら {metrics_text} と数値が突出。")

    return "\n".join(lines)


def _build_card(rank: int, row: pd.Series) -> str:
    """選手 1 名分の個票 (N5 風プロフィールカード) を Markdown で組み立てる。

    見出し (選手名) を本文 (ポジション以下) の上に積んだ 1 ブロックを返す。
    """
    return f"{card_heading(rank, row)}\n{card_body(row)}"


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
