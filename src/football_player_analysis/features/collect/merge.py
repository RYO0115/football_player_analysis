# 概要: 2 つの正規化済みデータソースを選手名で結合する純粋関数モジュール。
# FBref (age・基本/守備スタッツを持つが xG 系が無い) と Understat (xG 系を
# 持つが age が NA) は互いに欠けた指標を補い合う。両者を選手名で突き合わせ、
# 1 枚の正規化 DataFrame にまとめることで、下流 (analyze/predict) は結合済み
# データを 1 ソースとして扱える。
#
# 設計メモ:
# - ネットワーク副作用を持たない純粋関数のみで構成し、テストは偽データで行う。
# - 両ソースで選手名の表記が揺れる (FBref はアクセント付き "Luka Vušković"、
#   Understat は ASCII 寄り "Luka Vuskovic") ため、結合キーはアクセントを
#   除去し正規化した名前を用いる。

from __future__ import annotations

import logging

import pandas as pd
from unidecode import unidecode

from football_player_analysis.features.collect.base import (
    META_COLUMNS,
    validate_normalized,
)

logger = logging.getLogger(__name__)

# 結合に使う一時的な正規化名カラム。出力には残さない (技術的に閉じた内部名)。
_KEY_COLUMN = "_normalized_name"


def normalize_player_name(name: str) -> str:
    """選手名を結合キー用に正規化する。

    ソース間で表記が揺れる (アクセント有無・大文字小文字・余分な空白) ため、
    unidecode でアクセントを ASCII 化し、小文字化・空白正規化して
    同一選手が同じキーになるようにする。
    """
    return " ".join(unidecode(str(name)).lower().split())


def merge_sources(primary: pd.DataFrame, secondary: pd.DataFrame) -> pd.DataFrame:
    """primary を基準に secondary のスタッツ列を左結合する。

    league・season・正規化選手名をキーにした left join。メタ列は primary の
    ものを正とし (age を持つ FBref を基準にするため)、secondary からはスタッツ
    列 (`__` を含む列) のみを取り込む。secondary に居ない選手は NaN のまま残す。
    """
    key = ["league", "season", _KEY_COLUMN]

    p = primary.copy()
    s = secondary.copy()
    p[_KEY_COLUMN] = p["player"].map(normalize_player_name)
    s[_KEY_COLUMN] = s["player"].map(normalize_player_name)

    # secondary からはスタッツ列のみを取り込む。primary に既にある同名列は
    # メタ列の重複や suffix (_x/_y) 汚染を避けるため primary 側を優先して除外する。
    stat_cols = [c for c in s.columns if "__" in c and c not in p.columns]
    s = s[[*key, *stat_cols]]

    # 同一キーで複数行マッチする曖昧なケース (同名別人) は、誤って別人の
    # スタッツを付けてしまうため secondary 側から丸ごと除外する。
    dup_mask = s.duplicated(subset=key, keep=False)
    if dup_mask.any():
        logger.warning(
            "secondary の同名重複 %d 件を曖昧マッチとして除外", int(dup_mask.sum())
        )
        s = s[~dup_mask]

    merged = p.merge(s, on=key, how="left")

    # マッチ率 (primary のうち secondary のスタッツが 1 つでも付いた行の割合) を
    # 出しておくと、名前正規化が機能しているかを運用時に把握できる。
    if stat_cols:
        matched = int(merged[stat_cols].notna().any(axis=1).sum())
        total = len(merged)
        rate = matched / total * 100 if total else 0.0
        logger.info("マッチ率: %.1f%% (%d/%d)", rate, matched, total)

    merged = merged.drop(columns=[_KEY_COLUMN])
    # 列順はメタ列を先頭に揃える (下流の想定と一致させる)
    ordered = [c for c in META_COLUMNS if c in merged.columns]
    rest = [c for c in merged.columns if c not in ordered]
    return validate_normalized(merged[[*ordered, *rest]])
