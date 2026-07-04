# 概要: テスト共通のフィクスチャ。
# ネットワークに出ずにパイプライン全体を検証できるよう、
# FBref 相当の生データと正規化済みデータを合成して提供する。

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def raw_fbref_frames() -> dict[str, pd.DataFrame]:
    """soccerdata の read_player_season_stats 相当の生 DataFrame (stat_type 別)。"""
    standard = pd.DataFrame(
        {
            ("player", ""): ["Young Star", "Veteran", "Keeper Low"],
            ("team", ""): ["Alpha FC", "Beta FC", "Alpha FC"],
            ("pos", ""): ["FW", "MF,FW", "GK"],
            ("age", ""): ["18-120", "29-001", "24-050"],
            ("Playing Time", "Min"): [1800, 2700, 90],
            ("Performance", "Gls"): [12, 8, 0],
            ("Performance", "Ast"): [5, 10, 0],
            ("Expected", "npxG"): [10.5, 6.0, 0.0],
            ("Progression", "PrgC"): [80, 60, 1],
        }
    )
    standard.columns = pd.MultiIndex.from_tuples(standard.columns)
    shooting = pd.DataFrame(
        {
            ("player", ""): ["Young Star", "Veteran", "Keeper Low"],
            ("team", ""): ["Alpha FC", "Beta FC", "Alpha FC"],
            ("Standard", "Sh"): [60, 40, 0],
            ("Standard", "SoT%"): [45.0, 38.0, 0.0],
        }
    )
    shooting.columns = pd.MultiIndex.from_tuples(shooting.columns)
    return {"standard": standard, "shooting": shooting}


@pytest.fixture
def normalized_stats() -> pd.DataFrame:
    """collect 出力相当の正規化済み DataFrame。"""
    return pd.DataFrame(
        {
            "player": ["Young Star", "Veteran", "Mid Talent", "Old Ace"],
            "team": ["Alpha FC", "Beta FC", "Gamma FC", "Delta FC"],
            "league": ["TEST-League"] * 4,
            "season": ["2425"] * 4,
            "position": ["FW", "MF,FW", "FW", "FW"],
            "age": [18.0, 29.0, 21.0, 30.0],
            "minutes": [1800.0, 2700.0, 900.0, 2500.0],
            "standard__Performance_Gls": [12.0, 8.0, 4.0, 15.0],
            "standard__Expected_npxG": [10.5, 6.0, 3.5, 13.0],
            "standard__Progression_PrgC": [80.0, 60.0, 30.0, 70.0],
        }
    )
