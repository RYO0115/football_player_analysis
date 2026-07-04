# 概要: 選手シーズンスタッツ収集の共通インターフェースと正規化スキーマ。
# データソース (FBref / Understat / ...) を差し替え可能にするため、
# 全コレクターは「正規化済み DataFrame」を返す契約に統一する。

from __future__ import annotations

from typing import Protocol

import pandas as pd

# 正規化後に必ず存在するメタカラム。
# これらは「技術的に閉じた」スキーマ定義であり、分析側との契約になる。
META_COLUMNS = ["player", "team", "league", "season", "position", "age", "minutes"]

# 静的属性列の命名規約。
# 市場価値・身長のように「累積スタッツではなく選手固有の静的な属性」を表す
# スタッツ列は、`種別__attr_指標` の形で `__attr_` を含む名前にする。
# per-90 換算 (to_per90) はこの印を持つ列を換算対象から除外し、値をそのまま残す
# (市場価値を出場時間で割っても無意味なため)。merge は `__` を含む通常のスタッツ
# 列として自然に取り込むので、規約はこの列名だけで閉じている。
ATTR_MARKER = "__attr_"


def is_attr_column(col: str) -> bool:
    """per-90 換算が無意味な静的属性列 (市場価値・身長等) か判定する。"""
    return ATTR_MARKER in col


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
