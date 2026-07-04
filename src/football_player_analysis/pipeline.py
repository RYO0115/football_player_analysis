# 概要: collect → analyze → predict → report → publish を貫くパイプライン。
# CLI からもテストからも同じ関数を呼べるよう、CLI 解釈と処理本体を分離する。

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from football_player_analysis.core.config import Settings
from football_player_analysis.core.storage import ParquetStorage
from football_player_analysis.features.analyze import add_percentiles, to_per90
from football_player_analysis.features.collect import PlayerSeasonCollector
from football_player_analysis.features.predict import PotentialConfig, score_potential
from football_player_analysis.features.publish import SubstackPublisher
from football_player_analysis.features.report import Article, build_potential_article

# データセット名 (保存ディレクトリ名)。ストレージレイアウトの契約なので固定でよい。
RAW_DATASET = "raw_player_season"
ANALYZED_DATASET = "analyzed_player_season"


@dataclass
class Pipeline:
    """設定とコレクターを束ね、各フェーズを実行するオーケストレーター。"""

    settings: Settings
    collector: PlayerSeasonCollector

    @property
    def storage(self) -> ParquetStorage:
        return ParquetStorage(self.settings.data_dir)

    def collect(self, league: str, season: str) -> Path:
        """外部ソースから収集しローカル保存する (ネットワークを伴う唯一のフェーズ)。"""
        df = self.collector.collect(league, season)
        return self.storage.save(df, RAW_DATASET, league, season)

    def analyze(self, league: str, season: str, min_minutes: float = 450.0) -> Path:
        """per-90 換算 + ポジション内パーセンタイルを付与して保存する。"""
        raw = self.storage.load(RAW_DATASET, league, season)
        per90 = to_per90(raw, min_minutes=min_minutes)
        # 比較は per-90 換算した値で行う (累積値のパーセンタイルは出場時間の影響が大きい)
        pct_targets = [c for c in per90.columns if c.endswith("_per90")]
        analyzed = add_percentiles(per90, columns=pct_targets)
        return self.storage.save(analyzed, ANALYZED_DATASET, league, season)

    def predict(self, potential_config: PotentialConfig | None = None) -> pd.DataFrame:
        """解析済み全リーグを対象に潜在能力スコアを算出する。"""
        analyzed = self.storage.load_all(ANALYZED_DATASET)
        return score_potential(analyzed, potential_config)

    def build_article(self, ranked: pd.DataFrame, season: str, top_n: int = 20) -> Article:
        return build_potential_article(ranked, season=season, top_n=top_n)

    def publish(self, article: Article, publish_now: bool = False) -> str:
        publisher = SubstackPublisher(
            config=self.settings.substack,
            dry_run=self.settings.dry_run,
            out_dir=self.settings.data_dir / "output",
        )
        return publisher.publish(article, publish_now=publish_now)

    def run(
        self,
        leagues: list[str],
        season: str,
        potential_config: PotentialConfig | None = None,
        top_n: int = 20,
        publish_now: bool = False,
    ) -> str:
        """全フェーズを一括実行する。定期実行 (cron 等) のエントリポイント。"""
        for league in leagues:
            self.collect(league, season)
            self.analyze(league, season)
        ranked = self.predict(potential_config)
        article = self.build_article(ranked, season=season, top_n=top_n)
        return self.publish(article, publish_now=publish_now)
