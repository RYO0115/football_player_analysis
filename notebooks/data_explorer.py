# 概要: 収集済みデータ (merged: FBref × Understat × Transfermarkt) を
# インタラクティブに探索する marimo ノートブック。
# リポジトリルートから `uv run marimo edit notebooks/data_explorer.py` で起動する。
# 事前に collect/merge/analyze を実行し data/analyzed_player_season_merged/ が
# 存在している必要がある。

import marimo

__generated_with = "0.23.13"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md("""
    # ⚽ Football Player Analysis — データエクスプローラ

    3 ソース結合済みデータ (FBref: 基本/守備 + Understat: xG 系 + Transfermarkt: 市場価値/身長) を、
    著名アナリストの手法 (`docs/analyst_methods.md` 参照) に基づく評価で確認できます:

    - **PAdj**: 守備カウントはポゼッション調整済み (`TklW (PAdj)` 等)
    - **次元スコア 0-100**: 攻撃/創造/前進/守備を**同ポジション内**で相対化 (smarterscout 流)
    - **ポジション別レーダーテンプレート**: DF は守備・前進を厚く表示 (StatsBomb 流)
    - **母集団**: 全リーグ統合 (`--pool all` で解析済み)

    構成: **潜在能力ランキング → 次元スコア別リーダー → 散布図 → 選手個票**
    """)
    return


@app.cell
def _():
    from pathlib import Path

    import pandas as pd

    from football_player_analysis.core.storage import ParquetStorage
    from football_player_analysis.features.predict import (
        PotentialConfig,
        score_potential,
    )

    storage = ParquetStorage(Path("data"))
    # 解析済み (per-90 + パーセンタイル) の全リーグを縦結合
    analyzed = storage.load_all("analyzed_player_season_merged")
    potential_config = PotentialConfig.load(Path("config/potential.toml"))
    # 若手 (max_age 以下・最低出場時間以上) に潜在能力スコアを付与した降順ランキング
    ranked = score_potential(analyzed, potential_config)
    return Path, pd, ranked


@app.cell
def _(mo, ranked):
    league_dd = mo.ui.dropdown(
        options=["All", *sorted(ranked["league"].unique())],
        value="All",
        label="リーグ",
    )
    profile_dd = mo.ui.dropdown(
        options=["All", *sorted(ranked["applied_profile"].unique())],
        value="All",
        label="適用プロファイル",
    )
    top_slider = mo.ui.slider(5, 50, value=15, label="表示件数")
    mo.hstack([league_dd, profile_dd, top_slider], justify="start", gap=2)
    return league_dd, profile_dd, top_slider


@app.cell
def _(league_dd, mo, profile_dd, ranked, top_slider):
    view = ranked
    if league_dd.value != "All":
        view = view[view["league"] == league_dd.value]
    if profile_dd.value != "All":
        view = view[view["applied_profile"] == profile_dd.value]

    _cols = [
        "player",
        "team",
        "league",
        "position",
        "age",
        "minutes",
        "applied_profile",
        "potential_score",
    ]
    # 次元スコア (0-100、同ポジション内) を並べて選手タイプを読めるようにする
    _cols += [c for c in view.columns if str(c).startswith("dim_")]
    if "transfermarkt__attr_market_value_eur" in view.columns:
        _cols.append("transfermarkt__attr_market_value_eur")

    ranking_table = mo.ui.table(
        view[_cols].head(top_slider.value).round(1),
        selection=None,
        label="潜在能力スコア ランキング (若手のみ)",
    )
    ranking_table
    return


@app.cell
def _(mo):
    mo.md("""
    ## 次元スコア別リーダー (U24)

    smarterscout 流の次元スコアで「タイプ別のトップ若手」を発掘する。
    次元を選ぶと、その次元が同ポジション内で最も高い U24 選手が並ぶ。
    """)
    return


@app.cell
def _(mo, ranked):
    _dim_cols = [c for c in ranked.columns if str(c).startswith("dim_")]
    dim_dd = mo.ui.dropdown(
        options=_dim_cols,
        value=_dim_cols[0] if _dim_cols else None,
        label="次元",
    )
    dim_dd
    return (dim_dd,)


