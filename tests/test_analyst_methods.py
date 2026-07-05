# 概要: アナリスト手法対応 (ポジションテンプレート / 次元スコア / PAdj / 母集団プール)
# のユニットテスト。ネットワークなし・合成データで契約を検証する。

from __future__ import annotations

import pandas as pd
import pytest

from football_player_analysis.core.matching import match_longest_prefix
from football_player_analysis.features.analyze import (
    DimensionConfig,
    RadarAxesConfig,
    add_dimension_scores,
    add_percentiles,
    apply_padj,
    select_radar_metrics,
    to_per90,
)

COLUMNS = [
    "understat__np_xg_per90_pct",
    "standard__Performance_Gls_per90_pct",
    "shooting__Standard_SoT_per90_pct",
    "understat__xa_per90_pct",
    "understat__key_passes_per90_pct",
    "standard__Performance_Ast_per90_pct",
    "understat__xg_buildup_per90_pct",
    "understat__xg_chain_per90_pct",
    "misc__Performance_TklW_per90_pct",
    "misc__Performance_Int_per90_pct",
]


# --- core.matching -----------------------------------------------------------


def test_match_longest_prefix():
    assert match_longest_prefix("DF", ["D", "DF", "MF"]) == "DF"
    assert match_longest_prefix("D", ["DF", "MF"]) == "DF"  # 双方向の前方一致
    assert match_longest_prefix("GK", ["D", "MF"]) is None


# --- ポジション別レーダーテンプレート ---------------------------------------


@pytest.fixture
def template_config(tmp_path):
    path = tmp_path / "radar.toml"
    path.write_text(
        """
[categories.attack]
keywords = ["np_xg", "gls", "sot"]
axes = 3
[categories.defense]
keywords = ["tklw", "int"]
axes = 3

[templates.DF.categories.defense]
keywords = ["tklw", "int"]
axes = 2
[templates.DF.categories.progression]
keywords = ["xg_buildup", "xg_chain"]
axes = 2
[templates.DF.categories.attack]
keywords = ["np_xg"]
axes = 1
""",
        encoding="utf-8",
    )
    return RadarAxesConfig.load(path)


def test_template_applied_for_matching_position(template_config):
    metrics = select_radar_metrics(COLUMNS, template_config, position_group="DF")
    # DF テンプレートは守備 2 + 前進 2 + 攻撃 1 の並び
    assert metrics == [
        "misc__Performance_TklW_per90_pct",
        "misc__Performance_Int_per90_pct",
        "understat__xg_buildup_per90_pct",
        "understat__xg_chain_per90_pct",
        "understat__np_xg_per90_pct",
    ]


def test_template_matches_understat_style_group(template_config):
    # Understat 由来の "D" も前方一致で DF テンプレートに解決される
    assert select_radar_metrics(
        COLUMNS, template_config, position_group="D"
    ) == select_radar_metrics(COLUMNS, template_config, position_group="DF")


def test_default_categories_for_unknown_position(template_config):
    metrics = select_radar_metrics(COLUMNS, template_config, position_group="GK")
    assert metrics == select_radar_metrics(COLUMNS, template_config)


# --- 次元スコア ---------------------------------------------------------------


@pytest.fixture
def analyzed_two_positions():
    df = pd.DataFrame(
        {
            "player": ["AttFW", "DefFW", "AttDF", "DefDF"],
            "team": ["T1", "T2", "T3", "T4"],
            "league": ["L"] * 4,
            "season": ["2526"] * 4,
            "position": ["FW", "FW", "DF", "DF"],
            "age": [20.0] * 4,
            "minutes": [900.0] * 4,
            "understat__np_xg": [9.0, 1.0, 3.0, 0.5],
            "misc__Performance_TklW": [1.0, 3.0, 10.0, 30.0],
        }
    )
    return add_percentiles(to_per90(df))


def test_dimension_scores_are_position_relative(analyzed_two_positions):
    config = DimensionConfig(
        dimensions={"攻撃": {"np_xg": 1.0}, "守備": {"tklw": 1.0}}
    )
    result = add_dimension_scores(analyzed_two_positions, config)
    assert {"dim_攻撃", "dim_守備"} <= set(result.columns)
    # 各ポジション内で攻撃型が dim_攻撃 上位、守備型が dim_守備 上位になる
    by_player = result.set_index("player")
    assert by_player.loc["AttFW", "dim_攻撃"] > by_player.loc["DefFW", "dim_攻撃"]
    assert by_player.loc["DefDF", "dim_守備"] > by_player.loc["AttDF", "dim_守備"]
    # 0-100 の範囲
    assert result[["dim_攻撃", "dim_守備"]].stack().between(0, 100).all()


def test_dimension_skipped_when_no_keyword_matches(analyzed_two_positions):
    config = DimensionConfig(dimensions={"謎": {"nonexistent": 1.0}})
    result = add_dimension_scores(analyzed_two_positions, config)
    assert "dim_謎" not in result.columns


def test_dimension_config_load_falls_back(tmp_path):
    assert DimensionConfig.load(tmp_path / "missing.toml").dimensions


# --- PAdj ---------------------------------------------------------------------


def test_apply_padj_adjusts_defensive_counts_by_possession():
    df = pd.DataFrame(
        {
            "player": ["HighPoss", "LowPoss"],
            "team": ["Dominators", "Bus Parkers"],
            "league": ["L", "L"],
            "season": ["2526", "2526"],
            "position": ["DF", "DF"],
            "age": [20.0, 20.0],
            "minutes": [900.0, 900.0],
            "misc__Performance_TklW": [10.0, 10.0],
            "understat__np_xg": [1.0, 1.0],
        }
    )
    possession = pd.DataFrame(
        {
            "team": ["Dominators", "Bus Parkers"],
            "league": ["L", "L"],
            "season": ["2526", "2526"],
            "possession": [60.0, 40.0],
        }
    )
    result = apply_padj(df, possession).set_index("player")
    # 守備列は _padj にリネームされ、保持率 60% → ×50/40=1.25、40% → ×50/60≈0.833
    assert "misc__Performance_TklW_padj" in result.columns
    assert "misc__Performance_TklW" not in result.columns
    assert result.loc["HighPoss", "misc__Performance_TklW_padj"] == pytest.approx(12.5)
    assert result.loc["LowPoss", "misc__Performance_TklW_padj"] == pytest.approx(
        10 * 50 / 60
    )
    # 攻撃列は無調整
    assert result["understat__np_xg"].tolist() == [1.0, 1.0]


def test_apply_padj_keeps_rows_without_possession():
    df = pd.DataFrame(
        {
            "player": ["Unknown"],
            "team": ["Mystery FC"],
            "league": ["L"],
            "season": ["2526"],
            "position": ["DF"],
            "age": [20.0],
            "minutes": [900.0],
            "misc__Performance_Int": [8.0],
        }
    )
    possession = pd.DataFrame(
        {"team": ["Other"], "league": ["L"], "season": ["2526"], "possession": [50.0]}
    )
    result = apply_padj(df, possession)
    # ポゼッション不明チームは係数 1 (無調整) で残る
    assert result["misc__Performance_Int_padj"].iloc[0] == pytest.approx(8.0)
