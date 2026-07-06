"""
PLI SessionController - セッション制御ロジック（UI非依存）
翻訳パイプライン・STT制御・録音制御・セッション管理を統合

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
All rights reserved.
"""

import queue
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable, Optional

from core.interpreter import Interpreter, Utterance, Speaker, detect_unknown_words
from core.logging_setup import get_logger
from core.recorder import Recorder, RecordMode

logger = get_logger(__name__)


def decide_is_attorney(text: str, lang: str, target_lang: str) -> bool:
    """STT結果の話者（弁護人=日本語話者か）を判定する。

    設計: Whisperの言語自動判定は実接見で約10%誤爆する（日本語がen/ko/es/zh等と
    誤検出され、翻訳が逆方向に走る事故が43/386発話で発生）。日本語はかな・漢字と
    いう固有の文字体系を持つため、**認識テキストの文字種を主signal**とし、
    Whisperのlangは補助にのみ使う。

    Args:
        text: STT認識テキスト
        lang: Whisperの言語判定（補助signal）
        target_lang: セッションの相手言語（例 "en"）
    """
    if not text:
        return lang == "ja"

    n = len(text)
    kana = sum(1 for c in text if "぀" <= c <= "ヿ" or "･" <= c <= "ﾟ")
    cjk = sum(1 for c in text if "一" <= c <= "鿿")

    if target_lang == "zh":
        # 漢字は日中で共有 → 日本語固有のかなの有無で判定。
        # かなゼロの純漢字列（稀）だけWhisper langに委ねる
        if kana > 0:
            return True
        if cjk / n > 0.3:
            return lang == "ja"
        return False

    # 相手言語が非漢字圏（en/vi/es/pt/ur/tl等）: かな+漢字の比率で判定。
    # 日本語の実発話は助詞・送り仮名で必ずかなを含むため、この閾値で
    # ja↔en系の取り違えはほぼ起きない
    return (kana + cjk) / n > 0.3


# ---------------------------------------------------------------------------
# TranslationJob — 翻訳ジョブ定義
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TranslationJob:
    """翻訳キュー投入用のジョブ。
    kind: "manual_attorney" | "stt_attorney" | "defendant"
    """
    job_id: int
    session_token: int
    kind: str
    text: str


# ---------------------------------------------------------------------------
# SessionController — UI非依存のセッション制御
# ---------------------------------------------------------------------------

