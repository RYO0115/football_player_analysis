# 概要: Transfermarkt から選手の市場価値・身長等を収集するコレクター。
# 市場価値は (a) 記事の選手個票への表示、(b) 将来「市場価値上昇」を教師ラベルに
# した ML の基礎データ、の両用途を想定する。
#
# 設計メモ:
# - soccerdata では取得できないソースのため requests + BeautifulSoup で直接
#   スクレイプする。FBref/Understat の reader 注入と同じ思想で、ネットワーク関数
#   (url -> html) をコンストラクタ注入可能にし、テストは偽 HTML で行う。
# - 収集単位はリーグ 1 シーズン: トップページ (startseite) からクラブ一覧を得て、
#   各クラブの「詳細スカッド (kader/.../plus/1)」ページから選手を拾う。
# - 市場価値・身長は per-90 換算が無意味な静的属性のため、列名を `__attr_` を含む
#   形 (base.is_attr_column の規約) にして解析側で換算対象から外す。
# - 対応リーグ (soccerdata ID → TM の slug/競技 ID) はユーザーが自由に増やせるよう
#   config/transfermarkt_leagues.toml で管理し、コードに埋め込まない。

from __future__ import annotations

import logging
import re
import time
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from football_player_analysis.core.exceptions import CollectionError
from football_player_analysis.features.collect.base import validate_normalized

logger = logging.getLogger(__name__)

BASE_URL = "https://www.transfermarkt.com"

# リーグ対応表の既定パス (リポジトリ直下の config/)。
DEFAULT_CONFIG_PATH = Path("config/transfermarkt_leagues.toml")

# ブラウザ風 User-Agent (Transfermarkt はデフォルト UA をブロックするため必須)。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# polite scraping: リクエスト間の最小 sleep 秒数。
DEFAULT_SLEEP_SECONDS = 3.0

# 市場価値の単位 → 倍率。TM 英語版は "€30.00m" / "€800k" / "€1.50bn" 表記。
_VALUE_UNITS = {"bn": 1_000_000_000, "m": 1_000_000, "k": 1_000, "th.": 1_000}

# url -> html のネットワーク関数の型。
FetchFn = Callable[[str], str]


def convert_season(season: str) -> int:
    """soccerdata 形式のシーズン ("2526") を TM の saison_id (2025) に変換する。

    "2526" は 2025/26 シーズンを表し、TM は開始年 (2025) を saison_id に使う。
    4 桁の前半 2 桁を西暦下 2 桁とみなし 2000 を足す。
    """
    s = str(season).strip()
    if not (len(s) == 4 and s.isdigit()):
        raise CollectionError(
            f"シーズン表記が不正です: {season!r} (soccerdata 形式の 4 桁 例:'2526' を指定してください)"
        )
    return 2000 + int(s[:2])


def _parse_market_value(text: str) -> float | None:
    """市場価値表記 ("€30.00m" / "€800k") を EUR の数値に変換する。値なしは None。"""
    m = re.search(r"€\s*([\d.,]+)\s*(bn|m|k|Th\.)?", text, flags=re.IGNORECASE)
    if not m:
        return None
    number = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    return number * _VALUE_UNITS.get(unit, 1)


def _parse_height_cm(text: str) -> float | None:
    """身長表記 ("1,86m" / "1.86m") を cm の数値に変換する ("1,93m" -> 193)。"""
    m = re.search(r"(\d)[.,](\d{2})\s*m", text)
    if not m:
        return None
    return float(f"{m.group(1)}.{m.group(2)}") * 100.0


def _parse_age(text: str) -> float | None:
    """生年月日セル ("15/09/1995 (30)") の括弧内から年齢を取り出す。"""
    m = re.search(r"\((\d{1,2})\)", text)
    return float(m.group(1)) if m else None


def parse_club_list(html: str) -> list[tuple[str, str, str]]:
    """startseite HTML からリーグ所属クラブの (クラブ名, slug, verein_id) を返す。

    サイドバー等の余計なリンクを拾わないよう、メインのクラブ表 (table.items) に
    限定して抽出する。
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.items")
    if table is None:
        return []
    clubs: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for a in table.select("td.hauptlink a[href*='/startseite/verein/']"):
        href = str(a.get("href", ""))
        m = re.search(r"/([a-z0-9-]+)/startseite/verein/(\d+)", href)
        if not m:
            continue
        verein_id = m.group(2)
        if verein_id in seen:
            continue
        seen.add(verein_id)
        clubs.append((a.get_text(strip=True), m.group(1), verein_id))
    return clubs


def parse_squad(html: str) -> list[dict[str, object]]:
    """詳細スカッド (kader/.../plus/1) HTML から選手ごとの属性を抽出する。

    列位置に強く依存しないよう、名前/ポジションは posrela セルから、年齢/身長/
    市場価値はセルテキストのパターン一致で拾う。
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.items")
    if table is None:
        return []
    players: list[dict[str, object]] = []
    for row in table.select("tbody > tr"):
        posrela = row.select_one("td.posrela")
        if posrela is None:
            continue
        name_a = posrela.select_one("td.hauptlink a")
        if name_a is None:
            continue
        name = name_a.get_text(strip=True)
        inner = posrela.select("tr")
        # posrela セルは [名前行, ポジション行] の入れ子表。末尾行がポジション。
        position = inner[-1].get_text(strip=True) if inner else ""

        texts = [td.get_text(" ", strip=True) for td in row.find_all("td", recursive=False)]
        age = height = value = None
        for text in texts:
            if age is None and (a := _parse_age(text)) is not None:
                age = a
            if height is None and (h := _parse_height_cm(text)) is not None:
                height = h
            if value is None and "€" in text and (v := _parse_market_value(text)) is not None:
                value = v
        players.append(
            {
                "player": name,
                "position": position,
                "age": age,
                "market_value_eur": value,
                "height_cm": height,
            }
        )
    return players


