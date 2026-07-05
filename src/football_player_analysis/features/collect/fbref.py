# 概要: FBref (soccerdata 経由) から選手シーズンスタッツを収集するコレクター。
# FBref は xG や プログレッシブ系まで揃う最も網羅的な無料ソースのため、
# v0 の主データソースとして採用する。
#
# 設計メモ:
# - soccerdata はネットワークアクセスを伴うため、reader を注入可能にして
#   テストでは偽の DataFrame を返す関数に差し替えられるようにしている。
# - stat_type ごとの表を player/team で横結合し、列名は "種別__指標" に
#   フラット化する。指標の集合は FBref 側の都合で増減するため、
#   コード側で列名を列挙しない。

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

from football_player_analysis.core.exceptions import CollectionError
from football_player_analysis.features.collect.base import validate_normalized

# 取得する FBref の統計種別。soccerdata 1.9 が提供する全種別 (技術的に閉じた値)。
# 注: 2025-01 の Opta (StatsPerform) との契約解消により、FBref からは
# xG・プログレッシブ・passing/defense/possession 等の高度スタッツが消失した。
# xG 系は Understat コレクター (別ソース) で補完する方針。
DEFAULT_STAT_TYPES = ["standard", "shooting", "keeper", "playing_time", "misc"]

# soccerdata が返すメタ列 → 正規化スキーマの対応
_META_MAP = {"player": "player", "team": "team", "pos": "position", "age": "age"}

ReadFn = Callable[[str], pd.DataFrame]


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """MultiIndex 列を 'グループ_指標' 形式の 1 段に潰す。"""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            "_".join(str(p) for p in col if str(p) not in ("", "nan")).strip("_")
            for col in df.columns
        ]
    return df


def _parse_age(value: object) -> float | None:
    """FBref の年齢表記 '24-123' (歳-日) から歳数を取り出す。"""
    m = re.match(r"(\d+)", str(value))
    return float(m.group(1)) if m else None


def collect_team_possession(league: str, season: str) -> pd.DataFrame:
    """チームごとの平均ポゼッション% を取得する (PAdj 用)。

    2025-01 の Opta 契約解消後も FBref のチーム標準スタッツには Poss 列が
    残っているため、選手スタッツと別に 1 ページだけ取得する。
    """
    import soccerdata as sd

    fbref = sd.FBref(leagues=league, seasons=season)
    try:
        raw = fbref.read_team_season_stats(stat_type="standard").reset_index()
    except Exception as exc:
        raise CollectionError(
            f"FBref チームスタッツ取得失敗 league={league} season={season}: {exc}"
        ) from exc
    df = _flatten_columns(raw)
    poss_col = next((c for c in df.columns if str(c).lower() == "poss"), None)
    if poss_col is None:
        raise CollectionError(
            f"FBref チームスタッツに Poss 列がありません: league={league} season={season}"
        )
    out = pd.DataFrame(
        {
            "team": df["team"],
            "league": league,
            "season": season,
            "possession": pd.to_numeric(df[poss_col], errors="coerce"),
        }
    )
    return out.dropna(subset=["possession"]).reset_index(drop=True)


def soccerdata_reader(league: str, season: str) -> ReadFn:
    """本番用 reader。soccerdata の import はネットワーク副作用を遅延させるため関数内で行う。"""
    import soccerdata as sd

    fbref = sd.FBref(leagues=league, seasons=season)

    def read(stat_type: str) -> pd.DataFrame:
        return fbref.read_player_season_stats(stat_type=stat_type).reset_index()

    return read


class FBrefCollector:
    """FBref の複数統計表を 1 枚の正規化 DataFrame に統合するコレクター。"""

    def __init__(
        self,
        reader_factory: Callable[[str, str], ReadFn] = soccerdata_reader,
        stat_types: Sequence[str] = tuple(DEFAULT_STAT_TYPES),
    ) -> None:
        self._reader_factory = reader_factory
        self._stat_types = list(stat_types)

    def collect(self, league: str, season: str) -> pd.DataFrame:
        read = self._reader_factory(league, season)
        merged: pd.DataFrame | None = None
        for stat_type in self._stat_types:
            try:
                raw = read(stat_type)
            except (ValueError, TypeError) as exc:
                # 提供される stat_type はリーグにより異なる (詳細統計は
                # 'Big 5 European Leagues Combined' 等に限定)。世界中のリーグを
                # 扱えるよう、未対応種別はエラーにせずスキップする。
                # soccerdata はこれを TypeError で送出する。
                if "stat_type" in str(exc):
                    logger.warning(
                        "FBref: %s は league=%s で未提供のためスキップ (%s)",
                        stat_type,
                        league,
                        exc,
                    )
                    continue
                raise CollectionError(
                    f"FBref 収集失敗 league={league} season={season} stat={stat_type}: {exc}"
                ) from exc
            except Exception as exc:  # soccerdata 側の例外型は安定しないため広く捕捉
                raise CollectionError(
                    f"FBref 収集失敗 league={league} season={season} stat={stat_type}: {exc}"
                ) from exc
            frame = self._normalize(raw, stat_type, league, season)
            if merged is None:
                merged = frame
            else:
                # メタ列は standard 由来を正とし、以降はスタッツ列のみ足す
                stat_cols = [c for c in frame.columns if c.startswith(f"{stat_type}__")]
                merged = merged.merge(
                    frame[["player", "team", *stat_cols]],
                    on=["player", "team"],
                    how="left",
                )
        if merged is None or merged.empty:
            raise CollectionError(f"FBref から選手データを取得できませんでした: {league} {season}")
        return validate_normalized(merged)

    def _normalize(
        self, raw: pd.DataFrame, stat_type: str, league: str, season: str
    ) -> pd.DataFrame:
        df = _flatten_columns(raw)
        df.columns = [str(c).strip() for c in df.columns]

        out = pd.DataFrame()
        for src, dst in _META_MAP.items():
            if src in df.columns:
                out[dst] = df[src]
        out["league"] = league
        out["season"] = season
        if "age" in out.columns:
            out["age"] = out["age"].map(_parse_age)

        # 出場時間は per-90 換算の基準になるため明示的に拾う
        minutes_col = next(
            (c for c in df.columns if c.lower().endswith("_min") or c.lower() == "min"),
            None,
        )
        out["minutes"] = (
            pd.to_numeric(df[minutes_col], errors="coerce") if minutes_col else pd.NA
        )

        # メタ以外の数値列をすべて "種別__指標" として採用する。
        # 指標の増減は FBref 側の事情で起きるため、列挙せず動的に取り込む。
        # born (生年)・season 等は数値に見えるがスタッツではないため明示的に除外する。
        consumed = (
            set(_META_MAP)
            | ({minutes_col} if minutes_col else set())
            | {"league", "season", "born", "nation"}
        )
        for col in df.columns:
            if col in consumed:
                continue
            series = pd.to_numeric(df[col], errors="coerce")
            if series.notna().sum() == 0:
                continue
            out[f"{stat_type}__{col}"] = series
        return out