class SessionController:
    """AttorneyWindowから抽出した中央ロジック。

    PySide6 に一切依存しない。UI との通信は全てコールバック経由。

    コールバック一覧 (set_callbacks で設定):
        on_status_message(message: str, timeout_ms: int)
        on_attorney_translated(utt: Utterance)
        on_manual_attorney_translated(request_id: int, utt: Utterance)
        on_manual_attorney_failed(request_id: int, error: str)
        on_attorney_translation_failed(original: str, error: str)
        on_defendant_translated(utt: Utterance)
        on_interpreter_stream_token(utt: Utterance, token: str)
        on_interpreter_utterance(utt: Utterance)
        on_stt_toggled(active: bool)
        on_stt_sensitivity_changed(preset: str)
        on_stt_tempo_changed(preset: str)
        on_stt_state_change(state_name: str)
        on_stt_mode_label_update(mode: str, lang_mode: str)
        on_rec_mode_change(mode: RecordMode)
        on_rec_size_update(size_mb: float)
        on_session_reset(session_number: int)
        on_send_to_defendant(kind: str, text: str)
        on_stream_to_defendant(token: str)
        on_finish_defendant_stream()
        on_clear_defendant()
        on_translation_not_available(message: str)
    """

    def __init__(self, interpreter: Interpreter, recorder: Recorder):
        self.interpreter = interpreter
        self.recorder = recorder

        # ----- 翻訳パイプライン状態 -----
        self._translation_job_seq = 0
        self._translation_session_token = 0
        self._translation_state_lock = threading.Lock()
        self._cancelled_translation_job_ids: set[int] = set()
        self._translation_queue: queue.Queue[TranslationJob | None] = queue.Queue()
        self._translation_worker: Optional[threading.Thread] = None

        # ----- STT 状態 -----
        self._stt_active = False
        self._stt_lang_mode = "auto"  # "auto" / "attorney" / "defendant"

        # ----- セッション状態 -----
        self._session_count = 1

        # ----- コールバック -----
        self._cb_status_message: Optional[Callable] = None
        self._cb_attorney_translated: Optional[Callable] = None
        self._cb_manual_attorney_translated: Optional[Callable] = None
        self._cb_manual_attorney_failed: Optional[Callable] = None
        self._cb_attorney_translation_failed: Optional[Callable] = None
        self._cb_defendant_translated: Optional[Callable] = None
        self._cb_interpreter_stream_token: Optional[Callable] = None
        self._cb_interpreter_utterance: Optional[Callable] = None
        self._cb_stt_toggled: Optional[Callable] = None
        self._cb_stt_sensitivity_changed: Optional[Callable] = None
        self._cb_stt_tempo_changed: Optional[Callable] = None
        self._cb_stt_state_change: Optional[Callable] = None
        self._cb_stt_mode_label_update: Optional[Callable] = None
        self._cb_rec_mode_change: Optional[Callable] = None
        self._cb_rec_size_update: Optional[Callable] = None
        self._cb_session_reset: Optional[Callable] = None
        self._cb_send_to_defendant: Optional[Callable] = None
        self._cb_stream_to_defendant: Optional[Callable] = None
        self._cb_finish_defendant_stream: Optional[Callable] = None
        self._cb_clear_defendant: Optional[Callable] = None
        self._cb_translation_not_available: Optional[Callable] = None

    # ------------------------------------------------------------------
    # コールバック登録
    # ------------------------------------------------------------------

    def set_callbacks(self, **kwargs):
        """コールバックを一括登録。

        Usage::

            ctrl.set_callbacks(
                on_status_message=lambda msg, ms: ...,
                on_attorney_translated=lambda utt: ...,
            )
        """
        prefix = "on_"
        for name, fn in kwargs.items():
            attr = f"_cb_{name[len(prefix):]}" if name.startswith(prefix) else f"_cb_{name}"
            if hasattr(self, attr):
                setattr(self, attr, fn)
            else:
                raise ValueError(f"Unknown callback: {name}")

    def _emit_status(self, message: str, timeout_ms: int = 0):
        if self._cb_status_message:
            self._cb_status_message(message, timeout_ms)

    # ------------------------------------------------------------------
    # 翻訳パイプライン
    # ------------------------------------------------------------------

    def start_translation_worker(self):
        """翻訳ワーカースレッドを起動。"""
        worker = threading.Thread(target=self._translation_worker_loop, daemon=True)
        worker.start()
        self._translation_worker = worker

    def stop_translation_worker(self):
        """翻訳ワーカーを停止。"""
        self._translation_queue.put(None)
        if self._translation_worker and self._translation_worker.is_alive():
            self._translation_worker.join(timeout=5)

    def _next_translation_job(self, kind: str, text: str) -> TranslationJob:
        with self._translation_state_lock:
            self._translation_job_seq += 1
            return TranslationJob(
                job_id=self._translation_job_seq,
                session_token=self._translation_session_token,
                kind=kind,
                text=text,
            )

    def enqueue_translation_job(self, kind: str, text: str) -> TranslationJob:
        """翻訳ジョブをキューに投入して返す。"""
        job = self._next_translation_job(kind, text)
        self._translation_queue.put(job)
        return job

    def is_translation_job_active(self, job: TranslationJob) -> bool:
        with self._translation_state_lock:
            return (
                job.session_token == self._translation_session_token
                and job.job_id not in self._cancelled_translation_job_ids
            )

    def cancel_translation_job(self, job_id: int):
        with self._translation_state_lock:
            self._cancelled_translation_job_ids.add(job_id)

    def invalidate_translation_jobs(self):
        """全ジョブ無効化（セッションリセット時）。"""
        with self._translation_state_lock:
            self._translation_session_token += 1
            self._cancelled_translation_job_ids.clear()

    def translate_attorney_text(self, text: str) -> Utterance:
        """弁護人テキストを翻訳して Utterance を返す（ワーカースレッドから呼ばれる）。"""
        utt = Utterance(
            speaker=Speaker.ATTORNEY,
            original=text,
            timestamp=time.strftime("%H:%M"),
        )
        tgt = self.interpreter.target_lang
        # 秘匿: 発話本文はログに書かない（長さ・言語のみ）
        logger.debug("attorney翻訳開始 len=%d tgt=%s", len(text), tgt)

        processed_text, glossary_map = self.interpreter._glossary_pre_ja_to_foreign(text)
        if glossary_map:
            logger.debug("attorney glossary前処理: %d件置換 out_len=%d",
                         len(glossary_map), len(processed_text))

        if hasattr(self.interpreter.engine, "translate_detail"):
            result = self.interpreter.engine.translate_detail(processed_text, "ja", tgt)
            final_text = self.interpreter._glossary_post_ja_to_foreign(
                result.final_text, glossary_map
            )
            marked, unknowns = detect_unknown_words(text, final_text, "ja", tgt)
            utt.translated = marked
            utt.intermediate_en = result.intermediate_en
            utt.translation_route = result.route
            utt.unknown_words = unknowns
        else:
            raw = self.interpreter.engine.translate(processed_text, "ja", tgt)
            raw = self.interpreter._glossary_post_ja_to_foreign(raw, glossary_map)
            utt.translated = raw

        # 秘匿: 訳文本文はログに書かない
        logger.debug("attorney翻訳完了 translated_len=%d", len(utt.translated))
        return utt

    def _translation_worker_loop(self):
        """翻訳ワーカーのメインループ。"""
        while True:
            job = self._translation_queue.get()
            try:
                if job is None:
                    return
                if not self.is_translation_job_active(job):
                    continue

                if job.kind in ("manual_attorney", "stt_attorney"):
                    utt = self.translate_attorney_text(job.text)
                    if not self.is_translation_job_active(job):
                        continue
                    if job.kind == "manual_attorney":
                        if self._cb_manual_attorney_translated:
                            self._cb_manual_attorney_translated(job.job_id, utt)
                    else:
                        if self._cb_attorney_translated:
                            self._cb_attorney_translated(utt)
                elif job.kind == "defendant":
                    try:
                        utt = self.interpreter.translate_defendant(job.text)
                    except Exception as e:
                        utt = Utterance(
                            speaker=Speaker.DEFENDANT,
                            original=job.text,
                            translated=f"(翻訳エラー: {job.text})",
                            timestamp=time.strftime("%H:%M"),
                        )
                        logger.error("defendant翻訳エラー: %s", e)
                    if not self.is_translation_job_active(job):
                        continue
                    if self._cb_defendant_translated:
                        self._cb_defendant_translated(utt)
                else:
                    logger.warning("不明な翻訳ジョブ種別: %s", job.kind)
            except Exception as e:
                if not isinstance(job, TranslationJob) or not self.is_translation_job_active(job):
                    continue
                if job.kind == "manual_attorney":
                    if self._cb_manual_attorney_failed:
                        self._cb_manual_attorney_failed(job.job_id, str(e))
                elif job.kind == "stt_attorney":
                    if self._cb_attorney_translation_failed:
                        self._cb_attorney_translation_failed(job.text, str(e))
                elif job.kind == "defendant":
                    utt = Utterance(
                        speaker=Speaker.DEFENDANT,
                        original=job.text,
                        translated=f"(翻訳エラー: {job.text})",
                        timestamp=time.strftime("%H:%M"),
                    )
                    if self._cb_defendant_translated:
                        self._cb_defendant_translated(utt)
            finally:
                if isinstance(job, TranslationJob):
                    with self._translation_state_lock:
                        self._cancelled_translation_job_ids.discard(job.job_id)
                self._translation_queue.task_done()

    def ensure_translation_available(self) -> bool:
        """翻訳エンジンが利用可能かチェック。不可の場合コールバックで通知。"""
        if self.interpreter.translation_ready:
            return True
        if self.interpreter.model_load_state == "loading":
            message = "翻訳エンジン読込中 -- まだ送信できません"
        elif self.interpreter.model_load_error:
            message = self.interpreter.model_load_error
        else:
            message = "翻訳エンジンが利用できません"
        if self._cb_translation_not_available:
            self._cb_translation_not_available(message)
        return False

    # ------------------------------------------------------------------
    # Interpreter コールバック
    # ------------------------------------------------------------------

    def setup_interpreter_callbacks(self):
        """Interpreter に stream / utterance コールバックを設定。

        UIスレッドへの受け渡しは UI 側が行う（Qt Signal 等）。
        ここではコントローラのコールバックを中継する。
        """
        def on_stream_token(utt: Utterance, token: str):
            if self._cb_interpreter_stream_token:
                self._cb_interpreter_stream_token(utt, token)

        def on_utterance(utt: Utterance):
            if self._cb_interpreter_utterance:
                self._cb_interpreter_utterance(utt)

        self.interpreter.set_callbacks(
            on_utterance=on_utterance,
            on_stream_token=on_stream_token,
        )

    # ------------------------------------------------------------------
    # STT 制御
    # ------------------------------------------------------------------

    @property
    def stt_active(self) -> bool:
        return self._stt_active

    @property
    def stt_lang_mode(self) -> str:
        return self._stt_lang_mode

    def toggle_stt(self) -> bool:
        """STT ON/OFF トグル。成功時は新しい状態を返す。

        Returns:
            切替後の active 状態。モデル未準備時は False のまま。
        """
        if not self._stt_active and not self.interpreter._models_ready:
            if (self.interpreter.model_load_state in ("error", "degraded")
                    and self.interpreter.model_load_error):
                self._emit_status(self.interpreter.model_load_error, 6000)
            else:
                self._emit_status("モデル読込中 -- 音声認識はまだ使えません", 3000)
            return False

        self._stt_active = not self._stt_active

        if self._stt_active:
            self._emit_status("音声認識 ON -- マイク待機中")
        else:
            self._emit_status("音声認識 OFF")

        if self._cb_stt_toggled:
            self._cb_stt_toggled(self._stt_active)
        if self._cb_stt_mode_label_update:
            self._cb_stt_mode_label_update("toggle", self._stt_lang_mode)
        return self._stt_active

    def set_stt_lang_mode(self, mode: str):
        """STT言語モード切替: auto / attorney / defendant"""
        self._stt_lang_mode = mode
        labels = {"auto": "自動判定", "attorney": "弁護人入力", "defendant": "相手入力"}
        self._emit_status(f"言語モード: {labels.get(mode, mode)}", 3000)
        if self._cb_stt_mode_label_update:
            self._cb_stt_mode_label_update("mode_change", self._stt_lang_mode)

    def set_stt_sensitivity(self, preset: str):
        """マイク感度プリセット切替"""
        labels = {"ultra": "超高感度", "high": "高感度", "normal": "標準", "low": "低感度"}
        self._emit_status(f"マイク感度: {labels.get(preset, preset)}", 3000)
        if self._cb_stt_sensitivity_changed:
            self._cb_stt_sensitivity_changed(preset)

    def set_stt_tempo(self, preset: str):
        """発話テンポプリセット切替"""
        labels = {"slow": "ゆっくり", "normal": "標準", "fast": "早口"}
        self._emit_status(f"発話テンポ: {labels.get(preset, preset)}", 3000)
        if self._cb_stt_tempo_changed:
            self._cb_stt_tempo_changed(preset)

    def on_stt_result(self, text: str, lang: str):
        """STTリスナーからの結果を処理。

        弁護人/被疑者を判定し、対応する翻訳パイプラインに投入する。
        """
        if not text.strip():
            return

        mode = self._stt_lang_mode
        if mode == "attorney":
            is_attorney = True
        elif mode == "defendant":
            is_attorney = False
        else:
            # AUTO: 文字種を主signalに判定（Whisper langの約10%誤爆対策。
            # 実接見でja発話がen/ko/es等と誤検出→逆方向翻訳になる事故を修正）
            tgt = self.interpreter.target_lang
            is_attorney = decide_is_attorney(text, lang, tgt)
            # 秘匿: 認識テキスト本文はログに書かない
            logger.debug("STT自動判定 lang=%s target=%s is_attorney=%s len=%d",
                         lang, tgt, is_attorney, len(text))

        if is_attorney:
            logger.debug("STT -> attorney speech len=%d", len(text))
            self.process_attorney_speech(text)
        else:
            logger.debug("STT -> defendant speech len=%d", len(text))
            self.process_defendant_speech(text)

    def on_stt_state_change(self, state_name: str):
        """STTリスナーの状態変更を通知。"""
        if not self._stt_active:
            return
        if self._cb_stt_state_change:
            self._cb_stt_state_change(state_name)

    # ------------------------------------------------------------------
    # 発話処理（翻訳キュー投入）
    # ------------------------------------------------------------------

    def process_defendant_speech(self, text: str):
        """被疑者発言を非同期翻訳キューに投入。"""
        if not self.ensure_translation_available():
            return
        self._emit_status("翻訳中...")
        if self._cb_send_to_defendant:
            self._cb_send_to_defendant("defendant_echo", text)
        self.enqueue_translation_job("defendant", text)

    def process_attorney_speech(self, text: str):
        """弁護人STT発言を非同期翻訳キューに投入。"""
        if not self.ensure_translation_available():
            return
        self._emit_status("文字起こし完了 -- 翻訳中...")
        self.enqueue_translation_job("stt_attorney", text)

    # ------------------------------------------------------------------
    # 録音制御
    # ------------------------------------------------------------------

    def set_rec_mode(self, mode: RecordMode):
        """録音モード切替。録音開始に失敗した場合はOFFへ戻してエラーを通知する。"""
        self.recorder.set_mode(mode)
        if mode != RecordMode.OFF and not self.recorder.start():
            # 録音できていないのに「REC」を表示してはならない（録れてたつもり事故防止）
            error = self.recorder.last_error or "録音を開始できません"
            self.recorder.set_mode(RecordMode.OFF)
            self._emit_status(f"録音エラー: {error}")
            if self._cb_rec_mode_change:
                self._cb_rec_mode_change(RecordMode.OFF)
            return
        if mode == RecordMode.OFF:
            self._emit_status("待機中")
        elif mode == RecordMode.VOLATILE:
            self._emit_status("REC (揮発)")
        elif mode == RecordMode.SAVE:
            self._emit_status("REC (保存)")
        if self._cb_rec_mode_change:
            self._cb_rec_mode_change(mode)

    def update_rec_size(self):
        """録音バッファサイズを更新通知。"""
        if self.recorder.mode != RecordMode.OFF:
            size = self.recorder.get_buffer_size_mb()
        else:
            size = 0.0
        if self._cb_rec_size_update:
            self._cb_rec_size_update(size)

    # ------------------------------------------------------------------
    # セッション管理
    # ------------------------------------------------------------------

    @property
    def session_count(self) -> int:
        return self._session_count

    def end_session(self):
        """セッションを終了し新セッションを開始。"""
        self.interpreter.clear_conversation()
        self.recorder.wipe()
        self.clear_session_state()
        self._session_count += 1
        self._emit_status("新セッション")
        if self._cb_session_reset:
            self._cb_session_reset(self._session_count)

    def clear_session_state(self):
        """翻訳ジョブ無効化。UI側の clear_logs から呼ばれることを想定。"""
        self.invalidate_translation_jobs()
        if self._cb_clear_defendant:
            self._cb_clear_defendant()

    def wipe_all(self, delete_saved_recordings: bool = False):
        """全データ消去。"""
        self.interpreter.clear_conversation()
        self.recorder.wipe(delete_saved_files=delete_saved_recordings)
        self.clear_session_state()

    def save_conversation_json(self, path: str):
        """会話記録をJSON形式で保存。

        Raises:
            ValueError: 会話が空の場合
            Exception: ファイル書き込みエラー
        """
        if not self.interpreter.conversation:
            raise ValueError("保存する会話がありません")
        self.interpreter.save_conversation(path)
        self._emit_status(f"保存完了: {path}")

    def save_conversation_text(self, path: str):
        """会話記録をテキスト形式でエクスポート。

        Raises:
            ValueError: 会話が空の場合
            Exception: ファイル書き込みエラー
        """
        if not self.interpreter.conversation:
            raise ValueError("保存する会話がありません")
        self.interpreter.export_conversation_text(path)
        self._emit_status(f"エクスポート完了: {path}")

    @property
    def has_conversation(self) -> bool:
        return bool(self.interpreter.conversation)
