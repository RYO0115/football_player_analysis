# 概要: features/collect/merge.py の名前正規化・ソース結合ロジックのユニットテスト。
# 偽データのみ使用しネットワークには出ない。

from __future__ import annotations

import pandas as pd
import pytest

from football_player_analysis.features.collect import META_COLUMNS
from football_player_analysis.features.collect.merge import (
    merge_sources,
    normalize_player_name,
)


@pytest.fixture
def primary() -> pd.DataFrame:
    """FBref 相当の正規化済み DataFrame (age あり・アクセント付き名・xG 無し)。"""
    return pd.DataFrame(
        {
            "player": ["Luka Vušković", "Erling Haaland", "Lonely Guy"],
            "team": ["Alpha FC", "Beta FC", "Gamma FC"],
            "league": ["ENG-Premier League"] * 3,
            "season": ["2425"] * 3,
            "position": ["DF", "FW", "MF"],
            "age": [18.0, 24.0, 22.0],
            "minutes": [1800.0, 2500.0, 900.0],
            "misc__Performance_Int": [30.0, 5.0, 12.0],
        }
    )


@pytest.fixture
def secondary() -> pd.DataFrame:
    """Understat 相当の正規化済み DataFrame (age は NA・ASCII 名・xG 系あり)。"""
    return pd.DataFrame(
        {
            "player": ["Luka Vuskovic", "Erling Haaland"],
            "team": ["Alpha FC", "Beta FC"],
            "league": ["ENG-Premier League"] * 2,
            "season": ["2425"] * 2,
            "position": ["D", "F"],
            "age": [pd.NA, pd.NA],
            "minutes": [1800.0, 2500.0],
            "understat__xg": [1.2, 22.5],
            "understat__np_xg": [0.9, 18.0],
        }
    )


def test_normalize_removes_accents_and_case():
    # アクセント有無・大文字小文字が違っても同一キーになること
    assert normalize_player_name("Luka Vušković") == normalize_player_name(
        "Luka Vuskovic"
    )
    assert normalize_player_name("  Kylian  MBAPPÉ ") == "kylian mbappe"


def test_merge_keeps_primary_meta_and_adds_secondary_stats(primary, secondary):
    merged = merge_sources(primary, secondary)
    for col in META_COLUMNS:
        assert col in merged.columns
    luka = merged[merged["player"] == "Luka Vušković"].iloc[0]
    # メタは primary 優先 (age が付く / primary の position 表記が残る)
    assert luka["age"] == 18.0
    assert luka["position"] == "DF"
    # secondary のスタッツ列が名前正規化を跨いで取り込まれること
    assert luka["understat__xg"] == pytest.approx(1.2)
    assert luka["understat__np_xg"] == pytest.approx(0.9)
    # primary の元スタッツも保持される
    assert luka["misc__Performance_Int"] == pytest.approx(30.0)


def test_merge_left_join_keeps_unmatched_primary(primary, secondary):
    merged = merge_sources(primary, secondary)
    # secondary に居ない選手は primary 側に残り、スタッツ列は NaN
    assert len(merged) == len(primary)
    lonely = merged[merged["player"] == "Lonely Guy"].iloc[0]
    assert pd.isna(lonely["understat__xg"])


def test_merge_drops_ambiguous_duplicate_from_secondary(primary):
    # secondary に同名 (正規化後同一) が 2 人いる曖昧ケースは除外され、
    # 誤ったスタッツが付かない (NaN のまま) こと
    ambiguous = pd.DataFrame(
        {
            "player": ["Luka Vuskovic", "Luka Vuskovic"],
            "team": ["Alpha FC", "Zeta FC"],
            "league": ["ENG-Premier League"] * 2,
            "season": ["2425"] * 2,
            "position": ["D", "D"],
            "age": [pd.NA, pd.NA],
            "minutes": [1800.0, 500.0],
            "understat__xg": [1.2, 9.9],
        }
    )
    merged = merge_sources(primary, ambiguous)
    assert len(merged) == len(primary)
    luka = merged[merged["player"] == "Luka Vušković"].iloc[0]
    assert pd.isna(luka["understat__xg"])


def test_merge_does_not_leak_key_column(primary, secondary):
    merged = merge_sources(primary, secondary)
    assert not any(c.startswith("_") for c in merged.columns)
