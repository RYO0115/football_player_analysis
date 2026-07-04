# 概要: TransfermarktCollector のパース・正規化ロジックのユニットテスト。
# 実ページ構造を模した偽 HTML と偽 fetch を注入し、ネットワークなしで検証する。

from __future__ import annotations

import pandas as pd
import pytest

from football_player_analysis.core.exceptions import CollectionError
from football_player_analysis.features.collect import META_COLUMNS, TransfermarktCollector
from football_player_analysis.features.collect.transfermarkt import (
    convert_season,
    parse_club_list,
    parse_squad,
)

# 実ページの構造 (メインの table.items / posrela の入れ子表 / 列の並び) を模した偽 HTML。
STARTSEITE_HTML = """
<html><body>
<table class="items"><tbody>
  <tr><td class="zentriert">1</td>
      <td class="hauptlink"><a href="/alpha-fc/startseite/verein/1/saison_id/2024">Alpha FC</a></td></tr>
  <tr><td class="zentriert">2</td>
      <td class="hauptlink"><a href="/beta-fc/startseite/verein/2/saison_id/2024">Beta FC</a></td></tr>
</tbody></table>
<aside><a href="/other/startseite/verein/999/saison_id/2024">Sidebar Club</a></aside>
</body></html>
"""


def _squad_html(rows: str) -> str:
    return f'<html><body><table class="items"><tbody>{rows}</tbody></table></body></html>'


def _player_row(name: str, pos: str, dob: str, height: str, value: str) -> str:
    return f"""
    <tr>
      <td class="zentriert rueckennummer">9</td>
      <td class="posrela">
        <table><tr><td class="hauptlink"><a href="/p">{name}</a></td></tr>
               <tr><td>{pos}</td></tr></table>
      </td>
      <td class="zentriert">{dob}</td>
      <td class="zentriert"></td>
      <td class="zentriert">{height}</td>
      <td class="zentriert">right</td>
      <td class="zentriert">01/07/2023</td>
      <td class="zentriert"></td>
      <td class="zentriert">30/06/2028</td>
      <td class="rechts hauptlink">{value}</td>
    </tr>
    """


ALPHA_SQUAD = _squad_html(
    _player_row("Young Star", "Centre-Forward", "15/09/2005 (20)", "1,93m", "€60.00m")
    + _player_row("Squad Player", "Goalkeeper", "03/10/1994 (31)", "1,88m", "€800k")
)
BETA_SQUAD = _squad_html(
    # 市場価値なし ("-") の選手 → NA になること
    _player_row("No Value Guy", "Left-Back", "01/01/2000 (26)", "1,80m", "-")
)

LEAGUES = {"ENG-Premier League": {"slug": "premier-league", "competition_id": "GB1"}}


def _fake_fetch(url: str) -> str:
    if "startseite/wettbewerb" in url:
        return STARTSEITE_HTML
    if "/verein/1/" in url:
        return ALPHA_SQUAD
    if "/verein/2/" in url:
        return BETA_SQUAD
    raise AssertionError(f"想定外の URL: {url}")


def make_collector(fetch=_fake_fetch) -> TransfermarktCollector:
    return TransfermarktCollector(fetch=fetch, leagues=LEAGUES)


# --- season 変換 -----------------------------------------------------------


def test_convert_season():
    assert convert_season("2526") == 2025
    assert convert_season("2425") == 2024


def test_convert_season_rejects_bad_format():
    with pytest.raises(CollectionError):
        convert_season("25")
    with pytest.raises(CollectionError):
        convert_season("20xx")


# --- 個別パーサ ------------------------------------------------------------


def test_parse_club_list_scopes_to_main_table():
    clubs = parse_club_list(STARTSEITE_HTML)
    # サイドバーのクラブは拾わず、メイン表の 2 クラブのみ
    assert [(name, vid) for name, _slug, vid in clubs] == [("Alpha FC", "1"), ("Beta FC", "2")]