def polite_fetcher(
    user_agent: str = DEFAULT_USER_AGENT,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    max_attempts: int = 3,
) -> FetchFn:
    """本番用フェッチャ。ブラウザ風 UA を付け、リクエスト間に sleep を挟む。

    Transfermarkt は一時的な 5xx (502 等) を返すことがあり、1 回の失敗で
    リーグ全体の収集をやり直すのは高コストなため、5xx に限り指数バックオフで
    リトライする (4xx は恒久エラーとみなし即座に送出)。
    requests の import は (ネットワーク副作用側なので) ここに閉じ込める。
    """
    import requests

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    state = {"first": True}

    def fetch(url: str) -> str:
        if not state["first"]:
            time.sleep(sleep_seconds)  # polite: 連続リクエストの間隔を空ける
        state["first"] = False
        for attempt in range(1, max_attempts + 1):
            resp = session.get(url, timeout=30)
            if resp.status_code >= 500 and attempt < max_attempts:
                # サーバー側の一時障害はバックオフ後に再試行 (polite に間隔を広げる)
                time.sleep(sleep_seconds * (2**attempt))
                continue
            resp.raise_for_status()
            return resp.text
        raise AssertionError("unreachable")  # ループは必ず return/raise で抜ける

    return fetch


def _load_leagues(config_path: Path) -> Mapping[str, Mapping[str, str]]:
    if not config_path.exists():
        raise CollectionError(
            f"リーグ対応表が見つかりません: {config_path} (config/transfermarkt_leagues.toml を用意してください)"
        )
    with config_path.open("rb") as fp:
        return tomllib.load(fp)


class TransfermarktCollector:
    """Transfermarkt のリーグ 1 シーズン分の選手属性を正規化 DataFrame にするコレクター。"""

    def __init__(
        self,
        fetch: FetchFn | None = None,
        config_path: Path = DEFAULT_CONFIG_PATH,
        leagues: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        # fetch を注入しなければ本番用 polite フェッチャを使う (テストは偽 fetch を注入)。
        self._fetch = fetch if fetch is not None else polite_fetcher()
        self._config_path = Path(config_path)
        self._leagues = leagues  # None のときは collect 時に config から遅延ロード

    def _resolve_league(self, league: str) -> tuple[str, str]:
        leagues = self._leagues if self._leagues is not None else _load_leagues(self._config_path)
        entry = leagues.get(league)
        if entry is None:
            available = ", ".join(sorted(leagues)) or "(なし)"
            raise CollectionError(
                f"未対応のリーグ ID です: {league!r}。"
                f"config/transfermarkt_leagues.toml に追加してください。対応済み: {available}"
            )
        return str(entry["slug"]), str(entry["competition_id"])

    def _startseite_url(self, slug: str, competition_id: str, year: int) -> str:
        return f"{BASE_URL}/{slug}/startseite/wettbewerb/{competition_id}/plus/?saison_id={year}"

    def _squad_url(self, club_slug: str, verein_id: str, year: int) -> str:
        return f"{BASE_URL}/{club_slug}/kader/verein/{verein_id}/saison_id/{year}/plus/1"

    def collect(self, league: str, season: str) -> pd.DataFrame:
        year = convert_season(season)
        slug, competition_id = self._resolve_league(league)

        start_html = self._get(self._startseite_url(slug, competition_id, year), league, season)
        clubs = parse_club_list(start_html)
        if not clubs:
            raise CollectionError(
                f"Transfermarkt からクラブ一覧を取得できませんでした: {league} {season}"
            )

        rows: list[dict[str, object]] = []
        for club_name, club_slug, verein_id in clubs:
            squad_html = self._get(self._squad_url(club_slug, verein_id, year), league, season)
            for player in parse_squad(squad_html):
                rows.append(_build_row(player, club_name, league, season))
        if not rows:
            raise CollectionError(
                f"Transfermarkt から選手データを取得できませんでした: {league} {season}"
            )
        return validate_normalized(pd.DataFrame(rows))

    def _get(self, url: str, league: str, season: str) -> str:
        try:
            return self._fetch(url)
        except Exception as exc:  # ネットワーク側の例外型は安定しないため広く捕捉
            raise CollectionError(
                f"Transfermarkt 収集失敗 league={league} season={season} url={url}: {exc}"
            ) from exc


def _build_row(
    player: Mapping[str, object], team: str, league: str, season: str
) -> dict[str, object]:
    """パース済みの選手属性を正規化スキーマの 1 行に整形する。

    市場価値・身長は per-90 換算対象外を示す `__attr_` を含む列名にする。
    minutes は TM が提供しないため NA。
    """
    return {
        "player": player["player"],
        "team": team,
        "league": league,
        "season": season,
        "position": player.get("position"),
        "age": player.get("age"),
        "minutes": pd.NA,
        "transfermarkt__attr_market_value_eur": player.get("market_value_eur"),
        "transfermarkt__attr_height_cm": player.get("height_cm"),
    }
