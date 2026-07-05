# 概要: 守備スタッツのポゼッション調整 (PAdj)。
# 保持率の高いチームの守備者は守備機会そのものが少ないため、
# 生の守備カウントでは不当に低く見える。業界標準の
# `PAdj = 生スタッツ × 50 / 相手ポゼッション%` (Wyscout/StatsBomb 方式) で補正する。
# 調整対象の列は名前をコードに列挙せず、守備キーワード (radar.toml の
# defense カテゴリと同じ語彙) との照合で動的に決める。

from __future__ import annotations

import logging

import pandas as pd

from football_player_analysis.features.analyze.per90 import is_rate_column
from football_player_analysis.features.analyze.radar_axes import metric_key
from football_player_analysis.features.collect.base import META_COLUMNS, is_attr_column

logger = logging.getLogger(__name__)

# 既定の守備キーワード (config/radar.toml の defense カテゴリと同じ語彙)。
# apply_padj の引数で差し替え可能。
DEFAULT_DEFENSE_KEYWORDS = ("tklw", "tkl", "int", "aerial", "recov", "blocks", "clr")


def apply_padj(
    df: pd.DataFrame,
    possession: pd.DataFrame,
    defense_keywords: tuple[str, ...] = DEFAULT_DEFENSE_KEYWORDS,
) -> pd.DataFrame:
    """守備系カウント列を PAdj 値に置き換え、列名に _padj を付けて返す。

    possession は (league, season, team, possession) を持つ DataFrame
    (fbref.collect_team_possession の出力)。possession が引けない選手は
    調整係数 1 (無調整) とし、全体を落とさない。
    元の列は残さず _padj 列に置き換える — 生値と調整値が両方あると
    キーワード照合 (レーダー軸・重み) が二重に一致してしまうため。
    """
    result = df.merge(
        possession[["league", "season", "team", "possession"]],
        on=["league", "season", "team"],
        how="left",
    )
    matched = result["possession"].notna()
    if not matched.all():
        logger.warning(
            "PAdj: ポゼッション不明のチームが %d 行 (無調整で継続)",
            int((~matched).sum()),
        )
    # 相手ポゼッション% = 100 - 自チーム保持率。標準の 50% を基準に補正する
    factor = (50.0 / (100.0 - result["possession"])).fillna(1.0)

    renames: dict[str, str] = {}
    for col in df.columns:
        if col in META_COLUMNS or not pd.api.types.is_numeric_dtype(df[col]):
            continue
        if is_rate_column(col) or is_attr_column(col):
            continue  # 率・静的属性は機会補正の対象外
        key = metric_key(col)
        if any(keyword in key for keyword in defense_keywords):
            result[col] = result[col] * factor
            renames[col] = f"{col}_padj"

    result = result.drop(columns=["possession"]).rename(columns=renames)
    if renames:
        logger.info("PAdj 適用: %d 列 (%s ...)", len(renames), next(iter(renames)))
    return result
