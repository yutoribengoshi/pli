"""
PLI - Private Link Interpreter
Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class EngineType(Enum):
    MOCK = "mock"
    LLM = "llm"
    NLLB = "nllb"
    HYBRID = "hybrid"


class Speaker(Enum):
    ATTORNEY = "attorney"
    DEFENDANT = "defendant"


@dataclass
class TranslationResult:
    """翻訳結果（中間言語・経路情報を含む）"""
    final_text: str            # 最終翻訳文
    intermediate_en: str = ""  # 英語中間文（ピボット翻訳時）
    route: str = ""            # 翻訳経路 (例: "mul-en→OPUS-MT en→ja")
    src_lang: str = ""         # ソース言語コード
    tgt_lang: str = ""         # ターゲット言語コード
    unknown_words: list = field(default_factory=list)  # 不明語リスト


@dataclass
class Utterance:
    speaker: Speaker
    original: str          # STTで認識された原文
    translated: str = ""   # 最終翻訳結果
    intermediate_en: str = ""   # 英語中間文（ピボット翻訳時のみ）
    translation_route: str = "" # 翻訳経路 (例: "OPUS-MT 2段階 ne→en→ja")
    unknown_words: list = field(default_factory=list)  # 不明語リスト
    confirmed: bool = False
    timestamp: str = ""

    def to_dict(self) -> dict:
        """保存用辞書"""
        return {
            "speaker": self.speaker.value,
            "original": self.original,
            "translated": self.translated,
            "intermediate_en": self.intermediate_en,
            "translation_route": self.translation_route,
            "unknown_words": self.unknown_words,
            "confirmed": self.confirmed,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Utterance":
        """辞書から復元"""
        return cls(
            speaker=Speaker(d.get("speaker", "attorney")),
            original=d.get("original", ""),
            translated=d.get("translated", ""),
            intermediate_en=d.get("intermediate_en", ""),
            translation_route=d.get("translation_route", ""),
            unknown_words=d.get("unknown_words", []),
            confirmed=d.get("confirmed", False),
            timestamp=d.get("timestamp", ""),
        )


@dataclass
class SyntaxChunk:
    """構文反転チェック用の句"""
    english: str
    japanese: str
    index: int
