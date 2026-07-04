# 概要: 記事生成 (report) と Substack 投稿 (publish, dry_run) のユニットテスト。

from __future__ import annotations

import pandas as pd
import pytest

from football_player_analysis.core.config import SubstackConfig
from football_player_analysis.core.exceptions import PublishError
from football_player_analysis.features.analyze import add_percentiles, to_per90
from football_player_analysis.features.predict import PotentialConfig, score_potential
from football_player_analysis.features.publish import SubstackPublisher
from football_player_analysis.features.report import build_potential_article
from football_player_analysis.features.report.markdown import (
    _metric_label,
    _top_pct_metrics,
    potential_stars,
)


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


# --- 選手個票 (N5 風プロフィールカード) -------------------------------------


def test_potential_stars_boundaries():
    assert potential_stars(0) == "☆" * 8
    assert potential_stars(100) == "★" * 8
    assert potential_stars(50) == "★★★★☆☆☆☆"


def test_metric_label_extracts_last_segment_after_stripping_suffixes():
    assert _metric_label("understat__xg_per90_pct") == "xg"
    assert _metric_label("misc__Performance_TklW_per90_pct") == "TklW"


def test_top_pct_metrics_returns_top_three_by_value():
    row = pd.Series(
        {
            "a__foo_pct": 10.0,
            "a__bar_pct": 90.0,
            "a__baz_pct": 50.0,
            "a__qux_pct": 70.0,
            "unrelated": 5.0,
        }
    )
    top = _top_pct_metrics(row)
    assert [name for name, _ in top] == ["bar", "qux", "baz"]


def test_article_has_pickup_section_with_cards_n_players(ranked):
    # ranked フィクスチャは max_age フィルタ後 2 名 (Young Star, Mid Talent) しか残らない。
    article = build_potential_article(ranked, season="2425", top_n=5, cards_n=2)
    assert "## 注目株ピックアップ" in article.body_markdown
    for i in range(1, 3):
        assert f"### {i}. " in article.body_markdown
    assert "### 3. " not in article.body_markdown


def test_card_includes_strength_metrics_and_comment(ranked):
    article = build_potential_article(ranked, season="2425", top_n=5, cards_n=1)
    assert "強み指標" in article.body_markdown
    assert "💬" in article.body_markdown
    assert "ポテンシャル: " in article.body_markdown


def test_card_shows_market_value_and_height_when_columns_present(ranked):
    enriched = ranked.copy()
    enriched["transfermarkt__attr_market_value_eur"] = 60_000_000.0
    enriched["transfermarkt__attr_height_cm"] = 193.0

    article = build_potential_article(enriched, season="2425", top_n=5, cards_n=1)

    assert "市場価値: 60.00 M€" in article.body_markdown
    assert "身長: 193cm" in article.body_markdown


def test_card_omits_market_value_and_height_when_columns_absent(ranked):
    assert "transfermarkt__attr_market_value_eur" not in ranked.columns
    assert "transfermarkt__attr_height_cm" not in ranked.columns

    article = build_potential_article(ranked, season="2425", top_n=5, cards_n=1)

    assert "市場価値" not in article.body_markdown
    assert "身長" not in article.body_markdown


def test_top_pct_metrics_dedupes_labels_and_excludes_negative_metrics():
    # ソース違いの同名指標 (Gls) は 1 回だけ、規律系 (CrdR) は「強み」に出ないこと。
    row = pd.Series(
        {
            "standard__Performance_Gls_per90_pct": 97.0,
            "shooting__Standard_Gls_per90_pct": 97.0,
            "misc__Performance_CrdR_per90_pct": 99.0,
            "understat__xg_per90_pct": 90.0,
            "understat__shots_per90_pct": 80.0,
        }
    )
    top = _top_pct_metrics(row)
    labels = [name for name, _ in top]
    assert labels == ["Gls", "xg", "shots"]
