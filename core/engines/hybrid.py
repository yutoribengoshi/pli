"""
PLI Hybrid Engine - OPUS-MT専用ペア + NLLB汎用フォールバック
Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""

import os
import re
import time
import threading
from typing import Callable, Optional

from core.models import SyntaxChunk, TranslationResult
from core.engines.nllb import NLLBEngine


class HybridEngine:
    """OPUS-MT (言語ペア専用) + NLLB (汎用フォールバック) のハイブリッドエンジン

    32GB以上のRAM環境で最高精度を実現。
    - OPUS-MT: 言語ペア専用モデル（そのペアだけで訓練 → 高精度）
    - NLLB: OPUS-MTにないペアのフォールバック（200言語対応）

    遅延ロード: 言語ペアのモデルは初回使用時にロード。
    """

    def __init__(self, nllb_model_dir: str, target_lang: str = "en"):
        self._nllb_model_dir = nllb_model_dir
        self._target_lang = target_lang
        self._opus_models: dict[str, object] = {}   # {pair_key: ct2.Translator}
        self._opus_tokenizers: dict[str, object] = {}
        self._nllb_engine: Optional[NLLBEngine] = None
        self._load_error: Optional[str] = None
        self._lock = threading.Lock()
        # マルチリンガルOPUS-MT (mul-en / en-mul) 少数言語対応
        self._mul_models: dict[str, object] = {}       # {"mul-en": ct2.Translator, ...}
        self._mul_tokenizers: dict[str, object] = {}
        # NLLB HuggingFace 直接ロード (en→ja等、OPUS-MTが低品質なペア用)
        self._nllb_hf_model = None
        self._nllb_hf_tokenizer = None
        # OPUS-MT品質問題のあるペア → NLLBにフォールバック
        self._opus_blacklist: set[str] = {"en-ja"}  # en-jap = 聖書翻訳モデル

    def _get_opus_pair_key(self, src: str, tgt: str) -> str:
        return f"{src}-{tgt}"

    def _has_opus_pair(self, src: str, tgt: str) -> bool:
        """OPUS-MTモデルがダウンロード済みか"""
        try:
            from core.opus_downloader import OPUS_MODELS, is_downloaded
            pair_key = self._get_opus_pair_key(src, tgt)
            return pair_key in OPUS_MODELS and is_downloaded(pair_key)
        except ImportError:
            return False

    # ------ マルチリンガルOPUS-MT (少数言語対応) ------

    def _has_multilingual(self, direction: str) -> bool:
        """マルチリンガルモデル(mul-en/en-mul)がダウンロード済みか"""
        try:
            from core.opus_downloader import has_multilingual
            return has_multilingual(direction)
        except ImportError:
            return False

    def _ensure_multilingual_loaded(self, direction: str) -> bool:
        """マルチリンガルモデルの遅延ロード"""
        if direction in self._mul_models:
            return True
        if not self._has_multilingual(direction):
            return False

        with self._lock:
            # ロック獲得後に再チェック (double-checked locking)
            if direction in self._mul_models:
                return True

            try:
                from core.opus_downloader import get_model_dir, is_ct2_converted
                model_dir = get_model_dir(direction)
                if is_ct2_converted(direction):
                    import ctranslate2
                    translator = ctranslate2.Translator(
                        model_dir, device="cpu", compute_type="int8", inter_threads=4,
                    )
                    from transformers import MarianTokenizer
                    tokenizer = MarianTokenizer.from_pretrained(model_dir)
                    self._mul_models[direction] = translator
                    self._mul_tokenizers[direction] = tokenizer
                    print(f"[hybrid] マルチリンガル CTranslate2 ロード完了: {direction}")
                    return True
                else:
                    from transformers import MarianMTModel, MarianTokenizer
                    tokenizer = MarianTokenizer.from_pretrained(model_dir)
                    model = MarianMTModel.from_pretrained(model_dir)
                    self._mul_models[direction] = model
                    self._mul_tokenizers[direction] = tokenizer
                    print(f"[hybrid] マルチリンガル HuggingFace ロード完了: {direction}")
                    return True
            except Exception as e:
                print(f"[hybrid] マルチリンガル ロード失敗 ({direction}): {e}")
                return False

    def _translate_multilingual(self, direction: str, text: str,
                                 tgt_token: Optional[str] = None) -> str:
        """マルチリンガルモデルで翻訳
        direction: "mul-en" (多言語→英語) or "en-mul" (英語→多言語)
        tgt_token: en-mul 使用時のターゲット言語トークン (例: "jpn", "npi")
        """
        if direction not in self._mul_models:
            raise RuntimeError(f"マルチリンガルモデル未ロード: {direction}")

        # en-mul の場合、テキスト先頭にターゲット言語トークンを付与
        if direction == "en-mul" and tgt_token:
            text = f">>{tgt_token}<< {text}"

        model = self._mul_models[direction]
        tokenizer = self._mul_tokenizers[direction]

        try:
            import ctranslate2
            if isinstance(model, ctranslate2.Translator):
                inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True)
                input_tokens = [tokenizer.convert_ids_to_tokens(ids.tolist())
                                for ids in inputs["input_ids"]]
                results = model.translate_batch(
                    input_tokens, beam_size=4, max_batch_size=1,
                )
                output_tokens = results[0].hypotheses[0]
                output_ids = tokenizer.convert_tokens_to_ids(output_tokens)
                return self._clean_output(
                    tokenizer.decode(output_ids, skip_special_tokens=True))
        except (ImportError, TypeError):
            pass

        # HuggingFace形式
        inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True)
        outputs = model.generate(**inputs, num_beams=4, max_length=512)
        return self._clean_output(
            tokenizer.decode(outputs[0], skip_special_tokens=True))

    def _ensure_opus_loaded(self, src: str, tgt: str) -> bool:
        """OPUS-MTモデルの遅延ロード。成功したらTrue"""
        pair_key = self._get_opus_pair_key(src, tgt)
        if pair_key in self._opus_models:
            return True

        if not self._has_opus_pair(src, tgt):
            return False

        with self._lock:
            # ロック獲得後に再チェック (double-checked locking)
            if pair_key in self._opus_models:
                return True

            try:
                from core.opus_downloader import get_model_dir, is_ct2_converted
                model_dir = get_model_dir(pair_key)

                if is_ct2_converted(pair_key):
                    # CTranslate2形式 → ct2.Translatorで高速推論
                    import ctranslate2
                    translator = ctranslate2.Translator(
                        model_dir, device="cpu", compute_type="int8", inter_threads=4,
                    )
                    # トークナイザー（sentencepiece or HF tokenizer）
                    tokenizer = self._load_opus_tokenizer(model_dir)
                    self._opus_models[pair_key] = translator
                    self._opus_tokenizers[pair_key] = tokenizer
                    print(f"[hybrid] OPUS-MT CTranslate2 ロード完了: {pair_key}")
                    return True
                else:
                    # HuggingFace形式 → transformers pipeline
                    from transformers import MarianMTModel, MarianTokenizer
                    tokenizer = MarianTokenizer.from_pretrained(model_dir)
                    model = MarianMTModel.from_pretrained(model_dir)
                    self._opus_models[pair_key] = model
                    self._opus_tokenizers[pair_key] = tokenizer
                    print(f"[hybrid] OPUS-MT HuggingFace ロード完了: {pair_key}")
                    return True
            except Exception as e:
                print(f"[hybrid] OPUS-MT ロード失敗 ({pair_key}): {e}")
                return False

    def _load_opus_tokenizer(self, model_dir: str):
        """OPUS-MTのトークナイザーをロード"""
        from transformers import MarianTokenizer
        return MarianTokenizer.from_pretrained(model_dir)

    def _ensure_nllb_loaded(self):
        """NLLBフォールバックエンジンの遅延ロード"""
        if self._nllb_engine is not None:
            return
        if self._nllb_model_dir and os.path.isdir(self._nllb_model_dir):
            self._nllb_engine = NLLBEngine(self._nllb_model_dir)
            self._nllb_engine._ensure_loaded()
            print("[hybrid] NLLB フォールバックエンジン ロード完了")
        else:
            print("[hybrid] NLLB モデルディレクトリなし — OPUS-MTのみで動作")

    def load_model_async(self, on_done: Optional[Callable] = None):
        """主要ペアの事前ロード + マルチリンガル + NLLBフォールバック"""
        def _load():
            # NLLBフォールバックを先にロード
            self._ensure_nllb_loaded()

            # 現在の対象言語の主要ペアを事前ロード
            tgt = self._target_lang
            for src, dst in [("ja", tgt), (tgt, "ja")]:
                if self._has_opus_pair(src, dst):
                    self._ensure_opus_loaded(src, dst)

            # マルチリンガルモデル（少数言語サポート）を事前ロード
            if self._has_multilingual("mul-en"):
                self._ensure_multilingual_loaded("mul-en")
            if self._has_multilingual("en-mul"):
                self._ensure_multilingual_loaded("en-mul")

            if on_done:
                on_done()

        threading.Thread(target=_load, daemon=True).start()

    @property
    def is_ready(self) -> bool:
        return (bool(self._opus_models)
                or bool(self._mul_models)
                or (self._nllb_engine is not None and self._nllb_engine.is_ready))

    def _translate_opus_ct2(self, pair_key: str, text: str) -> str:
        """CTranslate2形式のOPUS-MTで翻訳"""
        import ctranslate2
        translator = self._opus_models[pair_key]
        tokenizer = self._opus_tokenizers[pair_key]

        # Marian tokenizer → トークン列
        inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True)
        input_tokens = [tokenizer.convert_ids_to_tokens(ids.tolist()) for ids in inputs["input_ids"]]

        results = translator.translate_batch(
            input_tokens,
            beam_size=4,
            max_batch_size=1,
        )
        output_tokens = results[0].hypotheses[0]
        output_ids = tokenizer.convert_tokens_to_ids(output_tokens)
        return tokenizer.decode(output_ids, skip_special_tokens=True).strip()

    def _translate_opus_hf(self, pair_key: str, text: str) -> str:
        """HuggingFace形式のOPUS-MTで翻訳"""
        model = self._opus_models[pair_key]
        tokenizer = self._opus_tokenizers[pair_key]

        inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True)
        outputs = model.generate(**inputs, num_beams=4, max_length=512)
        return tokenizer.decode(outputs[0], skip_special_tokens=True).strip()

    # --- NLLB HuggingFace 直接翻訳 (OPUS-MTが低品質なペア用) ---

    # Flores-200言語コード (NLLB用)
    _NLLB_LANG_MAP = {
        "ja": "jpn_Jpan", "en": "eng_Latn", "zh": "zho_Hans", "ko": "kor_Hang",
        "vi": "vie_Latn", "th": "tha_Thai", "tl": "tgl_Latn", "ne": "npi_Deva",
        "my": "mya_Mymr", "km": "khm_Khmr", "lo": "lao_Laoo", "bn": "ben_Beng",
        "hi": "hin_Deva", "ur": "urd_Arab", "ar": "arb_Arab", "fa": "pes_Arab",
        "tr": "tur_Latn", "ru": "rus_Cyrl", "uk": "ukr_Cyrl", "pt": "por_Latn",
        "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn", "it": "ita_Latn",
        "nl": "nld_Latn", "pl": "pol_Latn", "ro": "ron_Latn", "cs": "ces_Latn",
        "hu": "hun_Latn", "el": "ell_Grek", "bg": "bul_Cyrl", "hr": "hrv_Latn",
        "sk": "slk_Latn", "sl": "slv_Latn", "et": "est_Latn", "lv": "lvs_Latn",
        "lt": "lit_Latn", "fi": "fin_Latn", "sv": "swe_Latn", "da": "dan_Latn",
        "no": "nob_Latn", "id": "ind_Latn", "ms": "zsm_Latn", "sw": "swh_Latn",
        "am": "amh_Ethi", "si": "sin_Sinh", "mn": "khk_Cyrl", "ka": "kat_Geor",
        "he": "heb_Hebr", "ta": "tam_Taml", "te": "tel_Telu", "ml": "mal_Mlym",
        "gu": "guj_Gujr", "pa": "pan_Guru",
    }

    def _ensure_nllb_hf_loaded(self) -> bool:
        """NLLB HuggingFace モデルの遅延ロード"""
        if self._nllb_hf_model is not None:
            return True
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            model_name = "facebook/nllb-200-distilled-600M"
            print(f"[hybrid] NLLB HuggingFace ロード中: {model_name}")
            self._nllb_hf_tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._nllb_hf_model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
            print(f"[hybrid] NLLB HuggingFace ロード完了")
            return True
        except Exception as e:
            print(f"[hybrid] NLLB HuggingFace ロード失敗: {e}")
            return False

    def _translate_nllb_hf(self, text: str, src_lang: str, tgt_lang: str) -> str:
        """NLLB HuggingFaceで翻訳"""
        if not self._ensure_nllb_hf_loaded():
            return text
        src_code = self._NLLB_LANG_MAP.get(src_lang, f"{src_lang}_Latn")
        tgt_code = self._NLLB_LANG_MAP.get(tgt_lang, f"{tgt_lang}_Latn")
        self._nllb_hf_tokenizer.src_lang = src_code
        inputs = self._nllb_hf_tokenizer(text, return_tensors="pt", padding=True, truncation=True)
        tgt_token_id = self._nllb_hf_tokenizer.convert_tokens_to_ids(tgt_code)
        outputs = self._nllb_hf_model.generate(**inputs, forced_bos_token_id=tgt_token_id, max_length=256)
        return self._nllb_hf_tokenizer.decode(outputs[0], skip_special_tokens=True).strip()

    @staticmethod
    def _clean_output(text: str) -> str:
        """翻訳出力のクリーニング: 末尾の不要文字・日本語トークンスペースを除去"""
        if not text:
            return text
        # OPUS-MT / CTranslate2 / SentencePiece が末尾に付加する不要文字を除去
        text = text.rstrip("ー\u2010\u2011\u2012\u2013\u2014\u2015\u2212−-─━_\u2581")
        text = text.strip()

        # --- 日本語トークンスペース除去 ---
        # SentencePiece が「あなた は 苦しみ を」のようにトークン間にスペースを入れる
        # CJK文字・ひらがな・カタカナ・句読点の間のスペースを除去
        # ただし英数字の前後のスペースは保持する
        _CJK = (
            r'[\u3000-\u303f'   # CJK句読点（、。「」等）
            r'\u3040-\u309f'     # ひらがな
            r'\u30a0-\u30ff'     # カタカナ
            r'\u4e00-\u9fff'     # CJK統合漢字
            r'\uf900-\ufaff'     # CJK互換漢字
            r'\uff01-\uff60'     # 全角英数・記号
            r'\uff66-\uff9f'     # 半角カタカナ
            r'、。，．！？：；「」『』（）【】〈〉《》〔〕・ー]'
        )
        # パターン: CJK文字 + スペース + CJK文字 → スペース除去
        text = re.sub(f'({_CJK})\\s+({_CJK})', r'\1\2', text)
        # 2回適用（「あ は い」→「あは い」→「あはい」）
        text = re.sub(f'({_CJK})\\s+({_CJK})', r'\1\2', text)

        return text

    def translate_detail(self, text: str, src_lang: str, tgt_lang: str) -> TranslationResult:
        """ハイブリッド翻訳（詳細版）: 英語中間文・翻訳経路を含む結果を返す"""
        pair_key = self._get_opus_pair_key(src_lang, tgt_lang)

        def _result(final, en="", route=""):
            return TranslationResult(
                final_text=self._clean_output(final),
                intermediate_en=self._clean_output(en),
                route=route,
                src_lang=src_lang, tgt_lang=tgt_lang,
            )

        # --- Stage 1: OPUS-MT 直接翻訳 ---
        # ブラックリスト (en-ja=聖書モデル等) → NLLB HFにフォールバック
        if pair_key in self._opus_blacklist:
            try:
                result = self._translate_nllb_hf(text, src_lang, tgt_lang)
                route = f"NLLB直接 ({src_lang}→{tgt_lang})"
                print(f"[hybrid] {route}")
                # 直接翻訳: 中間文なし（ピボット翻訳時のみ英語中間文を表示）
                return _result(result, "", route)
            except Exception as e:
                print(f"[hybrid] NLLB HF翻訳失敗: {e}")
        elif self._ensure_opus_loaded(src_lang, tgt_lang):
            try:
                import ctranslate2
                translator = self._opus_models.get(pair_key)
                if isinstance(translator, ctranslate2.Translator):
                    result = self._translate_opus_ct2(pair_key, text)
                else:
                    result = self._translate_opus_hf(pair_key, text)
                route = f"OPUS-MT直接 ({pair_key})"
                print(f"[hybrid] {route}")
                # 直接翻訳: 中間文なし（ピボット翻訳時のみ英語中間文を表示）
                return _result(result, "", route)
            except Exception as e:
                print(f"[hybrid] OPUS-MT翻訳失敗 ({pair_key}): {e}")

        # --- Stage 2: OPUS-MT 2段階 (en経由) ---
        if src_lang == "ja" and tgt_lang not in ("en",):
            if self._has_opus_pair("ja", "en") and self._has_opus_pair("en", tgt_lang):
                try:
                    en_text = self._do_opus_translate("ja", "en", text)
                    result = self._do_opus_translate("en", tgt_lang, en_text)
                    route = f"OPUS-MT 2段階 (ja→en→{tgt_lang})"
                    print(f"[hybrid] {route}")
                    return _result(result, en_text, route)
                except Exception as e:
                    print(f"[hybrid] 2段階翻訳失敗: {e}")
        elif tgt_lang == "ja" and src_lang not in ("en",):
            if self._has_opus_pair(src_lang, "en") and self._has_opus_pair("en", "ja"):
                try:
                    en_text = self._do_opus_translate(src_lang, "en", text)
                    result = self._do_opus_translate("en", "ja", en_text)
                    route = f"OPUS-MT 2段階 ({src_lang}→en→ja)"
                    print(f"[hybrid] {route}")
                    return _result(result, en_text, route)
                except Exception as e:
                    print(f"[hybrid] 2段階翻訳失敗: {e}")

        # --- Stage 3: マルチリンガルOPUS-MT（少数言語対応） ---
        try:
            from core.opus_downloader import get_opus_token
        except ImportError:
            get_opus_token = lambda x: None

        src_token = get_opus_token(src_lang)
        tgt_token = get_opus_token(tgt_lang)

        # 3a: mul-en → 英語
        if (tgt_lang == "en" and src_token
                and self._ensure_multilingual_loaded("mul-en")):
            try:
                result = self._translate_multilingual("mul-en", text)
                route = f"mul-en ({src_lang}→en)"
                print(f"[hybrid] {route}")
                return _result(result, result, route)
            except Exception as e:
                print(f"[hybrid] mul-en翻訳失敗: {e}")

        # 3b: en-mul → 少数言語
        if (src_lang == "en" and tgt_token
                and self._ensure_multilingual_loaded("en-mul")):
            try:
                result = self._translate_multilingual("en-mul", text, tgt_token=tgt_token)
                route = f"en-mul (en→{tgt_lang})"
                print(f"[hybrid] {route}")
                return _result(result, text, route)
            except Exception as e:
                print(f"[hybrid] en-mul翻訳失敗: {e}")

        # 3c: mul-en + OPUS-MT
        if (src_lang != "en" and tgt_lang != "en" and src_token
                and self._ensure_multilingual_loaded("mul-en")
                and self._has_opus_pair("en", tgt_lang)):
            try:
                en_text = self._translate_multilingual("mul-en", text)
                self._ensure_opus_loaded("en", tgt_lang)
                result = self._do_opus_translate("en", tgt_lang, en_text)
                route = f"mul-en→OPUS-MT ({src_lang}→en→{tgt_lang})"
                print(f"[hybrid] {route}")
                return _result(result, en_text, route)
            except Exception as e:
                print(f"[hybrid] マルチリンガルピボット失敗: {e}")

        # 3d: OPUS-MT + en-mul
        if (src_lang != "en" and tgt_lang != "en" and tgt_token
                and self._has_opus_pair(src_lang, "en")
                and self._ensure_multilingual_loaded("en-mul")):
            try:
                self._ensure_opus_loaded(src_lang, "en")
                en_text = self._do_opus_translate(src_lang, "en", text)
                result = self._translate_multilingual("en-mul", en_text, tgt_token=tgt_token)
                route = f"OPUS-MT→en-mul ({src_lang}→en→{tgt_lang})"
                print(f"[hybrid] {route}")
                return _result(result, en_text, route)
            except Exception as e:
                print(f"[hybrid] マルチリンガルピボット失敗: {e}")

        # 3e: mul-en + en-mul
        if (src_lang != "en" and tgt_lang != "en"
                and src_token and tgt_token
                and self._ensure_multilingual_loaded("mul-en")
                and self._ensure_multilingual_loaded("en-mul")):
            try:
                en_text = self._translate_multilingual("mul-en", text)
                result = self._translate_multilingual("en-mul", en_text, tgt_token=tgt_token)
                route = f"mul-en→en-mul ({src_lang}→en→{tgt_lang})"
                print(f"[hybrid] {route}")
                return _result(result, en_text, route)
            except Exception as e:
                print(f"[hybrid] フルマルチリンガル失敗: {e}")

        # --- Stage 4: NLLBフォールバック ---
        self._ensure_nllb_loaded()
        if self._nllb_engine and self._nllb_engine.is_ready:
            # A: NLLB→en + OPUS-MT en→tgt
            if (src_lang != "en" and tgt_lang != "en"
                    and self._has_opus_pair("en", tgt_lang)):
                try:
                    en_text = self._nllb_engine.translate(text, src_lang, "en")
                    self._ensure_opus_loaded("en", tgt_lang)
                    result = self._do_opus_translate("en", tgt_lang, en_text)
                    route = f"NLLB→OPUS-MT ({src_lang}→en→{tgt_lang})"
                    print(f"[hybrid] {route}")
                    return _result(result, en_text, route)
                except Exception as e:
                    print(f"[hybrid] NLLBピボット失敗: {e}")

            # B: OPUS-MT src→en + NLLB en→tgt
            if (src_lang != "en" and tgt_lang != "en"
                    and self._has_opus_pair(src_lang, "en")):
                try:
                    self._ensure_opus_loaded(src_lang, "en")
                    en_text = self._do_opus_translate(src_lang, "en", text)
                    result = self._nllb_engine.translate(en_text, "en", tgt_lang)
                    route = f"OPUS-MT→NLLB ({src_lang}→en→{tgt_lang})"
                    print(f"[hybrid] {route}")
                    return _result(result, en_text, route)
                except Exception as e:
                    print(f"[hybrid] NLLBピボット失敗: {e}")

            # C: NLLB直接
            route = f"NLLB直接 ({src_lang}→{tgt_lang})"
            print(f"[hybrid] {route}")
            result = self._nllb_engine.translate(text, src_lang, tgt_lang)
            return _result(result, "", route)

        raise RuntimeError(f"翻訳エンジンが利用できません: {src_lang}→{tgt_lang}")

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        """ハイブリッド翻訳（互換ラッパー）"""
        return self.translate_detail(text, src_lang, tgt_lang).final_text

    def _do_opus_translate(self, src: str, tgt: str, text: str) -> str:
        """OPUS-MTで翻訳（内部用）。ブラックリストペアはNLLB HFにフォールバック"""
        pair_key = self._get_opus_pair_key(src, tgt)
        # ブラックリストペア → NLLB HF
        if pair_key in self._opus_blacklist:
            raw = self._translate_nllb_hf(text, src, tgt)
            return self._clean_output(raw)
        self._ensure_opus_loaded(src, tgt)
        try:
            import ctranslate2
            translator = self._opus_models.get(pair_key)
            if isinstance(translator, ctranslate2.Translator):
                raw = self._translate_opus_ct2(pair_key, text)
            else:
                raw = self._translate_opus_hf(pair_key, text)
            return self._clean_output(raw)
        except Exception:
            raise

    def translate_stream(self, text: str, src_lang: str, tgt_lang: str,
                         callback: Callable[[str], None]):
        """ストリーミング翻訳（OPUS-MT/NLLBは一括なので疑似ストリーミング）"""
        result = self.translate(text, src_lang, tgt_lang)
        words = result.split()
        for i, word in enumerate(words):
            token = word if i == 0 else " " + word
            callback(token)
            time.sleep(0.015)  # OPUS-MTは高速なので少し遅延

    def syntax_check(self, foreign_text: str, lang: str = "en") -> list[SyntaxChunk]:
        """ハイブリッドモードでは構文チェック非対応"""
        return [SyntaxChunk(
            english=foreign_text,
            japanese="[ハイブリッドモードでは構文チェックを利用できません]",
            index=0,
        )]

    def reconstruct(self, chunks: list[SyntaxChunk]) -> str:
        """単純結合"""
        return " ".join(c.english for c in chunks)

    def get_loaded_pairs(self) -> list[str]:
        """現在ロード済みのOPUS-MTペア一覧"""
        return list(self._opus_models.keys())

    def get_engine_for_pair(self, src: str, tgt: str) -> str:
        """指定ペアで使用されるエンジン名を返す（翻訳経路の診断用）"""
        pair_key = self._get_opus_pair_key(src, tgt)
        if pair_key in self._opus_models:
            return "OPUS-MT"
        if self._has_opus_pair(src, tgt):
            return "OPUS-MT (未ロード)"
        # OPUS-MT 2段階ピボット
        if src == "ja" and self._has_opus_pair("ja", "en") and self._has_opus_pair("en", tgt):
            return "OPUS-MT (ja→en→{})".format(tgt)
        if tgt == "ja" and self._has_opus_pair(src, "en") and self._has_opus_pair("en", "ja"):
            return "OPUS-MT ({}→en→ja)".format(src)
        # マルチリンガルOPUS-MT
        try:
            from core.opus_downloader import get_opus_token
            src_token = get_opus_token(src)
            tgt_token = get_opus_token(tgt)
        except ImportError:
            src_token = tgt_token = None
        if tgt == "en" and src_token and self._has_multilingual("mul-en"):
            return "OPUS-MT mul-en"
        if src == "en" and tgt_token and self._has_multilingual("en-mul"):
            return "OPUS-MT en-mul"
        if src != "en" and tgt != "en":
            if src_token and self._has_multilingual("mul-en") and self._has_opus_pair("en", tgt):
                return "mul-en+OPUS-MT ({}→en→{})".format(src, tgt)
            if tgt_token and self._has_opus_pair(src, "en") and self._has_multilingual("en-mul"):
                return "OPUS-MT+en-mul ({}→en→{})".format(src, tgt)
            if src_token and tgt_token and self._has_multilingual("mul-en") and self._has_multilingual("en-mul"):
                return "mul-en+en-mul ({}→en→{})".format(src, tgt)
        # ハイブリッドピボット（NLLB + OPUS-MT）
        if src != "en" and tgt != "en" and self._has_opus_pair("en", tgt):
            return "NLLB+OPUS-MT ({}→en→{})".format(src, tgt)
        if src != "en" and tgt != "en" and self._has_opus_pair(src, "en"):
            return "OPUS-MT+NLLB ({}→en→{})".format(src, tgt)
        return "NLLB"
