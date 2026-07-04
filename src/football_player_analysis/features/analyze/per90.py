# 概要: 累積スタッツの per-90 (90 分あたり) 換算。
# 出場時間の異なる選手を公平に比較するための前処理で、
# 解析・予測の両方がこの出力を前提とする。

from __future__ import annotations

import pandas as pd

from football_player_analysis.core.exceptions import AnalysisError
from football_player_analysis.features.collect.base import META_COLUMNS, is_attr_column

# 割合・パーセント系 (列名に含まれると per-90 換算が無意味になる) の指標を除外する目印。
# FBref の列名規約 (%・90 表記) に対する技術的判定であり、指標の内容を限定するものではない。
_RATE_MARKERS = ("%", "/90", "_90", "per90", "per 90")


def is_rate_column(column: str) -> bool:
    """すでに率・割合になっている列か判定する。"""
    lowered = column.lower()
    return any(marker in lowered for marker in _RATE_MARKERS)


def to_per90(df: pd.DataFrame, min_minutes: float = 0.0) -> pd.DataFrame:
    """数値スタッツ列を per-90 に換算した DataFrame を返す。

    min_minutes 未満の選手はサンプル過小でノイズになるため除外する。
    """
    if "minutes" not in df.columns:
        raise AnalysisError("minutes 列がありません。collect の出力を渡してください。")

    result = df[df["minutes"].fillna(0) >= max(min_minutes, 1e-9)].copy()
    if result.empty:
        raise AnalysisError(f"minutes >= {min_minutes} を満たす選手がいません。")

    stat_cols = [
        c
        for c in result.columns
        if c not in META_COLUMNS and pd.api.types.is_numeric_dtype(result[c])
    ]
    for col in stat_cols:
        if is_rate_column(col):
            continue  # 率系はそのまま比較可能なので換算しない
        if is_attr_column(col):
            continue  # 市場価値・身長等の静的属性は換算しても無意味なので残す
        result[f"{col}_per90"] = result[col] / result["minutes"] * 90.0
    return result
