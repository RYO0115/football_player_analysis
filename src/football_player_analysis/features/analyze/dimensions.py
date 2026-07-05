# 概要: smarterscout 流の「次元スコア」(攻撃/創造/前進/守備 の 0-100) を算出する。
# 単一の総合点ではなく次元別に選手を表すことで、ポジション・特性の異なる
# 選手を同じ物差しで誤って比較する問題を避ける。
# 次元の定義 (名前・キーワード・重み) はドメイン語彙のため config/dimensions.toml
# から読み、コードに列挙しない。

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from football_player_analysis.features.analyze.percentiles import position_group
from football_player_analysis.features.analyze.radar_axes import metric_key

# 次元スコア列の接頭辞 (技術的に閉じた命名規約)
DIM_PREFIX = "dim_"

# TOML が無い環境でも動くフォールバック (キーは表示名を兼ねる)
_FALLBACK_DIMENSIONS: dict[str, dict[str, float]] = {
    "攻撃": {"np_xg": 3.0, "gls": 2.0, "sot": 1.5, "shots": 1.0},
    "創造": {"xa": 3.0, "key_passes": 2.0, "ast": 2.0, "sca": 1.5},
    "前進": {"xg_buildup": 3.0, "xg_chain": 2.0, "prg": 2.0, "carries": 1.0},
    "守備": {"tklw": 3.0, "int": 3.0, "aerial": 1.5, "recov": 1.5},
}


@dataclass(frozen=True)
class DimensionConfig:
    """次元名 → {キーワード: 重み} の設定。定義順が表示順。"""

    dimensions: dict[str, dict[str, float]] = field(
        default_factory=lambda: dict(_FALLBACK_DIMENSIONS)
    )

    @classmethod
    def load(cls, path: Path | None) -> "DimensionConfig":
        """TOML から設定を読む。path=None や不存在時はフォールバック値を使う。"""
        if path is None or not Path(path).exists():
            return cls()
        with open(path, "rb") as f:
            data = tomllib.load(f)
        raw = data.get("dimensions", {})
        if not raw:
            return cls()
        return cls(
            dimensions={
                name: dict(spec.get("metric_weights", {})) for name, spec in raw.items()
            }
        )


def add_dimension_scores(
    df: pd.DataFrame, config: DimensionConfig | None = None
) -> pd.DataFrame:
    """次元ごとの 0-100 スコア列 (dim_<次元名>) を追加する。

    次元スコア = キーワードに一致した *_pct 列の重み付き平均を、さらに
    position_group 内でパーセンタイル化したもの (smarterscout の 0-99 相当)。
    ポジション内で再正規化するのは「DF の攻撃 80」のような値を
    同ポジション比較として解釈できるようにするため。
    キーワードが 1 列も一致しない次元は列を作らずスキップする。
    """
    config = config or DimensionConfig()
    result = df.copy()
    if "position_group" not in result.columns:
        result["position_group"] = result["position"].map(position_group)

    pct_cols = [c for c in result.columns if c.endswith("_pct")]
    keys = {c: metric_key(c) for c in pct_cols}

    for name, weights in config.dimensions.items():
        col_weights = {
            c: w
            for keyword, w in weights.items()
            for c in pct_cols
            if keyword.lower() in keys[c]
        }
        if not col_weights:
            continue
        composite = sum(
            result[c].fillna(50.0) * w for c, w in col_weights.items()
        ) / sum(col_weights.values())
        result[f"{DIM_PREFIX}{name}"] = (
            composite.groupby(result["position_group"]).rank(pct=True) * 100.0
        )
    return result
