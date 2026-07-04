# 概要: 潜在能力スコア (predict) のユニットテスト。
# 年齢フィルタ・重み適用・並び順という「外から見える契約」を検証する。

from __future__ import annotations

import pytest

from football_player_analysis.core.exceptions import AnalysisError
from football_player_analysis.features.analyze import add_percentiles, to_per90
from football_player_analysis.features.predict import PotentialConfig, score_potential


@pytest.fixture
def analyzed(normalized_stats):
    return add_percentiles(to_per90(normalized_stats))


def test_score_excludes_players_over_max_age(analyzed):
    ranked = score_potential(analyzed, PotentialConfig(max_age=24.0, min_minutes=0))
    assert set(ranked["player"]) <= {"Young Star", "Mid Talent"}
    assert "Veteran" not in set(ranked["player"])


def test_score_is_sorted_descending(analyzed):
    ranked = score_potential(analyzed, PotentialConfig(min_minutes=0))
    scores = ranked["potential_score"].tolist()
    assert scores == sorted(scores, reverse=True)


def test_younger_equal_ability_scores_higher():
    # 同能力なら若い方が高スコアになる (年齢係数の検証)
    import pandas as pd

    df = pd.DataFrame(
        {
            "player": ["A18", "B23"],
            "team": ["X", "Y"],
            "league": ["L", "L"],
            "season": ["2425", "2425"],
            "position": ["FW", "FW"],
            "age": [18.0, 23.0],
            "minutes": [1000.0, 1000.0],
            "gls_per90_pct": [80.0, 80.0],
        }
    )
    ranked = score_potential(
        df, PotentialConfig(metric_weights={"gls": 1.0}, min_minutes=0)
    )
    assert ranked.iloc[0]["player"] == "A18"
    assert ranked.iloc[0]["potential_score"] > ranked.iloc[1]["potential_score"]


def test_score_requires_percentile_columns(normalized_stats):
    with pytest.raises(AnalysisError):
        score_potential(normalized_stats)


def test_config_load_falls_back_without_file(tmp_path):
    config = PotentialConfig.load(tmp_path / "missing.toml")
    assert config.metric_weights  # フォールバック重みが入っている


def test_config_load_reads_toml(tmp_path):
    path = tmp_path / "potential.toml"
    path.write_text(
        'max_age = 22\n[metric_weights]\nxg = 5.0\n', encoding="utf-8"
    )
    config = PotentialConfig.load(path)
    assert config.max_age == 22.0
    assert config.metric_weights == {"xg": 5.0}
