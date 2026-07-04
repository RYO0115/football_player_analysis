# 概要: パイプライン全体の結合テスト (ネットワークなし・偽コレクター使用)。
# collect → analyze → predict → report → publish が契約どおり繋がることを検証する。

from __future__ import annotations

import pandas as pd
import pytest

from football_player_analysis.core.config import Settings, SubstackConfig
from football_player_analysis.core.storage import ParquetStorage
from football_player_analysis.features.predict import PotentialConfig
from football_player_analysis.pipeline import RAW_DATASET, Pipeline


class FakeCollector:
    """ネットワークに出ず normalized_stats を返す偽コレクター。"""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def collect(self, league: str, season: str) -> pd.DataFrame:
        return self._df.assign(league=league, season=season)


@pytest.fixture
def pipeline(tmp_path, normalized_stats):
    settings = Settings(
        data_dir=tmp_path, dry_run=True, substack=SubstackConfig()
    )
    return Pipeline(settings=settings, collector=FakeCollector(normalized_stats))


def test_full_run_produces_local_article(pipeline, tmp_path):
    result = pipeline.run(
        leagues=["TEST-League"],
        season="2425",
        potential_config=PotentialConfig(min_minutes=0),
        top_n=5,
    )
    # dry_run 既定なので成果物はローカル Markdown
    assert result.endswith(".md")
    assert (tmp_path / "output").exists()


def test_collect_then_analyze_persists_parquet(pipeline, tmp_path):
    pipeline.collect("TEST-League", "2425")
    pipeline.analyze("TEST-League", "2425", min_minutes=0)
    # ソース別にディレクトリが分かれること (複数ソースの共存が前提)
    assert (tmp_path / "raw_player_season_fbref").exists()
    assert (tmp_path / "analyzed_player_season_fbref").exists()


def test_predict_before_collect_raises(pipeline):
    with pytest.raises(FileNotFoundError):
        pipeline.predict()


def test_merge_then_analyze_merged_source(pipeline, tmp_path, normalized_stats):
    # primary (fbref) を収集
    pipeline.collect("TEST-League", "2425")
    # secondary (understat) 相当を直接保存する (別ソースは別コレクター前提のため)
    secondary = normalized_stats[["player", "team", "league", "season"]].assign(
        position="FW",
        age=pd.NA,
        minutes=[1800.0, 2700.0, 900.0, 2500.0],
        understat__xg=[10.0, 5.0, 3.0, 12.0],
    )
    ParquetStorage(tmp_path).save(
        secondary, f"{RAW_DATASET}_understat", "TEST-League", "2425"
    )

    merged_path = pipeline.merge("TEST-League", "2425", secondary_source="understat")
    assert merged_path.exists()

    # "merged" ソースの Pipeline は collector 無しでも analyze が通ること
    merged_pipeline = Pipeline(settings=pipeline.settings, source="merged")
    analyzed_path = merged_pipeline.analyze("TEST-League", "2425", min_minutes=0)
    assert analyzed_path.exists()
    analyzed = pd.read_parquet(analyzed_path)
    # secondary の xG が結合され per-90 換算列まで出来ていること
    assert "understat__xg_per90" in analyzed.columns
