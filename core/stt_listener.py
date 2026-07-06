"""
PLI STT Listener - リアルタイム音声認識
マイク入力 → VAD（音声区間検出）→ Whisper STT → コールバック

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.

使い方:
    listener = STTListener(stt_engine)
    listener.on_result = handle_result   # (text, lang) を受け取る
    listener.start()
    ...
    listener.stop()
"""

import io
import os
import shutil
import time
import wave
import struct
import tempfile
import threading
from typing import Callable, Optional
from enum import Enum

from core.logging_setup import get_logger

logger = get_logger(__name__)


class ListenerState(Enum):
    IDLE = "idle"           # 待機中
    LISTENING = "listening" # 音声検出中
    PROCESSING = "processing"  # Whisper処理中


def classify_mic_error(exc: Exception) -> str:
    """マイク入力ストリーム起動失敗の原因を分類する。

    Returns:
        "mic_denied"  — OSのマイク権限拒否（macOS プライバシー設定等）の可能性が高い
        "mic_missing" — 入力デバイスが見つからない
        ""            — 分類不能（呼び出し側で生メッセージを使う）
    """
    msg = str(exc).lower()
    missing_signs = (
        "no default input device",
        "error querying device",
        "invalid device",
        "no input device",
        "device unavailable",
        "invalid number of channels",
    )
    denied_signs = (
        "permission",
        "not permitted",
        "access denied",
        "-9986",                      # paInternalError: macOSでは大抵マイク権限拒否
        "internal portaudio error",
        "-9999",                      # paUnanticipatedHostError: CoreAudio権限系
        "unanticipated host error",
    )
    if any(s in msg for s in missing_signs):
        return "mic_missing"
    if any(s in msg for s in denied_signs):
        return "mic_denied"
    return ""


# Whisperがノイズ・無音から生成しがちな定型幻覚
# （実接見ログで「ありがとうございました」「ご視聴〜」のすり抜けを確認して拡充）
_HALLUCINATIONS = {
    "thank you", "thanks",
    "thank you for watching", "thanks for watching",
    "please subscribe", "like and subscribe",
    "you", "bye", "the end",
    "so", "oh", "um", "uh", "hmm", "okay",
    "ご視聴ありがとうございました", "チャンネル登録お願いします",
    "ありがとうございました", "ありがとうございます",
    "ご視聴ありがとうございます",
    "おやすみなさい", "ではまた", "お疲れ様でした",
}


def _is_repetition(s: str) -> bool:
    """反復幻覚を検出。

    - 「場場場場…」型: 異なり文字が極端に少ない
    - 「スライドスライドスライド…」型: 短い語句の周期繰り返し
      （(s+s).find(s,1) が最小周期を返す古典テク。周期が全長の1/3以下
      ＝3回以上の繰り返しなら幻覚と判定。実接見で発生）
    """
    stripped = s.replace(" ", "").replace("　", "")
    n = len(stripped)
    if n >= 10 and len(set(stripped)) <= 2:
        return True
    if n >= 9:
        period = (stripped + stripped).find(stripped, 1)
        if 0 < period <= n // 3:
            return True
    return False


def is_hallucination_text(text: str) -> bool:
    """STT結果がWhisper幻覚（無音・ノイズ由来の定型文/反復）かを判定する。

    日本語句読点も含めて正規化する（旧実装はASCII "." のみ剥がしており
    「〜ました。」の全角句点付き幻覚がすり抜けていた）。
    """
    if len(text) <= 1:
        return True
    text_norm = text.lower().strip().strip(".。、，…!！?？ 　")
    return text_norm in _HALLUCINATIONS or _is_repetition(text)


