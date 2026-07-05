# 概要: FBrefCollector の正規化・結合ロジックのユニットテスト。
# reader を偽物に差し替え、ネットワークなしで検証する。

from __future__ import annotations

import pandas as pd
import pytest

from football_player_analysis.core.exceptions import CollectionError
from football_player_analysis.features.collect import META_COLUMNS, FBrefCollector


def make_collector(frames: dict[str, pd.DataFrame]) -> FBrefCollector:
    def factory(league: str, season: str):
        def read(stat_type: str) -> pd.DataFrame:
            return frames[stat_type]

        return read

    return FBrefCollector(reader_factory=factory, stat_types=list(frames))


def test_collect_produces_normalized_schema(raw_fbref_frames):
    df = make_collector(raw_fbref_frames).collect("TEST-League", "2425")
    for col in META_COLUMNS:
        assert col in df.columns
    assert len(df) == 3


def test_collect_parses_age_and_minutes(raw_fbref_frames):
    df = make_collector(raw_fbref_frames).collect("TEST-League", "2425")
    young = df[df["player"] == "Young Star"].iloc[0]
    # '18-120' (歳-日) 表記から歳数のみ取り出せること
    assert young["age"] == 18.0
    assert young["minutes"] == 1800


def test_collect_excludes_born_and_season_columns(raw_fbref_frames):
    # born (生年) や season は数値に見えるがスタッツではないため取り込まないこと
    frames = dict(raw_fbref_frames)
    standard = frames["standard"].copy()
    standard[("born", "")] = [2006, 1995, 2000]
    standard[("season", "")] = [2526, 2526, 2526]
    frames["standard"] = standard
    df = make_collector(frames).collect("TEST-League", "2425")
    assert not any("born" in c for c in df.columns)
    assert not any(c == "standard__season" for c in df.columns)


def test_collect_merges_multiple_stat_types(raw_fbref_frames):
    df = make_collector(raw_fbref_frames).collect("TEST-League", "2425")
    assert any(c.startswith("standard__") for c in df.columns)
    assert any(c.startswith("shooting__") for c in df.columns)
    young = df[df["player"] == "Young Star"].iloc[0]
    assert young["shooting__Standard_Sh"] == 60


def test_collect_skips_unsupported_stat_types(raw_fbref_frames):
    # リーグによって提供されない stat_type (soccerdata が ValueError を出す) は
    # 収集全体を止めずスキップされること
    def factory(league: str, season: str):
        def read(stat_type: str) -> pd.DataFrame:
            if stat_type == "passing":
                # soccerdata は未対応 stat_type を TypeError で送出する
                raise TypeError(
                    "Invalid argument: stat_type should be in ['standard', 'shooting']"
                )
            return raw_fbref_frames[stat_type]

        return read

    collector = FBrefCollector(
        reader_factory=factory, stat_types=["standard", "passing", "shooting"]
    )
    df = collector.collect("TEST-League", "2425")
    assert len(df) == 3
    assert any(c.startswith("shooting__") for c in df.columns)
    assert not any(c.startswith("passing__") for c in df.columns)


def test_collect_raises_on_reader_failure(raw_fbref_frames):
    def factory(league: str, season: str):
        def read(stat_type: str) -> pd.DataFrame:
            raise RuntimeError("boom")

        return read

    collector = FBrefCollector(reader_factory=factory, stat_types=["standard"])
    with pytest.raises(CollectionError):
        collector.collect("TEST-League", "2425")
