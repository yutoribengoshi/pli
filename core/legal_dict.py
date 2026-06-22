"""
PLI 法律用語辞書 — ロード・出現語抽出（RAG-lite）・プロンプト整形

data/legal_dict.json (4,339語) の単一の真実源。UIの手動検索（ui/dialogs.py）と
ライブ翻訳のプロンプト注入（core/engines/llm.py）の両方がこのモジュールを共有する。

翻訳時、入力文に実出現した法律用語だけを動的に拾い、翻訳プロンプトに「この訳語を
使え」と注入する（強制置換はしない安全方式）。これにより「覚醒剤取締法」が
"Act on Control of Psychotropic Substances" のように誤訳されるのを防ぐ。

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""
import json
import os
from functools import lru_cache

from core.logging_setup import get_logger

logger = get_logger(__name__)

# 重要カテゴリ: ここに属する用語は文字数不問で採用する（逮捕・勾留・起訴等の
# 2文字法律用語を確実に拾うため）。それ以外（主にJLT汎用語=category空欄）は
# min_len_generic 以上の語のみ採用し、過剰マッチ（意思・氏・遺産等）を抑制する。
IMPORTANT_CATEGORIES = frozenset({
    "法令", "刑法罪名", "罪名", "特別法罪名", "条例罪名",
    "覚醒剤取締法", "大麻取締法", "麻薬取締法", "麻薬特例法",
    "手続", "薬物", "薬物スラング", "刑法総論", "量刑", "証拠",
    "犯罪", "犯罪収益", "銃刀法", "軽犯罪法", "道交法", "入管",
    "民事手続", "民事実体", "労働", "家事", "倒産", "権利", "人物", "施設",
})

_SENTINEL = "\x00"


@lru_cache(maxsize=1)
def load_legal_dict() -> tuple:
    """data/legal_dict.json の entries を読み込む（プロセス内1回）。

    パス解決は ui/dialogs.py._load_legal_dict と同じ:
    ~/pli-models/legal_dict.json → <repo>/data/legal_dict.json。
    未配置・読込失敗時は空タプル（呼び出し側は素通り）。

    戻り値は lru_cache のため immutable な tuple[dict, ...]。
    """
    paths = [
        os.path.expanduser("~/pli-models/legal_dict.json"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     "data", "legal_dict.json"),
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entries = data.get("entries", [])
                logger.info("法律辞書ロード: %d語 (%s)", len(entries), p)
                return tuple(entries)
            except Exception as e:
                logger.warning("法律辞書ロード失敗 (%s): %s", p, e)
                continue
    logger.warning("法律辞書が見つかりません")
    return tuple()


@lru_cache(maxsize=1)
def _sorted_terms() -> tuple:
    """(ja, en, category) を len(ja) 降順でソートしたタプル（最長一致用）。

    ja/en が空のエントリは除外する。
    """
    items = []
    for e in load_legal_dict():
        ja = (e.get("ja") or "").strip()
        en = (e.get("en") or "").strip()
        if not ja or not en:
            continue
        items.append((ja, en, e.get("category", "")))
    items.sort(key=lambda t: len(t[0]), reverse=True)
    return tuple(items)


def retrieve_terms(text: str, max_terms: int = 8,
                   min_len_generic: int = 3) -> list:
    """入力文に実出現した法律用語を最長一致・重要度順で抽出する。

    Args:
        text: 入力文（通常は日本語）
        max_terms: 返す用語の最大数（プロンプト肥大・レイテンシ抑制）
        min_len_generic: 非重要カテゴリ語の最小採用文字数（短い汎用語のノイズ抑制）

    Returns:
        [(ja, en, category), ...] 最大 max_terms 件。未マッチ時は空リスト。
    """
    if not text:
        return []
    scan = text  # 採用語のスパンを番兵で消費していく作業用コピー
    matched = []
    for ja, en, cat in _sorted_terms():
        # 採用フィルタ（ノイズ抑制）
        if cat not in IMPORTANT_CATEGORIES and len(ja) < min_len_generic:
            continue
        if ja in scan:
            matched.append((ja, en, cat))
            # 同一スパンで短い語が再ヒットしないよう番兵で消費
            scan = scan.replace(ja, _SENTINEL * len(ja))
    if not matched:
        return []
    # 重要カテゴリ優先 → 文字数降順で安定ソート
    matched.sort(key=lambda t: (t[2] not in IMPORTANT_CATEGORIES, -len(t[0])))
    return matched[:max_terms]


def format_glossary_for_prompt(terms: list) -> str:
    """抽出した用語を翻訳プロンプト用の指示文字列に整形する。

    強制置換はせず「この訳を使え」と指示するのみ（文法はLLMに委ねる安全方式）。
    空リストなら空文字を返す（呼び出し側は素通り）。
    """
    if not terms:
        return ""
    lines = ["【法律用語訳語（必ず下記の訳を使うこと）】"]
    for ja, en, _cat in terms:
        lines.append(f"{ja} → {en}")
    return "\n".join(lines)
