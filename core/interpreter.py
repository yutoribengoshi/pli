"""
PLI Core Interpreter - STT + LLM 翻訳エンジン
モデル未DL時はモックモードで動作

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""

import os
import re
import time
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Optional
from enum import Enum

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


# ---------------------------------------------------------------------------
# 不明語検出
# ---------------------------------------------------------------------------

def _script_category(ch: str) -> str:
    """文字のスクリプト系統を返す"""
    cat = unicodedata.category(ch)
    if cat.startswith(("P", "S", "Z", "C")):  # 句読点・記号・空白・制御
        return "neutral"
    cp = ord(ch)
    # 日本語系
    if (0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF  # ひらがな・カタカナ
            or 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF  # CJK漢字
            or 0xFF65 <= cp <= 0xFF9F):  # 半角カナ
        return "ja"
    # ラテン系
    if 0x0041 <= cp <= 0x024F or 0x1E00 <= cp <= 0x1EFF:
        return "latin"
    # 数字
    if cat == "Nd":
        return "digit"
    return "other"


def _is_number_or_punct(word: str) -> bool:
    """数字・句読点のみの語か判定"""
    return all(
        unicodedata.category(ch).startswith(("N", "P", "S", "Z"))
        for ch in word
    )


def detect_unknown_words(
    original: str,
    translated: str,
    src_lang: str,
    tgt_lang: str,
) -> tuple[str, list[str]]:
    """
    翻訳結果から不明語（未翻訳語）を検出し、マーク付き訳文と不明語リストを返す。

    判定ロジック:
    - foreign→ja: 訳文中に残った外国語スクリプトの連続トークン
    - ja→foreign: 訳文中に残った日本語スクリプトの連続トークン
    - 数字・固有名詞的なもの（大文字始まり英単語）はスキップ
    """
    if not original or not translated:
        return translated, []

    unknown: list[str] = []

    if tgt_lang == "ja":
        # --- 外国語→日本語: 訳文中に外国語文字が残っていないか ---
        # 日本語でも数字でもない連続文字列を抽出
        tokens = re.findall(r'[^\s、。！？「」（）\d\u3000-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF]+',
                            translated)
        for tok in tokens:
            tok_stripped = tok.strip(".,;:!?()[]{}\"'")
            if not tok_stripped or len(tok_stripped) <= 1:
                continue
            if _is_number_or_punct(tok_stripped):
                continue
            # 大文字始まり英語 = 固有名詞の可能性 → スキップ
            if tok_stripped[0].isupper() and all(
                _script_category(c) in ("latin", "neutral", "digit")
                for c in tok_stripped
            ):
                continue
            # 原文にも含まれている → 翻訳されずに残った不明語
            if tok_stripped in original:
                unknown.append(tok_stripped)

    elif src_lang == "ja":
        # --- 日本語→外国語: 訳文中に日本語が残っていないか ---
        tokens = re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]+',
                            translated)
        for tok in tokens:
            if len(tok) <= 1:
                continue
            if tok in original:
                unknown.append(tok)

    else:
        # --- 外国語→外国語: ソース文字が訳文にそのまま残っていないか ---
        src_words = set(re.findall(r'\S+', original))
        tgt_words = re.findall(r'\S+', translated)
        for w in tgt_words:
            w_clean = w.strip(".,;:!?()[]{}\"'")
            if not w_clean or len(w_clean) <= 1:
                continue
            if _is_number_or_punct(w_clean):
                continue
            if w_clean[0].isupper():
                continue
            if w_clean in src_words:
                unknown.append(w_clean)

    # 重複除去（出現順保持）
    seen = set()
    unique_unknown: list[str] = []
    for w in unknown:
        if w not in seen:
            seen.add(w)
            unique_unknown.append(w)

    # 訳文中の不明語をマーク
    marked = translated
    for w in unique_unknown:
        marked = marked.replace(w, f"【{w}】")

    return marked, unique_unknown


@dataclass
class SyntaxChunk:
    """構文反転チェック用の句"""
    english: str
    japanese: str
    index: int


# ---------------------------------------------------------------------------
# サポート言語
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES = {
    "en": {"name": "English",     "native": "English",    "tier": "◎"},
    "zh": {"name": "中国語",      "native": "中文",       "tier": "◎"},
    "ko": {"name": "韓国語",      "native": "한국어",     "tier": "◎"},
    "fr": {"name": "フランス語",   "native": "Français",   "tier": "◎"},
    "de": {"name": "ドイツ語",     "native": "Deutsch",    "tier": "◎"},
    "es": {"name": "スペイン語",   "native": "Español",    "tier": "◎"},
    "pt": {"name": "ポルトガル語", "native": "Português",  "tier": "○"},
    "ar": {"name": "アラビア語",   "native": "العربية",    "tier": "○"},
    "ru": {"name": "ロシア語",     "native": "Русский",    "tier": "○"},
    "it": {"name": "イタリア語",   "native": "Italiano",   "tier": "○"},
    "th": {"name": "タイ語",       "native": "ไทย",        "tier": "○"},
    "vi": {"name": "ベトナム語",   "native": "Tiếng Việt", "tier": "○"},
    "tl": {"name": "タガログ語",   "native": "Tagalog",    "tier": "△"},
    "ne": {"name": "ネパール語",   "native": "नेपाली",      "tier": "△"},
    "my": {"name": "ミャンマー語", "native": "မြန်မာ",       "tier": "△"},
    "fa": {"name": "ペルシャ語",   "native": "فارسی",      "tier": "△"},
    "tr": {"name": "トルコ語",     "native": "Türkçe",     "tier": "△"},
    "id": {"name": "インドネシア語", "native": "Bahasa Indonesia", "tier": "○"},
    "hi": {"name": "ヒンディー語", "native": "हिन्दी",       "tier": "○"},
    "bn": {"name": "ベンガル語",   "native": "বাংলা",       "tier": "△"},
    "ur": {"name": "ウルドゥー語", "native": "اردو",        "tier": "△"},
    "si": {"name": "シンハラ語",   "native": "සිංහල",       "tier": "△"},
    "km": {"name": "クメール語",   "native": "ខ្មែរ",        "tier": "△"},
    "mn": {"name": "モンゴル語",   "native": "Монгол",     "tier": "△"},
    # ---- マルチリンガル拡張で追加 ----
    "ta": {"name": "タミル語",       "native": "தமிழ்",       "tier": "△"},
    "te": {"name": "テルグ語",       "native": "తెలుగు",      "tier": "△"},
    "ml": {"name": "マラヤーラム語", "native": "മലയാളം",     "tier": "△"},
    "sw": {"name": "スワヒリ語",     "native": "Kiswahili",  "tier": "△"},
    "uk": {"name": "ウクライナ語",   "native": "Українська",  "tier": "○"},
    "pl": {"name": "ポーランド語",   "native": "Polski",      "tier": "○"},
    "el": {"name": "ギリシャ語",     "native": "Ελληνικά",   "tier": "○"},
    "he": {"name": "ヘブライ語",     "native": "עברית",       "tier": "○"},
    "ka": {"name": "ジョージア語",   "native": "ქართული",     "tier": "△"},
    "lo": {"name": "ラオ語",         "native": "ລາວ",        "tier": "△"},
    "am": {"name": "アムハラ語",     "native": "አማርኛ",       "tier": "△"},
    "so": {"name": "ソマリ語",       "native": "Soomaaliga",  "tier": "△"},
    # ---- NLLB対応の追加言語 ----
    "gu": {"name": "グジャラート語", "native": "ગુજરાતી",     "tier": "△"},
    "mr": {"name": "マラーティー語", "native": "मराठी",        "tier": "△"},
    "pa": {"name": "パンジャーブ語", "native": "ਪੰਜਾਬੀ",       "tier": "△"},
    "ro": {"name": "ルーマニア語",   "native": "Română",      "tier": "○"},
    "hu": {"name": "ハンガリー語",   "native": "Magyar",      "tier": "○"},
    "cs": {"name": "チェコ語",       "native": "Čeština",     "tier": "○"},
    "bg": {"name": "ブルガリア語",   "native": "Български",   "tier": "○"},
    "ms": {"name": "マレー語",       "native": "Bahasa Melayu", "tier": "○"},
    "jv": {"name": "ジャワ語",       "native": "Basa Jawa",   "tier": "△"},
    "su": {"name": "スンダ語",       "native": "Basa Sunda",  "tier": "△"},
    "ha": {"name": "ハウサ語",       "native": "Hausa",       "tier": "△"},
    "yo": {"name": "ヨルバ語",       "native": "Yorùbá",      "tier": "△"},
    "ig": {"name": "イボ語",         "native": "Igbo",        "tier": "△"},
    "zu": {"name": "ズールー語",     "native": "isiZulu",     "tier": "△"},
}


# ---------------------------------------------------------------------------
# NLLB Flores-200 言語コードマッピング
# ---------------------------------------------------------------------------

NLLB_LANG_MAP = {
    "ja": "jpn_Jpan",
    "en": "eng_Latn",
    "zh": "zho_Hans",
    "ko": "kor_Hang",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "es": "spa_Latn",
    "pt": "por_Latn",
    "ar": "arb_Arab",
    "ru": "rus_Cyrl",
    "it": "ita_Latn",
    "th": "tha_Thai",
    "vi": "vie_Latn",
    "tl": "tgl_Latn",
    "ne": "npi_Deva",
    "my": "mya_Mymr",
    "fa": "pes_Arab",
    "tr": "tur_Latn",
    "id": "ind_Latn",
    "hi": "hin_Deva",
    "bn": "ben_Beng",
    "ur": "urd_Arab",
    "si": "sin_Sinh",
    "km": "khm_Khmr",
    "mn": "khk_Cyrl",
    # ---- 追加言語（マルチリンガル対応拡張） ----
    "ta": "tam_Taml",    # タミル語
    "te": "tel_Telu",    # テルグ語
    "ml": "mal_Mlym",    # マラヤーラム語
    "gu": "guj_Gujr",    # グジャラート語
    "mr": "mar_Deva",    # マラーティー語
    "pa": "pan_Guru",    # パンジャーブ語
    "sw": "swh_Latn",    # スワヒリ語
    "am": "amh_Ethi",    # アムハラ語
    "lo": "lao_Laoo",    # ラオ語
    "ka": "kat_Geor",    # ジョージア語
    "he": "heb_Hebr",    # ヘブライ語
    "uk": "ukr_Cyrl",    # ウクライナ語
    "pl": "pol_Latn",    # ポーランド語
    "ro": "ron_Latn",    # ルーマニア語
    "hu": "hun_Latn",    # ハンガリー語
    "cs": "ces_Latn",    # チェコ語
    "el": "ell_Grek",    # ギリシャ語
    "bg": "bul_Cyrl",    # ブルガリア語
    "ms": "zsm_Latn",    # マレー語
    "jv": "jav_Latn",    # ジャワ語
    "su": "sun_Latn",    # スンダ語
    "so": "som_Latn",    # ソマリ語
    "ha": "hau_Latn",    # ハウサ語
    "yo": "yor_Latn",    # ヨルバ語
    "ig": "ibo_Latn",    # イボ語
    "zu": "zul_Latn",    # ズールー語
}


def get_language_name(lang_code: str) -> str:
    """言語コードからUI表示名を取得"""
    info = SUPPORTED_LANGUAGES.get(lang_code, {})
    return info.get("name", lang_code)


def get_language_native(lang_code: str) -> str:
    """言語コードから母語名を取得"""
    info = SUPPORTED_LANGUAGES.get(lang_code, {})
    return info.get("native", lang_code)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

def make_translate_system(target_lang: str) -> str:
    """対象言語に応じた翻訳プロンプトを生成"""
    lang_name = get_language_name(target_lang)
    lang_native = get_language_native(target_lang)
    return f"""あなたは接見室に同席する中立な通訳者です。
