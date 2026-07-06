"""
PLI Mock Engine - モデル未DL時のテスト用
Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
All rights reserved.
"""

import time
from typing import Callable

from core.models import SyntaxChunk


class MockEngine:
    """モデルなしでUIテストができるモックエンジン"""

    MOCK_TRANSLATIONS_JA_EN = {
        "黙秘権を行使します": "I wish to exercise my right to remain silent.",
        "弁護人が来るまで一切の供述を拒否します": "I refuse to make any statement until my attorney arrives.",
        "接見禁止の決定が出ています": "A communication ban has been imposed.",
        "勾留延長が認められました": "The extension of detention has been approved.",
        "保釈請求を検討しましょう": "Let us consider filing a bail request.",
    }

    MOCK_TRANSLATIONS_EN_JA = {
        "I did not do it": "私はやっていません",
        "I was at home that night": "その夜は自宅にいました",
        "I don't understand the charges": "起訴内容が理解できません",
        "I want a lawyer": "弁護士を呼んでください",
        "I am innocent": "私は無実です",
    }

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        time.sleep(0.5)  # 翻訳遅延をシミュレート
        if src_lang == "ja":
            for key, val in self.MOCK_TRANSLATIONS_JA_EN.items():
                if key in text:
                    return val
            return f"[Mock EN] {text}"
        else:
            for key, val in self.MOCK_TRANSLATIONS_EN_JA.items():
                if key.lower() in text.lower():
                    return val
            return f"[Mock JA] {text}"

    def translate_stream(self, text: str, src_lang: str, tgt_lang: str, callback: Callable[[str], None]):
        """ストリーミング翻訳（タイプライター表示用）"""
        result = self.translate(text, src_lang, tgt_lang)
        for char in result:
            callback(char)
            time.sleep(0.03)  # タイプライター速度

    def syntax_check(self, english_text: str) -> list[SyntaxChunk]:
        """構文反転チェックのモック"""
        time.sleep(0.3)
        words = english_text.split()
        chunks = []
        # 簡易的に2-3語ずつ句に分割
        i = 0
        idx = 0
        mock_ja = ["私は", "その夜", "自宅に", "いました", "それは", "事実です"]
        while i < len(words):
            chunk_size = min(2 + (idx % 2), len(words) - i)
            eng = " ".join(words[i:i + chunk_size])
            ja = mock_ja[idx] if idx < len(mock_ja) else f"[{eng}]"
            chunks.append(SyntaxChunk(english=eng, japanese=ja, index=idx))
            i += chunk_size
            idx += 1
        return chunks

    def reconstruct(self, chunks: list[SyntaxChunk]) -> str:
        """修正された対訳テーブルから英文を再構成"""
        time.sleep(0.3)
        return " ".join(c.english for c in chunks)
