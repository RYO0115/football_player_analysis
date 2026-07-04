# 概要: UnderstatCollector の正規化ロジックのユニットテスト。
# reader を偽物に差し替え、ネットワークなしで検証する。

from __future__ import annotations

import pandas as pd
import pytest

from football_player_analysis.core.exceptions import CollectionError
from football_player_analysis.features.collect import META_COLUMNS, UnderstatCollector


@pytest.fixture
def raw_understat() -> pd.DataFrame:
    """soccerdata Understat.read_player_season_stats().reset_index() 相当の生データ。"""
    return pd.DataFrame(
        {
            "league": ["ENG-Premier League"] * 2,
            "season": ["2425"] * 2,
            "team": ["Alpha FC", "Beta FC"],
            "team_id": [88, 89],
            "player": ["Young Star", "Veteran"],
            "player_id": [1001, 1002],
            "position": ["F M S", "M S"],
            "matches": [30, 34],
            "minutes": [1800, 2700],
            "goals": [12, 8],
            "xg": [10.2, 6.4],
            "np_xg": [9.1, 6.4],
            "assists": [5, 10],
            "xa": [4.2, 8.8],
            "shots": [60, 40],
            "key_passes": [30, 55],
            "xg_chain": [14.0, 12.0],
            "xg_buildup": [3.5, 6.0],
        }
    )


def make_collector(raw: pd.DataFrame) -> UnderstatCollector:
    return UnderstatCollector(reader_factory=lambda league, season: lambda: raw)


def test_collect_produces_normalized_schema(raw_understat):
    df = make_collector(raw_understat).collect("ENG-Premier League", "2425")
    for col in META_COLUMNS:
        assert col in df.columns
    assert len(df) == 2


def test_collect_prefixes_stats_and_drops_ids(raw_understat):
    df = make_collector(raw_understat).collect("ENG-Premier League", "2425")
    assert df.loc[0, "understat__np_xg"] == pytest.approx(9.1)
    assert df.loc[0, "understat__xg_chain"] == pytest.approx(14.0)
    # ID 列はスタッツではないので取り込まない
    assert not any("player_id" in c or "team_id" in c for c in df.columns)


def test_collect_sets_age_missing(raw_understat):
    # Understat は年齢を提供しないため NA になる (FBref との結合で補完する前提)
    df = make_collector(raw_understat).collect("ENG-Premier League", "2425")
    assert df["age"].isna().all()


def test_collect_raises_on_empty():
    collector = make_collector(pd.DataFrame())
    with pytest.raises(CollectionError):
        collector.collect("ENG-Premier League", "2425")


def test_collect_raises_on_reader_failure():
    def factory(league, season):
        def read():
            raise RuntimeError("boom")

        return read

    with pytest.raises(CollectionError):
        UnderstatCollector(reader_factory=factory).collect("ENG-Premier League", "2425")
