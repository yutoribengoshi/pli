"""
PLI 同音異義サーフェシング — 接見室で紛れやすい同音異義語のワンタップ訂正支援

Whisper STT に法律語彙バイアス（core/whisper_stt.py LEGAL_ASR_PROMPT）をかけると、
日本語法律フレーズの認識精度は上がるが、副作用として「石鹸」と言いたいのに
「接見」に寄る等の取り違えが起こり得る。逆に、バイアスが効かず「勾留」が「交流」に
誤認されることもある。

本モジュールは、紛れやすい同音異義語をグループとして手キュレーションし、STT結果に
グループ構成語が現れたとき「別の候補」を弁護人に提示する。弁護人が画面を見て
ワンタップで正しい語に差し替えられるようにするための土台。

依存ゼロ（読みライブラリ不要）・テキスト照合のみで動く。

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""

# 同音異義グループ: (読み, [表記候補...])
# ソース: core/whisper_stt.py LEGAL_ASR_PROMPT の法律語 + ASRベンチで実際に
# 誤認した語（黙秘権/勾留/起訴/公判/示談/前科 等）。
# 各グループ内の語のいずれかが STT 結果に出たら、他の語を代替候補として提示する。
# 双方向に効く: 接見↔石鹸（バイアス過剰）も 交流↔勾留（バイアス失敗）も同じ仕組み。
HOMOPHONE_GROUPS = [
    ("せっけん", ["接見", "石鹸"]),
    ("こうりゅう", ["勾留", "拘留", "交流"]),
    ("きそ", ["起訴", "基礎"]),
    ("こうはん", ["公判", "後半"]),
    ("ぜんか", ["前科", "全課", "前過"]),
    ("じだん", ["示談", "時談"]),
    ("こうそ", ["控訴", "公訴", "高祖"]),
    ("じょうこく", ["上告", "上刻"]),
    ("べんご", ["弁護", "弁吾"]),
    ("もくひ", ["黙秘", "目比", "目秘"]),
    ("ようぎ", ["容疑", "用議"]),
    ("ひこく", ["被告", "非告"]),
    ("こうい", ["故意", "行為", "好意", "恋"]),
    ("かしつ", ["過失", "果実"]),
    ("じはく", ["自白", "事博"]),
    ("りょうけい", ["量刑", "良計"]),
    ("ほしゃく", ["保釈", "補釈"]),
    ("そうさ", ["捜査", "操作"]),
    ("おうしゅう", ["押収", "応酬", "欧州"]),
    ("きょうはく", ["脅迫", "強迫"]),
    ("せいとうぼうえい", ["正当防衛", "政党防衛"]),
    ("かくせいざい", ["覚醒剤", "覚せい剤"]),
]

# 表記 → グループ（読み, 全候補）の逆引き索引
_SURFACE_INDEX = {}
for _yomi, _surfaces in HOMOPHONE_GROUPS:
    for _s in _surfaces:
        _SURFACE_INDEX[_s] = (_yomi, _surfaces)


def find_homophone_candidates(text: str) -> list:
    """テキストに出現した同音異義グループ構成語と、その別候補を返す。

    Args:
        text: STT結果などの日本語テキスト

    Returns:
        [(surface, [alternatives...]), ...]
        surface = テキスト中に実出現した表記、alternatives = 同グループの他候補。
        同一表記の重複は除く。未該当なら空リスト。
    """
    if not text:
        return []
    found = []
    seen = set()
    # 長い表記を優先（正当防衛を先に、覚醒剤など）
    for surface in sorted(_SURFACE_INDEX, key=len, reverse=True):
        if surface in seen:
            continue
        if surface in text:
            _yomi, surfaces = _SURFACE_INDEX[surface]
            alts = [s for s in surfaces if s != surface]
            if alts:
                found.append((surface, alts))
                seen.add(surface)
    return found