1. 入力された発言を、意図を変えずに正確に翻訳してください。
2. 刑事手続き上の専門用語（勾留、接見禁止、起訴状など）を適切に扱ってください。
3. 翻訳先言語は{lang_name}（{lang_native}）です。
4. 許可されていない私的なアドバイスは行わず、翻訳に徹してください。
翻訳文のみを出力し、説明は不要です。"""


def make_syntax_check_system(target_lang: str) -> str:
    """対象言語に応じた構文チェックプロンプトを生成"""
    lang_name = get_language_name(target_lang)
    return f"""{lang_name}の文を句単位に分解し、日本語の語順（SOV）で並べ替えて対訳を生成してください。
出力形式は必ず以下のJSON配列にしてください。他のテキストは一切出力しないでください:
[{{"original": "句1", "japanese": "訳1"}}, {{"original": "句2", "japanese": "訳2"}}, ...]"""


RECONSTRUCT_SYSTEM = """以下の日本語の対訳テーブルに基づいて、正しい文を再構成してください。
元の言語で出力し、説明は不要です。"""


# 後方互換用
TRANSLATE_SYSTEM = make_translate_system("en")
SYNTAX_CHECK_SYSTEM = make_syntax_check_system("en")


# ---------------------------------------------------------------------------
# Mock engine (モデル未DL時のテスト用)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Real LLM engine
# ---------------------------------------------------------------------------

class LLMEngine:
    """llama.cpp ベースの実エンジン（遅延ロード対応）"""

    def __init__(self, model_path: str, n_ctx: int = 2048):
        import json as _json
        self._json = _json
        self._model_path = model_path
        self._n_ctx = n_ctx
        self._llm = None
        self._loading = False
        self._load_error: Optional[str] = None

    def load_model_async(self, on_done: Optional[Callable] = None):
        """バックグラウンドでモデルをロード"""
        self._loading = True

        def _load():
            try:
                from llama_cpp import Llama
                self._llm = Llama(
                    model_path=self._model_path,
                    n_ctx=self._n_ctx,
                    n_gpu_layers=-1,
                    n_threads=10,
                    verbose=False,
                )
                print(f"[info] LLMモデルのロード完了 (n_ctx={self._n_ctx})")
            except Exception as e:
                self._load_error = str(e)
                print(f"[error] LLMモデルのロード失敗: {e}")
            finally:
                self._loading = False
                if on_done:
                    on_done()

        t = threading.Thread(target=_load, daemon=True)
        t.start()

    @property
    def is_ready(self) -> bool:
        return self._llm is not None

    def _ensure_loaded(self):
        """モデルが未ロードの場合は同期ロード"""
        if self._llm is None:
            if self._loading:
                # 非同期ロード中 — 待つ
                import time as _time
                while self._loading:
                    _time.sleep(0.1)
            if self._llm is None and not self._load_error:
                from llama_cpp import Llama
                self._llm = Llama(
                    model_path=self._model_path,
                    n_ctx=self._n_ctx,
                    n_gpu_layers=-1,
                    n_threads=10,
                    verbose=False,
                )

    def _chat(self, system: str, user: str, max_tokens: int = 256, stream: bool = False):
        self._ensure_loaded()
        if self._llm is None:
            raise RuntimeError("LLMモデルが利用できません")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if stream:
            return self._llm.create_chat_completion(
                messages=messages, max_tokens=max_tokens, temperature=0.1, stream=True
            )
        resp = self._llm.create_chat_completion(
            messages=messages, max_tokens=max_tokens, temperature=0.1
        )
        return resp["choices"][0]["message"]["content"].strip()

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        src_name = "日本語" if src_lang == "ja" else get_language_name(src_lang)
        tgt_name = "日本語" if tgt_lang == "ja" else get_language_name(tgt_lang)
        user_msg = f"{src_name}を{tgt_name}に翻訳:\n{text}"
        system = make_translate_system(tgt_lang)
        return self._chat(system, user_msg)

    def translate_stream(self, text: str, src_lang: str, tgt_lang: str, callback: Callable[[str], None]):
        src_name = "日本語" if src_lang == "ja" else get_language_name(src_lang)
        tgt_name = "日本語" if tgt_lang == "ja" else get_language_name(tgt_lang)
        user_msg = f"{src_name}を{tgt_name}に翻訳:\n{text}"
        system = make_translate_system(tgt_lang)
        for chunk in self._chat(system, user_msg, stream=True):
            delta = chunk["choices"][0]["delta"].get("content", "")
            if delta:
                callback(delta)

    def syntax_check(self, foreign_text: str, lang: str = "en") -> list[SyntaxChunk]:
        lang_name = get_language_name(lang)
        user_msg = f"{lang_name}文: {foreign_text}"
        system = make_syntax_check_system(lang)
        result = self._chat(system, user_msg, max_tokens=512)
        try:
            data = self._json.loads(result)
            return [
                SyntaxChunk(
                    english=item.get("original", item.get("english", "")),
                    japanese=item.get("japanese", ""),
                    index=i,
                )
                for i, item in enumerate(data)
            ]
        except (self._json.JSONDecodeError, KeyError):
            return [SyntaxChunk(english=foreign_text, japanese="[解析失敗]", index=0)]

    def reconstruct(self, chunks: list[SyntaxChunk]) -> str:
        table = "\n".join(f"{c.english} → {c.japanese}" for c in chunks)
        user_msg = f"対訳テーブル:\n{table}"
        return self._chat(RECONSTRUCT_SYSTEM, user_msg)


# ---------------------------------------------------------------------------
# NLLB engine (CTranslate2 翻訳特化)
# ---------------------------------------------------------------------------

class NLLBEngine:
    """NLLB-200 + CTranslate2 ベースの軽量翻訳エンジン（8GB対応）

    翻訳専用モデルのため syntax_check / reconstruct は非対応。
    遅延ロード: 初回翻訳時にモデルをメモリへ読み込む。
    """

    def __init__(self, model_dir: str):
        self._model_dir = model_dir
        self._translator = None
        self._tokenizer = None
        self._loading = False
        self._load_error: Optional[str] = None

    def _ensure_loaded(self):
        """モデルが未ロードの場合に同期ロード"""
        if self._translator is not None:
            return
        if self._loading:
            import time as _time
            while self._loading:
                _time.sleep(0.1)
            return

        self._loading = True
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
        finally:
            self._loading = False

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


# ---------------------------------------------------------------------------
# Hybrid engine (OPUS-MT専用ペア + NLLB汎用フォールバック)
# ---------------------------------------------------------------------------

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
        self._loading = False
        self._load_error: Optional[str] = None
        # OPUS-MTモデルのロード中ペアを追跡
        self._loading_pairs: set[str] = set()
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
        if direction in self._loading_pairs:
            import time as _time
            for _ in range(300):
                if direction in self._mul_models:
                    return True
                if direction not in self._loading_pairs:
                    break
                _time.sleep(0.1)
            return direction in self._mul_models

        self._loading_pairs.add(direction)
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
        finally:
            self._loading_pairs.discard(direction)

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

        if pair_key in self._loading_pairs:
            # 別スレッドがロード中 — 待つ
            import time as _time
            for _ in range(300):  # 最大30秒待機
                if pair_key in self._opus_models:
                    return True
                if pair_key not in self._loading_pairs:
                    break
                _time.sleep(0.1)
            return pair_key in self._opus_models

        self._loading_pairs.add(pair_key)
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
        finally:
            self._loading_pairs.discard(pair_key)

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


# ---------------------------------------------------------------------------
# STT engine
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


class WhisperSTT:
    """STTエンジン — プラットフォームに応じて自動選択

    macOS (Apple Silicon): mlx-whisper (Metal GPU加速) ~0.5秒/2秒音声
    Windows/Linux: faster-whisper (CUDA/CPU) ~5秒/2秒音声
    """

    def __init__(self, whisper_model: str = ""):
        import sys
        if sys.platform == "darwin":
            # macOS: mlx-whisper (Apple Silicon GPU加速)
            import mlx_whisper
            self._backend = "mlx"
            self._mlx_whisper = mlx_whisper
            self._repo = "mlx-community/whisper-turbo"
        else:
            # Windows/Linux: faster-whisper (CUDA優先、失敗時CPUフォールバック)
            from faster_whisper import WhisperModel
            self._backend = "faster"
            model_name = whisper_model or "small"
            print(f"[info] Whisperモデル: {model_name}")
            try:
                self._model = WhisperModel(
                    model_name,
                    device="cuda",
                    compute_type="float16",
                )
            except Exception:
                self._model = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
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
            segments, info = self._model.transcribe(audio_path)
            text = "".join(seg.text for seg in segments)
            return text.strip(), info.language


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
                    print("[info] モックモード: Whisper STTをロード中...")
                    self.stt = WhisperSTT(whisper_model=self._whisper_model)
                    self._stt_ready = True
                    print("[info] Whisper STTのロード完了")
                except Exception as e:
                    load_ok = False
                    self._stt_ready = False
                    message = f"翻訳は利用できますが、音声認識は使えません: {e}"
                    self._model_load_error = message
                    print(f"[warn] STTロード失敗（モックSTT継続）: {e}")
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
                self._translation_ready = True
            except Exception as e:
                self._translation_ready = False
                load_errors.append(f"翻訳エンジンのロード失敗: {e}")
                print(f"[error] {load_errors[-1]}")

            try:
                if on_progress:
                    on_progress("stt", 0.0)
                print("[info] Whisper STTをロード中...")
                self.stt = WhisperSTT()
                self._stt_ready = True
                if on_progress:
                    on_progress("stt", 1.0)
                print("[info] Whisper STTのロード完了")
            except Exception as e:
                self._stt_ready = False
                load_errors.append(f"音声認識モデルのロード失敗: {e}")
                print(f"[error] {load_errors[-1]}")

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
        """LLMエンジン（llama.cpp）のロード"""
        print("[info] LLMモデルをロード中...")
        if on_progress:
            on_progress("llm", 0.0)

        _llm_done = threading.Event()
        if on_progress and os.path.exists(self._model_path):
            file_size = os.path.getsize(self._model_path)
            def _monitor_progress():
                try:
                    import resource
                    start_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    while not _llm_done.is_set():
                        cur_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                        delta = max(0, cur_rss - start_rss)
                        ratio = min(delta / file_size, 0.95) if file_size > 0 else 0
                        on_progress("llm", ratio)
                        if _llm_done.wait(timeout=1.0):
                            break
                except Exception:
                    pass
            monitor = threading.Thread(target=_monitor_progress, daemon=True)
            monitor.start()

        try:
            llm = LLMEngine(self._model_path, n_ctx=self._n_ctx)
            llm._ensure_loaded()
            _llm_done.set()
            if on_progress:
                on_progress("llm", 1.0)
            self.engine = llm
            print("[info] LLMモデルのロード完了")
        finally:
            _llm_done.set()

    def _load_nllb(self, on_progress):
        """NLLBエンジン（CTranslate2）のロード"""
        print(f"[info] NLLBモデルをロード中: {self._nllb_model_dir}")
        if on_progress:
            on_progress("nllb", 0.0)

        nllb = NLLBEngine(self._nllb_model_dir)
        nllb._ensure_loaded()

        if on_progress:
            on_progress("nllb", 1.0)
        self.engine = nllb
        print("[info] NLLBモデルのロード完了")

    def _load_hybrid(self, on_progress):
        """ハイブリッドエンジン（OPUS-MT + NLLB）のロード"""
        print(f"[info] ハイブリッドエンジンをロード中...")
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
        print(f"[info] ハイブリッドエンジンのロード完了 "
              f"(OPUS-MT: {len(hybrid.get_loaded_pairs())}ペア)")

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
                print(f"[info] グロッサリー読込: {len(self.glossary)}件 ({path})")
        except Exception as e:
            print(f"[warn] グロッサリー読込失敗: {e}")
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
        print(f"[info] グロッサリー保存: {len(entries)}件")

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
        print(f"[glossary] _pre called: text={text}, glossary件数={len(self.glossary)}")
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
                print(f"[glossary] 直接置換: {ja} → {foreign}")
        if replaced:
            print(f"[glossary] エンジンへの入力: {result}")
        return result, replaced

    def _glossary_post_ja_to_foreign(self, translated: str, replaced_names: list) -> str:
        """翻訳後: 固有名詞が正しく保持されているか確認し、誤訳があれば修正"""
        if not replaced_names:
            return translated
        result = translated
        for name in replaced_names:
            if name.lower() in result.lower():
                print(f"[glossary] 後処理: '{name}' が訳文に保持されている OK")
                continue
            # 名前が訳文に無い → エンジンが誤訳した → 誤訳名を探して強制置換
            print(f"[glossary] 後処理: '{name}' が訳文に無い → 誤訳名を探して置換")
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
                print(f"[glossary] 強制置換: '{candidate}' → '{prefix}{correct_name}'")
                break
        return translated

    def _apply_glossary_foreign_to_ja(self, text: str) -> str:
        """翻訳前: 外国語テキスト中のグロッサリー語句を直接日本語に置換"""
        result = text
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
                print(f"[glossary] 置換: {foreign} → {ja}")
                lower_result = result.lower()
                pos = lower_result.find(lower_foreign)
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
        print(f"[glossary] 翻訳エンジンへの入力: {processed_text}")

        def run():
            # 中間言語情報を取得してからストリーミング
            if hasattr(self.engine, "translate_detail"):
                result = self.engine.translate_detail(
                    processed_text, "ja", tgt
                )
                print(f"[glossary] エンジン出力: {result.final_text}")
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
                print(f"[glossary] ストリームエンジン出力: {utt.translated}")
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
