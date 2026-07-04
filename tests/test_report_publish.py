# 概要: 記事生成 (report) と Substack 投稿 (publish, dry_run) のユニットテスト。

from __future__ import annotations

import pytest

from football_player_analysis.core.config import SubstackConfig
from football_player_analysis.core.exceptions import PublishError
from football_player_analysis.features.analyze import add_percentiles, to_per90
from football_player_analysis.features.predict import PotentialConfig, score_potential
from football_player_analysis.features.publish import SubstackPublisher
from football_player_analysis.features.report import build_potential_article


@pytest.fixture
def ranked(normalized_stats):
    analyzed = add_percentiles(to_per90(normalized_stats))
    return score_potential(analyzed, PotentialConfig(min_minutes=0))


def test_article_contains_top_players_and_season(ranked):
    article = build_potential_article(ranked, season="2425", top_n=5)
    assert "2425" in article.title
    assert "Young Star" in article.body_markdown
    # Markdown テーブルとして成立していること
    assert "| 順位 |" in article.body_markdown


def test_dry_run_writes_local_markdown(tmp_path, ranked):
    article = build_potential_article(ranked, season="2425")
    publisher = SubstackPublisher(SubstackConfig(), dry_run=True, out_dir=tmp_path)
    path = publisher.publish(article)
    assert path.endswith(".md")
    content = (tmp_path / path.split("/")[-1]).read_text(encoding="utf-8")
    assert article.title in content


def test_real_publish_requires_credentials(ranked):
    article = build_potential_article(ranked, season="2425")
    publisher = SubstackPublisher(SubstackConfig(), dry_run=False)
    with pytest.raises(PublishError):
        publisher.publish(article)
