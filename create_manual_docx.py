#!/usr/bin/env python3
"""PLI 仕様書兼取扱説明書 Word (.docx) 生成スクリプト（フル版）

秘匿ポリシー: 実接見の会話内容・依頼者情報・録音・pli_recordファイル等は
一切引用しない。実戦実績は「拘置所接見386発話で通訳した」等の抽象記載のみ。

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）
"""

from docx import Document
from docx.shared import Pt, Cm, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml
import os

# ── カラー ──
NAVY = RGBColor(0x1a, 0x3a, 0x6a)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
DGRAY = RGBColor(0x55, 0x55, 0x55)
ACCENT = RGBColor(0x3a, 0x7a, 0xbf)
WARN = RGBColor(0x8a, 0x3a, 0x1a)
OK_GREEN = RGBColor(0x2a, 0x6a, 0x30)
LIGHT_BG = "e8ecf5"
WARN_BG = "fdeae0"


# ── ヘルパー ──
def set_cell_shading(cell, color_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    tcPr.append(shd)


def set_cell_border(cell, **kwargs):
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = parse_xml(f'''<w:tcBorders {nsdecls("w")}>
        <w:top w:val="single" w:sz="4" w:color="AAAAAA"/>
        <w:left w:val="single" w:sz="4" w:color="AAAAAA"/>
        <w:bottom w:val="single" w:sz="4" w:color="AAAAAA"/>
        <w:right w:val="single" w:sz="4" w:color="AAAAAA"/>
    </w:tcBorders>''')
    tcPr.append(tcBorders)


def make_header_cell(cell, text):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.font.size = Pt(10)
    run.font.bold = True
    run.font.color.rgb = WHITE
    set_cell_shading(cell, "1a3a6a")
    set_cell_border(cell)


def make_body_cell(cell, text, bold=False, center=False):
    cell.text = ""
    p = cell.paragraphs[0]
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.font.size = Pt(10)
    if bold:
        run.font.bold = True
    set_cell_border(cell)


def add_styled_table(doc, headers, rows, col_widths=None):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        make_header_cell(t.rows[0].cells[i], h)
    for ri, row in enumerate(rows, 1):
        for ci, val in enumerate(row):
            make_body_cell(t.rows[ri].cells[ci], val,
                           bold=(ci == 0), center=(ci > 0 and len(val) < 12))
    if col_widths:
        for row in t.rows:
            for i, w in enumerate(col_widths):
                row.cells[i].width = Cm(w)
    return t


def add_h1(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(18)
    p.paragraph_format.space_after = Pt(8)
    run = p.add_run(text)
    run.font.size = Pt(20)
    run.font.bold = True
    run.font.color.rgb = NAVY
    pPr = p._p.get_or_add_pPr()
    pBdr = parse_xml(f'''<w:pBdr {nsdecls("w")}>
        <w:bottom w:val="single" w:sz="12" w:color="1a3a6a"/>
    </w:pBdr>''')
    pPr.append(pBdr)


def add_h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    run.font.size = Pt(14)
    run.font.bold = True
    run.font.color.rgb = NAVY


def add_h3(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    run.font.size = Pt(11)
    run.font.bold = True
    run.font.color.rgb = ACCENT


def add_body(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    run.font.size = Pt(10.5)


def add_bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(1)
    run = p.runs[0] if p.runs else p.add_run("")
    run = p.add_run(text)
    run.font.size = Pt(10.5)


def add_code(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.5)
    p.paragraph_format.space_after = Pt(4)
    pPr = p._p.get_or_add_pPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="f2f4f8"/>')
    pPr.append(shd)
    run = p.add_run(text)
    run.font.name = "Menlo"
    run.font.size = Pt(9)
    run.font.color.rgb = DGRAY


def add_note(doc, text, color=WARN, bg=WARN_BG):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.3)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    pPr = p._p.get_or_add_pPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg}"/>')
    pPr.append(shd)
    run = p.add_run(text)
    run.font.size = Pt(10)
    run.font.color.rgb = color


def add_page_break(doc):
    doc.add_page_break()


# ── メイン生成 ──
def main():
    doc = Document()

    # ページ設定（A4・余白狭め）
    for section in doc.sections:
        section.page_height = Cm(29.7)
        section.page_width = Cm(21.0)
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.2)
        section.right_margin = Cm(2.2)

    # 既定フォント
    style = doc.styles["Normal"]
    style.font.name = "游明朝"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "游明朝")

    # ================================================================
    # 表紙
    # ================================================================
    for _ in range(4):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("PLI")
    run.font.size = Pt(48)
    run.font.bold = True
    run.font.color.rgb = NAVY

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Private Link Interpreter")
    run.font.size = Pt(20)
    run.font.color.rgb = NAVY

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("完全オフラインで動作する、刑事弁護人のための法律通訳AI")
    run.font.size = Pt(13)
    run.font.color.rgb = DGRAY

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("仕様書 兼 取扱説明書")
    run.font.size = Pt(16)
    run.font.color.rgb = NAVY
    run.font.bold = True

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Version 2.0 β / 2026年7月版")
    run.font.size = Pt(11)
    run.font.color.rgb = DGRAY

    for _ in range(6):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("開発")
    run.font.size = Pt(10)
    run.font.color.rgb = DGRAY

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("中野通り法律事務所")
    run.font.size = Pt(14)
    run.font.color.rgb = NAVY
    run.font.bold = True

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("弁護士 関 智之（東京弁護士会所属）")
    run.font.size = Pt(14)
    run.font.color.rgb = NAVY
    run.font.bold = True

    add_page_break(doc)

    # ================================================================
    # 巻頭免責事項（1枚目に明確に）
    # ================================================================
    add_h1(doc, "はじめに / 免責事項")
    add_body(doc, "本ソフトウェア「PLI（Private Link Interpreter）」は、外国人刑事事件の接見・公判等における通訳問題の解消を目的として、中野通り法律事務所 弁護士 関 智之（東京弁護士会所属）が個人的に開発したソフトウェアです。")

    add_h2(doc, "重要な免責事項")
    add_note(doc, "本ソフトウェアは「現状有姿（AS IS）」で提供されます。利用は完全に利用者自身の責任で行ってください。開発者は、本ソフトウェアの利用に起因する一切の損害（誤訳・誤動作・データ消失・依頼者への不利益・量刑・判決結果への影響等）について、いかなる責任も負いません。")
    add_body(doc, "機械翻訳には常に誤訳のリスクが存在します。重要な場面では必ず人間の通訳人による確認を併用してください。本ソフトウェアは「人間の通訳人を代替する」ものではなく、あくまで弁護人の業務を補助する道具です。")

    add_h2(doc, "β版であることのご理解")
    add_body(doc, "本ソフトウェアは現在β版です。実接見での運用検証は進めているものの、未検証言語、既知の不具合、環境依存の問題が残存しています。利用に際しては本書「9. β版の限界と既知の課題」を必ずご確認ください。")

    add_h2(doc, "秘匿性についての設計原則")
    add_body(doc, "本ソフトウェアは、依頼者の発言を一切外部に送信しません。すべての音声認識・翻訳処理は、利用者のPC本体の中で動作するローカルAI（ローカルLLM）で完結します。この設計は、弁護士法23条（守秘義務）の順守を第一とする刑事弁護実務の要請に応じたものです。")

    add_page_break(doc)

    # ================================================================
    # 目次
    # ================================================================
    add_h1(doc, "目次")
    toc_items = [
        ("1", "開発の経緯"),
        ("2", "PLIができること"),
        ("3", "対応言語（22言語）"),
        ("4", "システム構成と動作原理"),
        ("5", "「ローカルLLM」とは"),
        ("6", "誤訳予防の8つの仕組み"),
        ("7", "翻訳精度の検証結果"),
        ("8", "動作環境（Mac / Windows）"),
        ("9", "β版の限界と既知の課題"),
        ("10", "セットアップ手順"),
        ("11", "使い方（接見での操作）"),
        ("12", "接見室での運用のコツ"),
        ("13", "録音・記録・エクスポート"),
        ("14", "実戦実績と現場フィードバック反映"),
        ("15", "ライセンスと著作権"),
        ("16", "第三者ソフトウェアの帰属"),
        ("17", "開発者クレジット / お問い合わせ"),
    ]
    for num, title in toc_items:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(f"  {num}.  {title}")
        run.font.size = Pt(11)
        run.font.color.rgb = NAVY

    add_page_break(doc)

    # ================================================================
    # 1. 開発の経緯
    # ================================================================
    add_h1(doc, "1. 開発の経緯")
    add_body(doc, "外国人刑事事件を弁護していると、通訳を巡って次のような問題に繰り返し直面します。")
    for item in [
        "「非弁通訳」が依頼者を取り込もうとしてくる",
        "強引な通訳人が、依頼者に勝手なことを吹き込んでいる",
        "法テラスから通訳費用の立替を命じられ、結果として弁護費用が高くつく",
        "通訳人が法廷の柵（バー）に入れず、弁護権が事実上制限される",
        "そもそも稀少言語の通訳人が見つからない",
        "拘置所・接見室ではオンラインAI翻訳サービスに接続できない（電波・Wi-Fiが届かない）",
        "たとえ接続できても、依頼者の発言を外部サーバーに送るのは守秘義務違反のおそれがある",
    ]:
        add_bullet(doc, item)
    add_body(doc, "「依頼者と弁護人の間に、信頼できる通訳が常に介在する状態」を、外部の通訳人に依存せず、依頼者の発言を外部に一切送信しない形で作れないか。この問題意識から、約半年をかけて本ソフトウェアを開発しました。")

    add_page_break(doc)

    # ================================================================
    # 2. PLIができること
    # ================================================================
    add_h1(doc, "2. PLIができること")
    add_styled_table(
        doc,
        ["利用シーン", "できること"],
        [
            ["接見室（拘置所・警察署）", "依頼者との打ち合わせを、日本語↔相手言語でリアルタイム通訳"],
            ["公判前整理手続", "弁護人と依頼者の意思疎通を、席に置いたMacBook 1台で通訳"],
            ["公判廷・裁判員裁判", "弁護人席で起動し、依頼者と即時通訳。第三者を席に入れない"],
            ["取調べ立会", "取調べ室での弁護人・依頼者間の通訳"],
            ["書面ドラフト作成", "依頼者の陳述内容の翻訳を、後日確認できる形で記録・出力"],
        ],
        col_widths=[5.0, 11.0],
    )
    add_note(doc,
             "すべての処理はMacBook（またはWindows PC）1台の中で完結します。Wi-Fi・モバイル回線への接続は不要であり、むしろ守秘義務の観点から接続してはいけない設計です。",
             color=NAVY, bg=LIGHT_BG)

    add_page_break(doc)

    # ================================================================
    # 3. 対応言語
    # ================================================================
    add_h1(doc, "3. 対応言語（22言語）")
    add_body(doc, "外国人刑事事件・入管事件で扱う機会の多い言語を中心に、以下の22言語に対応しています。")
    add_styled_table(
        doc,
        ["地域", "対応言語"],
        [
            ["東アジア", "英語・中国語（簡体字/繁体字）・韓国語"],
            ["東南アジア", "ベトナム語・タガログ語・タイ語・インドネシア語・ビルマ語・クメール語"],
            ["南アジア", "ウルドゥー語・パンジャーブ語・ヒンディー語・ベンガル語・シンハラ語"],
            ["中東", "アラビア語・ペルシャ語・トルコ語"],
            ["南米", "ポルトガル語・スペイン語"],
            ["欧州", "フランス語・ドイツ語・ロシア語"],
        ],
        col_widths=[3.5, 12.5],
    )
    add_note(doc, "上記のうち、法律用語精度を個別検証済みなのは英語・中国語・ベトナム語・スペイン語・ポルトガル語・ウルドゥー語の6言語です。他の言語はライブラリが技術的に対応していますが、法律用語精度の個別検証は未了です（第9章参照）。")

    add_page_break(doc)

    # ================================================================
    # 4. システム構成と動作原理
    # ================================================================
    add_h1(doc, "4. システム構成と動作原理")
    add_body(doc, "PLIは、次の3段階の処理をすべてPC本体内で動作させます。")
    add_h3(doc, "処理1: 音声認識（発話を文字に）")
    add_body(doc, "マイクから拾った音声を、OpenAI Whisper（Apple Silicon向けにMLXで最適化されたturbo版）で文字起こしします。発話の言語は自動判別されます。さらに「法律語彙バイアス」により、同音異義語で法律用語側の漢字が優先されるよう調整済みです。")
    add_h3(doc, "処理2: 翻訳（法律用語辞書の動的注入付き）")
    add_body(doc, "文字起こしされた発言を、ローカルLLM（Qwen3.5-9B 標準／Qwen2.5-72B 高精度）で翻訳します。翻訳時、内蔵の法律用語辞書4,339語のうち、発話に実際に登場した用語だけを翻訳プロンプトに動的注入し、正式訳語（例：覚醒剤取締法→Stimulant Drugs Control Act）を強制します。")
    add_h3(doc, "処理3: 逆翻訳と画面表示")
    add_body(doc, "訳文を再度日本語に逆翻訳し、原文・訳文・逆翻訳を同時に画面表示します。弁護人が「依頼者に何が伝わったか」を日本語でその場で確認できる誤訳予防の要となる工程です。")

    add_page_break(doc)

    # ================================================================
    # 5. ローカルLLMとは
    # ================================================================
    add_h1(doc, "5. 「ローカルLLM」とは")
    add_body(doc, "「LLM」はLarge Language Model（大規模言語モデル）の略で、ChatGPT、Claude、Geminiなどの名前で知られているAI技術です。")

    add_h2(doc, "クラウドLLMとの決定的な違い")
    add_body(doc, "通常のChatGPT等は、入力した文章をすべてインターネット経由で外部企業のサーバー（米国等）に送信し、そこで処理してから結果を返す仕組みです。これに対しローカルLLMは、これらのAI技術を「利用者のPC本体の中」で動かす方式を指します。")

    add_h2(doc, "弁護士業務でローカルLLMが重要な理由")
    for item in [
        "外部企業のサーバーに依頼者の発言が保存されない",
        "海外（米国・EU等）のデータ管轄に発言が出ない",
        "AI事業者の学習データに使われない",
        "第三国の捜査機関が令状で取得することができない",
        "拘置所・法廷でWi-Fiが繋がらない環境でも動作する",
    ]:
        add_bullet(doc, item)
    add_note(doc, "裁判で否認している依頼者の発言が、米国捜査機関の令状でアクセス可能な状態にあるサーバーに保存されている——これは弁護士法23条の守秘義務に照らし、許容できません。ローカルLLMであれば、この問題が構造的に生じません。",
             color=NAVY, bg=LIGHT_BG)

    add_h2(doc, "PLIで使用しているモデル")
    add_styled_table(
        doc,
        ["モデル", "開発元", "役割"],
        [
            ["Qwen3.5-9B（標準）", "Alibaba", "翻訳LLM。16GB Macで実用速度"],
            ["Qwen2.5-72B（高精度）", "Alibaba", "翻訳LLM。64GB Mac向け高精度"],
            ["Whisper-turbo", "OpenAI（MLX最適化はApple）", "音声認識"],
            ["NLLB-200", "Meta", "多言語翻訳フォールバック"],
            ["OPUS-MT", "ヘルシンキ大学", "言語ペア専用軽量翻訳"],
        ],
        col_widths=[5.0, 4.0, 7.0],
    )

    add_page_break(doc)

    # ================================================================
    # 6. 誤訳予防の8つの仕組み
    # ================================================================
    add_h1(doc, "6. 誤訳予防の8つの仕組み")
    add_body(doc, "通訳AIで弁護人が最も恐れるべきは「気付かないうちに依頼者に誤った内容が伝わっていること」です。PLIは以下の8つの仕組みでこれを防ぎます。")

    for i, (title, desc) in enumerate([
        ("中間英語の併記表示",
         "日本語→英語→相手言語の3段階翻訳を行い、英語段階を弁護人画面に常時表示。robberyとtheftのように、英語レベルで誤訳を弁護人が即座に検知できます。"),
        ("逆翻訳の併記表示",
         "相手言語への翻訳文を、もう一度日本語に戻して弁護人画面に併記。依頼者に何が伝わるかを日本語で確認できます。"),
        ("法律用語辞書のプロンプト動的注入（4,339語）",
         "内蔵の法律用語辞書から、発話に実際に登場した法律用語だけを翻訳プロンプトに動的注入。例：「覚醒剤取締法」→ AIが素で訳すと誤訳する所を、辞書注入により正式訳 Stimulant Drugs Control Act に固定。"),
        ("音声認識にも法律語彙バイアス",
         "Whisperに法律用語の語彙ヒントを常時与え、日本語音声認識の同音異義語誤りを抑制。実測で法律日本語フレーズの文字誤り率(CER)を54%削減。"),
        ("同音異義語のワンタップ訂正",
         "「接見↔石鹸」「勾留↔交流」等の紛らわしい同音異義語が発話に含まれると、バブルに🔄マークを表示。タップで別候補に差替→自動で再翻訳。"),
        ("未知語のハイライト",
         "辞書にない固有名詞・俗語・方言を画面で警告し、弁護人が確認するまで翻訳を確定させない設定が可能。"),
        ("全履歴のローカル暗号化保存",
         "原文・中間英語・相手言語・逆翻訳の4つをタイムスタンプ付きで保存可能。控訴審での通訳の正確性立証にも使えます。保存はPC本体のみ・暗号化。"),
        ("複数翻訳エンジンの切替・併用",
         "用途・言語に応じて、Qwen3.5-9B / Qwen2.5-72B / NLLB-200 / OPUS-MT を切替可能。"),
    ], 1):
        add_h3(doc, f"{i}. {title}")
        add_body(doc, desc)

    add_page_break(doc)

    # ================================================================
    # 7. 翻訳精度の検証結果
    # ================================================================
    add_h1(doc, "7. 翻訳精度の検証結果")
    add_body(doc, "刑事弁護想定18フレーズで主要7言語をテストしました（詳細はdocs/BENCHMARK.md）。")
    add_body(doc, "下表はQwen2.5-72B（高精度オプション）での検証値です。標準のQwen3.5-9Bは辞書注入により72Bと同等の法律用語精度を保ちつつ、GPU実測0.5秒/文で動作します。")

    add_styled_table(
        doc,
        ["言語", "エンジン", "成功率", "平均速度", "法律用語", "総合"],
        [
            ["英語", "Qwen2.5-72B Q4", "18/18", "3.7秒", "◎", "実用可"],
            ["中国語", "Qwen2.5-72B Q4", "18/18", "3.6秒", "◎", "実用可"],
            ["ベトナム語", "Qwen2.5-72B Q4", "18/18", "3.8秒", "◎", "実用可"],
            ["スペイン語", "Qwen2.5-72B Q4", "18/18", "4.2秒", "◎", "実用可"],
            ["ポルトガル語", "Qwen2.5-72B Q4", "18/18", "5.3秒", "○", "実用可"],
            ["ウルドゥー語", "Qwen2.5-72B Q4", "18/18", "7.3秒", "○", "実用可"],
            ["タガログ語", "Qwen2.5-72B Q4", "18/18", "15.6秒", "△", "要追加対策"],
        ],
        col_widths=[2.8, 4.0, 1.8, 2.0, 2.0, 3.0],
    )

    add_h2(doc, "音声認識の精度検証（macOS TTS音声・法律フレーズ18本）")
    add_styled_table(
        doc,
        ["構成", "平均CER", "所感"],
        [
            ["Whisper-turbo（プロンプトなし）", "0.091", "汎用ベースライン"],
            ["Whisper-turbo + 法律語彙バイアス", "0.042", "同じフレーズでの誤字率54%減"],
        ],
        col_widths=[8.0, 2.5, 5.5],
    )

    add_h2(doc, "法律用語横断精度")
    add_styled_table(
        doc,
        ["日本語", "英語", "ベトナム語", "スペイン語"],
        [
            ["強盗", "robbery", "cướp", "robo"],
            ["窃盗", "theft", "trộm cắp", "hurto"],
            ["故意", "intent", "cố ý", "dolo"],
            ["過失", "negligence", "sơ suất", "negligencia"],
            ["黙秘", "remain silent", "giữ im lặng", "guardar silencio"],
            ["保釈", "bail", "tại ngoại", "libertad bajo fianza"],
            ["弁護人", "defense counsel", "luật sư bào chữa", "abogado defensor"],
            ["正当防衛", "self-defense", "tự vệ chính đáng", "legítima defensa"],
        ],
        col_widths=[3.0, 4.0, 5.0, 4.0],
    )

    add_page_break(doc)

    # ================================================================
    # 8. 動作環境
    # ================================================================
    add_h1(doc, "8. 動作環境（Mac / Windows）")

    add_h2(doc, "macOS（Apple Silicon）")
    add_body(doc, "PLIはApple SiliconのMac（M1/M2/M3/M4）を推奨環境として設計しています。CPUとGPUがメモリを共有する「ユニファイドメモリ」構造により、搭載メモリ容量がそのままAI処理性能に直結します。")
    add_styled_table(
        doc,
        ["メモリ", "推奨構成", "速度"],
        [
            ["8GB", "Qwen3.5-4B + 辞書注入", "簡易接見向き"],
            ["16GB（推奨）", "Qwen3.5-9B + 辞書注入", "GPU実測0.5秒/文"],
            ["24GB", "Qwen3.5-9B + NLLB-3.3B併用", "公判廷向き"],
            ["32GB", "Qwen3.6-35B-A3B（MoE）", "文脈理解強化"],
            ["64GB（プロ）", "Qwen2.5-72B", "通訳人レベル"],
        ],
        col_widths=[3.0, 8.0, 5.0],
    )

    add_h2(doc, "Windows")
    add_body(doc, "Windows版は開発対応済みですが、実機での動作検証は現状未了です。GPUなしのCPU推論のみでの動作を想定した設計になっており、Mac CPUでの実測値からWindows CPUでの推定速度を算出しています（あくまで推定値）。")
    add_styled_table(
        doc,
        ["メモリ", "推奨モデル", "Windows推定速度"],
        [
            ["8GB", "Qwen3.5-4B", "5〜10秒/文"],
            ["16GB", "Qwen3.5-9B", "4〜8秒/文"],
            ["32GB", "Qwen3.6-35B-A3B（MoE）", "実測待ち"],
        ],
        col_widths=[3.0, 8.0, 5.0],
    )

    add_page_break(doc)

    # ================================================================
    # 9. β版の限界
    # ================================================================
    add_h1(doc, "9. β版の限界と既知の課題")
    add_note(doc, "本ソフトウェアは現在β版です。以下の点を必ずご理解のうえ、利用をご検討ください。")

    add_h2(doc, "動作実証済み言語")
    add_bullet(doc, "英語・中国語・ベトナム語・スペイン語・ポルトガル語・ウルドゥー語（個別フレーズテスト18本完了）")
    add_bullet(doc, "タガログ語（一部誤訳あり、辞書補強推奨）")

    add_h2(doc, "動作未検証の言語")
    add_body(doc, "以下の言語は、翻訳ライブラリ（NLLB-200・Qwen2.5）が技術的にはサポートしているものの、法律用語精度の個別検証が未了です。これらの言語で重要な刑事弁護に利用される場合は、必ず人間の通訳人による確認を併用してください。")
    add_bullet(doc, "韓国語・タイ語・インドネシア語・ビルマ語・クメール語")
    add_bullet(doc, "パンジャーブ語・ヒンディー語・ベンガル語・シンハラ語")
    add_bullet(doc, "アラビア語・ペルシャ語・トルコ語")
    add_bullet(doc, "フランス語・ドイツ語・ロシア語")

    add_h2(doc, "動作環境の実証状況")
    add_bullet(doc, "macOS（Apple Silicon）: 実際の拘置所接見での通訳運用実績あり（2026年7月）")
    add_bullet(doc, "Windows: コード対応済・CPU推論の推定値算出済だが、実機検証は未了")
    add_bullet(doc, "Linux: 未対応")

    add_h2(doc, "既知の不具合・制約")
    add_bullet(doc, "タガログ語で長文翻訳時、LLMが解説文を混入することがある")
    add_bullet(doc, "一部言語で逆翻訳に意訳のブレが生じる")
    add_bullet(doc, "ガラス壁の接見室では、物理的なマイク配置が音声認識精度を左右する（通話孔にマイクを寄せる／外付けマイク推奨）")
    add_bullet(doc, "インストールに一定の技術知識が必要（Python環境構築）")
    add_bullet(doc, "配布バイナリ（.dmg）は現時点で未提供")

    add_h2(doc, "今後の改善予定")
    add_bullet(doc, "タガログ語法律用語辞書の手動補強")
    add_bullet(doc, "マイクデバイス選択UI（外付けマイク運用の簡易化）")
    add_bullet(doc, "macOS用 .dmg 配布パッケージの整備")
    add_bullet(doc, "Windows版の実機検証と最適化")
    add_bullet(doc, "セットアップ動画・マニュアルの整備")

    add_page_break(doc)

    # ================================================================
    # 10. セットアップ
    # ================================================================
    add_h1(doc, "10. セットアップ手順")

    add_h2(doc, "macOS")
    add_body(doc, "以下はターミナルからのセットアップ手順です。")
    add_code(doc,
             "# 1. リポジトリ取得\n"
             "git clone https://github.com/yutoribengoshi/pli.git\n"
             "cd pli\n\n"
             "# 2. Python環境（pyenv推奨）\n"
             "pyenv install 3.12.2\n"
             "pyenv local 3.12.2\n\n"
             "# 3. 依存パッケージ\n"
             "pip install -r requirements.txt\n\n"
             "# 4. llama.cpp（LLM推論エンジン）\n"
             "brew install llama.cpp\n\n"
             "# 5. モデル配置（例: Qwen3.5-9B）\n"
             "mkdir -p ~/models\n"
             "# HuggingFaceからQwen3.5-9B-Q4_K_M.ggufをダウンロードして配置\n\n"
             "# 6. 起動\n"
             "./scripts/pli-start.sh")

    add_h2(doc, "Windows")
    add_body(doc, "Windowsは実機検証が未完了のため、動作保証はありません。Python 3.12・llama.cpp・requirements-windows.txt を用意する必要があります。詳細はリポジトリのdocs/windows_setup.mdを参照してください。")

    add_page_break(doc)

    # ================================================================
    # 11. 使い方
    # ================================================================
    add_h1(doc, "11. 使い方（接見での操作）")

    add_h2(doc, "起動")
    add_code(doc, "cd ~/dev/pli\n./scripts/pli-start.sh          # 標準（Qwen3.5-9B）\n./scripts/pli-start.sh quality  # 高精度（Qwen2.5-72B・要64GB）\n./scripts/pli-start.sh stop     # 停止")
    add_body(doc, "初回起動時にmacOSからマイク・アクセシビリティのアクセス許可を求められます。「許可」を選択してください。")

    add_h2(doc, "画面構成")
    add_bullet(doc, "上部メニュー: セッション / 表示 / 音声認識 / 録音 / ヘルプ")
    add_bullet(doc, "会話ログ: 弁護人発話（青バー・上）／相手発話（緑バー・下）")
    add_bullet(doc, "各バブル: 原文・中間英語・訳文・逆翻訳を4行併記")
    add_bullet(doc, "下部入力欄: 手入力での翻訳送信も可")

    add_h2(doc, "キーボードショートカット")
    add_styled_table(
        doc,
        ["キー", "動作"],
        [
            ["Enter", "入力した文章を送信"],
            ["Space", "マイクON/OFF（入力欄以外にフォーカスがあるとき）"],
            ["⌘5", "マイクON/OFF"],
            ["⌘6", "話者自動判定"],
            ["⌘7", "弁護人として入力（自分の日本語を確実に日本語→英語）"],
            ["⌘8", "相手として入力（依頼者の発言を確実に英語→日本語）"],
            ["⌘1", "画面を隠す（ハイドモード）"],
            ["⌘2", "緊急消去（画面隠し＋会話ログ消去）"],
            ["⌘3", "相手画面を別モニタに切替"],
            ["⌘/", "ショートカット一覧を表示"],
        ],
        col_widths=[3.0, 13.0],
    )

    add_h2(doc, "接見中に迷ったら")
    add_bullet(doc, "翻訳の向きが逆になる場合: ⌘7（弁護人）または ⌘8（相手）で話者を固定")
    add_bullet(doc, "相手の声が拾えない: メニュー「音声認識→マイク感度→超高感度」を選択")
    add_bullet(doc, "誤認識が起きた: 会話バブルの🔄マークをタップして候補から差替")
    add_bullet(doc, "画面を見せたくない状況: ⌘1で即時ハイド、⌘2で即時消去")

    add_page_break(doc)

    # ================================================================
    # 12. 接見室での運用のコツ
    # ================================================================
    add_h1(doc, "12. 接見室での運用のコツ")

    add_h2(doc, "マイクの物理配置が最重要")
    add_body(doc, "接見室は通常、アクリル板やガラス壁で仕切られており、相手の声は通話孔（小さな穴やメッシュ部分）を通ってきます。この物理特性を無視して感度だけ上げても限界があります。")
    add_bullet(doc, "MacBookのマイク（キーボード上部・ヒンジ寄り）を、通話孔に寄せる")
    add_bullet(doc, "相手に「通話孔に向かって話してください」と一言伝える")
    add_bullet(doc, "余裕があればUSBグースネックマイク（千円台〜）を1本用意し、通話孔にテープで固定するのが劇的に効く")

    add_h2(doc, "感度プリセットの使い分け")
    add_styled_table(
        doc,
        ["プリセット", "用途"],
        [
            ["超高感度", "ガラス壁越し・小声・アクリル板越し"],
            ["高感度", "小声の相手・静かな接見室"],
            ["標準", "通常の対面会話"],
            ["低感度", "ノイズが多い環境"],
        ],
        col_widths=[4.0, 12.0],
    )

    add_h2(doc, "話者モードの積極的な使い分け")
    add_body(doc, "話者の自動判定は、実接見データによる文字種主導ロジックに更新済みですが、100%正確とは限りません。重要な打ち合わせでは⌘7（弁護人固定）と⌘8（相手固定）を積極的に使い分けることを推奨します。")

    add_h2(doc, "ネット環境")
    add_body(doc, "PLIはインターネット接続を必要としません。接見室ではWi-Fiがなくても、モバイル通信をオフにしていても、完全に動作します。むしろ守秘義務の観点から、接続してはいけない設計です。")

    add_page_break(doc)

    # ================================================================
    # 13. 録音・記録・エクスポート
    # ================================================================
    add_h1(doc, "13. 録音・記録・エクスポート")

    add_h2(doc, "録音モード")
    add_styled_table(
        doc,
        ["モード", "動作"],
        [
            ["OFF", "録音しない"],
            ["VOLATILE（揮発）", "RAM上に保持。ハイド／緊急消去でゼロ埋め即消去"],
            ["SAVE", "~/pli-recordings/ にWAV保存"],
        ],
        col_widths=[3.5, 12.5],
    )

    add_h2(doc, "会話ログの保存")
    add_bullet(doc, "メニュー「セッション→記録を保存 (JSON)」: 構造化データ。原文・訳文・話者・タイムスタンプ")
    add_bullet(doc, "メニュー「セッション→記録をエクスポート (テキスト)」: 読みやすいテキスト形式")
    add_bullet(doc, "会話はメモリ上のみ（守秘のため自動保存しない設計）。アプリを閉じる前に保存操作が必要")

    add_h2(doc, "動作ログ（技術ログ）")
    add_body(doc, "~/Library/Logs/PLI/pli.log に、STT秒数・翻訳秒数・言語判定結果等が記録されます。発話本文はマスキング（長さ・言語コード・件数のみ記録）されるため、秘匿義務違反にはなりません。")

    add_h2(doc, "証拠化への活用")
    add_body(doc, "JSON形式の会話ログには、原文・中間英語・相手言語・逆翻訳の4つがタイムスタンプ付きで記録されるため、控訴審での通訳正確性の立証や、後日の別通訳人による検証にも活用できます。")

    add_page_break(doc)

    # ================================================================
    # 14. 実戦実績（秘匿順守：数値のみ）
    # ================================================================
    add_h1(doc, "14. 実戦実績と現場フィードバック反映")
    add_note(doc, "本章では、特定案件の内容・依頼者の発言・具体的な会話には一切触れません。開発者自身が担当した実接見で得た定量情報（総発話数）と、それに基づき実装した修正のみを記載します。")

    add_h2(doc, "運用実績（数値のみ）")
    add_bullet(doc, "2026年7月時点で、開発者自身が担当する外国人刑事事件の実接見において、日本語↔英語の通訳運用実績を蓄積")
    add_bullet(doc, "1回の接見で総発話数386件を通訳した実運用例あり")
    add_bullet(doc, "同接見の定量データ（発話数・言語判定分布・処理時間分布）を用いた事後監査を実施")

    add_h2(doc, "現場運用から発見・修正した問題（2026年7月）")

    add_h3(doc, "問題1: 話者自動判定の誤爆")
    add_body(doc, "Whisperの言語自動判定に依拠していたため、日本語発話が英語・韓国語・スペイン語等と誤検出されると翻訳の向きが逆転する事故が発生（発生率約12%）。")
    add_body(doc, "修正: 判定ロジックを文字種主導に変更（かな・漢字の比率で判定）。同接見の実データで再生検証したところ、話者取り違えは0件に減少。")

    add_h3(doc, "問題2: Whisper幻覚のすり抜け")
    add_body(doc, "無音時にWhisperが「ありがとうございました」等の定型幻覚を生成し、フィルタをすり抜けて会話ログに混入。原因は全角句点の処理漏れ。")
    add_body(doc, "修正: 幻覚フィルタを日本語句読点に対応。「スライドスライドスライド…」型の反復幻覚検出も追加。")

    add_h3(doc, "問題3: ガラス壁越しの小声を拾えない")
    add_body(doc, "VAD閾値の下限が一律200固定で、静かな接見室でガラス越しの小声（エネルギー100〜180程度）が下限に弾かれ、発話検出すら始まらなかった。")
    add_body(doc, "修正: 下限値を感度プリセット連動化。「超高感度」プリセット（下限80）を新設。")

    add_h3(doc, "問題4: 過去ログ閲覧中の強制スクロール")
    add_body(doc, "新しい発話が来るたびに画面が最下部に強制スクロールされ、過去ログを読めなかった。")
    add_body(doc, "修正: チャットアプリ標準の「stick to bottom」挙動に変更。最下部にいる時のみ自動追従。")

    add_h3(doc, "問題5: サーバー切断時のクラッシュ")
    add_body(doc, "翻訳サーバー（llama-server）が接見中に落ちた場合、翻訳スレッドが例外未捕捉で墜落する構造だった。")
    add_body(doc, "修正: URLError等を捕捉し、日本語メッセージ「翻訳サーバーに接続できません」に変換して画面通知。")

    add_page_break(doc)

    # ================================================================
    # 15. ライセンス
    # ================================================================
    add_h1(doc, "15. ライセンスと著作権")

    add_h2(doc, "本ソフトウェアの利用許諾")
    add_bullet(doc, "刑事弁護目的での利用: 完全無償（ライセンス料不要）")
    add_bullet(doc, "個人弁護士・法律事務所での業務利用: 可")
    add_bullet(doc, "国選弁護・私選弁護・接見・公判・取調べ立会: 可")
    add_bullet(doc, "改変・再配布: 可（ただし商用販売は要相談）")

    add_h2(doc, "開発者クレジット保持義務")
    add_body(doc, "本ソフトウェアの開発者クレジット「中野通り法律事務所 弁護士 関 智之（東京弁護士会所属）」を削除・改変することを禁じます。")

    add_h2(doc, "無保証・自己責任")
    add_note(doc, "本ソフトウェアは無保証で提供されます。利用は完全に利用者の自己責任であり、明示・黙示を問わず、商品性、特定目的への適合性、第三者の権利非侵害を含むいかなる保証も行いません。開発者は、本ソフトウェアの利用または利用不能から生じる一切の直接・間接・付随的・特別・派生的損害について責任を負いません。")
    add_body(doc, "特に、本ソフトウェアによる翻訳結果の正確性については保証されません。誤訳に起因して発生した依頼者への不利益、訴訟結果への影響、その他の法的不利益について、開発者は一切の責任を負わないものとします。")

    add_page_break(doc)

    # ================================================================
    # 16. 第三者ソフトウェア
    # ================================================================
    add_h1(doc, "16. 第三者ソフトウェアの帰属")
    add_body(doc, "本ソフトウェアは、以下のオープンソースソフトウェア・公開データを利用しています。各々の著作権・ライセンスに従ってご利用ください。詳細はリポジトリのNOTICE.mdをご参照ください。")
    add_styled_table(
        doc,
        ["カテゴリ", "コンポーネント", "ライセンス"],
        [
            ["UI", "PySide6", "LGPL v3"],
            ["音声認識", "OpenAI Whisper / mlx-whisper / faster-whisper", "MIT"],
            ["翻訳", "NLLB-200 (Meta)", "CC-BY-NC 4.0"],
            ["翻訳", "OPUS-MT (Helsinki-NLP)", "CC-BY 4.0"],
            ["LLM", "Qwen2.5 / Qwen3.5 / Qwen3.6 (Alibaba)", "Apache 2.0"],
            ["LLM実行", "llama.cpp / ggml (Georgi Gerganov)", "MIT"],
            ["ライブラリ", "transformers (HuggingFace)", "Apache 2.0"],
            ["ライブラリ", "ctranslate2 (OpenNMT)", "MIT"],
            ["ライブラリ", "sentencepiece (Google)", "Apache 2.0"],
            ["音声入力", "sounddevice / PyAudio", "MIT"],
        ],
        col_widths=[3.0, 8.0, 5.0],
    )
    add_note(doc, "重要: NLLB-200はCC-BY-NC（非商用）ライセンスのため、商用利用時にはMeta社への確認が必要です。")

    add_h2(doc, "内蔵法律用語辞書の出典")
    add_bullet(doc, "法務省 日本法令翻訳辞書 (JLT) v18.0 — 約3,769語")
    add_bullet(doc, "DEA Intelligence Report DIR-022-18（薬物スラング） — 約81語・パブリックドメイン")
    add_bullet(doc, "NIDA（NIH）薬物用語 — パブリックドメイン")
    add_bullet(doc, "関 智之 弁護士（東京弁護士会所属）による手動追加 — 約570語")

    add_page_break(doc)

    # ================================================================
    # 17. クレジット・お問い合わせ
    # ================================================================
    add_h1(doc, "17. 開発者クレジット / お問い合わせ")
    for _ in range(3):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("開発")
    run.font.size = Pt(11)
    run.font.color.rgb = DGRAY

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("中野通り法律事務所")
    run.font.size = Pt(18)
    run.font.bold = True
    run.font.color.rgb = NAVY

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("弁護士 関 智之（東京弁護士会所属）")
    run.font.size = Pt(16)
    run.font.bold = True
    run.font.color.rgb = NAVY

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("GitHub: https://github.com/yutoribengoshi/pli")
    run.font.size = Pt(11)
    run.font.color.rgb = ACCENT

    for _ in range(4):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("© 2025-2026 中野通り法律事務所 弁護士 関 智之（東京弁護士会所属）")
    run.font.size = Pt(9)
    run.font.color.rgb = DGRAY

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("All rights reserved.")
    run.font.size = Pt(9)
    run.font.color.rgb = DGRAY

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("NO WARRANTY. USE AT YOUR OWN RISK.")
    run.font.size = Pt(9)
    run.font.italic = True
    run.font.color.rgb = DGRAY

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("本ソフトウェアの開発者クレジットを削除・改変することを禁じます。")
    run.font.size = Pt(8)
    run.font.italic = True
    run.font.color.rgb = DGRAY

    # ================================================================
    # 保存
    # ================================================================
    output_path = os.path.join(os.path.expanduser("~/Desktop"),
                               "PLI_仕様書_取扱説明書.docx")
    doc.save(output_path)
    print(f"Word生成完了: {output_path}")
    return output_path


if __name__ == "__main__":
    main()
