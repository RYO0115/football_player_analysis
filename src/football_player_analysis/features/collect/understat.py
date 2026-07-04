# 概要: Understat から選手シーズンスタッツを収集するコレクター。
# 2025-01 に FBref から xG 系スタッツが消失したため、xG / npxG / xA /
# xGChain / xGBuildup の供給源として Understat を採用する。
# 対応リーグは欧州 5 大リーグ + ロシア (Understat 側の提供範囲)。
#
# 設計メモ:
# - FBrefCollector と同じく reader を注入可能にし、テストはネットワークなしで行う。
# - Understat は年齢を提供しないため age は欠損 (NA) とし、
#   年齢が必要な処理 (potential スコア) は FBref 由来データとの結合で補う。

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from football_player_analysis.core.exceptions import CollectionError
from football_player_analysis.features.collect.base import validate_normalized

# soccerdata の Understat 出力のうちメタとして扱う列 → 正規化スキーマの対応
_META_MAP = {
    "player": "player",
    "team": "team",
    "position": "position",
    "minutes": "minutes",
}

# ID 系はスタッツではないため取り込まない (技術的に閉じた値)
_ID_COLUMNS = {"league_id", "season_id", "team_id", "player_id", "position_id"}

ReadFn = Callable[[], pd.DataFrame]


def soccerdata_reader(league: str, season: str) -> ReadFn:
    """本番用 reader。import をここに閉じ込めてネットワーク副作用を遅延させる。"""
    import soccerdata as sd

    understat = sd.Understat(leagues=league, seasons=season)

    def read() -> pd.DataFrame:
        return understat.read_player_season_stats().reset_index()

    return read


class UnderstatCollector:
    """Understat の選手シーズンスタッツを正規化 DataFrame にするコレクター。"""

    def __init__(
        self, reader_factory: Callable[[str, str], ReadFn] = soccerdata_reader
    ) -> None:
        self._reader_factory = reader_factory

    def collect(self, league: str, season: str) -> pd.DataFrame:
        try:
            raw = self._reader_factory(league, season)()
        except Exception as exc:  # soccerdata 側の例外型は安定しないため広く捕捉
            raise CollectionError(
                f"Understat 収集失敗 league={league} season={season}: {exc}"
            ) from exc
        if raw.empty:
            raise CollectionError(
                f"Understat から選手データを取得できませんでした: {league} {season}"
            )

        out = pd.DataFrame()
        for src, dst in _META_MAP.items():
            if src in raw.columns:
                out[dst] = raw[src]
        out["league"] = league
        out["season"] = season
        # Understat は生年月日・年齢を提供しない (FBref 側との結合で補完する)
        out["age"] = pd.NA
        out["minutes"] = pd.to_numeric(out.get("minutes"), errors="coerce")

        # メタ・ID 以外の数値列を動的に取り込む (指標の増減はソース都合のため列挙しない)
        consumed = set(_META_MAP) | _ID_COLUMNS | {"league", "season"}
        for col in raw.columns:
            if col in consumed:
                continue
            series = pd.to_numeric(raw[col], errors="coerce")
            if series.notna().sum() == 0:
                continue
            out[f"understat__{col}"] = series
        return validate_normalized(out)
