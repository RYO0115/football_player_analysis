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


def test_config_load_without_profiles_section_defaults_empty(tmp_path):
    # profiles 無しの旧形式 TOML でも従来どおり動くこと (後方互換)。
    path = tmp_path / "potential.toml"
    path.write_text('[metric_weights]\nxg = 5.0\n', encoding="utf-8")
    config = PotentialConfig.load(path)
    assert config.profiles == {}


def test_config_load_reads_profiles(tmp_path):
    path = tmp_path / "potential.toml"
    path.write_text(
        "max_age = 22\n"
        "[metric_weights]\n"
        "xg = 5.0\n"
        "[profiles.DF.metric_weights]\n"
        "tklw = 2.5\n"
        "int = 2.5\n"
        "[profiles.MF.metric_weights]\n"
        "xg_buildup = 2.0\n",
        encoding="utf-8",
    )
    config = PotentialConfig.load(path)
    assert config.profiles["DF"] == {"tklw": 2.5, "int": 2.5}
    assert config.profiles["MF"] == {"xg_buildup": 2.0}


def test_applied_profile_column_defaults_without_profiles(analyzed):
    # profiles 未設定なら全選手 "default" が適用される。
    ranked = score_potential(analyzed, PotentialConfig(min_minutes=0))
    assert "applied_profile" in ranked.columns
    assert set(ranked["applied_profile"]) == {"default"}


def test_df_profile_boosts_defensive_young_player_over_default_weights():
    # 守備型の若手 DF は、攻撃寄りの既定重みより DF プロファイル適用時の方が
    # 高スコアになるべき (ボランチ・DF 型の若手過小評価を是正する目的の検証)。
    import pandas as pd

    df = pd.DataFrame(
        {
            "player": ["Young DF"],
            "team": ["X"],
            "league": ["L"],
            "season": ["2425"],
            "position": ["DF"],
            "age": [19.0],
            "minutes": [1000.0],
            "misc__Performance_TklW_per90_pct": [90.0],
            "misc__Performance_Int_per90_pct": [90.0],
            "standard__Expected_npxG_per90_pct": [10.0],
        }
    )
    attack_weights = {"npxg": 3.0, "gls": 2.0}

    with_profile = score_potential(
        df,
        PotentialConfig(
            metric_weights=attack_weights,
            profiles={"DF": {"tklw": 2.5, "int": 2.5}},
            min_minutes=0,
        ),
    )
    without_profile = score_potential(
        df, PotentialConfig(metric_weights=attack_weights, min_minutes=0)
    )

    assert with_profile.iloc[0]["applied_profile"] == "DF"
    assert without_profile.iloc[0]["applied_profile"] == "default"
    assert (
        with_profile.iloc[0]["potential_score"]
        > without_profile.iloc[0]["potential_score"]
    )


def test_profile_falls_back_to_default_when_no_keyword_matches():
    # プロファイルの重みキーワードが 1 列も一致しない場合は既定にフォールバック
    # し、全体をエラーにしないこと。
    import pandas as pd

    df = pd.DataFrame(
        {
            "player": ["Some DF"],
            "team": ["X"],
            "league": ["L"],
            "season": ["2425"],
            "position": ["DF"],
            "age": [20.0],
            "minutes": [1000.0],
            "standard__Expected_npxG_per90_pct": [70.0],
        }
    )
    config = PotentialConfig(
        metric_weights={"npxg": 3.0},
        profiles={"DF": {"nonexistent_keyword": 1.0}},
        min_minutes=0,
    )
    ranked = score_potential(df, config)
    assert ranked.iloc[0]["applied_profile"] == "default"


def test_profile_prefix_matching_prefers_longest_key():
    # position_group "DF" はキー "D" にも "DF" にもマッチしうるが、
    # 最長一致の "DF" が優先されるべき。
    import pandas as pd

    df = pd.DataFrame(
        {
            "player": ["P1"],
            "team": ["X"],
            "league": ["L"],
            "season": ["2425"],
            "position": ["DF"],
            "age": [20.0],
            "minutes": [1000.0],
            "standard__Expected_npxG_per90_pct": [50.0],
            "tklw_per90_pct": [80.0],
            "int_per90_pct": [80.0],
        }
    )
    config = PotentialConfig(
        metric_weights={"npxg": 3.0},
        profiles={"D": {"tklw": 1.0}, "DF": {"int": 2.0}},
        min_minutes=0,
    )
    ranked = score_potential(df, config)
    assert ranked.iloc[0]["applied_profile"] == "DF"


def test_position_group_derived_when_missing_from_input():
    # position_group 列が無い入力でも position 列から導出して動作すること。
    import pandas as pd

    df = pd.DataFrame(
        {
            "player": ["Young DF"],
            "team": ["X"],
            "league": ["L"],
            "season": ["2425"],
            "position": ["DF,MF"],
            "age": [20.0],
            "minutes": [1000.0],
            "standard__Expected_npxG_per90_pct": [50.0],
            "tklw_per90_pct": [80.0],
        }
    )
    config = PotentialConfig(
        metric_weights={"npxg": 3.0},
        profiles={"DF": {"tklw": 2.0}},
        min_minutes=0,
    )
    ranked = score_potential(df, config)
    assert ranked.iloc[0]["applied_profile"] == "DF"
