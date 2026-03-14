"""
PLI Recorder - 録音機能
OFF / 揮発 / 保存 の3モード対応

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""

import io
import os
import time
import wave
import struct
import threading
from enum import Enum
from typing import Optional


class RecordMode(Enum):
    OFF = "off"
    VOLATILE = "volatile"   # RAM上のみ
    SAVE = "save"           # ファイル保存


class Recorder:
    """録音管理クラス"""

    def __init__(self):
        self.mode = RecordMode.OFF
        self._buffer: io.BytesIO = io.BytesIO()   # 揮発用RAMバッファ
        self._buffer_lock = threading.Lock()
        self._recording = False
        self._stream = None
        self._audio = None
        self._thread: Optional[threading.Thread] = None
        self._save_dir = os.path.expanduser("~/pli-recordings")
        self._saved_files: list[str] = []
        self._sample_rate = 16000
        self._channels = 1

    def set_mode(self, mode: RecordMode):
        was_recording = self._recording
        if was_recording:
            self.stop()
        self.mode = mode
        if was_recording and mode != RecordMode.OFF:
            self.start()

    def set_save_dir(self, path: str):
        self._save_dir = path

    def start(self):
        if self.mode == RecordMode.OFF or self._recording:
            return
        self._recording = True
        with self._buffer_lock:
            self._buffer = io.BytesIO()
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_recording_thread()
        if self.mode == RecordMode.SAVE and self.get_buffer_size_mb() > 0:
            self._save_to_file()

    def _stop_recording_thread(self, timeout: float = 2.0):
        """録音スレッドを停止し、音声デバイスを解放する"""
        self._recording = False
        self._close_audio_handles()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        self._close_audio_handles()

    def _close_audio_handles(self):
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._audio:
            try:
                self._audio.terminate()
            except Exception:
                pass
            self._audio = None

    def _record_loop(self):
        """PyAudioによる録音ループ"""
        try:
            import pyaudio
            self._audio = pyaudio.PyAudio()
            self._stream = self._audio.open(
                format=pyaudio.paInt16,
                channels=self._channels,
                rate=self._sample_rate,
                input=True,
                frames_per_buffer=1024,
            )
            while self._recording:
                data = self._stream.read(1024, exception_on_overflow=False)
                with self._buffer_lock:
                    self._buffer.write(data)
        except ImportError:
            # PyAudio未インストール時はダミー録音
            while self._recording:
                # 無音データを生成
                silence = b'\x00\x00' * 1024
                with self._buffer_lock:
                    self._buffer.write(silence)
                time.sleep(1024 / self._sample_rate)
        except Exception:
            pass
        finally:
            self._close_audio_handles()

    def _save_to_file(self):
        """M4AファイルとしてRAMバッファを保存（WAVで一旦保存）"""
        os.makedirs(self._save_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        # まずWAVで保存（M4A変換はffmpegで後から可能）
        wav_path = os.path.join(self._save_dir, f"pli_session_{timestamp}.wav")

        with self._buffer_lock:
            self._buffer.seek(0)
            raw_data = self._buffer.read()
        if not raw_data:
            return None

        with wave.open(wav_path, 'wb') as wf:
            wf.setnchannels(self._channels)
            wf.setsampwidth(2)  # 16bit
            wf.setframerate(self._sample_rate)
            wf.writeframes(raw_data)

        self._saved_files.append(wav_path)
        return wav_path

    def purge_saved_files(self):
        """このプロセスで保存した録音ファイルを削除する"""
        remaining: list[str] = []
        for path in self._saved_files:
            if not path:
                continue
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                remaining.append(path)
        self._saved_files = remaining

    def wipe(self, delete_saved_files: bool = False):
        """即時消去（パニックボタン用）"""
        self._stop_recording_thread()
        # バッファをゼロで上書きしてから解放
        with self._buffer_lock:
            size = self._buffer.tell()
            self._buffer.seek(0)
            self._buffer.write(b'\x00' * size)
            self._buffer = io.BytesIO()
        if delete_saved_files:
            self.purge_saved_files()

    def get_buffer_size_mb(self) -> float:
        """現在のバッファサイズ(MB)"""
        with self._buffer_lock:
            return self._buffer.tell() / (1024 * 1024)