def test_parse_squad_extracts_attributes():
    players = parse_squad(ALPHA_SQUAD)
    assert len(players) == 2
    star = players[0]
    assert star["player"] == "Young Star"
    assert star["position"] == "Centre-Forward"
    assert star["age"] == 20.0
    # "1,93m" -> 193 cm / "€60.00m" -> 60,000,000
    assert star["height_cm"] == pytest.approx(193.0)
    assert star["market_value_eur"] == pytest.approx(60_000_000.0)
    # "€800k" -> 800,000
    assert players[1]["market_value_eur"] == pytest.approx(800_000.0)


def test_parse_squad_handles_missing_market_value():
    players = parse_squad(BETA_SQUAD)
    assert players[0]["market_value_eur"] is None


# --- collect (正規化スキーマ) ----------------------------------------------


def test_collect_produces_normalized_schema():
    df = make_collector().collect("ENG-Premier League", "2425")
    for col in META_COLUMNS:
        assert col in df.columns
    # 2 クラブ合計 3 選手
    assert len(df) == 3
    # minutes は TM が提供しないため NA
    assert df["minutes"].isna().all()


def test_collect_uses_attr_column_names():
    df = make_collector().collect("ENG-Premier League", "2425")
    assert "transfermarkt__attr_market_value_eur" in df.columns
    assert "transfermarkt__attr_height_cm" in df.columns
    star = df[df["player"] == "Young Star"].iloc[0]
    assert star["transfermarkt__attr_market_value_eur"] == pytest.approx(60_000_000.0)
    assert star["team"] == "Alpha FC"
    # 市場価値なしの選手は NA
    novalue = df[df["player"] == "No Value Guy"].iloc[0]
    assert pd.isna(novalue["transfermarkt__attr_market_value_eur"])


def test_collect_raises_on_unknown_league():
    with pytest.raises(CollectionError, match="未対応のリーグ"):
        make_collector().collect("JPN-J1 League", "2425")


def test_collect_wraps_fetch_failure_in_collection_error():
    def boom(url: str) -> str:
        raise RuntimeError("network down")

    with pytest.raises(CollectionError):
        make_collector(fetch=boom).collect("ENG-Premier League", "2425")


def test_collect_raises_when_no_clubs():
    def empty_fetch(url: str) -> str:
        return "<html><body>no table</body></html>"

    with pytest.raises(CollectionError):
        make_collector(fetch=empty_fetch).collect("ENG-Premier League", "2425")


def test_polite_fetcher_retries_on_5xx(monkeypatch):
    # 一時的な 502 は指数バックオフで再試行し、成功レスポンスを返すこと
    # (1 回の 5xx でリーグ全体の収集が落ちないための保険)。
    import requests

    from football_player_analysis.features.collect.transfermarkt import polite_fetcher

    class FakeResponse:
        def __init__(self, status_code: int, text: str = "ok") -> None:
            self.status_code = status_code
            self.text = text

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError(f"{self.status_code} error")

    responses = [FakeResponse(502), FakeResponse(200, "recovered")]
    calls = {"n": 0}

    class FakeSession:
        headers: dict = {}

        def get(self, url, timeout):
            calls["n"] += 1
            return responses.pop(0)

    monkeypatch.setattr(requests, "Session", FakeSession)
    fetch = polite_fetcher(sleep_seconds=0)
    assert fetch("https://example.com") == "recovered"
    assert calls["n"] == 2


def test_polite_fetcher_raises_immediately_on_4xx(monkeypatch):
    # 4xx は恒久エラーなので再試行しないこと。
    import requests

    from football_player_analysis.features.collect.transfermarkt import polite_fetcher

    class FakeResponse:
        status_code = 404
        text = ""

        def raise_for_status(self) -> None:
            raise requests.HTTPError("404 error")

    calls = {"n": 0}

    class FakeSession:
        headers: dict = {}

        def get(self, url, timeout):
            calls["n"] += 1
            return FakeResponse()

    monkeypatch.setattr(requests, "Session", FakeSession)
    fetch = polite_fetcher(sleep_seconds=0)
    with pytest.raises(requests.HTTPError):
        fetch("https://example.com")
    assert calls["n"] == 1
