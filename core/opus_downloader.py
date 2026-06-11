"""
OPUS-MT モデルカタログ & ダウンロードヘルパー

Helsinki-NLP/OPUS-MT の言語ペア専用翻訳モデルを
CTranslate2 形式で ~/pli-models/opus/ に管理する。

ハイブリッドエンジンの「主要言語ペア高精度翻訳」を担当。
NLLB（200言語汎用）と組み合わせて最高精度を実現。
"""

import os
import shutil
from typing import Callable, Optional

from core.logging_setup import get_logger

logger = get_logger(__name__)


class DiskSpaceError(RuntimeError):
    """ディスク空き容量不足エラー（ダウンロード前チェックで送出）"""


# 1ペアあたりのダウンロード容量概算（HF重み + CT2変換一時ファイル込み）
OPUS_PAIR_SIZE_GB = 0.5

# ---------------------------------------------------------------------------
# 言語ペアカタログ
# ---------------------------------------------------------------------------
# key: "{src}-{tgt}" 形式
# CTranslate2 変換済みモデルを優先。なければ自動変換する。

OPUS_MODELS = {
    # ======= 日本語 ↔ 英語（最重要ペア） =======
    "ja-en": {
        "repo": "Helsinki-NLP/opus-mt-ja-en",
        "label": "日本語 → 英語",
        "ram_gb": 1.5,
        "priority": 1,
    },
    "en-ja": {
        "repo": "Helsinki-NLP/opus-mt-en-jap",
        "label": "英語 → 日本語",
        "ram_gb": 1.5,
        "priority": 1,
    },

    # ======= 日本語 → 他言語 (jaを経由せずenをpivot) =======
    # ※ OPUS-MTにja直接ペアが少ないため、en経由のペアも用意

    # ======= 中国語 ↔ 英語 =======
    "zh-en": {
        "repo": "Helsinki-NLP/opus-mt-zh-en",
        "label": "中国語 → 英語",
        "ram_gb": 1.5,
        "priority": 2,
    },
    "en-zh": {
        "repo": "Helsinki-NLP/opus-mt-en-zh",
        "label": "英語 → 中国語",
        "ram_gb": 1.5,
        "priority": 2,
    },

    # ======= 韓国語 ↔ 英語 =======
    "ko-en": {
        "repo": "Helsinki-NLP/opus-mt-ko-en",
        "label": "韓国語 → 英語",
        "ram_gb": 1.5,
        "priority": 2,
    },
    "en-ko": {
        "repo": "Helsinki-NLP/opus-mt-en-ko",
        "label": "英語 → 韓国語",
        "ram_gb": 1.5,
        "priority": 2,
    },

    # ======= フランス語 ↔ 英語 =======
    "fr-en": {
        "repo": "Helsinki-NLP/opus-mt-fr-en",
        "label": "フランス語 → 英語",
        "ram_gb": 1.5,
        "priority": 3,
    },
    "en-fr": {
        "repo": "Helsinki-NLP/opus-mt-en-fr",
        "label": "英語 → フランス語",
        "ram_gb": 1.5,
        "priority": 3,
    },

    # ======= ドイツ語 ↔ 英語 =======
    "de-en": {
        "repo": "Helsinki-NLP/opus-mt-de-en",
        "label": "ドイツ語 → 英語",
        "ram_gb": 1.5,
        "priority": 3,
    },
    "en-de": {
        "repo": "Helsinki-NLP/opus-mt-en-de",
        "label": "英語 → ドイツ語",
        "ram_gb": 1.5,
        "priority": 3,
    },

    # ======= スペイン語 ↔ 英語 =======
    "es-en": {
        "repo": "Helsinki-NLP/opus-mt-es-en",
        "label": "スペイン語 → 英語",
        "ram_gb": 1.5,
        "priority": 3,
    },
    "en-es": {
        "repo": "Helsinki-NLP/opus-mt-en-es",
        "label": "英語 → スペイン語",
        "ram_gb": 1.5,
        "priority": 3,
    },

    # ======= ポルトガル語 ↔ 英語 =======
    "pt-en": {
        "repo": "Helsinki-NLP/opus-mt-tc-big-en-pt",
        "label": "英語 → ポルトガル語",
        "ram_gb": 1.5,
        "priority": 4,
    },

    # ======= ロシア語 ↔ 英語 =======
    "ru-en": {
        "repo": "Helsinki-NLP/opus-mt-ru-en",
        "label": "ロシア語 → 英語",
        "ram_gb": 1.5,
        "priority": 3,
    },
    "en-ru": {
        "repo": "Helsinki-NLP/opus-mt-en-ru",
        "label": "英語 → ロシア語",
        "ram_gb": 1.5,
        "priority": 3,
    },

    # ======= アラビア語 ↔ 英語 =======
    "ar-en": {
        "repo": "Helsinki-NLP/opus-mt-ar-en",
        "label": "アラビア語 → 英語",
        "ram_gb": 1.5,
        "priority": 4,
    },
    "en-ar": {
        "repo": "Helsinki-NLP/opus-mt-en-ar",
        "label": "英語 → アラビア語",
        "ram_gb": 1.5,
        "priority": 4,
    },

    # ======= ベトナム語 ↔ 英語 =======
    "vi-en": {
        "repo": "Helsinki-NLP/opus-mt-vi-en",
        "label": "ベトナム語 → 英語",
        "ram_gb": 1.5,
        "priority": 4,
    },
    "en-vi": {
        "repo": "Helsinki-NLP/opus-mt-en-vi",
        "label": "英語 → ベトナム語",
        "ram_gb": 1.5,
        "priority": 4,
    },

    # ======= タイ語 ↔ 英語 =======
    "th-en": {
        "repo": "Helsinki-NLP/opus-mt-th-en",
        "label": "タイ語 → 英語",
        "ram_gb": 1.5,
        "priority": 4,
    },

    # ======= ヒンディー語 ↔ 英語 =======
    "hi-en": {
        "repo": "Helsinki-NLP/opus-mt-hi-en",
        "label": "ヒンディー語 → 英語",
        "ram_gb": 1.5,
        "priority": 4,
    },

    # ======= トルコ語 ↔ 英語 =======
    "tr-en": {
        "repo": "Helsinki-NLP/opus-mt-tr-en",
        "label": "トルコ語 → 英語",
        "ram_gb": 1.5,
        "priority": 4,
    },
    "en-tr": {
        "repo": "Helsinki-NLP/opus-mt-en-tr",
        "label": "英語 → トルコ語",
        "ram_gb": 1.5,
        "priority": 4,
    },
}

