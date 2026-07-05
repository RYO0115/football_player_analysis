# 概要: レーダーチャートの軸 (指標) をカテゴリ均等に選択するモジュール。
# 攻撃系キーワードだけで軸を埋めると DF/ボランチ型の選手が不当に
# 「凹んだ」レーダーになるため、攻撃/創造/前進/守備のカテゴリごとに
# 軸数を割り当てて選ぶ。カテゴリ定義とキーワードはドメイン語彙であり
# ユーザーが調整したいため config/radar.toml から読む (無ければフォールバック)。

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from football_player_analysis.core.matching import match_longest_prefix

# 列名から取り除く技術的サフィックス (解析パイプラインの命名規約)。
# 順序が重要: "..._padj_per90_pct" を外側から順に剥がす。
_SUFFIXES = ("_pct", "_per90", "_padj")

# TOML が無い環境でも動くフォールバック。カテゴリの並び順が軸の並び順になる。
_FALLBACK_CATEGORIES: dict[str, dict] = {
    # gls (FBref) と goals (Understat) は同義のため、間に sot/shots を挟み
    # 得点系だけで攻撃枠が埋まらないようにしている
    "attack": {"keywords": ["np_xg", "gls", "sot", "shots", "goals"], "axes": 3},
    "creation": {"keywords": ["xa", "key_passes", "ast", "assists", "sca"], "axes": 3},
    "progression": {"keywords": ["xg_buildup", "xg_chain", "prg", "carries"], "axes": 3},
    "defense": {"keywords": ["tklw", "tkl", "int", "aerial", "recov", "blocks", "clr"], "axes": 3},
}


def metric_key(column: str) -> str:
    """列名からソース接頭辞と技術的サフィックスを除いた照合用キーを返す。

    例: 'understat__np_xg_per90_pct' → 'np_xg' /
        'misc__Performance_TklW_per90_pct' → 'performance_tklw'
    キーワード照合を「指標部分」に限定し、ソース名 (shooting__ 等) への
    偶発一致を防ぐ。
    """
    stripped = column
    for suffix in _SUFFIXES:
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
    if "__" in stripped:
        stripped = stripped.split("__", 1)[1]
    return stripped.lower()


def metric_label(column: str) -> str:
    """レーダーの目盛り表示用の短い指標名を返す。

    FBref 系は 'カテゴリ_指標' (Performance_TklW 等) なので最後のトークンを、
    Understat 系は全小文字スネークケース 1 語 (np_xg, key_passes 等) なので
    全体を保持する (最後のトークンだけだと np_xg が 'xg' に化けるため)。
    """
    stripped = column
    is_padj = False
    for suffix in _SUFFIXES:
        if stripped.endswith(suffix):
            if suffix == "_padj":
                is_padj = True
            stripped = stripped[: -len(suffix)]
    raw_key = stripped.split("__", 1)[1] if "__" in stripped else stripped
    if raw_key == raw_key.lower():
        base = raw_key  # Understat 系: 全体が 1 つの指標名
    else:
        # FBref 由来: 表示用に元の大文字小文字を保った最後のトークンを使う
        raw_tokens = [t for t in re.split(r"[_]+", raw_key) if t]
        base = raw_tokens[-1] if raw_tokens else raw_key
    # ポゼッション調整済みは N5 等の慣例に合わせて明示する (例: 'TklW (PAdj)')
    return f"{base} (PAdj)" if is_padj else base


# 略称 (metric_label の出力) → 正式名称。レーダーの軸ラベルは重なり防止のため
# 略称表示のままにし、図の注釈でこの正式名称を補足する。照合は小文字化した
# 略称で行うため、キーはすべて小文字で定義する。未登録の略称はそのまま使う。
# 値は画像に描画されるため、日本語フォントに依存しないよう英語の正式名称にする
# (matplotlib 既定フォントは CJK を描けず豆腐になるため)。
_FULL_NAMES: dict[str, str] = {
    "np_xg": "Non-Penalty Expected Goals (npxG)",
    "npxg": "Non-Penalty Expected Goals (npxG)",
    "xg": "Expected Goals (xG)",
    "xa": "Expected Assists (xA)",
    "xag": "Expected Assisted Goals (xAG)",
    "xg_buildup": "xG Buildup",
    "xg_chain": "xG Chain",
    "key_passes": "Key Passes",
    "goals": "Goals",
    "gls": "Goals",
    "assists": "Assists",
    "ast": "Assists",
    "shots": "Shots",
    "sh": "Shots",
    "sot": "Shots on Target",
    "sca": "Shot-Creating Actions",
    "gca": "Goal-Creating Actions",
    "prgc": "Progressive Carries",
    "prgp": "Progressive Passes",
    "prgr": "Progressive Passes Received",
    "carries": "Carries",
    "tklw": "Tackles Won",
    "tkl": "Tackles",
    "int": "Interceptions",
    "blocks": "Blocks",
    "clr": "Clearances",
    "recov": "Ball Recoveries",
    "won": "Aerial Duels Won",
}


