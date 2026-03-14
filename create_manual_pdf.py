#!/usr/bin/env python3
"""PLI 仕様書兼取扱説明書 PDF 生成スクリプト"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate, Frame
from reportlab.lib import colors
import os

# ── 日本語フォント登録 ──
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

FONT_M = "HeiseiMin-W3"    # 明朝
FONT_G = "HeiseiKakuGo-W5" # ゴシック

# ── カラー ──
NAVY   = HexColor("#1a3a6a")
GREEN  = HexColor("#2a6a30")
ACCENT = HexColor("#3a7abf")
BEIGE  = HexColor("#f5f0e8")
LGRAY  = HexColor("#e8e4dc")
DGRAY  = HexColor("#666666")

# ── スタイル ──
styles = {}

styles["title"] = ParagraphStyle(
    "title", fontName=FONT_G, fontSize=22, leading=30,
    textColor=NAVY, alignment=TA_CENTER, spaceAfter=4*mm,
)
styles["subtitle"] = ParagraphStyle(
    "subtitle", fontName=FONT_M, fontSize=11, leading=15,
    textColor=DGRAY, alignment=TA_CENTER, spaceAfter=10*mm,
)
styles["h1"] = ParagraphStyle(
    "h1", fontName=FONT_G, fontSize=16, leading=22,
    textColor=NAVY, spaceBefore=8*mm, spaceAfter=4*mm,
    borderWidth=0, borderPadding=0,
)
styles["h2"] = ParagraphStyle(
    "h2", fontName=FONT_G, fontSize=13, leading=18,
    textColor=NAVY, spaceBefore=5*mm, spaceAfter=3*mm,
)
styles["h3"] = ParagraphStyle(
    "h3", fontName=FONT_G, fontSize=11, leading=15,
    textColor=HexColor("#2a5090"), spaceBefore=3*mm, spaceAfter=2*mm,
)
styles["body"] = ParagraphStyle(
    "body", fontName=FONT_M, fontSize=9.5, leading=15,
    textColor=black, spaceAfter=2*mm, alignment=TA_JUSTIFY,
)
styles["body_indent"] = ParagraphStyle(
    "body_indent", parent=styles["body"],
    leftIndent=8*mm, spaceAfter=1.5*mm,
)
styles["bullet"] = ParagraphStyle(
    "bullet", parent=styles["body"],
    leftIndent=10*mm, bulletIndent=5*mm,
    spaceAfter=1*mm, spaceBefore=0.5*mm,
)
styles["code"] = ParagraphStyle(
    "code", fontName="Courier", fontSize=8.5, leading=12,
    textColor=HexColor("#333333"), backColor=HexColor("#f0ede5"),
    leftIndent=8*mm, rightIndent=8*mm,
    spaceBefore=2*mm, spaceAfter=2*mm,
    borderWidth=0.5, borderColor=LGRAY, borderPadding=4,
)
styles["note"] = ParagraphStyle(
    "note", fontName=FONT_M, fontSize=8.5, leading=13,
    textColor=DGRAY, leftIndent=8*mm, spaceAfter=2*mm,
)
styles["toc_item"] = ParagraphStyle(
    "toc_item", fontName=FONT_M, fontSize=10, leading=18,
    textColor=NAVY, leftIndent=5*mm,
)
styles["toc_sub"] = ParagraphStyle(
    "toc_sub", fontName=FONT_M, fontSize=9, leading=15,
    textColor=HexColor("#444444"), leftIndent=12*mm,
)
styles["table_header"] = ParagraphStyle(
    "table_header", fontName=FONT_G, fontSize=9, leading=13,
    textColor=white, alignment=TA_CENTER,
)
styles["table_cell"] = ParagraphStyle(
    "table_cell", fontName=FONT_M, fontSize=9, leading=13,
    textColor=black,
)
styles["table_cell_c"] = ParagraphStyle(
    "table_cell_c", parent=styles["table_cell"], alignment=TA_CENTER,
)
styles["footer"] = ParagraphStyle(
    "footer", fontName=FONT_M, fontSize=7.5, leading=10,
    textColor=DGRAY, alignment=TA_CENTER,
)


# ── ヘルパー ──
def P(style_name, text):
    return Paragraph(text, styles[style_name])

def HR():
    return HRFlowable(width="100%", thickness=0.5, color=LGRAY, spaceAfter=3*mm, spaceBefore=2*mm)

def make_table(headers, rows, col_widths=None):
    """テーブルを作る"""
    hdr = [P("table_header", h) for h in headers]
    data = [hdr]
    for row in rows:
        data.append([P("table_cell", c) if not isinstance(c, Paragraph) else c for c in row])

    w = col_widths or [None] * len(headers)
    t = Table(data, colWidths=w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",    (0, 0), (-1, 0), white),
        ("FONTNAME",     (0, 0), (-1, 0), FONT_G),
        ("FONTSIZE",     (0, 0), (-1, 0), 9),
        ("ALIGN",        (0, 0), (-1, 0), "CENTER"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND",   (0, 1), (-1, -1), white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#f8f6f0")]),
        ("GRID",         (0, 0), (-1, -1), 0.4, LGRAY),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t

def section_bar(text):
    """セクション番号付きの見出しバー"""
    t = Table([[P("table_header", text)]], colWidths=[170*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), NAVY),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
    ]))
    return t


# ══════════════════════════════════════════════════════
#  本文を構築
# ══════════════════════════════════════════════════════
def build_content():
    story = []

    # ━━ 表紙 ━━
    story.append(Spacer(1, 35*mm))
    story.append(P("title", "PLI - Private Link Interpreter"))
    story.append(P("subtitle", "秘匿通訳支援システム"))
    story.append(Spacer(1, 8*mm))
    story.append(HR())
    story.append(Spacer(1, 5*mm))
    story.append(P("h2", "仕様書 兼 取扱説明書"))
    story.append(Spacer(1, 15*mm))

    info_data = [
        ["バージョン", "2.0.0"],
        ["対応OS", "macOS 12+ (Apple Silicon)"],
        ["開発者", "関 智幸 (Tomoyuki Seki)"],
        ["作成日", "2026年3月14日"],
        ["Bundle ID", "com.seki.pli"],
    ]
    info_table = Table(
        [[P("table_cell", r[0]), P("table_cell", r[1])] for r in info_data],
        colWidths=[45*mm, 80*mm],
    )
    info_table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.3, LGRAY),
        ("BACKGROUND", (0,0), (0,-1), HexColor("#f0ede5")),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(info_table)

    story.append(PageBreak())

    # ━━ 目次 ━━
    story.append(P("h1", "目次"))
    story.append(HR())
    toc_items = [
        ("1.", "概要"),
        ("2.", "システム要件"),
        ("3.", "インストールと起動"),
        ("4.", "画面構成"),
        ("  4.1", "弁護人ウィンドウ（メインコンソール）"),
        ("  4.2", "被疑者ウィンドウ（表示用）"),
        ("5.", "翻訳エンジン"),
        ("  5.1", "Hybrid（OPUS-MT + NLLB）"),
        ("  5.2", "NLLB単体"),
        ("  5.3", "LLM（llama.cpp）"),
        ("6.", "音声認識（STT）"),
        ("7.", "定型文テンプレート"),
        ("8.", "固有名詞辞書（グロッサリー）"),
        ("9.", "辞書検索"),
        ("10.", "セッション管理・エクスポート"),
        ("11.", "秘匿モード（Hide / Panic）"),
        ("12.", "キーボードショートカット"),
        ("13.", "設定項目一覧"),
        ("14.", "対応言語一覧"),
        ("15.", "ファイル構成"),
        ("16.", "トラブルシューティング"),
    ]
    for num, title in toc_items:
        if num.startswith("  "):
            story.append(P("toc_sub", f"{num}  {title}"))
        else:
            story.append(P("toc_item", f"<b>{num}</b>  {title}"))

    story.append(PageBreak())

    # ━━ 1. 概要 ━━
    story.append(section_bar("1. 概要"))
    story.append(Spacer(1, 3*mm))
    story.append(P("body",
        "PLI（Private Link Interpreter）は、弁護人と外国人被疑者の接見時に使用する"
        "リアルタイム通訳支援アプリケーションです。"
    ))
    story.append(P("body",
        "弁護人が日本語で話す／入力すると、自動的に相手方の言語に翻訳して被疑者画面に表示します。"
        "逆に被疑者が外国語で話した内容は日本語に翻訳して弁護人画面に表示します。"
    ))
    story.append(P("h3", "主な特徴"))
    features = [
        "Apple Silicon GPU 加速の音声認識（mlx-whisper）",
        "複数翻訳エンジン対応（OPUS-MT / NLLB / LLM）",
        "40以上の言語に対応",
        "固有名詞辞書によるカスタマイズ可能な翻訳",
        "法律分野に特化した定型文テンプレート",
        "秘匿モード（Hide）とパニックボタン",
        "会話ログの保存・エクスポート",
        "完全オフライン動作（モデルダウンロード後）",
    ]
    for f in features:
        story.append(P("bullet", f"<bullet>&bull;</bullet> {f}"))

    story.append(Spacer(1, 3*mm))

    # ━━ 2. システム要件 ━━
    story.append(section_bar("2. システム要件"))
    story.append(Spacer(1, 3*mm))
    req_rows = [
        ["OS",       "macOS 12 (Monterey) 以上"],
        ["CPU",      "Apple Silicon (M1/M2/M3/M4)"],
        ["メモリ",    "8GB 以上（推奨16GB以上）"],
        ["ストレージ", "約3GB（アプリ＋翻訳モデル）"],
        ["Python",   "3.10 以上（開発モード時）"],
        ["マイク",    "内蔵マイクまたは外付けマイク"],
    ]
    story.append(make_table(["項目", "要件"], req_rows, [35*mm, 120*mm]))
    story.append(P("note", "※ LLMエンジン使用時は追加で4〜64GBのメモリが必要です。"))

    # ━━ 3. インストールと起動 ━━
    story.append(section_bar("3. インストールと起動"))
    story.append(Spacer(1, 3*mm))
    story.append(P("h3", "3.1 アプリ版（.app）で起動"))
    story.append(P("body",
        "dist/PLI.app をFinderでダブルクリックするか、ターミナルから以下を実行します。"
    ))
    story.append(P("code", "open dist/PLI.app"))
    story.append(P("note",
        "※ 初回起動時に「開発元不明」警告が表示されます。"
        "右クリック →「開く」で許可してください。"
    ))

    story.append(P("h3", "3.2 開発モードで起動"))
    story.append(P("code", "python main.py            # モックモード（テスト用）"))
    story.append(P("code", "python main.py --real      # 実モデル使用"))

    story.append(P("h3", "3.3 起動オプション"))
    opt_rows = [
        ["--real",           "実モデルを使用（デフォルトはモック）"],
        ["--display MODE",   "表示モード: auto / switch / unified / dual"],
        ["--engine ENGINE",  "翻訳エンジン: auto / llm / nllb / hybrid"],
        ["--model PATH",     "LLMモデルファイルのパスを指定"],
        ["--n-ctx N",        "LLMコンテキスト長を指定"],
    ]
    story.append(make_table(["オプション", "説明"], opt_rows, [40*mm, 115*mm]))

    story.append(P("h3", "3.4 再ビルド（ソース変更後）"))
    story.append(P("body",
        "ソースコードを変更した場合、.appに反映するには再ビルドが必要です。"
    ))
    story.append(P("code", "pyinstaller PLI.spec"))
    story.append(P("note",
        "※ python main.py で直接起動する場合はビルド不要です。"
    ))

    story.append(PageBreak())

    # ━━ 4. 画面構成 ━━
    story.append(section_bar("4. 画面構成"))
    story.append(Spacer(1, 3*mm))

    story.append(P("h2", "4.1 弁護人ウィンドウ（メインコンソール）"))
    story.append(P("body",
        "弁護人が操作するメインウィンドウです。会話ログの表示、テキスト入力、"
        "音声認識の制御、各種設定を行います。"
    ))

    story.append(P("h3", "画面レイアウト"))
    layout_rows = [
        ["メニューバー",    "言語(L) / 表示(V) / セッション(S) / 録音(R) / 音声認識(M) / テスト(T) / 設定(O) / ヘルプ(H)"],
        ["ツールバー",      "モードインジケーター、読込状態、対象言語表示"],
        ["会話ログ",       "吹き出し形式の会話履歴（弁護人=紺色、被疑者=緑色）"],
        ["承認パネル",      "被疑者発言の確認ボックス（OK / やり直し / 編集ボタン）"],
        ["入力エリア",      "定型文ボタン / 辞書ボタン / テキスト入力欄 / 送信ボタン"],
        ["ステータスバー",   "セッション番号、録音サイズ、STTモード表示"],
    ]
    story.append(make_table(["領域", "内容"], layout_rows, [30*mm, 125*mm]))

    story.append(P("h3", "表示モード"))
    view_rows = [
        ["switch",  "フルスクリーン切替（弁護人画面 / 被疑者画面をF3で切替）"],
        ["unified", "左右分割（左に弁護人コンソール、右に被疑者パネル）"],
        ["split",   "スプリッター分割（弁護人・被疑者を自由にリサイズ）"],
    ]
    story.append(make_table(["モード", "説明"], view_rows, [25*mm, 130*mm]))

    story.append(P("h3", "会話バブルの操作"))
    bubble_rows = [
        ["右クリック",      "コピーメニュー（原文+訳文 / 原文のみ / 訳文のみ）"],
        ["修正ボタン",      "弁護人発言の翻訳を手動修正"],
        ["取消ボタン",      "発言の翻訳を取り消し"],
        ["編集ボタン",      "被疑者発言の翻訳を手動修正"],
    ]
    story.append(make_table(["操作", "内容"], bubble_rows, [30*mm, 125*mm]))

    story.append(Spacer(1, 4*mm))
    story.append(P("h2", "4.2 被疑者ウィンドウ（表示用）"))
    story.append(P("body",
        "被疑者に見せる表示専用ウィンドウです。タイプライター効果で翻訳結果を表示します。"
        "操作ボタンはなく、表示のみの画面です。"
    ))
    def_rows = [
        ["メッセージ表示",  "色分けされた吹き出し（弁護人発言=紺、被疑者発言=緑）"],
        ["タイプライター効果", "弁護人の翻訳が一文字ずつ表示される演出"],
        ["ステータスバナー",  "多言語対応の状態メッセージ（確認中/確定/修正中 等）"],
        ["自動スクロール",   "新しいメッセージに自動追従"],
    ]
    story.append(make_table(["要素", "説明"], def_rows, [35*mm, 120*mm]))

    story.append(PageBreak())

    # ━━ 5. 翻訳エンジン ━━
    story.append(section_bar("5. 翻訳エンジン"))
    story.append(Spacer(1, 3*mm))
    story.append(P("body",
        "PLIは3種類の翻訳エンジンに対応しています。設定メニューから切り替え可能です。"
    ))

    story.append(P("h2", "5.1 Hybrid（OPUS-MT + NLLB）【推奨】"))
    story.append(P("body",
        "OPUS-MTモデルを主翻訳エンジンとして使用し、"
        "対応していない言語ペアではNLLBにフォールバックします。"
        "最も高精度な翻訳が可能です。"
    ))
    story.append(P("body_indent",
        "<b>翻訳フロー:</b> 日本語 → (OPUS-MT) → 英語 → (OPUS-MT) → 対象言語"
    ))
    story.append(P("note",
        "※ 英語を中間言語（ピボット）として使用する2段階翻訳方式です。"
    ))

    story.append(P("h2", "5.2 NLLB 単体"))
    story.append(P("body",
        "Meta社のNLLB-200モデルをCTranslate2で最適化して使用します。"
        "軽量でメモリ消費が少なく、CPU環境でも動作します。"
    ))

    story.append(P("h2", "5.3 LLM（llama.cpp）"))
    story.append(P("body",
        "大規模言語モデル（Qwen2.5等）を使用した翻訳です。"
        "構文チェック機能が利用可能ですが、大量のメモリを必要とします。"
    ))
    llm_rows = [
        ["7B (Q4_K_M)",  "約8GB",  "基本的な翻訳"],
        ["14B (Q4_K_M)", "約12GB", "高品質な翻訳"],
        ["32B (Q4_K_M)", "約24GB", "専門分野対応"],
        ["72B (Q3_K_M)", "約40GB", "最高品質"],
    ]
    story.append(make_table(
        ["モデルサイズ", "必要メモリ", "特徴"],
        llm_rows, [35*mm, 30*mm, 90*mm]
    ))

    # ━━ 6. 音声認識 ━━
    story.append(section_bar("6. 音声認識（STT）"))
    story.append(Spacer(1, 3*mm))
    story.append(P("body",
        "Apple Silicon GPU加速のmlx-whisperを使用したリアルタイム音声認識です。"
        "マイクから取得した音声を自動でテキストに変換します。"
    ))

    story.append(P("h3", "操作方法"))
    stt_op_rows = [
        ["Space / メニュー", "STTの開始・停止を切替"],
        ["Command+6",              "自動言語検出モード"],
        ["Command+7",              "弁護人入力モード（日本語固定）"],
        ["Command+8",              "被疑者入力モード（外国語固定）"],
    ]
    story.append(make_table(["操作", "説明"], stt_op_rows, [40*mm, 115*mm]))

    story.append(P("h3", "感度設定"))
    sens_rows = [
        ["high (1.3x)",   "小さな声も検出（静かな環境向け）"],
        ["normal (1.8x)", "標準（推奨）"],
        ["low (2.5x)",    "周囲の騒音が大きい環境向け"],
    ]
    story.append(make_table(["レベル", "説明"], sens_rows, [35*mm, 120*mm]))

    story.append(P("h3", "テンポ設定"))
    tempo_rows = [
        ["slow",   "無音判定 1.2秒 / 最小発話 0.5秒（ゆっくり話す人向け）"],
        ["normal", "無音判定 0.8秒 / 最小発話 0.3秒（標準）"],
        ["fast",   "無音判定 0.5秒 / 最小発話 0.15秒（早口の人向け）"],
    ]
    story.append(make_table(["レベル", "説明"], tempo_rows, [25*mm, 130*mm]))

    story.append(P("note",
        "※ STT動作中は入力欄の背景が黄色に変わります。"
    ))

    story.append(PageBreak())

    # ━━ 7. 定型文テンプレート ━━
    story.append(section_bar("7. 定型文テンプレート"))
    story.append(Spacer(1, 3*mm))
    story.append(P("body",
        "入力エリアの「定型文」ボタンから、法律分野で頻出する定型文を選択して"
        "ワンクリックで翻訳・送信できます。"
    ))

    story.append(P("h3", "組込みカテゴリ"))
    phrase_rows = [
        ["権利告知",    "黙秘権の告知 / 弁護人選任権 / 供述の自由 / 接見交通権"],
        ["手続説明",    "勾留の流れ / 保釈の説明 / 起訴・不起訴 / 裁判の流れ / 取調べの注意"],
        ["接見時の定型句", "挨拶 / 体調確認 / 次回面会 / 家族への連絡 / 終了の挨拶"],
    ]
    story.append(make_table(
        ["カテゴリ", "含まれるフレーズ"],
        phrase_rows, [35*mm, 120*mm]
    ))

    story.append(P("h3", "カスタマイズ"))
    story.append(P("body",
        "設定メニュー →「定型文編集」から、カテゴリの追加・削除、フレーズの編集が可能です。"
    ))
    story.append(P("body",
        "また、~/pli-models/定型文.docx をWordで直接編集することもできます。"
        "見出し1がカテゴリ名、2列の表（ラベル｜本文）がフレーズとして読み込まれます。"
    ))
    story.append(P("note",
        "読み込み優先順: ユーザーdocx → ユーザーjson → 同梱json"
    ))

    # ━━ 8. グロッサリー ━━
    story.append(section_bar("8. 固有名詞辞書（グロッサリー）"))
    story.append(Spacer(1, 3*mm))
    story.append(P("body",
        "人名や組織名などの固有名詞を正確に翻訳するための辞書機能です。"
        "翻訳エンジンに送る前に日本語の固有名詞を対応する外国語表記に直接置換し、"
        "翻訳後に正しく保持されているかチェックします。"
    ))

    story.append(P("h3", "動作の流れ"))
    glo_flow = [
        ["1. 前処理", "入力テキスト中の固有名詞をローマ字/英語表記に置換"],
        ["2. 翻訳",  "置換済みテキストを翻訳エンジンに送信"],
        ["3. 後処理", "翻訳結果に固有名詞が保持されているか確認。欠落時は強制置換"],
    ]
    story.append(make_table(["ステップ", "内容"], glo_flow, [25*mm, 130*mm]))

    story.append(P("h3", "辞書の編集"))
    story.append(P("body",
        "設定メニュー →「固有名詞辞書」から、日本語と外国語のペアを追加・削除できます。"
        "type: \"name\" のエントリのみが固有名詞として処理されます。"
    ))
    story.append(P("h3", "登録例"))
    glo_ex = [
        ["関智幸",      "Tomoyuki Seki"],
        ["東京弁護士会", "Tokyo Bar Association"],
    ]
    story.append(make_table(["日本語", "外国語"], glo_ex, [45*mm, 110*mm]))

    # ━━ 9. 辞書検索 ━━
    story.append(section_bar("9. 辞書検索"))
    story.append(Spacer(1, 3*mm))
    story.append(P("body",
        "入力エリアの「辞書」ボタンから、単語やフレーズの翻訳を検索できます。"
        "翻訳エンジンを使用して双方向（日本語→外国語、外国語→日本語）の"
        "リアルタイム検索が可能です。"
    ))
    story.append(P("note",
        "※ 検索結果は参考用です。会話ログには追加されません。"
    ))

    story.append(PageBreak())

    # ━━ 10. セッション管理 ━━
    story.append(section_bar("10. セッション管理・エクスポート"))
    story.append(Spacer(1, 3*mm))

    story.append(P("h3", "セッション"))
    story.append(P("body",
        "アプリ起動からの一連の会話を「セッション」として管理します。"
        "セッションメニューから新規セッションの開始や終了が可能です。"
    ))

    story.append(P("h3", "エクスポート形式"))
    exp_rows = [
        ["JSON保存",   "全データ（原文/訳文/中間英語/タイムスタンプ/ルート等）を構造化保存"],
        ["テキスト出力", "人間可読な形式（話者ラベル + 原文 → 訳文）で出力"],
    ]
    story.append(make_table(["形式", "内容"], exp_rows, [30*mm, 125*mm]))

    story.append(P("h3", "録音モード"))
    rec_rows = [
        ["OFF",      "録音しない（デフォルト）"],
        ["VOLATILE", "RAM上に一時保存（アプリ終了で消滅）"],
        ["SAVE",     "WAVファイルとして ~/pli-recordings/ に保存"],
    ]
    story.append(make_table(["モード", "説明"], rec_rows, [30*mm, 125*mm]))

    # ━━ 11. 秘匿モード ━━
    story.append(section_bar("11. 秘匿モード（Hide / Panic）"))
    story.append(Spacer(1, 3*mm))
    story.append(P("body",
        "接見中に第三者の目がある場合に、アプリの存在を隠す機能です。"
    ))

    story.append(P("h3", "Hide モード（Command+1）"))
    story.append(P("body",
        "画面を即座にダミーPDF表示に切り替えます。"
        "トグル操作で元の画面に復帰できます。"
    ))
    story.append(P("body_indent",
        "オプション: 会話ログの消去 / 録音バッファの消去を設定可能"
    ))

    story.append(P("h3", "Panic モード（Command+2）"))
    story.append(P("body",
        "<b>不可逆のデータ破棄</b>を行います。以下を即座に実行します。"
    ))
    panic_items = [
        "録音バッファをゼロで上書き消去",
        "会話ログを完全消去",
        "STTを停止",
        "画面をダミー表示に切替",
    ]
    for item in panic_items:
        story.append(P("bullet", f"<bullet>&bull;</bullet> {item}"))
    story.append(P("note",
        "Panicモードで消去されたデータは復元できません。"
    ))

    # ━━ 12. ショートカット ━━
    story.append(section_bar("12. キーボードショートカット"))
    story.append(Spacer(1, 3*mm))
    sc_rows = [
        ["Command+1", "秘匿モード切替（Hide）"],
        ["Command+2", "パニックボタン（データ全消去）"],
        ["Command+3", "被疑者画面の表示切替 / 埋込パネル切替"],
        ["Command+5", "音声認識 ON/OFF"],
        ["Command+6", "STT: 自動言語検出モード"],
        ["Command+7", "STT: 弁護人入力モード（日本語固定）"],
        ["Command+8", "STT: 被疑者入力モード（外国語固定）"],
        ["Command+D", "テスト: 被疑者発言シミュレーション"],
        ["Command+/", "ショートカット一覧を表示"],
        ["Space",   "音声認識 ON/OFF（入力欄未選択時）"],
        ["Enter",   "テキスト送信"],
    ]
    story.append(make_table(
        ["ショートカット", "機能"],
        sc_rows, [35*mm, 120*mm]
    ))

    story.append(PageBreak())

    # ━━ 13. 設定項目一覧 ━━
    story.append(section_bar("13. 設定項目一覧"))
    story.append(Spacer(1, 3*mm))
    story.append(P("body",
        "メニューバーの「設定(O)」から各種設定を変更できます。"
    ))
    cfg_rows = [
        ["文字サイズ",          "3段階のフォントスケーリング（小/中/大）"],
        ["LLMモデル",          "llama.cppモデルファイルの選択"],
        ["コンテキスト長",      "LLMのコンテキストトークン数"],
        ["翻訳エンジン",        "Hybrid / NLLB / LLM の切替"],
        ["NLLBモデル",         "NLLBモデルサイズの選択"],
        ["OPUS-MTモデル",      "OPUS-MTモデルの管理"],
        ["定型文編集",          "定型文テンプレートの追加・編集・削除"],
        ["固有名詞辞書",        "グロッサリーの追加・編集・削除"],
        ["ダミーPDF",          "秘匿モード用のPDFファイル選択"],
    ]
    story.append(make_table(
        ["項目", "説明"],
        cfg_rows, [35*mm, 120*mm]
    ))

    story.append(P("h3", "設定ファイルの保存先"))
    story.append(P("code", "~/pli-models/"))
    file_rows = [
        ["last_engine.txt",     "最後に使用した翻訳エンジン"],
        ["last_model.txt",      "最後に使用したLLMモデルパス"],
        ["last_n_ctx.txt",      "最後に使用したコンテキスト長"],
        ["last_nllb_model.txt", "最後に使用したNLLBモデル"],
    ]
    story.append(make_table(["ファイル", "内容"], file_rows, [45*mm, 110*mm]))

    # ━━ 14. 対応言語 ━━
    story.append(section_bar("14. 対応言語一覧"))
    story.append(Spacer(1, 3*mm))
    story.append(P("body",
        "言語(L)メニューから対象言語を選択できます。品質ランクは以下の通りです。"
    ))
    rank_rows = [
        ["(OPUS直通)", "日本語との直接OPUS-MTモデルあり。最高品質"],
        ["Tier A",   "英語ピボット経由。OPUS-MTで高品質"],
        ["Tier B",   "NLLBフォールバック。実用レベル"],
    ]
    story.append(make_table(["ランク", "説明"], rank_rows, [30*mm, 125*mm]))

    story.append(P("h3", "主な対応言語"))
    lang_rows = [
        ["英語",       "English",     "OPUS直通"],
        ["中国語(簡体)", "Chinese",    "OPUS直通"],
        ["韓国語",      "Korean",     "OPUS直通"],
        ["ベトナム語",   "Vietnamese", "Tier A"],
        ["ポルトガル語",  "Portuguese", "Tier A"],
        ["スペイン語",   "Spanish",    "Tier A"],
        ["タガログ語",   "Tagalog",    "Tier A"],
        ["ネパール語",   "Nepali",     "Tier B"],
        ["ミャンマー語",  "Burmese",    "Tier B"],
        ["タイ語",      "Thai",       "Tier A"],
        ["インドネシア語", "Indonesian", "Tier A"],
        ["フランス語",   "French",     "OPUS直通"],
    ]
    story.append(make_table(
        ["言語", "Language", "ランク"],
        lang_rows, [35*mm, 40*mm, 80*mm]
    ))
    story.append(P("note", "※ 上記以外にも40以上の言語に対応しています。"))

    story.append(PageBreak())

    # ━━ 15. ファイル構成 ━━
    story.append(section_bar("15. ファイル構成"))
    story.append(Spacer(1, 3*mm))
    file_struct = [
        ["main.py",                 "アプリケーションエントリーポイント"],
        ["core/interpreter.py",     "翻訳エンジン・グロッサリー処理"],
        ["core/stt_listener.py",    "音声認識（mlx-whisper）"],
        ["core/recorder.py",        "音声録音"],
        ["ui/attorney_window.py",   "弁護人ウィンドウ UI"],
        ["ui/defendant_window.py",  "被疑者ウィンドウ UI"],
        ["data/phrases.json",       "定型文テンプレートデータ"],
        ["data/glossary.json",      "固有名詞辞書データ"],
        ["assets/PLI.icns",         "macOSアプリアイコン"],
        ["PLI.spec",                "PyInstallerビルド設定"],
        ["pyproject.toml",          "Pythonプロジェクト設定"],
        ["requirements.txt",        "依存パッケージ一覧"],
        ["run.sh",                  "開発用起動スクリプト"],
    ]
    story.append(make_table(
        ["ファイル", "説明"],
        file_struct, [45*mm, 110*mm]
    ))

    # ━━ 16. トラブルシューティング ━━
    story.append(section_bar("16. トラブルシューティング"))
    story.append(Spacer(1, 3*mm))

    ts_rows = [
        ["「開発元不明」で起動できない",
         "Finderで右クリック →「開く」で許可"],
        ["翻訳が遅い",
         "Hybridエンジンの初回起動時はモデルダウンロードが必要。2回目以降は高速"],
        ["マイクが認識されない",
         "システム設定 → プライバシーとセキュリティ → マイク で許可を確認"],
        ["固有名詞が正しく翻訳されない",
         "設定 → 固有名詞辞書に登録。type: name が設定されているか確認"],
        ["メモリ不足エラー",
         "翻訳エンジンをHybridまたはNLLBに変更（LLMより軽量）"],
        ["音声認識が途切れる",
         "音声認識メニューからテンポ設定を「slow」に変更"],
        [".appに変更が反映されない",
         "pyinstaller PLI.spec で再ビルドが必要"],
    ]
    story.append(make_table(
        ["症状", "対処法"],
        ts_rows, [45*mm, 110*mm]
    ))

    story.append(Spacer(1, 10*mm))
    story.append(HR())
    story.append(P("note",
        "本書は PLI v2.0.0 の仕様に基づいて作成されています。"
        "機能の詳細や最新の変更点についてはソースコードを参照してください。"
    ))
    story.append(P("note", "作成: 2026年3月14日  |  PLI - Private Link Interpreter"))

    return story


# ══════════════════════════════════════════════════════
#  PDF生成
# ══════════════════════════════════════════════════════
def add_page_number(canvas_obj, doc):
    """ページ番号とフッターを描画"""
    canvas_obj.saveState()
    page_num = canvas_obj.getPageNumber()
    # ページ番号
    canvas_obj.setFont(FONT_M, 8)
    canvas_obj.setFillColor(DGRAY)
    canvas_obj.drawCentredString(A4[0] / 2, 12*mm, f"- {page_num} -")
    # ヘッダー線
    if page_num > 1:
        canvas_obj.setStrokeColor(LGRAY)
        canvas_obj.setLineWidth(0.3)
        canvas_obj.line(20*mm, A4[1] - 15*mm, A4[0] - 20*mm, A4[1] - 15*mm)
        canvas_obj.setFont(FONT_M, 7)
        canvas_obj.drawString(20*mm, A4[1] - 13*mm, "PLI 仕様書兼取扱説明書")
        canvas_obj.drawRightString(A4[0] - 20*mm, A4[1] - 13*mm, "v2.0.0")
    canvas_obj.restoreState()


def main():
    output_path = os.path.join(
        os.path.dirname(__file__),
        "PLI_仕様書_取扱説明書.pdf"
    )

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=20*mm,
        bottomMargin=20*mm,
        leftMargin=20*mm,
        rightMargin=20*mm,
        title="PLI 仕様書兼取扱説明書",
        author="関 智幸",
        subject="PLI - Private Link Interpreter 仕様書兼取扱説明書",
    )

    story = build_content()
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"PDF生成完了: {output_path}")
    return output_path


if __name__ == "__main__":
    main()
