"""
PLI Core Interpreter - STT + 翻訳エンジン統合パイプライン
モデル未DL時はモックモードで動作

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
All rights reserved.
"""

import os
import threading
import time
from typing import Callable, Optional

from core.logging_setup import get_logger

# --- 分割モジュールからの再エクスポート（後方互換性維持） ---
from core.models import EngineType, Speaker, TranslationResult, Utterance, SyntaxChunk  # noqa: F401
from core.lang_utils import (  # noqa: F401
    SUPPORTED_LANGUAGES, NLLB_LANG_MAP,
    get_language_name, get_language_native,
    detect_unknown_words, make_translate_system, make_syntax_check_system,
)
from core.engines import MockEngine, LLMEngine, NLLBEngine, HybridEngine  # noqa: F401
from core.whisper_stt import MockSTT, WhisperSTT, detect_cpu_backend, get_available_backends  # noqa: F401

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Interpreter (統合クラス)
# ---------------------------------------------------------------------------

class Interpreter:
    """STT + LLM を統合する翻訳パイプライン"""

    def __init__(self, mock: bool = True, model_path: str = "",
                 n_ctx: int = 2048,
                 engine_type: EngineType = EngineType.MOCK,
                 nllb_model_dir: str = "",
                 whisper_model: str = ""):
        self.mock = mock
        self.target_lang = "en"  # デフォルト: 英語
        self._model_path = model_path
        self._n_ctx = n_ctx
        self._engine_type = engine_type
        self._nllb_model_dir = nllb_model_dir
        self._whisper_model = whisper_model
        self._models_ready = False  # load_models_async完了後にTrue
        self._on_models_ready: Optional[Callable] = None
        self._translation_ready = bool(mock)
        self._stt_ready = False
        self._model_load_error = ""
        self._model_load_state = "idle"
        self._state_lock = threading.Lock()  # 状態変更の排他制御

        # 初期はモックエンジンで起動（GUIブロック防止）
        # --real時は load_models_async() で差し替え
        self.engine = MockEngine()
        self.stt = MockSTT()

        self.conversation: list[Utterance] = []
        self._on_utterance: Optional[Callable] = None
        self._on_stream_token: Optional[Callable] = None
        self._paused = False

        # 固有名詞辞書（グロッサリー）
        self.glossary: list[dict] = []  # [{"ja": "...", "foreign": "..."}]
        self._load_glossary()

    @property
    def engine_type(self) -> EngineType:
        return self._engine_type

    @property
    def translation_ready(self) -> bool:
        return self._translation_ready

    @property
    def stt_ready(self) -> bool:
        return self._stt_ready

    @property
    def model_load_error(self) -> str:
        return self._model_load_error

    @property
    def model_load_state(self) -> str:
        return self._model_load_state

    @property
    def supports_syntax_check(self) -> bool:
        """現在のエンジンが構文チェックに対応しているか"""
        return not isinstance(self.engine, (NLLBEngine, HybridEngine))

    def load_models_async(self, on_ready: Optional[Callable] = None,
                          on_progress: Optional[Callable[[str, float], None]] = None):
        """GUI表示後に呼ぶ: LLM + STT をバックグラウンドでロード

        Args:
            on_ready: 全モデル準備完了時コールバック
            on_progress: 進捗コールバック (phase: str, progress: 0.0〜1.0)
                         phase = "llm" or "stt"
        """
        self._model_load_state = "loading"
        self._model_load_error = ""
        self._models_ready = False
        self._translation_ready = bool(self.mock)
        self._stt_ready = False

        if self.mock:
            # モックでもSTTだけはWhisperを使う（実際の音声認識が必要）
            def _load_stt_only():
                load_ok = True
                message = ""
                try:
                    logger.info("モックモード: Whisper STTをロード中")
                    self.stt = WhisperSTT(whisper_model=self._whisper_model)
                    with self._state_lock:
                        self._stt_ready = True
                    logger.info("Whisper STTのロード完了")
                except Exception as e:
                    load_ok = False
                    with self._state_lock:
                        self._stt_ready = False
                        self._model_load_error = f"翻訳は利用できますが、音声認識は使えません: {e}"
                    message = self._model_load_error
                    logger.warning("STTロード失敗（モックSTT継続）: %s", e)
                with self._state_lock:
                    self._models_ready = self._translation_ready and self._stt_ready
                    self._model_load_state = "ready" if load_ok else "degraded"
                if on_ready:
                    on_ready(load_ok, message)
            threading.Thread(target=_load_stt_only, daemon=True).start()
            return
        self._on_models_ready = on_ready

        def _load():
            load_errors: list[str] = []

            # --- 翻訳エンジンのロード ---
            try:
                if self._engine_type == EngineType.HYBRID:
                    self._load_hybrid(on_progress)
                elif self._engine_type == EngineType.NLLB:
                    self._load_nllb(on_progress)
                else:
                    self._load_llm(on_progress)
                with self._state_lock:
                    self._translation_ready = True
                # P0-4: HYBRIDで1モデルもロードできなかった場合（NLLBなし・
                # OPUSペアなし）は翻訳未準備として扱う（偽の「✓準備完了」防止）
                if (self._engine_type == EngineType.HYBRID
                        and not getattr(self.engine, "is_ready", True)):
                    no_model_msg = (
                        "翻訳モデルが未ダウンロードです。"
                        "メニュー「エンジン」からモデルをダウンロードしてください。"
                    )
                    with self._state_lock:
                        self._translation_ready = False
                        self._model_load_error = no_model_msg
                    load_errors.append(no_model_msg)
                    logger.warning("%s", no_model_msg)
            except Exception as e:
                with self._state_lock:
                    self._translation_ready = False
                load_errors.append(f"翻訳エンジンのロード失敗: {e}")
                logger.error("%s", load_errors[-1])

            try:
                if on_progress:
                    on_progress("stt", 0.0)
                logger.info("Whisper STTをロード中")
                self.stt = WhisperSTT(whisper_model=self._whisper_model)
                with self._state_lock:
                    self._stt_ready = True
                if on_progress:
                    on_progress("stt", 1.0)
                logger.info("Whisper STTのロード完了")
            except Exception as e:
                with self._state_lock:
                    self._stt_ready = False
                load_errors.append(f"音声認識モデルのロード失敗: {e}")
                logger.error("%s", load_errors[-1])

            with self._state_lock:
                self._models_ready = self._translation_ready and self._stt_ready
                if self._models_ready:
                    self._model_load_state = "ready"
                    self._model_load_error = ""
                elif self._translation_ready or self._stt_ready:
                    self._model_load_state = "degraded"
                    if self._translation_ready and not self._stt_ready:
                        self._model_load_error = (
                            "翻訳は利用できますが、音声認識は使えません: "
                            + " / ".join(load_errors)
                        )
                    elif self._stt_ready and not self._translation_ready:
                        self._model_load_error = (
                            "音声認識は利用できますが、翻訳エンジンは使えません: "
                            + " / ".join(load_errors)
                        )
                    else:
                        self._model_load_error = " / ".join(load_errors)
                else:
                    self._model_load_state = "error"
                    self._model_load_error = " / ".join(load_errors)
            if self._on_models_ready:
                self._on_models_ready(self._models_ready, self._model_load_error)

        threading.Thread(target=_load, daemon=True).start()

    def _load_llm(self, on_progress):
        """LLMエンジン（llama-server API方式 or llama-cpp-python フォールバック）のロード"""
        tier_name, total_gb = LLMEngine.detect_tier()
        logger.info("メモリ: %dGB → ティア: %s", total_gb, tier_name)

        if tier_name == "lite":
            logger.info("8GB以下: LLMスキップ → NLLBにフォールバック")
            self._load_nllb(on_progress)
            return

        if on_progress:
            on_progress("llm", 0.0)

        llm = LLMEngine(self._model_path, n_ctx=self._n_ctx)

        # サーバー起動（API方式を優先試行）
        if on_progress:
            on_progress("llm", 0.3)

        _llm_done = threading.Event()

        def _on_done():
            _llm_done.set()

        llm.load_model_async(on_done=_on_done)

        # 最大120秒待機（大型モデルのロードに時間がかかる）
        if not _llm_done.wait(timeout=120):
            logger.warning("LLMロードタイムアウト")

        if llm.is_ready:
            if on_progress:
                on_progress("llm", 1.0)
            self.engine = llm
            mode = "API (llama-server)" if llm._use_api else "in-process (llama-cpp-python)"
            logger.info("LLMエンジンのロード完了 (%s)", mode)
        else:
            logger.warning("LLMロード失敗: %s → NLLBにフォールバック", llm._load_error)
            self._load_nllb(on_progress)

    def _load_nllb(self, on_progress):
        """NLLBエンジン（CTranslate2）のロード"""
        logger.info("NLLBモデルをロード中: %s", self._nllb_model_dir)
        if on_progress:
            on_progress("nllb", 0.0)

        nllb = NLLBEngine(self._nllb_model_dir)
        nllb._ensure_loaded()

        if on_progress:
            on_progress("nllb", 1.0)
        self.engine = nllb
        logger.info("NLLBモデルのロード完了")

    def _load_hybrid(self, on_progress):
        """ハイブリッドエンジン（OPUS-MT + NLLB）のロード"""
        logger.info("ハイブリッドエンジンをロード中")
        if on_progress:
            on_progress("hybrid", 0.0)

        hybrid = HybridEngine(
            nllb_model_dir=self._nllb_model_dir,
            target_lang=self.target_lang,
        )

        # NLLBフォールバック + 主要OPUS-MTペアを事前ロード
        done_event = threading.Event()
        def _on_done():
            done_event.set()
        hybrid.load_model_async(on_done=_on_done)
        if not done_event.wait(timeout=120):
            raise TimeoutError("ハイブリッドエンジンの初期ロードがタイムアウトしました")

        if on_progress:
            on_progress("hybrid", 1.0)
        self.engine = hybrid
        logger.info("ハイブリッドエンジンのロード完了 (OPUS-MT: %dペア)",
                    len(hybrid.get_loaded_pairs()))

    def cleanup(self):
        """終了処理: llama-server を停止してメモリ解放"""
        if isinstance(self.engine, LLMEngine):
            self.engine.stop_server()
        elif isinstance(self.engine, HybridEngine):
            # HybridEngineの中にLLMEngineがあればそれも停止
            if hasattr(self.engine, '_llm_engine') and isinstance(self.engine._llm_engine, LLMEngine):
                self.engine._llm_engine.stop_server()

    def set_target_language(self, lang_code: str):
        """被疑者側の言語を設定"""
        self.target_lang = lang_code

    def set_callbacks(self, on_utterance=None, on_stream_token=None):
        self._on_utterance = on_utterance
        self._on_stream_token = on_stream_token

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    # ------------------------------------------------------------------
    # 固有名詞辞書（グロッサリー）
    # ------------------------------------------------------------------

    def _load_glossary(self):
        """グロッサリーを読み込み（ユーザー版優先 → 同梱版フォールバック）"""
        import json as _json
        user_path = os.path.expanduser("~/pli-models/glossary.json")
        bundled_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "glossary.json"
        )
        path = user_path if os.path.exists(user_path) else bundled_path
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
                self.glossary = data.get("entries", [])
                logger.info("グロッサリー読込: %d件 (%s)", len(self.glossary), path)
        except Exception as e:
            logger.warning("グロッサリー読込失敗: %s", e)
            self.glossary = []

    def save_glossary(self, entries: list[dict]):
        """グロッサリーを保存"""
        import json as _json
        self.glossary = entries
        user_path = os.path.expanduser("~/pli-models/glossary.json")
        os.makedirs(os.path.dirname(user_path), exist_ok=True)
        data = {"entries": entries}
        with open(user_path, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("グロッサリー保存: %d件", len(entries))

    def reload_glossary(self):
        """グロッサリーを再読み込み"""
        self._load_glossary()

    def _glossary_pre_ja_to_foreign(self, text: str) -> tuple[str, list]:
        """翻訳前: 固有名詞を直接外国語に置換（type=name のみ）

        マーカー方式はエンジンが変形するため、直接ラテン文字に置換する。
        法律用語は除外済み（glossary.jsonにはnameタイプのみ）なので
        日英混在による混乱は発生しない。

        Returns: (処理済テキスト, 置換した foreign 名のリスト)
        """
        # 秘匿: 発話本文・固有名詞はログに書かない（長さ・件数のみ）
        logger.debug("glossary前処理開始 text_len=%d glossary件数=%d",
                     len(text), len(self.glossary))
        name_entries = [e for e in self.glossary if e.get("type") == "name"]
        sorted_entries = sorted(name_entries, key=lambda e: len(e.get("ja", "")), reverse=True)

        result = text
        replaced = []
        for entry in sorted_entries:
            ja = entry.get("ja", "")
            foreign = entry.get("foreign", "")
            if not ja or not foreign:
                continue
            if ja in result:
                result = result.replace(ja, foreign)
                replaced.append(foreign)
        if replaced:
            logger.debug("glossary直接置換: %d件適用 out_len=%d",
                         len(replaced), len(result))
        return result, replaced

    def _glossary_post_ja_to_foreign(self, translated: str, replaced_names: list) -> str:
        """翻訳後: 固有名詞が正しく保持されているか確認し、誤訳があれば修正"""
        if not replaced_names:
            return translated
        result = translated
        for name in replaced_names:
            if name.lower() in result.lower():
                # 秘匿: 固有名詞そのものはログに書かない
                logger.debug("glossary後処理: 固有名詞は訳文に保持 OK")
                continue
            # 名前が訳文に無い → エンジンが誤訳した → 誤訳名を探して強制置換
            logger.debug("glossary後処理: 固有名詞が訳文に無い → 強制置換を試行")
            result = self._force_replace_name(result, name)
        return result

    def _force_replace_name(self, translated: str, correct_name: str) -> str:
        """訳文中の誤った固有名詞を正しい名前に置換"""
        import re as _re
        common = {"I", "Mr", "Mrs", "Ms", "Dr", "My", "The", "A", "An", "He",
                  "She", "It", "We", "They", "This", "That", "His", "Her",
                  "Your", "Our", "Their", "Am", "Is", "Are", "Was", "Were",
                  "Do", "Does", "Did", "Have", "Has", "Had", "Will", "Would",
                  "Can", "Could", "May", "Might", "Shall", "Should", "Not",
                  "So", "But", "And", "Or", "If", "As", "At", "By", "For",
                  "In", "Of", "On", "To", "Up", "No", "Yes"}
        pattern = r'(?:Mr\.?\s+|Mrs\.?\s+|Ms\.?\s+)?(?:[A-Z][a-z\-]+(?:\s+[A-Z][a-z\-]+)*)'
        matches = list(_re.finditer(pattern, translated))
        for m in reversed(matches):
            candidate = m.group()
            words = candidate.split()
            non_common = [w.rstrip('.') for w in words if w.rstrip('.') not in common]
            if len(non_common) >= 1:
                prefix = ""
                if words[0].rstrip('.') in ("Mr", "Mrs", "Ms", "Dr"):
                    prefix = words[0] + " "
                translated = translated[:m.start()] + prefix + correct_name + translated[m.end():]
                # 秘匿: 置換前後の固有名詞はログに書かない
                logger.debug("glossary強制置換: 実行 (candidate_len=%d)", len(candidate))
                break
        return translated

    def _apply_glossary_foreign_to_ja(self, text: str) -> str:
        """翻訳前: 外国語テキスト中のグロッサリー語句を直接日本語に置換"""
        result = text
        replaced_count = 0
        sorted_entries = sorted(self.glossary, key=lambda e: len(e.get("foreign", "")), reverse=True)
        for entry in sorted_entries:
            ja = entry.get("ja", "")
            foreign = entry.get("foreign", "")
            if not ja or not foreign:
                continue
            # 大文字小文字を無視して検索・置換
            lower_result = result.lower()
            lower_foreign = foreign.lower()
            pos = lower_result.find(lower_foreign)
            while pos >= 0:
                result = result[:pos] + ja + result[pos + len(foreign):]
                replaced_count += 1
                lower_result = result.lower()
                pos = lower_result.find(lower_foreign)
        if replaced_count:
            # 秘匿: 語句そのものはログに書かない
            logger.debug("glossary置換 (foreign→ja): %d件適用", replaced_count)
        return result

    def translate_attorney(self, japanese_text: str):
        """弁護人の日本語発言を被疑者の言語に翻訳（ストリーミング）"""
        utt = Utterance(
            speaker=Speaker.ATTORNEY,
            original=japanese_text,
            timestamp=time.strftime("%H:%M"),
        )

        def on_token(token):
            utt.translated += token
            if self._on_stream_token:
                self._on_stream_token(utt, token)

        tgt = self.target_lang

        # グロッサリー前処理: 固有名詞をマーカーに置換
        processed_text, glossary_map = self._glossary_pre_ja_to_foreign(japanese_text)
        # 秘匿: 入力本文はログに書かない（言語・長さのみ）
        logger.debug("translate ja->%s len=%d", tgt, len(processed_text))

        def run():
            # 中間言語情報を取得してからストリーミング
            if hasattr(self.engine, "translate_detail"):
                result = self.engine.translate_detail(
                    processed_text, "ja", tgt
                )
                # 秘匿: 訳文本文はログに書かない
                logger.debug("エンジン出力 len=%d", len(result.final_text))
                # グロッサリー後処理: マーカーを正しい固有名詞に置換
                final = self._glossary_post_ja_to_foreign(
                    result.final_text, glossary_map
                )
                # 不明語検出
                marked, unknowns = detect_unknown_words(
                    japanese_text, final, "ja", tgt,
                )
                utt.translated = marked
                utt.intermediate_en = result.intermediate_en
                utt.translation_route = result.route
                utt.unknown_words = unknowns
                # ストリーミング通知（全文を1回で送出）
                if self._on_stream_token:
                    self._on_stream_token(utt, marked)
            else:
                self.engine.translate_stream(
                    processed_text, "ja", tgt, on_token
                )
                # 秘匿: 訳文本文はログに書かない
                logger.debug("ストリームエンジン出力 len=%d", len(utt.translated))
                # グロッサリー後処理
                final = self._glossary_post_ja_to_foreign(
                    utt.translated, glossary_map
                )
                # ストリーム完了後に不明語検出
                marked, unknowns = detect_unknown_words(
                    japanese_text, final, "ja", tgt,
                )
                utt.translated = marked
                utt.unknown_words = unknowns
            utt.confirmed = True
            self.conversation.append(utt)
            if self._on_utterance:
                self._on_utterance(utt)

        threading.Thread(target=run, daemon=True).start()

    def translate_defendant(self, foreign_text: str) -> Utterance:
        """被疑者の発言を日本語に翻訳（同期）— 中間言語・経路・不明語も記録"""
        # グロッサリー前処理: 外国語の固有名詞を直接日本語に置換
        processed_text = self._apply_glossary_foreign_to_ja(foreign_text)

        if hasattr(self.engine, "translate_detail"):
            result = self.engine.translate_detail(
                processed_text, self.target_lang, "ja"
            )
            # 不明語検出 → 訳文にマーク
            marked, unknowns = detect_unknown_words(
                foreign_text, result.final_text,
                self.target_lang, "ja",
            )
            utt = Utterance(
                speaker=Speaker.DEFENDANT,
                original=foreign_text,
                translated=marked,
                intermediate_en=result.intermediate_en,
                translation_route=result.route,
                unknown_words=unknowns,
                timestamp=time.strftime("%H:%M"),
            )
        else:
            raw = self.engine.translate(
                processed_text, self.target_lang, "ja"
            )
            marked, unknowns = detect_unknown_words(
                foreign_text, raw, self.target_lang, "ja",
            )
            utt = Utterance(
                speaker=Speaker.DEFENDANT,
                original=foreign_text,
                translated=marked,
                unknown_words=unknowns,
                timestamp=time.strftime("%H:%M"),
            )
        return utt

    def confirm_utterance(self, utt: Utterance):
        """弁護人がOKを押して確定"""
        utt.confirmed = True
        if utt not in self.conversation:
            self.conversation.append(utt)

    def syntax_check(self, foreign_text: str) -> list[SyntaxChunk]:
        """構文反転チェック"""
        return self.engine.syntax_check(foreign_text, self.target_lang)

    def reconstruct(self, chunks: list[SyntaxChunk]) -> str:
        """修正された対訳から英文再構成"""
        return self.engine.reconstruct(chunks)

    def retranslate(self, foreign_text: str) -> str:
        """修正後の外国語文を日本語に再翻訳"""
        return self.engine.translate(foreign_text, self.target_lang, "ja")

    def save_conversation(self, path: str):
        """会話ログをJSON保存（原文・英語中間文・翻訳・経路・不明語すべて含む）"""
        import json
        # セッション全体の不明語を集約
        all_unknowns: list[dict] = []
        for u in self.conversation:
            for w in u.unknown_words:
                all_unknowns.append({
                    "word": w,
                    "timestamp": u.timestamp,
                    "speaker": u.speaker.value,
                    "context": u.original[:60],
                })
        data = {
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "target_lang": self.target_lang,
            "engine_type": self.engine_type.value
                if hasattr(self, "engine_type") else "unknown",
            "utterances": [u.to_dict() for u in self.conversation],
            "unknown_words_summary": all_unknowns,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def export_conversation_text(self, path: str):
        """会話ログをテキスト形式でエクスポート（3段表示＋不明語一覧）"""
        lines: list[str] = []
        lines.append(f"=== PLI 通訳記録 ===")
        lines.append(f"保存日時: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"対象言語: {self.target_lang}")
        lines.append("=" * 50)
        lines.append("")
        all_unknowns: list[tuple[str, str, str]] = []  # (word, time, context)
        for u in self.conversation:
            tag = "弁護人" if u.speaker == Speaker.ATTORNEY else "相手"
            lines.append(f"[{u.timestamp}] {tag}")
            lines.append(f"  原文: {u.original}")
            if u.intermediate_en:
                lines.append(f"  英語: {u.intermediate_en}")
            lines.append(f"  訳文: {u.translated}")
            if u.translation_route:
                lines.append(f"  経路: {u.translation_route}")
            if u.unknown_words:
                lines.append(f"  ⚠ 不明語: {', '.join(u.unknown_words)}")
                for w in u.unknown_words:
                    all_unknowns.append((w, u.timestamp, u.original[:60]))
            lines.append("")
        # 末尾に不明語一覧
        if all_unknowns:
            lines.append("=" * 50)
            lines.append("【不明語一覧】")
            lines.append(f"  合計: {len(all_unknowns)} 語")
            lines.append("")
            seen = set()
            for word, ts, ctx in all_unknowns:
                if word not in seen:
                    seen.add(word)
                    lines.append(f"  ・{word}")
                    lines.append(f"    初出: [{ts}] {ctx}")
                    lines.append(f"    意味: ________________（後日記入）")
                    lines.append("")
            lines.append("=" * 50)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def clear_conversation(self):
        """会話ログ全消去"""
        self.conversation.clear()
