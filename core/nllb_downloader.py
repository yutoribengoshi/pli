"""
NLLB-200 モデルカタログ & ダウンロードヘルパー

CTranslate2 形式の NLLB モデルを ~/pli-models/nllb/ に管理する。
HuggingFace Hub からの自動ダウンロードに対応。
"""

import os
import shutil
from typing import Callable, Optional

from core.logging_setup import get_logger

logger = get_logger(__name__)


class DiskSpaceError(RuntimeError):
    """ディスク空き容量不足エラー（ダウンロード前チェックで送出）"""

# ---------------------------------------------------------------------------
# モデルカタログ
# ---------------------------------------------------------------------------

NLLB_MODELS = {
    "nllb-3.3b-int8": {
        "repo": "michaelfeil/ct2fast-nllb-200-3.3B",
        "tokenizer_repo": "facebook/nllb-200-3.3B",
        "label": "NLLB-200 3.3B int8（推奨・RAM ~4GB）",
        "size_gb": 3.5,
        "ram_gb": 5.0,
    },
    "nllb-1.3b-int8": {
        "repo": "JustFrederik/nllb-200-distilled-1.3B-ct2-int8",
        "tokenizer_repo": "facebook/nllb-200-distilled-1.3B",
        "label": "NLLB-200 1.3B int8（軽量・RAM ~3GB）",
        "size_gb": 1.5,
        "ram_gb": 3.0,
    },
}

NLLB_BASE_DIR = os.path.expanduser("~/pli-models/nllb")


def get_model_dir(model_key: str) -> str:
    """モデルのローカルディレクトリパスを返す"""
    return os.path.join(NLLB_BASE_DIR, model_key)


def _ensure_disk_space(dest_dir: str, required_gb: float) -> None:
    """ダウンロード先の空き容量を確認し、不足なら DiskSpaceError を送出する。

    *dest_dir* は存在している必要がある（os.makedirs 後に呼ぶこと）。
    """
    free_gb = shutil.disk_usage(dest_dir).free / (1024 ** 3)
    if free_gb < required_gb:
        raise DiskSpaceError(
            f"ディスク空き容量が不足しています"
            f"（必要: {required_gb:.1f} GB / 空き: {free_gb:.1f} GB）"
        )


def _verify_downloaded_files(dest: str) -> None:
    """ダウンロード結果の整合性チェック。必須ファイル欠落なら例外を送出する。

    - CTranslate2 モデル本体: model.bin
    - トークナイザー: tokenizer/ 配下の設定 + 語彙ファイル
    """
    missing = []
    if not os.path.exists(os.path.join(dest, "model.bin")):
        missing.append("model.bin")
    tokenizer_dir = os.path.join(dest, "tokenizer")
    if not os.path.exists(os.path.join(tokenizer_dir, "tokenizer_config.json")):
        missing.append("tokenizer/tokenizer_config.json")
    if not (
        os.path.exists(os.path.join(tokenizer_dir, "sentencepiece.bpe.model"))
        or os.path.exists(os.path.join(tokenizer_dir, "tokenizer.json"))
    ):
        missing.append("tokenizer/（sentencepiece.bpe.model または tokenizer.json）")
    if missing:
        raise RuntimeError(
            "ダウンロードしたモデルデータが不完全です"
            f"（不足ファイル: {', '.join(missing)}）。"
            "もう一度ダウンロードをお試しください。"
        )


def is_downloaded(model_key: str) -> bool:
    """モデルがダウンロード済みか確認"""
    model_dir = get_model_dir(model_key)
    if not os.path.isdir(model_dir):
        return False
    # CTranslate2 モデルの必須ファイル
    return os.path.exists(os.path.join(model_dir, "model.bin"))


def list_downloaded() -> list[str]:
    """ダウンロード済みモデルキーのリストを返す"""
    return [key for key in NLLB_MODELS if is_downloaded(key)]


def download_model(
    model_key: str,
    on_progress: Optional[Callable[[float], None]] = None,
) -> str:
    """
    HuggingFace Hub からモデルをダウンロード

    Args:
        model_key: NLLB_MODELS のキー
        on_progress: 進捗コールバック (0.0〜1.0)

    Returns:
        ダウンロード先のローカルパス
    """
    if model_key not in NLLB_MODELS:
        raise ValueError(f"不明なモデルキー: {model_key}")

    info = NLLB_MODELS[model_key]
    dest = get_model_dir(model_key)
    os.makedirs(dest, exist_ok=True)

    # ダウンロード前にディスク空き容量を確認
    _ensure_disk_space(dest, info["size_gb"])

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise RuntimeError(
            "この機能は現在利用できません"
            "（ダウンロードコンポーネントが見つかりません）。"
        )

    if on_progress:
        on_progress(0.05)

    # CTranslate2 モデルをダウンロード
    logger.info("nllb: モデルをダウンロード中: %s", info["repo"])
    snapshot_download(
        repo_id=info["repo"],
        local_dir=dest,
        local_dir_use_symlinks=False,
    )

    if on_progress:
        on_progress(0.8)

    # トークナイザーもダウンロード（同じディレクトリ内の tokenizer/ に）
    tokenizer_dir = os.path.join(dest, "tokenizer")
    os.makedirs(tokenizer_dir, exist_ok=True)

    logger.info("nllb: トークナイザーをダウンロード中: %s", info["tokenizer_repo"])
    try:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(info["tokenizer_repo"])
        tokenizer.save_pretrained(tokenizer_dir)
    except Exception as e:
        # トークナイザーが無いと翻訳時に必ず失敗する。
        # 黙殺せず、ここで失敗として呼び出し元（エラー表示経路）に伝える。
        raise RuntimeError(
            f"トークナイザーのダウンロードに失敗しました: {e}"
        ) from e

    # ダウンロード結果の整合性チェック（必須ファイルの存在確認）
    _verify_downloaded_files(dest)

    if on_progress:
        on_progress(1.0)

    logger.info("nllb: ダウンロード完了: %s", dest)
    return dest


def check_dependencies() -> tuple[bool, str]:
    """
    NLLB に必要なパッケージがインストールされているか確認

    Returns:
        (ok, message)
    """
    missing = []
    for pkg in ["ctranslate2", "transformers", "sentencepiece"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        return False, (
            "この機能は現在利用できません"
            f"（必要なコンポーネントが見つかりません: {', '.join(missing)}）"
        )
    return True, "OK"
