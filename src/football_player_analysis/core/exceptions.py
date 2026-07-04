# 概要: アプリ共通の例外階層。
# feature 側で発生したエラーを CLI が一括ハンドリングできるよう、
# すべて FpaError を基底とする。

class FpaError(Exception):
    """本アプリの全例外の基底クラス。"""


class CollectionError(FpaError):
    """外部データソースからの収集失敗。"""


class AnalysisError(FpaError):
    """解析処理の失敗(必須カラム欠損など)。"""


class PublishError(FpaError):
    """Substack への投稿失敗。"""
