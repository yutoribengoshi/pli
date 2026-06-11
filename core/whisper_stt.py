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

# mlx-whisper が使うHuggingFaceリポジトリ（macOS / Apple Silicon用）
WHISPER_REPO = "mlx-community/whisper-turbo"


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
        print(f"[warn] detect_cpu_backend: CUDA check failed: {e}")
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
        print(f"[warn] get_available_backends: CUDA check failed: {e}")
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

            print(f"[info] Whisperモデル: {model_name}, バックエンド: {cpu_backend}")

            if cpu_backend == "cuda":
                try:
                    self._model = WhisperModel(
                        model_name, device="cuda", compute_type="float16",
                    )
                    return
                except Exception as e:
                    print(f"[info] CUDA失敗、CPUにフォールバック: {e}")
                    cpu_backend = "cpu"

            if cpu_backend == "openvino":
                try:
                    self._model = WhisperModel(
                        model_name, device="cpu", compute_type="int8",
                        backend="openvino",
                    )
                    print("[info] OpenVINOバックエンドで起動")
                    return
                except Exception as e:
                    print(f"[info] OpenVINO失敗、CPUにフォールバック: {e}")
                    cpu_backend = "cpu"

            # 汎用CPU
            print(f"[info] CPUバックエンドで起動 (selected: {cpu_backend})")
            self._model = WhisperModel(
                model_name, device="cpu", compute_type="int8",
            )

    def transcribe(self, audio_path: str) -> tuple[str, str]:
        if self._backend == "mlx":
            result = self._mlx_whisper.transcribe(
                audio_path,
                path_or_hf_repo=self._repo,
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
            )
            text = "".join(seg.text for seg in segments)
            return text.strip(), info.language