class STTListener:
    """マイク → VAD → Whisper のリアルタイムパイプライン"""

    def __init__(self, stt_engine=None):
        """
        Args:
            stt_engine: transcribe(audio_path) -> (text, lang) を持つSTTエンジン
        """
        self.stt = stt_engine
        self.state = ListenerState.IDLE
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # コールバック
        self.on_result: Optional[Callable[[str, str], None]] = None  # (text, lang)
        self.on_state_change: Optional[Callable[[ListenerState], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

        # 直近のマイク起動エラー
        # "mic_denied" / "mic_missing" / 生メッセージ / None(正常)
        self.last_error: Optional[str] = None

        # VAD設定
        self._sample_rate = 16000
        self._channels = 1
        self._chunk_size = 1024       # フレーム数/チャンク
        self._energy_threshold = 400   # エネルギー閾値（自動調整可）
        self._silence_duration = 0.8   # 無音判定秒数
        self._min_speech_duration = 0.3  # 最小発話秒数
        self._max_speech_duration = 30.0  # 最大発話秒数（安全弁）

        # 自動ゲイン
        self._auto_threshold = True
        self._ambient_energy = 0
        self._sensitivity_multiplier = 1.8  # 閾値 = ノイズ × この値
        self._threshold_floor = 200         # 閾値の下限（感度プリセット連動）

        # プリセット名（UI表示用）
        self._sensitivity_preset = "normal"  # "high" / "normal" / "low"
        self._tempo_preset = "normal"        # "slow" / "normal" / "fast"
        self._cleanup_stale_temp_dirs()
        self._temp_dir = tempfile.mkdtemp(prefix="pli-stt-")

    def set_sensitivity(self, preset: str):
        """マイク感度プリセット: ultra(超高感度) / high(高感度) / normal(標準) / low(低感度)

        (multiplier, floor): 閾値 = max(floor, ノイズ × multiplier)。
        床値が一律200だと、静かな接見室ではガラス越しの小声（エネルギー
        100〜180程度）が床に弾かれて全く拾えない — 実接見で発生したため
        床もプリセット連動にした。ultraはガラス壁・アクリル板越し用。
        """
        presets = {
            "ultra":  (1.1, 80),    # ガラス越し・ささやき声（誤検出は幻覚フィルタで吸収）
            "high":   (1.3, 120),   # 小声でも拾う
            "normal": (1.8, 200),   # 標準
            "low":    (2.5, 300),   # 大きい声だけ拾う（ノイズ環境）
        }
        if preset not in presets:
            return
        self._sensitivity_preset = preset
        self._sensitivity_multiplier, self._threshold_floor = presets[preset]
        # 既にキャリブレーション済みなら閾値を再計算
        if self._ambient_energy > 0:
            self._energy_threshold = max(
                self._threshold_floor,
                self._ambient_energy * self._sensitivity_multiplier)
            logger.info("STT感度変更: %s → 閾値=%.0f", preset, self._energy_threshold)

    def set_tempo(self, preset: str):
        """発話テンポプリセット: slow(ゆっくり) / normal(標準) / fast(早口)"""
        presets = {
            "slow":   {"silence": 1.2, "min_speech": 0.5},
            "normal": {"silence": 0.8, "min_speech": 0.3},
            "fast":   {"silence": 0.5, "min_speech": 0.15},
        }
        if preset not in presets:
            return
        self._tempo_preset = preset
        p = presets[preset]
        self._silence_duration = p["silence"]
        self._min_speech_duration = p["min_speech"]
        logger.info("STTテンポ変更: %s → 無音=%s秒, 最小発話=%s秒",
                    preset, self._silence_duration, self._min_speech_duration)

    def start(self):
        """リスニング開始"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """リスニング停止"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self._set_state(ListenerState.IDLE)

    def calibrate_threshold(self, duration: float = 1.0):
        """環境ノイズからエネルギー閾値を自動調整"""
        try:
            import sounddevice as sd
            import numpy as np
            energies = []
            chunks = int(self._sample_rate / self._chunk_size * duration)
            for _ in range(chunks):
                data = sd.rec(self._chunk_size, samplerate=self._sample_rate,
                              channels=self._channels, dtype='int16')
                sd.wait()
                energy = self._calc_energy(data.tobytes())
                energies.append(energy)

            if energies:
                avg = sum(energies) / len(energies)
                self._ambient_energy = avg
                # 閾値 = 環境ノイズ × 感度倍率（最低200）
                self._energy_threshold = max(self._threshold_floor, avg * self._sensitivity_multiplier)
                logger.info("STT環境ノイズ: %.0f, 閾値: %.0f (×%s)",
                            avg, self._energy_threshold, self._sensitivity_multiplier)
        except Exception as e:
            logger.warning("STTキャリブレーション失敗: %s", e)

    def _set_state(self, state: ListenerState):
        if self.state != state:
            self.state = state
            if self.on_state_change:
                self.on_state_change(state)

    def _calc_energy(self, audio_data: bytes) -> float:
        """PCM16データのRMSエネルギーを計算"""
        count = len(audio_data) // 2
        if count == 0:
            return 0
        samples = struct.unpack(f"<{count}h", audio_data)
        return (sum(s * s for s in samples) / count) ** 0.5

    def _cleanup_stale_temp_dirs(self, max_age_hours: int = 24):
        """前回クラッシュ等で残った一時音声を起動時に掃除する"""
        cutoff = time.time() - (max_age_hours * 3600)
        temp_root = tempfile.gettempdir()
        try:
            entries = os.listdir(temp_root)
        except OSError:
            return
        for name in entries:
            if not name.startswith("pli-stt-"):
                continue
            path = os.path.join(temp_root, name)
            try:
                if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass

    def _listen_loop(self):
        """メインリスニングループ"""
        try:
            import sounddevice as sd
        except ImportError:
            if self.on_error:
                self.on_error("音声入力モジュールを読み込めません。アプリの再インストールをお試しください。")
            return

        try:
            stream = sd.RawInputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype='int16',
                blocksize=self._chunk_size,
            )
            stream.start()
        except Exception as e:
            # 権限拒否/デバイス無しを分類し、構造化エラーとしてUIに渡す
            code = classify_mic_error(e)
            self.last_error = code if code else f"マイクを開けません: {e}"
            logger.error("STTマイク起動失敗 (%s): %s", code or "unknown", e)
            if self.on_error:
                self.on_error(self.last_error)
            return
        self.last_error = None

        try:
            # 自動キャリブレーション（最初の1秒）
            if self._auto_threshold:
                energies = []
                cal_chunks = int(self._sample_rate / self._chunk_size * 1.0)
                for _ in range(cal_chunks):
                    if not self._running:
                        break
                    data, overflowed = stream.read(self._chunk_size)
                    energies.append(self._calc_energy(bytes(data)))
                if energies:
                    avg = sum(energies) / len(energies)
                    self._ambient_energy = avg
                    self._energy_threshold = max(self._threshold_floor, avg * self._sensitivity_multiplier)
                    logger.info("STT自動キャリブレーション: ノイズ=%.0f, 閾値=%.0f (×%s)",
                                avg, self._energy_threshold, self._sensitivity_multiplier)

            self._set_state(ListenerState.IDLE)
            speech_buffer: list[bytes] = []
            silence_chunks = 0
            speech_start_time = 0.0
            silence_limit = int(self._silence_duration * self._sample_rate / self._chunk_size)
            min_speech_chunks = int(self._min_speech_duration * self._sample_rate / self._chunk_size)

            # プリバッファ: 発話検出前の音声を保持（出だしの切れ防止）
            from collections import deque
            _PRE_BUFFER_CHUNKS = int(0.5 * self._sample_rate / self._chunk_size)  # 0.5秒分
            pre_buffer: deque[bytes] = deque(maxlen=_PRE_BUFFER_CHUNKS)

            while self._running:
                try:
                    data, overflowed = stream.read(self._chunk_size)
                    data = bytes(data)
                except Exception:
                    continue

                energy = self._calc_energy(data)
                is_speech = energy > self._energy_threshold

                if self.state == ListenerState.IDLE:
                    if is_speech:
                        # 発話開始 — プリバッファの内容も含める（出だし保護）
                        speech_buffer = list(pre_buffer) + [data]
                        pre_buffer.clear()
                        silence_chunks = 0
                        speech_start_time = time.time()
                        self._set_state(ListenerState.LISTENING)
                    else:
                        # 待機中はプリバッファに溜める
                        pre_buffer.append(data)

                elif self.state == ListenerState.LISTENING:
                    speech_buffer.append(data)

                    if is_speech:
                        silence_chunks = 0
                    else:
                        silence_chunks += 1

                    elapsed = time.time() - speech_start_time

                    # 無音が続いた → 発話終了
                    if silence_chunks >= silence_limit:
                        if len(speech_buffer) >= min_speech_chunks:
                            self._set_state(ListenerState.PROCESSING)
                            self._process_speech(speech_buffer)
                        speech_buffer = []
                        silence_chunks = 0
                        self._set_state(ListenerState.IDLE)

                    # 安全弁: 長すぎる発話は強制処理
                    elif elapsed >= self._max_speech_duration:
                        self._set_state(ListenerState.PROCESSING)
                        self._process_speech(speech_buffer)
                        speech_buffer = []
                        silence_chunks = 0
                        self._set_state(ListenerState.IDLE)
        finally:
            # クリーンアップ
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _process_speech(self, audio_chunks: list[bytes]):
        """音声バッファをWhisperで処理"""
        if not self.stt:
            return

        # 一時WAVファイルに書き出し
        tmp_path = None
        try:
            t0 = time.time()
            raw_data = b"".join(audio_chunks)
            duration_sec = len(raw_data) / (self._sample_rate * 2)  # 16bit=2bytes
            fd, tmp_path = tempfile.mkstemp(suffix=".wav", dir=self._temp_dir)
            os.close(fd)
            with wave.open(tmp_path, 'wb') as wf:
                wf.setnchannels(self._channels)
                wf.setsampwidth(2)  # 16bit
                wf.setframerate(self._sample_rate)
                wf.writeframes(raw_data)

            # Whisper実行（monotonic: 壁時計のNTP補正で負の時間が出るのを防ぐ）
            t1 = time.monotonic()
            text, lang = self.stt.transcribe(tmp_path)
            t2 = time.monotonic()
            text = text.strip()

            # 秘匿: 認識テキスト本文はログに書かない（長さ・言語・所要時間のみ）
            logger.debug("STT 音声=%.1f秒 Whisper=%.2f秒 lang=%s text_len=%d",
                         duration_sec, t2 - t1, lang, len(text))

            # --- Whisper幻覚フィルタ（実装はモジュール関数 is_hallucination_text）---
            is_hallucination = (
                is_hallucination_text(text)
                or duration_sec < 0.3  # 0.3秒未満の音声はノイズ
            )
            if is_hallucination:
                # 秘匿: 除外テキスト本文もログに書かない（誤判定なら発話の可能性）
                logger.debug("STT幻覚フィルタ除外 text_len=%d (音声=%.1f秒)",
                             len(text), duration_sec)
            elif self.on_result:
                self.on_result(text, lang)

        except Exception as e:
            if self.on_error:
                self.on_error(f"STTエラー: {e}")
        finally:
            # 一時ファイル削除
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
