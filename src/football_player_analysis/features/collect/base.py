# 概要: 選手シーズンスタッツ収集の共通インターフェースと正規化スキーマ。
# データソース (FBref / Understat / ...) を差し替え可能にするため、
# 全コレクターは「正規化済み DataFrame」を返す契約に統一する。

from __future__ import annotations

from typing import Protocol

import pandas as pd

# 正規化後に必ず存在するメタカラム。
# これらは「技術的に閉じた」スキーマ定義であり、分析側との契約になる。
META_COLUMNS = ["player", "team", "league", "season", "position", "age", "minutes"]


class PlayerSeasonCollector(Protocol):
    """1 リーグ・1 シーズン分の選手スタッツを収集するコレクターの契約。"""

    def collect(self, league: str, season: str) -> pd.DataFrame:
        """META_COLUMNS + 任意個の数値スタッツ列を持つ DataFrame を返す。"""
        ...


def validate_normalized(df: pd.DataFrame) -> pd.DataFrame:
    """コレクター出力が正規化スキーマを満たすか検証する。

    分析側の前提を早期に壊れ検知するためのガード。
    """
    missing = [c for c in META_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"正規化スキーマ違反: 欠損カラム {missing}")
    return df
