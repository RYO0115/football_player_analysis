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


def test_to_per90_skips_already_per90_columns(normalized_stats):
    # FBref の 'Per 90 Minutes' グループはすでに per-90 なので二重換算しないこと
    df = normalized_stats.assign(**{"standard__Per 90 Minutes_Gls": [0.6, 0.3, 0.4, 0.5]})
    result = to_per90(df)
    assert "standard__Per 90 Minutes_Gls_per90" not in result.columns
    assert result["standard__Per 90 Minutes_Gls"].tolist()[:2] == [0.6, 0.3]


def test_to_per90_requires_minutes_column(normalized_stats):
    with pytest.raises(AnalysisError):
        to_per90(normalized_stats.drop(columns=["minutes"]))


def test_to_per90_skips_attr_columns(normalized_stats):
    # 市場価値等の `__attr_` 静的属性列は per-90 換算せず値をそのまま残すこと
    df = normalized_stats.assign(
        **{"transfermarkt__attr_market_value_eur": [6.0e7, 3.0e7, 1.0e7, 2.0e7]}
    )
    result = to_per90(df)
    assert "transfermarkt__attr_market_value_eur_per90" not in result.columns
    young = result[result["player"] == "Young Star"].iloc[0]
    assert young["transfermarkt__attr_market_value_eur"] == pytest.approx(6.0e7)


def test_position_group_takes_primary_position():
    assert position_group("MF,FW") == "MF"  # FBref 形式
    assert position_group("D M S") == "D"  # Understat 形式 (空白区切り)
    assert position_group("None") == "None"  # 未知表記でも落ちない
    assert position_group("") == "UNKNOWN"


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


# --- レーダー軸のカテゴリ均等選択 (radar_axes) --------------------------------


def test_select_radar_metrics_balances_categories():
    # 攻撃系キーワードだけで軸が埋まらず、守備系も必ず含まれること
    from football_player_analysis.features.analyze import select_radar_metrics

    columns = [
        "understat__np_xg_per90_pct",
        "standard__Performance_Gls_per90_pct",
        "shooting__Standard_SoT_per90_pct",
        "shooting__Standard_Sh_per90_pct",
        "understat__xa_per90_pct",
        "understat__key_passes_per90_pct",
        "standard__Performance_Ast_per90_pct",
        "understat__xg_buildup_per90_pct",
        "understat__xg_chain_per90_pct",
        "misc__Performance_TklW_per90_pct",
        "misc__Performance_Int_per90_pct",
    ]
    metrics = select_radar_metrics(columns)
    # 守備カテゴリ (TklW / Int) が末尾側に含まれる
    assert "misc__Performance_TklW_per90_pct" in metrics
    assert "misc__Performance_Int_per90_pct" in metrics
    # 攻撃はカテゴリ上限 (3 本) を超えない
    attack = [m for m in metrics if any(k in m.lower() for k in ("xg_per", "np_xg", "gls", "sot", "sh_"))]
    assert len(attack) <= 3


def test_select_radar_metrics_dedupes_same_label_across_sources():
    from football_player_analysis.features.analyze import select_radar_metrics

    columns = [
        "standard__Performance_Gls_per90_pct",
        "shooting__Standard_Gls_per90_pct",  # ソース違いの同名指標
        "misc__Performance_TklW_per90_pct",
    ]
    metrics = select_radar_metrics(columns)
    gls = [m for m in metrics if "gls" in m.lower()]
    assert len(gls) == 1


def test_select_radar_metrics_skips_junk_and_rate_columns():
    from football_player_analysis.features.analyze import select_radar_metrics

    columns = [
        "standard__born_per90_pct",  # 生年 (指標ではない)
        "shooting__Standard_G/Sh_per90_pct",  # 率系の派生
        "misc__Performance_Int_per90_pct",
    ]
    metrics = select_radar_metrics(columns)
    assert metrics == ["misc__Performance_Int_per90_pct"]


def test_radar_axes_config_load(tmp_path):
    from football_player_analysis.features.analyze import (
        RadarAxesConfig,
        select_radar_metrics,
    )

    path = tmp_path / "radar.toml"
    path.write_text(
        '[categories.defense]\nkeywords = ["int"]\naxes = 1\n', encoding="utf-8"
    )
    config = RadarAxesConfig.load(path)
    metrics = select_radar_metrics(
        ["understat__xg_per90_pct", "misc__Performance_Int_per90_pct"], config
    )
    # 設定したカテゴリだけが使われる
    assert metrics == ["misc__Performance_Int_per90_pct"]


def test_radar_axes_config_load_falls_back_without_file(tmp_path):
    from football_player_analysis.features.analyze import RadarAxesConfig

    config = RadarAxesConfig.load(tmp_path / "missing.toml")
    assert config.categories  # フォールバックのカテゴリ定義が入っている


def test_metric_label_keeps_snake_case_names_intact():
    # np_xg が 'xg' に化けず、FBref 系はカテゴリを落として短くなること
    from football_player_analysis.features.analyze.radar_axes import metric_label

    assert metric_label("understat__np_xg_per90_pct") == "np_xg"
    assert metric_label("understat__key_passes_per90_pct") == "key_passes"
    assert metric_label("misc__Performance_TklW_per90_pct") == "TklW"
    assert metric_label("shooting__Standard_SoT_per90_pct") == "SoT"


def test_metric_full_name_maps_abbreviations_to_official_names():
    # 略称 (SoT, TklW, np_xg 等) が正式名称に対応づくこと
    from football_player_analysis.features.analyze.radar_axes import metric_full_name

    assert metric_full_name("shooting__Standard_SoT_per90_pct").startswith(
        "Shots on Target"
    )
    assert metric_full_name("misc__Performance_TklW_per90_pct").startswith(
        "Tackles Won"
    )
    assert metric_full_name("understat__np_xg_per90_pct").startswith(
        "Non-Penalty Expected Goals"
    )
    # 対応表に無い略称は略称のまま返す (注釈側で省略される)
    assert metric_full_name("shooting__Foo_Bar_per90_pct") == "Bar"


def test_metric_display_label_uses_conventional_xg_xa_casing():
    # Understat 系の全小文字ラベルは慣用表記 (xG / xA) に整える
    from football_player_analysis.features.analyze.radar_axes import (
        metric_display_label,
    )

    assert metric_display_label("understat__xg_per90_pct") == "xG"
    assert metric_display_label("understat__xa_per90_pct") == "xA"
    assert metric_display_label("understat__np_xg_per90_pct") == "np_xG"
    assert metric_display_label("understat__xg_buildup_per90_pct") == "xG_buildup"
    assert metric_display_label("understat__key_passes_per90_pct") == "key_passes"
    # FBref 系は元の大小文字を尊重する
    assert metric_display_label("misc__Performance_TklW_per90_pct") == "TklW"
