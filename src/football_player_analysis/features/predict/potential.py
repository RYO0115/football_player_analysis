# 概要: 若手選手の「スーパースター潜在能力スコア」算出。
# v0 はドメイン知識ベースの重み付きパーセンタイル合成 + 年齢カーブで実装し、
# 将来的に「翌シーズン以降の市場価値上昇」を教師にした ML モデルへ
# 差し替えられるよう、入出力を DataFrame 契約で固定している。
#
# 重み・年齢パラメータはコードに埋めず TOML (config/potential.toml) から読む。
# 指標名はデータソース側で増減するため、重みのキーは「列名に含まれる
# キーワード」として扱い、一致した *_pct 列すべてに適用する。

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from football_player_analysis.core.exceptions import AnalysisError

# TOML が無い環境でも動かすための最終フォールバック。
# 攻撃貢献 (xG/ゴール)・前進 (プログレッシブ)・創造性 (アシスト/キーパス) を重視する。
_FALLBACK_WEIGHTS = {
    "npxg": 3.0,
    "xg": 2.0,
    "gls": 2.0,
    "ast": 1.5,
    "sca": 1.5,
    "prg": 2.0,
    "carries": 1.0,
    "tkl": 0.5,
}


@dataclass(frozen=True)
class PotentialConfig:
    """潜在能力スコアのパラメータ一式。"""

    # キーワード → 重み。キーワードを含む *_pct 列すべてに重みが掛かる。
    metric_weights: dict[str, float] = field(
        default_factory=lambda: dict(_FALLBACK_WEIGHTS)
    )
    # この年齢以下なら年齢ボーナスが最大になる
    full_bonus_age: float = 18.0
    # この年齢を超えると「今後スーパースターになる」候補から外す
    max_age: float = 24.0
    # 年齢によらず能力そのものに与える最低ウェイト (若さだけで上位に来るのを防ぐ)
    ability_floor: float = 0.35
    # スコア対象とする最低出場時間 (ノイズ除去)
    min_minutes: float = 450.0

    @classmethod
    def load(cls, path: Path | None) -> "PotentialConfig":
        """TOML から設定を読む。path=None や不存在時はフォールバック値を使う。"""
        if path is None or not Path(path).exists():
            return cls()
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return cls(
            metric_weights=dict(data.get("metric_weights", _FALLBACK_WEIGHTS)),
            full_bonus_age=float(data.get("full_bonus_age", 18.0)),
            max_age=float(data.get("max_age", 24.0)),
            ability_floor=float(data.get("ability_floor", 0.35)),
            min_minutes=float(data.get("min_minutes", 450.0)),
        )


def _age_factor(age: float, config: PotentialConfig) -> float:
    """若いほど 1.0 に近づく年齢係数。max_age で ability_floor まで減衰する。"""
    if age <= config.full_bonus_age:
        return 1.0
    span = config.max_age - config.full_bonus_age
    decay = max(0.0, 1.0 - (age - config.full_bonus_age) / span)
    return config.ability_floor + (1.0 - config.ability_floor) * decay


def score_potential(
    df: pd.DataFrame, config: PotentialConfig | None = None
) -> pd.DataFrame:
    """パーセンタイル付き DataFrame に potential_score 列を追加し降順で返す。

    入力は analyze.add_percentiles の出力 (*_pct 列を含む) を想定する。
    """
    config = config or PotentialConfig()

    pct_cols = [c for c in df.columns if c.endswith("_pct")]
    if not pct_cols:
        raise AnalysisError("*_pct 列がありません。先に add_percentiles を実行してください。")
    if "age" not in df.columns:
        raise AnalysisError("age 列がありません。")

    result = df[
        (df["age"].notna())
        & (df["age"] <= config.max_age)
        & (df["minutes"].fillna(0) >= config.min_minutes)
    ].copy()
    if result.empty:
        raise AnalysisError(
            f"対象選手がいません (age<={config.max_age}, minutes>={config.min_minutes})。"
        )

    # キーワードに一致する列へ重みを割り当てる (列ごとに最初に一致した重みを使う)
    col_weights: dict[str, float] = {}
    for col in pct_cols:
        lowered = col.lower()
        for keyword, weight in config.metric_weights.items():
            if keyword.lower() in lowered:
                col_weights[col] = weight
                break
    if not col_weights:
        raise AnalysisError(
            "重みキーワードに一致する指標がありません。config/potential.toml を確認してください。"
        )

    weighted = sum(
        result[col].fillna(50.0) * w for col, w in col_weights.items()
    ) / sum(col_weights.values())
    result["ability_score"] = weighted
    result["age_factor"] = result["age"].map(lambda a: _age_factor(float(a), config))
    result["potential_score"] = result["ability_score"] * result["age_factor"]
    return result.sort_values("potential_score", ascending=False).reset_index(drop=True)