OPUS_BASE_DIR = os.path.expanduser("~/pli-models/opus")


# ---------------------------------------------------------------------------
# マルチリンガルモデル（少数言語対応）
# ---------------------------------------------------------------------------
# Helsinki-NLP/opus-mt-mul-en: 120言語 → 英語
# Helsinki-NLP/opus-mt-en-mul: 英語 → 120言語
# 少数言語は個別ペアが存在しないため、これらの汎用モデルで対応。
# en-mul は入力テキスト先頭に >>lang_code<< を付与して対象言語を指定。

OPUS_MULTILINGUAL = {
    "mul-en": {
        "repo": "Helsinki-NLP/opus-mt-mul-en",
        "label": "多言語 → 英語（120言語対応）",
        "ram_gb": 2.0,
        "priority": 5,
    },
    "en-mul": {
        "repo": "Helsinki-NLP/opus-mt-en-mul",
        "label": "英語 → 多言語（120言語対応）",
        "ram_gb": 2.0,
        "priority": 5,
    },
}

# PLI言語コード → OPUS マルチリンガルモデルの言語トークン
# en-mul モデルでは >>token<< 形式でターゲット言語を指定
PLI_TO_OPUS_TOKEN = {
    "ja": "jpn",
    "en": "eng",      # 不要だが参照用
    "zh": "cmn_Hans",
    "ko": "kor_Hang",  # mul-en非対応、OPUS個別ペアを使用
    "fr": "fra",
    "de": "deu",
    "es": "spa",
    "pt": "por",
    "ar": "ara",
    "ru": "rus",
    "it": "ita",
    "th": "tha",
    "vi": "vie",
    "tl": "tgl_Latn",
    # ---- 少数言語（ここが重要）----
    "ne": "npi",       # ネパール語
    "my": "mya",       # ミャンマー語
    "fa": "pes",       # ペルシア語
    "id": "ind",       # インドネシア語
    "hi": "hin",       # ヒンディー語
    "bn": "ben",       # ベンガル語
    "ur": "urd",       # ウルドゥー語
    "si": "sin",       # シンハラ語
    "km": "khm",       # クメール語
    "mn": "mon",       # モンゴル語
    "tr": "tur",       # トルコ語
    "ta": "tam",       # タミル語
    "te": "tel",       # テルグ語
    "ml": "mal",       # マラヤーラム語
    "gu": "guj",       # グジャラート語
    "mr": "mar",       # マラーティー語
    "pa": "pan_Guru",  # パンジャーブ語
    "sw": "swh",       # スワヒリ語
    "am": "amh",       # アムハラ語
    "lo": "lao",       # ラオ語
    "ka": "kat",       # ジョージア語
    "he": "heb",       # ヘブライ語
    "uk": "ukr",       # ウクライナ語
    "pl": "pol",       # ポーランド語
    "ro": "ron",       # ルーマニア語
    "hu": "hun",       # ハンガリー語
    "cs": "ces",       # チェコ語
    "el": "ell",       # ギリシャ語
    "bg": "bul",       # ブルガリア語
    "ms": "zsm_Latn",  # マレー語
    "jv": "jav",       # ジャワ語
    "su": "sun",       # スンダ語
    "ceb": "ceb",      # セブアノ語
    "so": "som",       # ソマリ語
    "ha": "hau_Latn",  # ハウサ語
    "yo": "yor",       # ヨルバ語
    "ig": "ibo",       # イボ語
    "zu": "zul",       # ズールー語
}


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def get_pair_key(src_lang: str, tgt_lang: str) -> str:
    """PLI言語コード → OPUS-MTペアキー"""
    return f"{src_lang}-{tgt_lang}"