# Understat 系ラベルは全小文字 (np_xg, xa 等) だが、慣用表記は xG / xA。
# 表示時のみ `_` 区切りトークン単位で大小文字を補正する (FBref 系は元表記を尊重)。
_LABEL_TOKEN_CASE = {"xg": "xG", "xa": "xA", "npxg": "npxG", "xag": "xAG"}

# metric_label が付ける PAdj マーカー。表示名変換の前に分離し、変換後に戻す。
_PADJ_MARKER = " (PAdj)"


def _split_padj(label: str) -> tuple[str, str]:
    if label.endswith(_PADJ_MARKER):
        return label[: -len(_PADJ_MARKER)], _PADJ_MARKER
    return label, ""


def metric_display_label(column: str) -> str:
    """レーダー軸に表示する略称を慣用表記に整えて返す。

    metric_label の出力のうち、全小文字の Understat 系ラベルだけ
    xg→xG / xa→xA と補正する (np_xg → np_xG, xg_buildup → xG_buildup)。
    FBref 系 (SoT, TklW 等) は元の大小文字が正しいためそのまま返す。
    """
    label, padj = _split_padj(metric_label(column))
    if label == label.lower():
        label = "_".join(_LABEL_TOKEN_CASE.get(t, t) for t in label.split("_"))
    return f"{label}{padj}"


def metric_full_name(column: str) -> str:
    """レーダー軸の略称に対応する正式名称を返す。

    metric_label が返す略称 (SoT, TklW, np_xg 等) を正式名称に対応づける。
    未登録の略称は略称そのものを返す (注釈側で略称と一致すれば表示を省く)。
    """
    label, padj = _split_padj(metric_label(column))
    return f"{_FULL_NAMES.get(label.lower(), label)}{padj}"


def _parse_categories(raw: dict) -> dict[str, dict]:
    return {
        name: {
            "keywords": list(spec.get("keywords", [])),
            "axes": int(spec.get("axes", 3)),
        }
        for name, spec in raw.items()
    }


@dataclass(frozen=True)
class RadarAxesConfig:
    """レーダー軸選択の設定。

    categories: 既定のカテゴリ定義 (名前 → {keywords, axes}、定義順 = 軸の並び順)。
    templates: ポジショングループ別のテンプレート (StatsBomb 流)。
        キーはポジション接頭辞 (DF/MF/FW 等) で、position_group と
        core.matching の緩い前方一致 (最長キー優先) で解決する。
        該当が無いポジションは既定 categories を使う。
    """

    categories: dict[str, dict] = field(
        default_factory=lambda: dict(_FALLBACK_CATEGORIES)
    )
    templates: dict[str, dict[str, dict]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> "RadarAxesConfig":
        """TOML から設定を読む。path=None や不存在時はフォールバック値を使う。"""
        if path is None or not Path(path).exists():
            return cls()
        with open(path, "rb") as f:
            data = tomllib.load(f)
        raw = data.get("categories", {})
        templates = {
            name: _parse_categories(spec.get("categories", {}))
            for name, spec in data.get("templates", {}).items()
        }
        if not raw and not templates:
            return cls()
        return cls(
            categories=_parse_categories(raw) if raw else dict(_FALLBACK_CATEGORIES),
            templates=templates,
        )

    def categories_for(self, position_group: str | None) -> dict[str, dict]:
        """position_group に対応するテンプレートを返す (無ければ既定)。"""
        if position_group:
            key = match_longest_prefix(str(position_group), self.templates)
            if key is not None:
                return self.templates[key]
        return self.categories


# 生年・シーズンなど、指標として無意味なのに数値として紛れ込みうるキー。
# 過去に収集済みの Parquet にも残っているため、選択側でも防波堤を張る。
_JUNK_KEYS = ("born", "season", "matches")


def select_radar_metrics(
    columns: Iterable[str],
    config: RadarAxesConfig | None = None,
    position_group: str | None = None,
) -> list[str]:
    """カテゴリ均等にレーダー軸となる *_pct 列を選ぶ。

    position_group を渡すと該当するポジションテンプレート (StatsBomb 流) を使い、
    無ければ既定カテゴリを使う。カテゴリごとに keywords を順に照合し、
    最大 axes 本まで採用する。同じ表示ラベルの指標はソース違いでも 1 本に絞る
    (Gls の重複等)。データに無いカテゴリは静かにスキップし、選べた軸だけ返す。
    """
    config = config or RadarAxesConfig()
    categories = config.categories_for(position_group)
    candidates = [
        c
        for c in columns
        if c.endswith("_pct")
        and "/" not in c  # 率系の派生 (G/Sh 等) は per-90 換算が無意味なので除外
        and not any(junk in metric_key(c) for junk in _JUNK_KEYS)
    ]

    chosen: list[str] = []
    seen_labels: set[str] = set()
    for spec in categories.values():
        picked = 0
        for keyword in spec["keywords"]:
            if picked >= spec["axes"]:
                break
            col = next(
                (
                    c
                    for c in candidates
                    if keyword in metric_key(c)
                    and c not in chosen
                    and metric_label(c).lower() not in seen_labels
                ),
                None,
            )
            if col is not None:
                chosen.append(col)
                seen_labels.add(metric_label(col).lower())
                picked += 1
    return chosen
