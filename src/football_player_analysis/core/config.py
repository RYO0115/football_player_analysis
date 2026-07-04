# 概要: アプリ全体の設定を一元管理するモジュール。
# 環境変数 (.env) と引数の両方から設定を組み立てられるようにし、
# 各 feature が直接 os.environ を触らないための境界層として機能する。

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class SubstackConfig:
    """Substack 投稿に必要な認証情報。

    非公式 API (python-substack) はメール/パスワード認証を使うため、
    認証情報は必ず環境変数経由で受け取り、コードや設定ファイルに書かせない。
    """

    email: str | None = None
    password: str | None = None
    publication_url: str | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.email and self.password and self.publication_url)


@dataclass(frozen=True)
class Settings:
    """アプリ全体の設定値。

    リーグ・シーズンはユーザーが自由に増減させる値なので、
    コード内の固定リストではなく CLI 引数/環境変数から受け取る。
    """

    data_dir: Path = Path("data")
    # dry_run 既定 True: 外部公開 (Substack 投稿) は明示的に解除しない限り行わない
    dry_run: bool = True
    substack: SubstackConfig = field(default_factory=SubstackConfig)

    @classmethod
    def from_env(cls) -> "Settings":
        """環境変数 (.env 含む) から設定を構築する。"""
        load_dotenv()
        return cls(
            data_dir=Path(os.environ.get("FPA_DATA_DIR", "data")),
            dry_run=os.environ.get("FPA_DRY_RUN", "true").lower() != "false",
            substack=SubstackConfig(
                email=os.environ.get("SUBSTACK_EMAIL"),
                password=os.environ.get("SUBSTACK_PASSWORD"),
                publication_url=os.environ.get("SUBSTACK_PUBLICATION_URL"),
            ),
        )
