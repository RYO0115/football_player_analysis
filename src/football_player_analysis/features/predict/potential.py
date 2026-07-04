# 概要: 若手選手の「スーパースター潜在能力スコア」算出。
# v0 はドメイン知識ベースの重み付きパーセンタイル合成 + 年齢カーブで実装し、
# 将来的に「翌シーズン以降の市場価値上昇」を教師にした ML モデルへ
# 差し替えられるよう、入出力を DataFrame 契約で固定している。
#
# 重み・年齢パラメータはコードに埋めず TOML (config/potential.toml) から読む。
# 指標名はデータソース側で増減するため、重みのキーは「列名に含まれる
# キーワード」として扱い、一致した *_pct 列すべてに適用する。
#
# 単一の metric_weights は攻撃寄りの重みになりがちで、ボランチ型・DF型の
# 若手を過小評価する。そこで position_group (プレフィックス) ごとに重み
# プロファイルを切り替えられるようにする。プロファイル名の集合はコードに
# 列挙せず、TOML に現れたものをそのまま使う (ハードコード禁止原則)。

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from football_player_analysis.core.exceptions import AnalysisError
from football_player_analysis.features.analyze.percentiles import (
    position_group as derive_position_group,
)

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

# フォールバック時に既定プロファイルを表す名前 (applied_profile 列で使う)。
_DEFAULT_PROFILE_NAME = "default"


@dataclass(frozen=True)
class PotentialConfig:
    """潜在能力スコアのパラメータ一式。"""

    # キーワード → 重み。キーワードを含む *_pct 列すべてに重みが掛かる。
    # どのプロファイルにも該当しない選手に使う既定重み。
    metric_weights: dict[str, float] = field(
        default_factory=lambda: dict(_FALLBACK_WEIGHTS)
    )
    # ポジショングループ (プレフィックス) → metric_weights 相当の重み辞書。
    # 例: {"DF": {"tklw": 2.0, ...}, "MF": {...}}
    profiles: dict[str, dict[str, float]] = field(default_factory=dict)
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
        # [profiles.<name>.metric_weights] を name → 重み辞書に展開する。
        # プロファイル名はここで列挙せず TOML に現れたキーをそのまま使う。
        profiles_raw = data.get("profiles", {})
        profiles = {
            name: dict(section.get("metric_weights", {}))
            for name, section in profiles_raw.items()
            if isinstance(section, dict)
        }
        return cls(
            metric_weights=dict(data.get("metric_weights", _FALLBACK_WEIGHTS)),
            profiles=profiles,
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


def _col_weights(weights: dict[str, float], pct_cols: list[str]) -> dict[str, float]:
    """metric_weights (キーワード) を実際の *_pct 列名に割り当てる。

    列ごとに最初に一致したキーワードの重みを採用する。1 列も一致しなければ
    空辞書を返す (呼び出し側でフォールバック判定に使う)。
    """
    col_weights: dict[str, float] = {}
    for col in pct_cols:
        lowered = col.lower()
        for keyword, weight in weights.items():
            if keyword.lower() in lowered:
                col_weights[col] = weight
                break
    return col_weights


def _match_profile(group: str, profiles: dict[str, dict[str, float]]) -> str | None:
    """position_group にマッチするプロファイルキーを探す。

    ソースによってポジション表記の粒度が異なる (FBref: "DF" / Understat: "D")
    ため、「グループ名がキーで始まる」または「キーがグループ名で始まる」の
    緩い前方一致で判定する。複数一致する場合は最長キーを優先する
    (例: グループ "DF" はキー "D" にも "DF" にも一致するが "DF" を採用)。
    """
    group_lower = group.lower()
    best_key: str | None = None
    for key in profiles:
        key_lower = key.lower()
        if group_lower.startswith(key_lower) or key_lower.startswith(group_lower):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    return best_key


def score_potential(
    df: pd.DataFrame, config: PotentialConfig | None = None
) -> pd.DataFrame:
    """パーセンタイル付き DataFrame に potential_score 列を追加し降順で返す。

    入力は analyze.add_percentiles の出力 (*_pct 列と position_group 列を
    含む) を想定するが、position_group が無い場合は position 列から導出する。
    ポジショングループごとに config.profiles の重みを適用し、適用結果を
    applied_profile 列 (プロファイル名 or "default") に記録する。
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

    # position_group が無ければ position から導出する (predict→analyze の
    # 依存は既存の依存方向 collect←analyze←predict に合致する)。
    if "position_group" in result.columns:
        groups = result["position_group"].astype(str)
    elif "position" in result.columns:
        groups = result["position"].map(derive_position_group)
    else:
        raise AnalysisError("position_group も position も列にありません。")

    # 既定重みは必ず有効でなければならない (全体のフォールバック先のため)。
    default_col_weights = _col_weights(config.metric_weights, pct_cols)
    if not default_col_weights:
        raise AnalysisError(
            "重みキーワードに一致する指標がありません。config/potential.toml を確認してください。"
        )

    # 出現するポジショングループごとに、適用するプロファイル名と列重みを
    # 一度だけ解決する (行ごとに毎回探索し直さない)。
    group_to_profile: dict[str, tuple[str, dict[str, float]]] = {}
    for group in groups.unique():
        profile_key = _match_profile(group, config.profiles)
        weights = _col_weights(config.profiles[profile_key], pct_cols) if profile_key else {}
        if profile_key is not None and weights:
            group_to_profile[group] = (profile_key, weights)
        else:
            # プロファイル未該当、またはキーワードが 1 列も一致しない場合は
            # 既定重みへフォールバックする (全体エラーにはしない)。
            group_to_profile[group] = (_DEFAULT_PROFILE_NAME, default_col_weights)

    result["applied_profile"] = groups.map(lambda g: group_to_profile[g][0])

    ability_score = pd.Series(0.0, index=result.index)
    for group, (_, weights) in group_to_profile.items():
        mask = (groups == group).to_numpy()
        total_weight = sum(weights.values())
        weighted = sum(
            result.loc[mask, col].fillna(50.0) * w for col, w in weights.items()
        ) / total_weight
        ability_score.loc[mask] = weighted
    result["ability_score"] = ability_score
    result["age_factor"] = result["age"].map(lambda a: _age_factor(float(a), config))
    result["potential_score"] = result["ability_score"] * result["age_factor"]
    return result.sort_values("potential_score", ascending=False).reset_index(drop=True)
