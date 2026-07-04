# 概要: analyze (per-90 / パーセンタイル / レーダー) のユニットテスト。

from __future__ import annotations

import pandas as pd
import pytest

from football_player_analysis.core.exceptions import AnalysisError
from football_player_analysis.features.analyze import (
    add_percentiles,
    position_group,
    render_radar,
    to_per90,
)


def test_to_per90_scales_by_minutes(normalized_stats):
    result = to_per90(normalized_stats)
    young = result[result["player"] == "Young Star"].iloc[0]
    # 1800 分で 12 ゴール → 90 分あたり 0.6
    assert young["standard__Performance_Gls_per90"] == pytest.approx(0.6)


def test_to_per90_filters_low_minutes(normalized_stats):
    result = to_per90(normalized_stats, min_minutes=1000)
    assert "Mid Talent" not in set(result["player"])


def test_to_per90_requires_minutes_column(normalized_stats):
    with pytest.raises(AnalysisError):
        to_per90(normalized_stats.drop(columns=["minutes"]))


def test_position_group_takes_primary_position():
    assert position_group("MF,FW") == "MF"
    assert position_group(None) == "None"  # 未知表記でも落ちない


def test_add_percentiles_ranks_within_position_group(normalized_stats):
    per90 = to_per90(normalized_stats)
    result = add_percentiles(per90, columns=["standard__Performance_Gls_per90"])
    fw = result[result["position_group"] == "FW"]
    pct = fw.set_index("player")["standard__Performance_Gls_per90_pct"]
    # FW グループ内で per-90 ゴール最上位の選手が 100 パーセンタイル
    assert pct.idxmax() == "Young Star"
    assert pct.max() == pytest.approx(100.0)


def test_render_radar_writes_png(tmp_path, normalized_stats):
    per90 = to_per90(normalized_stats)
    analyzed = add_percentiles(per90)
    row = analyzed.iloc[0]
    metrics = [c for c in analyzed.columns if c.endswith("_pct")][:3]
    out = render_radar(row, metrics, tmp_path / "radar.png")
    assert out.exists() and out.stat().st_size > 0
