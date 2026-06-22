"""
PLI Core Whisper STT - 音声認識エンジン
WhisperSTT / MockSTT / バックエンド検出ユーティリティ

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""

import os
import platform
import sys
from pathlib import Path

from core.logging_setup import get_logger

logger = get_logger(__name__)

# mlx-whisper が使うHuggingFaceリポジトリ（macOS / Apple Silicon用）
WHISPER_REPO = "mlx-community/whisper-turbo"

# 法律語彙バイアス用プロンプト（Whisper initial_prompt）
# 接見文脈と同音異義で誤りやすい刑事弁護用語を提示し、Whisperに
# 正しい漢字を優先させる。実測で日本語法律フレーズのCERを54%削減
# （黙秘権←目比券, 保釈←補釈, 示談←時短, 前科←善化, 勾留←交流 等）。
# 英語等の他言語認識には影響しない（Whisperは言語を自動判定するため）。
LEGAL_ASR_PROMPT = (
    "これは刑事事件の接見における弁護人と被疑者の会話です。"
    "黙秘権、勾留、保釈、起訴、不起訴、接見、接見禁止、執行猶予、"
    "公判前整理手続、示談、前科、前歴、正当防衛、故意、過失、"
    "覚醒剤取締法、大麻取締法、被告人、被疑者、弁護人、検察官、"
    "傷害、窃盗、強盗、詐欺、横領、勾留延長、保釈保証金、求刑、"
    "といった法律用語が登場します。"
)


# ---------------------------------------------------------------------------
# モデルダウンロード管理（macOS / mlx-whisper 用）
# ---------------------------------------------------------------------------

def _hf_hub_cache_dir() -> Path:
    """HuggingFaceハブのキャッシュディレクトリ（環境変数の上書きに対応）"""
    env = os.environ.get("HF_HUB_CACHE")
    if env:
        return Path(env)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def whisper_model_downloaded() -> bool:
    """Whisper STTモデルがHFキャッシュにダウンロード済みか

    macOS (mlx-whisper) のみ実チェックする。Windows/Linux の
    faster-whisper は独自のキャッシュ管理を持つため、非macOSでは
    常に True を返す（今後の課題）。
    """
    if sys.platform != "darwin":
        return True
    snapshots = (
        _hf_hub_cache_dir()
        / ("models--" + WHISPER_REPO.replace("/", "--"))
        / "snapshots"
    )
    if not snapshots.is_dir():
        return False
    for snap in snapshots.iterdir():
        if not snap.is_dir():
            continue
        for pattern in ("*.safetensors", "weights.npz"):
            for f in snap.glob(pattern):
                try:
                    # snapshot内はblobへのsymlink。blob欠損（壊れたリンク）を除外
                    if f.exists() and f.stat().st_size > 0:
                        return True
                except OSError:
                    continue
    return False


def download_whisper_model(progress_cb=None) -> str:
    """Whisper STTモデル（約1.5GB）をHuggingFaceからダウンロードする

    Args:
        progress_cb: callable(float) — 開始時に 0.0、完了時に 1.0 で呼ばれる
    Returns:
        ダウンロードされたスナップショットのローカルパス
    """
    from huggingface_hub import snapshot_download
    if progress_cb:
        progress_cb(0.0)
    path = snapshot_download(WHISPER_REPO)
    if progress_cb:
        progress_cb(1.0)
    return path


# ---------------------------------------------------------------------------
# MockSTT
# ---------------------------------------------------------------------------

class MockSTT:
    """音声認識のモック"""

    _MOCK_PHRASES = [
        ("黙秘権を行使します", "ja"),
        ("保釈請求を検討しましょう", "ja"),
        ("接見禁止の決定が出ています", "ja"),
        ("I did not do it", "en"),
        ("I want a lawyer", "en"),
    ]
    _mock_idx = 0

    def transcribe(self, audio_path_or_data=None) -> tuple[str, str]:
        """Returns (text, language) — モックはサンプル文を順番に返す"""
        text, lang = self._MOCK_PHRASES[self._mock_idx % len(self._MOCK_PHRASES)]
        MockSTT._mock_idx += 1
        return text, lang


# ---------------------------------------------------------------------------
# Backend detection utilities
# ---------------------------------------------------------------------------

def detect_cpu_backend() -> str:
    """CPUベンダーを検出して最適なバックエンドを返す

    Returns:
        "cuda" (NVIDIA), "openvino" (Intel), "directml" (AMD GPU), "cpu" (汎用)
    """
    # NVIDIA GPU チェック
    try:
        import ctranslate2
        if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
            return "cuda"
    except Exception as e:
        logger.warning("detect_cpu_backend: CUDA check failed: %s", e)
    # CPU ベンダー検出
    cpu_info = platform.processor().lower()
    if "intel" in cpu_info or "genuineintel" in cpu_info:
        try:
            import openvino  # noqa: F401
            return "openvino"
        except ImportError:
            return "cpu"
    if "amd" in cpu_info or "authenticamd" in cpu_info:
        try:
            import onnxruntime_directml  # noqa: F401
            return "directml"
        except ImportError:
            return "cpu"
    return "cpu"


def get_available_backends() -> list[str]:
    """インストール済みのバックエンドを検出してリストで返す"""
    backends = ["cpu"]
    try:
        import ctranslate2
        if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
            backends.append("cuda")
    except Exception as e:
        logger.warning("get_available_backends: CUDA check failed: %s", e)
    try:
        import openvino  # noqa: F401
        backends.append("openvino")
    except ImportError:
        pass
    try:
        import onnxruntime_directml  # noqa: F401
        backends.append("directml")
    except ImportError:
        pass
    return backends


# ---------------------------------------------------------------------------
# WhisperSTT
# ---------------------------------------------------------------------------

class WhisperSTT:
    """STTエンジン — プラットフォーム・CPUに応じて自動選択

    macOS (Apple Silicon): mlx-whisper (Metal GPU加速) ~0.5秒/2秒音声
    Windows/Linux: faster-whisper (CUDA/OpenVINO/CPU) ~5秒/2秒音声
    """

    def __init__(self, whisper_model: str = "", cpu_backend: str = "auto"):
        self._cpu_backend = cpu_backend
        if sys.platform == "darwin":
            # macOS: mlx-whisper (Apple Silicon GPU加速)
            import mlx_whisper
            self._backend = "mlx"
            self._mlx_whisper = mlx_whisper
            self._repo = WHISPER_REPO
        else:
            # Windows/Linux: faster-whisper
            from faster_whisper import WhisperModel
            self._backend = "faster"
            model_name = whisper_model or "medium"

            # バックエンド自動検出
            if cpu_backend == "auto":
                cpu_backend = detect_cpu_backend()
                self._cpu_backend = cpu_backend

            logger.info("Whisperモデル: %s, バックエンド: %s", model_name, cpu_backend)

            if cpu_backend == "cuda":
                try:
                    self._model = WhisperModel(
                        model_name, device="cuda", compute_type="float16",
                    )
                    return
                except Exception as e:
                    logger.info("CUDA失敗、CPUにフォールバック: %s", e)
                    cpu_backend = "cpu"

            if cpu_backend == "openvino":
                try:
                    self._model = WhisperModel(
                        model_name, device="cpu", compute_type="int8",
                        backend="openvino",
                    )
                    logger.info("OpenVINOバックエンドで起動")
                    return
                except Exception as e:
                    logger.info("OpenVINO失敗、CPUにフォールバック: %s", e)
                    cpu_backend = "cpu"

            # 汎用CPU
            logger.info("CPUバックエンドで起動 (selected: %s)", cpu_backend)
            self._model = WhisperModel(
                model_name, device="cpu", compute_type="int8",
            )

    @staticmethod
    def _decode_wav_mono16k(path: str):
        """PCM16 WAV を float32 mono ndarray にデコードする（ffmpeg非依存）。

        mlx-whisper はパスを渡すと内部で ffmpeg CLI を呼ぶため、PyInstaller
        で固めた .app では STT が動かない（ffmpeg非同梱・PATH外）。自前で
        wave+numpy デコードして ndarray を渡すことで ffmpeg 依存を断つ。
        PLIのSTTは常に16kHz/mono/PCM16のWAVを生成するため前提を満たす。
        """
        import wave
        import numpy as np
        with wave.open(path, "rb") as w:
            sampwidth = w.getsampwidth()
            n_ch = w.getnchannels()
            raw = w.readframes(w.getnframes())
        if sampwidth != 2:
            # 想定外フォーマットはパスのまま返し、呼び出し側のフォールバックに委ねる
            raise ValueError(f"unsupported sample width: {sampwidth}")
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if n_ch > 1:
            audio = audio.reshape(-1, n_ch).mean(axis=1)
        return audio

    def transcribe(self, audio_path: str,
                   initial_prompt: str = LEGAL_ASR_PROMPT) -> tuple[str, str]:
        """音声を書き起こす。

        Args:
            audio_path: 16kHz mono WAV のパス
            initial_prompt: Whisperへの語彙バイアス。デフォルトで法律用語
                プロンプトを与え、同音異義語の誤認識を抑制する。
                他言語認識には影響しない。空文字で無効化可能。
        """
        if self._backend == "mlx":
            # WAVを自前デコードしてndarrayで渡す（ffmpeg依存を断つ）。
            # デコード失敗時のみパス渡しにフォールバック。
            try:
                audio_input = self._decode_wav_mono16k(audio_path)
            except Exception as e:
                logger.warning("WAV自前デコード失敗、パス渡しにフォールバック: %s", e)
                audio_input = audio_path
            result = self._mlx_whisper.transcribe(
                audio_input,
                path_or_hf_repo=self._repo,
                initial_prompt=initial_prompt or None,
            )
            text = result.get("text", "")
            lang = result.get("language", "ja")
            return text.strip(), lang
        else:
            segments, info = self._model.transcribe(
                audio_path,
                beam_size=5,
                best_of=5,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=True,
                initial_prompt=initial_prompt or None,
            )
            text = "".join(seg.text for seg in segments)
            return text.strip(), info.language