def get_model_dir(pair_key: str) -> str:
    """モデルのローカルディレクトリパスを返す"""
    return os.path.join(OPUS_BASE_DIR, pair_key)


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

    - CTranslate2 形式: model.bin
    - HuggingFace 形式（CT2変換失敗時のフォールバック）:
      config.json + 重みファイル（pytorch_model.bin / model.safetensors）
    """
    if os.path.exists(os.path.join(dest, "model.bin")):
        return  # CTranslate2 形式 OK
    has_weights = (
        os.path.exists(os.path.join(dest, "pytorch_model.bin"))
        or os.path.exists(os.path.join(dest, "model.safetensors"))
    )
    if os.path.exists(os.path.join(dest, "config.json")) and has_weights:
        return  # HuggingFace 形式 OK
    raise RuntimeError(
        "ダウンロードしたモデルデータが不完全です"
        "（モデル本体ファイルが見つかりません）。"
        "もう一度ダウンロードをお試しください。"
    )


def is_downloaded(pair_key: str) -> bool:
    """CTranslate2変換済みモデルが存在するか"""
    model_dir = get_model_dir(pair_key)
    if not os.path.isdir(model_dir):
        return False
    # CTranslate2形式 or HuggingFace形式のいずれかが存在すればOK
    ct2_ok = os.path.exists(os.path.join(model_dir, "model.bin"))
    hf_ok = os.path.exists(os.path.join(model_dir, "pytorch_model.bin")) or \
            os.path.exists(os.path.join(model_dir, "model.safetensors"))
    return ct2_ok or hf_ok


def is_ct2_converted(pair_key: str) -> bool:
    """CTranslate2形式に変換済みか"""
    model_dir = get_model_dir(pair_key)
    return os.path.exists(os.path.join(model_dir, "model.bin"))


def list_downloaded() -> list[str]:
    """ダウンロード済みペアキーのリスト"""
    return [key for key in OPUS_MODELS if is_downloaded(key)]


def list_downloaded_multilingual() -> list[str]:
    """ダウンロード済みマルチリンガルモデルのリスト"""
    return [key for key in OPUS_MULTILINGUAL if is_downloaded(key)]


def list_available_for_lang(lang_code: str) -> list[str]:
    """指定言語が関係するペアのリスト"""
    return [key for key in OPUS_MODELS if lang_code in key.split("-")]


def has_pair(src: str, tgt: str) -> bool:
    """指定言語ペアのOPUS-MTモデルが（カタログに）存在するか"""
    return get_pair_key(src, tgt) in OPUS_MODELS


def has_multilingual(direction: str) -> bool:
    """マルチリンガルモデルがダウンロード済みか
    direction: "mul-en" or "en-mul"
    """
    return direction in OPUS_MULTILINGUAL and is_downloaded(direction)


def get_opus_token(lang_code: str) -> Optional[str]:
    """PLI言語コード → OPUS マルチリンガルトークン"""
    return PLI_TO_OPUS_TOKEN.get(lang_code)


def estimate_ram_for_lang(lang_code: str) -> float:
    """言語に関連するペアを全部ロードした場合のRAM概算(GB)"""
    pairs = list_available_for_lang(lang_code)
    return sum(OPUS_MODELS[p]["ram_gb"] for p in pairs)


# ---------------------------------------------------------------------------
# ダウンロード & CTranslate2 変換
# ---------------------------------------------------------------------------

def download_model(
    pair_key: str,
    on_progress: Optional[Callable[[float], None]] = None,
    convert_to_ct2: bool = True,
) -> str:
    """
    HuggingFace Hub からOPUS-MTモデルをダウンロード＆CTranslate2変換

    Args:
        pair_key: OPUS_MODELS のキー (例: "ja-en")
        on_progress: 進捗コールバック (0.0〜1.0)
        convert_to_ct2: CTranslate2形式に変換する（デフォルトTrue）

    Returns:
        ダウンロード先のローカルパス
    """
    # ペア専用モデル or マルチリンガルモデル
    if pair_key in OPUS_MODELS:
        info = OPUS_MODELS[pair_key]
    elif pair_key in OPUS_MULTILINGUAL:
        info = OPUS_MULTILINGUAL[pair_key]
    else:
        raise ValueError(f"不明なペアキー: {pair_key}")

    dest = get_model_dir(pair_key)
    os.makedirs(dest, exist_ok=True)

    # ダウンロード前にディスク空き容量を確認
    _ensure_disk_space(dest, OPUS_PAIR_SIZE_GB)

    if on_progress:
        on_progress(0.05)

    # Step 1: HuggingFaceからダウンロード
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        raise RuntimeError(
            "この機能は現在利用できません"
            "（ダウンロードコンポーネントが見つかりません）。"
        )

    logger.info("opus: モデルをダウンロード中: %s", info["repo"])
    snapshot_download(
        repo_id=info["repo"],
        local_dir=dest,
        local_dir_use_symlinks=False,
    )

    if on_progress:
        on_progress(0.6)

    # Step 2: CTranslate2 変換
    if convert_to_ct2 and not is_ct2_converted(pair_key):
        _convert_to_ct2(dest, on_progress)
    elif on_progress:
        on_progress(0.95)

    # ダウンロード結果の整合性チェック（必須ファイルの存在確認）
    _verify_downloaded_files(dest)

    if on_progress:
        on_progress(1.0)

    logger.info("opus: 完了: %s", dest)
    return dest


def _convert_to_ct2(model_dir: str,
                    on_progress: Optional[Callable[[float], None]] = None):
    """Marian-MTモデルをCTranslate2形式に変換"""
    try:
        import ctranslate2
    except ImportError:
        logger.warning("opus: ctranslate2 未インストール — HuggingFace形式のまま使用")
        return

    ct2_dir = model_dir + "_ct2_tmp"
    try:
        logger.info("opus: CTranslate2変換中: %s", model_dir)
        converter = ctranslate2.converters.OpusMTConverter(model_dir)
        converter.convert(ct2_dir, quantization="int8")

        if on_progress:
            on_progress(0.9)

        # 変換結果を元ディレクトリに移動
        import shutil
        for fname in os.listdir(ct2_dir):
            src = os.path.join(ct2_dir, fname)
            dst = os.path.join(model_dir, fname)
            if os.path.isfile(src):
                shutil.move(src, dst)
        shutil.rmtree(ct2_dir, ignore_errors=True)

        logger.info("opus: CTranslate2変換完了")
    except Exception as e:
        logger.warning("opus: CTranslate2変換失敗（HuggingFace形式で使用）: %s", e)
        import shutil
        shutil.rmtree(ct2_dir, ignore_errors=True)


def download_pairs_for_lang(
    lang_code: str,
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> list[str]:
    """
    指定言語の関連ペアを一括ダウンロード

    Args:
        lang_code: PLI言語コード (例: "en", "zh")
        on_progress: (pair_key, ratio) コールバック

    Returns:
        ダウンロード済みペアキーのリスト
    """
    pairs = list_available_for_lang(lang_code)
    # priority順にソート
    pairs.sort(key=lambda k: OPUS_MODELS[k].get("priority", 99))

    # 一括ダウンロードの合計サイズ分の空き容量を先に確認
    remaining = [p for p in pairs if not is_downloaded(p)]
    if remaining:
        os.makedirs(OPUS_BASE_DIR, exist_ok=True)
        _ensure_disk_space(OPUS_BASE_DIR, OPUS_PAIR_SIZE_GB * len(remaining))

    done = []
    for i, pair_key in enumerate(pairs):
        if is_downloaded(pair_key):
            done.append(pair_key)
            continue
        try:
            def _prog(ratio):
                if on_progress:
                    total_ratio = (i + ratio) / len(pairs)
                    on_progress(pair_key, total_ratio)
            download_model(pair_key, on_progress=_prog)
            done.append(pair_key)
        except DiskSpaceError:
            # 容量不足は以降のペアも全て失敗するため、握り潰さず中断して通知
            raise
        except Exception as e:
            logger.error("opus: %s ダウンロード失敗: %s", pair_key, e)
    return done


# ---------------------------------------------------------------------------
# 依存チェック
# ---------------------------------------------------------------------------

def check_dependencies() -> tuple[bool, str]:
    """OPUS-MT/Hybrid に必要なパッケージ確認"""
    missing = []
    for pkg in ["ctranslate2", "transformers", "sentencepiece", "huggingface_hub"]:
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
