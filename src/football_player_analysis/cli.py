# 概要: コマンドラインエントリポイント。
# サブコマンド (collect / analyze / predict / run) を提供し、
# 処理本体は pipeline.Pipeline に委譲する。
#
# 使用例:
#   uv run fpa collect --league "ENG-Premier League" --season 2425
#   uv run fpa run --league "ENG-Premier League" --league "ESP-La Liga" --season 2425

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from football_player_analysis.core.config import Settings
from football_player_analysis.core.exceptions import FpaError
from football_player_analysis.features.collect import FBrefCollector
from football_player_analysis.features.predict import PotentialConfig
from football_player_analysis.pipeline import Pipeline


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpa", description="フットボール選手スタッツの収集・解析・投稿パイプライン"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_league_season(p: argparse.ArgumentParser) -> None:
        # リーグはユーザーが自由に増やせる値なので必須引数として受け取る
        p.add_argument(
            "--league",
            action="append",
            required=True,
            help="soccerdata のリーグ ID (例: 'ENG-Premier League')。複数指定可",
        )
        p.add_argument("--season", required=True, help="シーズン (例: 2425)")

    p_collect = sub.add_parser("collect", help="FBref から選手スタッツを収集して保存")
    add_league_season(p_collect)

    p_analyze = sub.add_parser("analyze", help="per-90 換算とパーセンタイルを付与")
    add_league_season(p_analyze)
    p_analyze.add_argument("--min-minutes", type=float, default=450.0)

    p_predict = sub.add_parser("predict", help="潜在能力スコアの上位を表示")
    p_predict.add_argument("--config", type=Path, default=Path("config/potential.toml"))
    p_predict.add_argument("--top", type=int, default=20)

    p_run = sub.add_parser("run", help="収集→解析→予測→記事生成→投稿を一括実行")
    add_league_season(p_run)
    p_run.add_argument("--config", type=Path, default=Path("config/potential.toml"))
    p_run.add_argument("--top", type=int, default=20)
    p_run.add_argument(
        "--publish-now",
        action="store_true",
        help="下書きではなく即時公開する (FPA_DRY_RUN=false のときのみ有効)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = Settings.from_env()
    pipeline = Pipeline(settings=settings, collector=FBrefCollector())

    try:
        if args.command == "collect":
            for league in args.league:
                path = pipeline.collect(league, args.season)
                print(f"収集完了: {path}")
        elif args.command == "analyze":
            for league in args.league:
                path = pipeline.analyze(league, args.season, min_minutes=args.min_minutes)
                print(f"解析完了: {path}")
        elif args.command == "predict":
            ranked = pipeline.predict(PotentialConfig.load(args.config))
            cols = ["player", "team", "league", "position", "age", "potential_score"]
            print(ranked[cols].head(args.top).to_string(index=False))
        elif args.command == "run":
            result = pipeline.run(
                leagues=args.league,
                season=args.season,
                potential_config=PotentialConfig.load(args.config),
                top_n=args.top,
                publish_now=args.publish_now,
            )
            print(f"パイプライン完了: {result}")
    except (FpaError, FileNotFoundError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
