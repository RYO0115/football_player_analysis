# 概要: collect パッケージ。外部ソースからの選手スタッツ収集を担う。

from football_player_analysis.features.collect.base import (
    META_COLUMNS,
    PlayerSeasonCollector,
)
from football_player_analysis.features.collect.fbref import FBrefCollector
from football_player_analysis.features.collect.merge import (
    merge_sources,
    normalize_player_name,
)
from football_player_analysis.features.collect.understat import UnderstatCollector

# データソース名 → コレクター実装のレジストリ。
# 新ソース追加時はここに 1 行足すだけで CLI から使えるようにする。
SOURCES = {
    "fbref": FBrefCollector,
    "understat": UnderstatCollector,
}

__all__ = [
    "META_COLUMNS",
    "PlayerSeasonCollector",
    "FBrefCollector",
    "UnderstatCollector",
    "SOURCES",
    "merge_sources",
    "normalize_player_name",
]
