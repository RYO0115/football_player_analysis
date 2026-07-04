# 概要: Substack への記事投稿 (python-substack 経由)。
# Substack に公式 API は無く、非公式 API はメール/パスワード認証のため、
# 認証情報は環境変数からのみ受け取る。誤投稿防止のため dry_run を既定とし、
# dry_run 時はローカルにファイル出力して内容を確認できるようにする。

from __future__ import annotations

from pathlib import Path

from football_player_analysis.core.config import SubstackConfig
from football_player_analysis.core.exceptions import PublishError
from football_player_analysis.features.report.markdown import Article


class SubstackPublisher:
    """記事 (Article) を Substack に下書き投稿/公開するパブリッシャー。"""

    def __init__(
        self,
        config: SubstackConfig,
        dry_run: bool = True,
        out_dir: Path = Path("output"),
    ) -> None:
        self._config = config
        self._dry_run = dry_run
        self._out_dir = Path(out_dir)

    def publish(self, article: Article, publish_now: bool = False) -> str:
        """記事を投稿する。戻り値は保存先パスまたは投稿結果の識別子。

        publish_now=False の場合は Substack 上に「下書き」として作成し、
        最終確認は人間が行う運用を既定とする。
        """
        if self._dry_run:
            return str(self._write_local(article))

        if not self._config.is_configured:
            raise PublishError(
                "Substack 認証情報が未設定です。"
                " SUBSTACK_EMAIL / SUBSTACK_PASSWORD / SUBSTACK_PUBLICATION_URL を設定してください。"
            )
        # ネットワーク副作用を持つ import は実投稿時まで遅延させる
        from substack import Api
        from substack.post import Post

        try:
            api = Api(
                email=self._config.email,
                password=self._config.password,
                publication_url=self._config.publication_url,
            )
            post = Post(
                title=article.title,
                subtitle=article.subtitle,
                user_id=api.get_user_id(),
            )
            # python-substack は段落単位で本文を組み立てる仕様
            for paragraph in article.body_markdown.split("\n\n"):
                post.add({"type": "paragraph", "content": paragraph})
            draft = api.post_draft(post.get_draft())
            if publish_now:
                api.prepublish_draft(draft.get("id"))
                api.publish_draft(draft.get("id"))
            return str(draft.get("id"))
        except PublishError:
            raise
        except Exception as exc:  # 非公式 API の例外型は不安定なため広く捕捉
            raise PublishError(f"Substack 投稿に失敗しました: {exc}") from exc

    def _write_local(self, article: Article) -> Path:
        """dry_run 時: 記事をローカル Markdown として保存する。"""
        self._out_dir.mkdir(parents=True, exist_ok=True)
        safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in article.title)
        path = self._out_dir / f"{safe_title.strip().replace(' ', '_')}.md"
        path.write_text(
            f"# {article.title}\n\n_{article.subtitle}_\n\n{article.body_markdown}\n",
            encoding="utf-8",
        )
        return path