@app.cell
def _(dim_dd, mo, ranked):
    _dim = dim_dd.value
    _cols = ["player", "team", "league", "position", "age", "minutes", _dim]
    _others = [c for c in ranked.columns if str(c).startswith("dim_") and c != _dim]
    leaders = ranked.sort_values(_dim, ascending=False).head(10)
    dim_table = mo.ui.table(
        leaders[_cols + _others].round(1),
        selection=None,
        label=f"{str(_dim).removeprefix('dim_')} 次元のトップ 10 (U24)",
    )
    dim_table
    return


@app.cell
def _(mo):
    mo.md("""
    ## 市場価値 × 潜在能力スコア
    """)
    return


@app.cell
def _(pd, ranked):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _mv_col = "transfermarkt__attr_market_value_eur"
    scatter_df = ranked[pd.notna(ranked.get(_mv_col))]

    _fig, _ax = plt.subplots(figsize=(9, 5))
    for _profile, _grp in scatter_df.groupby("applied_profile"):
        _ax.scatter(
            _grp["potential_score"],
            _grp[_mv_col] / 1e6,
            label=_profile,
            alpha=0.6,
            s=24,
        )
    # スコア上位は名前を添えて「割安/割高」を読めるようにする
    for _, _row in scatter_df.head(12).iterrows():
        _ax.annotate(
            _row["player"],
            (_row["potential_score"], _row[_mv_col] / 1e6),
            fontsize=7,
            xytext=(4, 2),
            textcoords="offset points",
        )
    _ax.set_xlabel("potential_score")
    _ax.set_ylabel("market value (M EUR)")
    _ax.set_title("Market value vs potential score (U24, GER+FRA 2526)")
    _ax.legend(title="profile", fontsize=8)
    _ax.grid(alpha=0.3)
    _fig
    return plt, scatter_df


@app.cell
def _(mo):
    mo.md("""
    ## 選手個票 — レーダーチャート + N5 風カード
    """)
    return


@app.cell
def _(mo, ranked):
    # 同名選手がいると dropdown のキーが衝突するため、順位を保ったまま重複除去する
    _unique_players = list(dict.fromkeys(ranked["player"]))
    player_dd = mo.ui.dropdown(
        options=_unique_players,
        value=_unique_players[0],
        label="選手",
    )
    player_dd
    return (player_dd,)


@app.cell
def _(Path, mo, player_dd, plt, ranked):
    from football_player_analysis.features.analyze import (
        RadarAxesConfig,
        render_radar,
        select_radar_metrics,
    )
    from football_player_analysis.features.report.markdown import (
        card_body,
        card_heading,
    )

    _hit = ranked[ranked["player"] == player_dd.value]
    _rank = _hit.index[0] + 1
    _row = _hit.iloc[0]

    # レーダーの軸: ポジション別テンプレート (StatsBomb 流、config/radar.toml)
    _metrics = select_radar_metrics(
        _row.index,
        RadarAxesConfig.load(Path("config/radar.toml")),
        position_group=_row.get("position_group"),
    )

    _radar_path = Path("data/output/_radar_preview.png")
    render_radar(_row, _metrics, _radar_path, title=f"{_row['player']} ({_row['team']})")
    plt.close("all")

    # 右カラムは選手名 (見出し) を上に、ポジション等の情報をその下に縦積みする
    mo.hstack(
        [
            mo.image(str(_radar_path), width=430),
            mo.vstack(
                [
                    mo.md(card_heading(_rank, _row)),
                    mo.md(card_body(_row)),
                ],
                align="start",
                gap=0.5,
            ),
        ],
        gap=2,
        align="center",
    )
    return


@app.cell
def _(mo, scatter_df):
    mo.md(f"""
    ---
    データ: 解析済み {len(scatter_df)} 人 (市場価値あり・U24)。
    収集からの再生成は `uv run fpa collect/merge/analyze` (README 参照)。
    """)
    return


if __name__ == "__main__":
    app.run()
