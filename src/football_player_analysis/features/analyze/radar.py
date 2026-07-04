# 概要: 選手 1 人のパーセンタイルをレーダーチャート (PNG) に描画する。
# Substack 記事に添付する図の生成を想定。matplotlib は描画時のみ import し、
# ヘッドレス環境でも動くよう Agg バックエンドを強制する。

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from football_player_analysis.core.exceptions import AnalysisError


def render_radar(
    row: pd.Series,
    metrics: list[str],
    out_path: Path,
    title: str | None = None,
) -> Path:
    """パーセンタイル列 (*_pct, 0-100) をレーダーチャートとして保存する。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    missing = [m for m in metrics if m not in row.index]
    if missing:
        raise AnalysisError(f"レーダー描画対象の列がありません: {missing}")

    values = [float(row[m]) for m in metrics]
    # 閉じた多角形にするため先頭値を末尾に複製する
    angles = [n / len(metrics) * 2 * math.pi for n in range(len(metrics))]
    angles += angles[:1]
    values += values[:1]

    fig, ax = plt.subplots(figsize=(6, 6), subplot_kw={"polar": True})
    ax.plot(angles, values, linewidth=2)
    ax.fill(angles, values, alpha=0.25)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([m.removesuffix("_pct") for m in metrics], fontsize=8)
    ax.set_ylim(0, 100)
    ax.set_title(title or str(row.get("player", "")))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path
