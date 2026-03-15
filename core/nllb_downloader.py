"""
NLLB-200 モデルカタログ & ダウンロードヘルパー

CTranslate2 形式の NLLB モデルを ~/pli-models/nllb/ に管理する。
HuggingFace Hub からの自動ダウンロードに対応。
"""

import os
from typing import Callable, Optional

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

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise RuntimeError(
            "huggingface_hub が未インストールです。\n"
            "pip install huggingface_hub でインストールしてください。"
        )

    if on_progress:
        on_progress(0.05)

    # CTranslate2 モデルをダウンロード
    print(f"[nllb] モデルをダウンロード中: {info['repo']}")
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

    print(f"[nllb] トークナイザーをダウンロード中: {info['tokenizer_repo']}")
    try:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(info["tokenizer_repo"])
        tokenizer.save_pretrained(tokenizer_dir)
    except Exception as e:
        print(f"[nllb] トークナイザーのダウンロードに失敗: {e}")
        # トークナイザーが失敗してもモデルは使える場合がある

    if on_progress:
        on_progress(1.0)

    print(f"[nllb] ダウンロード完了: {dest}")
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
        return False, f"未インストール: {', '.join(missing)}\npip install {' '.join(missing)}"
    return True, "OK"
