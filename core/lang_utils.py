"""
PLI - Private Link Interpreter
Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
"""

import re
import unicodedata


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


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

def make_translate_system(target_lang: str) -> str:
    """対象言語に応じた翻訳プロンプトを生成

    環境変数 PLI_LEAN_PROMPT が設定されている場合（主にWindows等のCPU推論）、
    few-shot例を省いた軽量プロンプトを返す。CPUではプロンプトのプレフィルが
    支配的（実測: few-shotで1文5.3秒→leanで2.1秒）であり、few-shotの精度寄与は
    法律辞書の動的注入と重複するため、CPU環境では辞書注入だけで十分。
    Apple Silicon GPU環境ではfew-shotは無コストなのでデフォルトで付与する。
    """
    import os as _os
    lang_name = get_language_name(target_lang)
    lang_native = get_language_native(target_lang)
    base = f"""あなたは接見室に同席する中立な通訳者です。
1. 入力された発言を、意図を変えずに正確に翻訳してください。
2. 刑事手続き上の専門用語（勾留、接見禁止、起訴状など）を適切に扱ってください。
3. 翻訳先言語は{lang_name}（{lang_native}）です。
4. 許可されていない私的なアドバイスは行わず、翻訳に徹してください。
5. 入力に「法律用語訳語」の指定がある場合は、必ずその訳語を使ってください。
翻訳文のみを出力し、説明は不要です。"""
    if _os.environ.get("PLI_LEAN_PROMPT"):
        return base  # CPU環境: few-shot省略（速度優先、精度は辞書注入で担保）
    # few-shot（静的＝prefixキャッシュ可能）。英語は全言語話者の参照基準になるため
    # 日→英で2例だけ示す。対象が日本語のときは英→日に反転。
    if target_lang == "ja":
        examples = """

例:
I was arrested for violating the Stimulant Drugs Control Act. → 覚醒剤取締法違反で逮捕されました
I will exercise my right to remain silent. → 黙秘権を行使します"""
    else:
        examples = """

例:
覚醒剤取締法違反で逮捕されました → I was arrested for violating the Stimulant Drugs Control Act.
黙秘権を行使します → I will exercise my right to remain silent."""
    return base + examples


def make_syntax_check_system(target_lang: str) -> str:
    """対象言語に応じた構文チェックプロンプトを生成"""
    lang_name = get_language_name(target_lang)
    return f"""{lang_name}の文を句単位に分解し、日本語の語順（SOV）で並べ替えて対訳を生成してください。
出力形式は必ず以下のJSON配列にしてください。他のテキストは一切出力しないでください:
[{{"original": "句1", "japanese": "訳1"}}, {{"original": "句2", "japanese": "訳2"}}, ...]"""


# ---------------------------------------------------------------------------
# Reconstruct prompt
# ---------------------------------------------------------------------------

RECONSTRUCT_SYSTEM = """以下の日本語の対訳テーブルに基づいて、正しい文を再構成してください。
元の言語で出力し、説明は不要です。"""
