"""
PLI NLLB Engine - CTranslate2 翻訳特化エンジン (8GB対応)
Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""

import os
import time
import threading
from typing import Callable, Optional

from core.models import SyntaxChunk
from core.lang_utils import NLLB_LANG_MAP


class NLLBEngine:
    """NLLB-200 + CTranslate2 ベースの軽量翻訳エンジン（8GB対応）

    翻訳専用モデルのため syntax_check / reconstruct は非対応。
    遅延ロード: 初回翻訳時にモデルをメモリへ読み込む。
    """

    def __init__(self, model_dir: str):
        self._model_dir = model_dir
        self._translator = None
        self._tokenizer = None
        self._load_error: Optional[str] = None
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        """モデルが未ロードの場合に同期ロード"""
        if self._translator is not None:
            return

        with self._lock:
            # ロック獲得後に再チェック (double-checked locking)
            if self._translator is not None:
                return

            try:
                import ctranslate2
                from transformers import AutoTokenizer

                tokenizer_dir = os.path.join(self._model_dir, "tokenizer")
                if os.path.isdir(tokenizer_dir):
                    self._tokenizer = AutoTokenizer.from_pretrained(tokenizer_dir)
                else:
                    # トークナイザーが別ディレクトリにない場合、モデルディレクトリから試行
                    self._tokenizer = AutoTokenizer.from_pretrained(self._model_dir)

                # CTranslate2 は Apple Metal 未対応 → CPU のみ
                self._translator = ctranslate2.Translator(
                    self._model_dir,
                    device="cpu",
                    compute_type="int8",
                    inter_threads=4,
                )
                print(f"[nllb] モデルロード完了: {self._model_dir}")
            except Exception as e:
                self._load_error = str(e)
                print(f"[nllb] モデルロード失敗: {e}")

    def load_model_async(self, on_done: Optional[Callable] = None):
        """バックグラウンドでモデルをロード"""
        def _load():
            self._ensure_loaded()
            if on_done:
                on_done()
        threading.Thread(target=_load, daemon=True).start()

    @property
    def is_ready(self) -> bool:
        return self._translator is not None

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        """NLLB翻訳（同期）"""
        self._ensure_loaded()
        if self._translator is None or self._tokenizer is None:
            raise RuntimeError("NLLBモデルが利用できません")

        src_flores = NLLB_LANG_MAP.get(src_lang, "eng_Latn")
        tgt_flores = NLLB_LANG_MAP.get(tgt_lang, "jpn_Jpan")

        # トークナイザーのソース言語を設定
        self._tokenizer.src_lang = src_flores
        inputs = self._tokenizer(text, return_tensors="np", padding=True, truncation=True)
        input_ids = inputs["input_ids"].tolist()

        # CTranslate2 はトークンIDリストを受け取る
        input_tokens = [self._tokenizer.convert_ids_to_tokens(ids) for ids in input_ids]

        # ターゲット言語トークン
        target_prefix = [[tgt_flores]]

        results = self._translator.translate_batch(
            input_tokens,
            target_prefix=target_prefix,
            beam_size=4,
            max_batch_size=1,
        )

        # デコード
        output_tokens = results[0].hypotheses[0]
        # ターゲット言語トークンを除去してデコード
        if output_tokens and output_tokens[0] == tgt_flores:
            output_tokens = output_tokens[1:]

        output_ids = self._tokenizer.convert_tokens_to_ids(output_tokens)
        translated = self._tokenizer.decode(output_ids, skip_special_tokens=True)
        return translated.strip()

    def translate_stream(self, text: str, src_lang: str, tgt_lang: str,
                         callback: Callable[[str], None]):
        """タイプライター風のストリーミング出力（NLLBは一括翻訳なので擬似的に送出）"""
        result = self.translate(text, src_lang, tgt_lang)
        # 単語単位で疑似ストリーミング
        words = result.split()
        for i, word in enumerate(words):
            token = word if i == 0 else " " + word
            callback(token)
            time.sleep(0.02)

    def syntax_check(self, foreign_text: str, lang: str = "en") -> list[SyntaxChunk]:
        """NLLBモードでは構文チェック非対応"""
        return [SyntaxChunk(
            english=foreign_text,
            japanese="[NLLBモードでは構文チェックを利用できません]",
            index=0,
        )]

    def reconstruct(self, chunks: list[SyntaxChunk]) -> str:
        """NLLBモードでは再構成非対応 — 単純結合"""
        return " ".join(c.english for c in chunks)
