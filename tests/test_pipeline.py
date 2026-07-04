# 概要: パイプライン全体の結合テスト (ネットワークなし・偽コレクター使用)。
# collect → analyze → predict → report → publish が契約どおり繋がることを検証する。

from __future__ import annotations

import pandas as pd
import pytest

from football_player_analysis.core.config import Settings, SubstackConfig
from football_player_analysis.features.predict import PotentialConfig
from football_player_analysis.pipeline import Pipeline


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
    assert (tmp_path / "raw_player_season").exists()
    assert (tmp_path / "analyzed_player_season").exists()


def test_predict_before_collect_raises(pipeline):
    with pytest.raises(FileNotFoundError):
        pipeline.predict()
