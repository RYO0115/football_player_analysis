# 概要: 収集・解析結果のローカル永続化 (Parquet)。
# 収集(ネットワーク)と解析(ローカル)を疎結合にするため、
# 中間データはすべて Parquet ファイル経由で受け渡す。

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


def _slug(text: str) -> str:
    """リーグ名等をファイル名に安全に使える形へ変換する。"""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")


class ParquetStorage:
    """データセット名 (league/season/種別) をキーにした Parquet 保存層。"""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    def path_for(self, dataset: str, league: str, season: str) -> Path:
        return self.data_dir / dataset / f"{_slug(league)}_{_slug(season)}.parquet"

    def save(self, df: pd.DataFrame, dataset: str, league: str, season: str) -> Path:
        path = self.path_for(dataset, league, season)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        return path

    def load(self, dataset: str, league: str, season: str) -> pd.DataFrame:
        path = self.path_for(dataset, league, season)
        if not path.exists():
            raise FileNotFoundError(
                f"データが未収集です: {path} (先に collect を実行してください)"
            )
        return pd.read_parquet(path)

    def load_all(self, dataset: str) -> pd.DataFrame:
        """dataset 配下の全リーグ・全シーズンを縦結合して返す。

        リーグ横断の比較・学習用。ファイル単位で増減できるので、
        対応リーグをコードに列挙しなくてよい。
        """
        base = self.data_dir / dataset
        files = sorted(base.glob("*.parquet")) if base.exists() else []
        if not files:
            raise FileNotFoundError(f"データが未収集です: {base}")
        return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
