"""
PLI Logging Setup - サポート・診断用ログ基盤

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.

ログ出力先:
  macOS:   ~/Library/Logs/PLI/pli.log
  Windows: %LOCALAPPDATA%/PLI/logs/pli.log
  その他:  ~/.local/state/PLI/logs/pli.log
ローテーション: 5MB × 3世代（最大 ~20MB で頭打ち）

使い方:
    # main.py の main() 冒頭で1回だけ
    from core.logging_setup import setup_logging
    setup_logging()

    # 各モジュールでは
    from core.logging_setup import get_logger
    logger = get_logger(__name__)
    logger.info("モデルロード完了")

==========================================================================
【最重要・プライバシー規律】発話本文は絶対にログに書かない
==========================================================================
PLI は弁護人接見の通訳ツールであり、依頼者（被疑者・被告人）の発言・
弁護人の発言・翻訳結果・英語中間文・グロッサリー登録名（人名）は
すべて接見内容の秘匿（秘密交通権）の対象である。

- 発話テキスト・訳文・固有名詞をログに書くことを禁止する。
- デバッグ目的で必要な場合は「長さ」「言語コード」「件数」のみ記録する。
    NG: logger.debug("translated: %s", text)
    OK: logger.debug("translate ja->%s len=%d", lang, len(text))
- 例外メッセージに発話が混入し得る箇所では str(e) の内容に注意する。
==========================================================================
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

# ログフォーマット（仕様固定）
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# PLI 名前空間ロガーのルート名
_PLI_ROOT = "pli"

_configured = False


def get_log_dir() -> Path:
    """プラットフォーム別のログディレクトリを返す（作成はしない）"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "PLI"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(
            Path.home() / "AppData" / "Local")
        return Path(base) / "PLI" / "logs"
    # Linux ほか
    base = os.environ.get("XDG_STATE_HOME") or str(
        Path.home() / ".local" / "state")
    return Path(base) / "PLI" / "logs"


def get_log_file() -> Path:
    """ログファイル本体のパス"""
    return get_log_dir() / "pli.log"


def setup_logging(level: int = logging.DEBUG) -> logging.Logger:
    """ログ基盤を初期化する（main() 冒頭で1回呼ぶ。多重呼出は無害）。

    - RotatingFileHandler: 5MB × 3世代
    - StreamHandler: 非frozen（開発時の python main.py）のみ追加
    - サードパーティライブラリは WARNING 以上のみファイルに記録
    """
    global _configured
    root = logging.getLogger()
    pli_logger = logging.getLogger(_PLI_ROOT)
    if _configured:
        return pli_logger
    _configured = True

    formatter = logging.Formatter(LOG_FORMAT)

    # --- ファイルハンドラ（失敗してもアプリは起動させる） ---
    try:
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            str(get_log_file()),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)
    except OSError as e:
        # ログディレクトリが作れない環境でも起動は止めない
        sys.stderr.write(f"pli: log file unavailable: {e}\n")

    # --- 開発コンソール（PyInstaller frozen .app では追加しない） ---
    if not getattr(sys, "frozen", False):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(level)
        root.addHandler(stream_handler)

    # サードパーティ（transformers / urllib3 等）は WARNING 以上のみ
    root.setLevel(logging.WARNING)
    # PLI 自身のログは指定レベル（既定 DEBUG）まで記録
    pli_logger.setLevel(level)
    return pli_logger


def get_logger(name: str = "") -> logging.Logger:
    """PLI 名前空間のロガーを返す。

    get_logger(__name__) と呼ぶと "pli.core.interpreter" のような
    名前になり、setup_logging() のレベル設定が効く。
    """
    if not name or name == _PLI_ROOT:
        return logging.getLogger(_PLI_ROOT)
    if name.startswith(_PLI_ROOT + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_PLI_ROOT}.{name}")


def read_recent_errors(max_lines: int = 5) -> list[str]:
    """ログファイル末尾から ERROR/CRITICAL 行を新しい順に最大 max_lines 件返す。

    サポート情報コピー用。発話本文はそもそもログに書かれない運用のため、
    ここで返る行に接見内容は含まれない。
    """
    path = get_log_file()
    if not path.is_file():
        return []
    try:
        # ローテーション上限が5MBなので全読みで問題ない
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    errors = [
        ln for ln in lines
        if " ERROR " in ln or " CRITICAL " in ln
    ]
    return errors[-max_lines:]
