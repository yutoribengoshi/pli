"""
PLI Recorder - 録音機能
OFF / 揮発 / 保存 の3モード対応

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
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

from core.logging_setup import get_logger

logger = get_logger(__name__)


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
        self._error: Optional[str] = None

    def set_mode(self, mode: RecordMode):
        was_recording = self._recording
        if was_recording:
            self.stop()
        self.mode = mode
        if was_recording and mode != RecordMode.OFF:
            self.start()

    def set_save_dir(self, path: str):
        self._save_dir = path

    @property
    def last_error(self) -> Optional[str]:
        """直近の録音エラーメッセージ（正常時はNone）"""
        return self._error

    def start(self) -> bool:
        """録音を開始する。

        Returns:
            True: 録音開始成功（既に録音中の場合を含む）
            False: モードOFF、または録音デバイス初期化失敗（last_errorに理由を設定）
        """
        if self.mode == RecordMode.OFF:
            return False
        if self._recording:
            return True
        self._error = None
        # デバイス初期化は start() 内で同期的に行い、失敗を即座に呼び出し元へ返す。
        # 注意: 失敗時に無音ダミーへフォールバックしてはならない
        # （無音を「録音中」と偽ると、接見後に何も録れていない事故になる）。
        try:
            import sounddevice as sd
            stream = sd.RawInputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype='int16',
                blocksize=1024,
            )
            stream.start()
        except Exception as e:
            self._error = "録音デバイスを初期化できません。マイク接続と権限を確認してください。"
            logger.error("recorder: 録音開始失敗: %s", e)
            return False
        self._stream = stream
        with self._buffer_lock:
            self._buffer = io.BytesIO()
        self._recording = True
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        return True

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
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.error("recorder: close failed: %s", e)
            self._stream = None
        self._audio = None

    def _record_loop(self):
        """sounddeviceによる録音ループ（ストリームは start() で開設済み）"""
        stream = self._stream
        try:
            while self._recording and stream is not None:
                data, overflowed = stream.read(1024)
                with self._buffer_lock:
                    self._buffer.write(bytes(data))
        except Exception as e:
            # stop()/wipe() がストリームを閉じた際の例外はエラー扱いしない
            if self._recording:
                self._error = f"録音が中断されました: {e}"
                self._recording = False
                logger.error("recorder: %s", e)
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
