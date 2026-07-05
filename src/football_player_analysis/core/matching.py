# 概要: ポジショングループ名と設定キーの照合ヘルパー。
# ソースによってポジション表記の粒度が異なる (FBref: "DF" / Understat: "D") ため、
# 予測プロファイル・レーダーテンプレートなど複数の機能で同じ照合規則を共有する。

from __future__ import annotations

from collections.abc import Iterable


def match_longest_prefix(group: str, keys: Iterable[str]) -> str | None:
    """group にマッチするキーを緩い前方一致で探し、最長キーを返す。

    「グループ名がキーで始まる」または「キーがグループ名で始まる」を一致とみなす
    (例: グループ "DF" はキー "D" にも "DF" にも一致するが、最長の "DF" を採用)。
    一致が無ければ None。
    """
    group_lower = group.lower()
    best_key: str | None = None
    for key in keys:
        key_lower = key.lower()
        if group_lower.startswith(key_lower) or key_lower.startswith(group_lower):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    return best_key
