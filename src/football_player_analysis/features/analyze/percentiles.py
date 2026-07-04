# 概要: ポジショングループ内でのパーセンタイル算出。
# 「FW と DF をタックル数で直接比べない」ために、比較母集団を
# ポジショングループごとに分けてランク付けする。

from __future__ import annotations

import re

import pandas as pd

from football_player_analysis.core.exceptions import AnalysisError
from football_player_analysis.features.collect.base import META_COLUMNS


def position_group(position: object) -> str:
    """複合ポジション表記から主ポジションを取り出す。

    区切りはソースにより異なる (FBref: 'MF,FW' / Understat: 'D M S') ため、
    カンマ・空白の両方で分割し先頭を採用する。グループの種類は
    データに現れた値をそのまま使い、コード側でポジション一覧を網羅しない。
    """
    tokens = re.split(r"[,\s]+", str(position).strip())
    return (tokens[0] if tokens else "") or "UNKNOWN"


def add_percentiles(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """指定列 (省略時は全数値スタッツ列) のポジション内パーセンタイル列 *_pct を追加する。"""
    if "position" not in df.columns:
        raise AnalysisError("position 列がありません。collect の出力を渡してください。")

    result = df.copy()
    result["position_group"] = result["position"].map(position_group)

    if columns is None:
        columns = [
            c
            for c in result.columns
            if c not in META_COLUMNS
            and c != "position_group"
            and pd.api.types.is_numeric_dtype(result[c])
        ]
    for col in columns:
        result[f"{col}_pct"] = (
            result.groupby("position_group")[col].rank(pct=True) * 100.0
        )
    return result
