"""
PLI - Dialog classes
構文チェック・定型文編集・固有名詞辞書・辞書検索ダイアログ

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
All rights reserved.
"""

import os
import threading

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QListWidget, QComboBox,
    QInputDialog, QMessageBox, QRadioButton, QButtonGroup,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont

from core.models import SyntaxChunk
from core.interpreter import Interpreter


# ---------------------------------------------------------------------------
# スタイル定数 — 平成初期レトロ（暖灰・紺・深緑）
# ---------------------------------------------------------------------------

_BG       = "#d6d2c8"
_SURFACE  = "#e8e4da"
_SUNKEN   = "#c4c0b4"
_RAISED   = "#e0dcd2"
_RAISED_L = "#f2eee6"
_RAISED_D = "#9e9a8e"
_FIELD    = "#fffff4"
_TEXT     = "#1a1a10"
_DIM      = "#6a6658"
_ACCENT   = "#1a3a6a"
_DEF_CLR  = "#2a6a30"
_WARN     = "#8a3a1a"
_BTN_OK   = "#3a6a44"
_BTN_NG   = "#7a3a3a"
_BTN_EDIT = "#5a5a3a"
_BTN_SEND = "#3a4a6a"
_BTN_TEXT = "#f0ece0"


def _raised_border(bg=_SURFACE):
    return (
        f"background-color: {bg};"
        f"border-top: 1px solid {_RAISED_L};"
        f"border-left: 1px solid {_RAISED_L};"
        f"border-bottom: 1px solid {_RAISED_D};"
        f"border-right: 1px solid {_RAISED_D};"
    )

def _sunken_border(bg=_SUNKEN):
    return (
        f"background-color: {bg};"
        f"border-top: 1px solid {_RAISED_D};"
        f"border-left: 1px solid {_RAISED_D};"
        f"border-bottom: 1px solid {_RAISED_L};"
        f"border-right: 1px solid {_RAISED_L};"
    )


def _make_btn(label: str, bg: str) -> QPushButton:
    btn = QPushButton(label)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {bg}; color: {_BTN_TEXT};
            border-top: 1px solid {_RAISED_L};
            border-left: 1px solid {_RAISED_L};
            border-bottom: 1px solid {_RAISED_D};
            border-right: 1px solid {_RAISED_D};
            padding: 4px 14px;
            font-size: 11px;
        }}
        QPushButton:pressed {{
            border-top: 1px solid {_RAISED_D};
            border-left: 1px solid {_RAISED_D};
            border-bottom: 1px solid {_RAISED_L};
            border-right: 1px solid {_RAISED_L};
        }}
    """)
    return btn


# ---------------------------------------------------------------------------
# エディタ用共通スタイル
# ---------------------------------------------------------------------------

_EDITOR_BTN = f"""
    QPushButton {{
        background-color: {_SURFACE}; color: {_TEXT};
        border-top: 1px solid {_RAISED_L};
        border-left: 1px solid {_RAISED_L};
        border-bottom: 1px solid {_RAISED_D};
        border-right: 1px solid {_RAISED_D};
        padding: 3px 10px; font-size: 11px;
    }}
    QPushButton:hover {{ background-color: {_ACCENT}; color: white; }}
    QPushButton:disabled {{ color: {_RAISED_D}; }}
"""

_EDITOR_LIST = f"""
    QListWidget {{
        background-color: {_FIELD}; color: {_TEXT};
        border-top: 1px solid {_RAISED_D};
        border-left: 1px solid {_RAISED_D};
        border-bottom: 1px solid {_RAISED_L};
        border-right: 1px solid {_RAISED_L};
        font-size: 12px; padding: 2px;
    }}
    QListWidget::item {{ padding: 3px 4px; }}
    QListWidget::item:selected {{
        background-color: {_ACCENT}; color: white;
    }}
"""

_EDITOR_INPUT = f"""
    QLineEdit {{
        background-color: {_FIELD}; color: {_TEXT};
        border-top: 1px solid {_RAISED_D};
        border-left: 1px solid {_RAISED_D};
        border-bottom: 1px solid {_RAISED_L};
        border-right: 1px solid {_RAISED_L};
        padding: 3px 6px; font-size: 12px;
    }}
"""

_EDITOR_TEXTEDIT = f"""
    QTextEdit {{
        background-color: {_FIELD}; color: {_TEXT};
        border-top: 1px solid {_RAISED_D};
        border-left: 1px solid {_RAISED_D};
        border-bottom: 1px solid {_RAISED_L};
        border-right: 1px solid {_RAISED_L};
        padding: 4px 6px; font-size: 12px;
    }}
"""

_EDITOR_COMBO = f"""
    QComboBox {{
        background-color: {_FIELD}; color: {_TEXT};
        border-top: 1px solid {_RAISED_D};
        border-left: 1px solid {_RAISED_D};
        border-bottom: 1px solid {_RAISED_L};
        border-right: 1px solid {_RAISED_L};
        padding: 2px 6px; font-size: 12px;
    }}
    QComboBox::drop-down {{
        border-left: 1px solid {_RAISED_D}; width: 18px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {_FIELD}; color: {_TEXT};
        selection-background-color: {_ACCENT}; selection-color: white;
    }}
"""


# ---------------------------------------------------------------------------
# 構文反転チェック ダイアログ
# ---------------------------------------------------------------------------

class SyntaxCheckDialog(QDialog):
    confirmed = Signal(str, str)

    def __init__(self, english_text: str, chunks: list[SyntaxChunk],
                 interpreter: Interpreter, parent=None):
        super().__init__(parent)
        self.english_text = english_text
        self.chunks = chunks
        self.interpreter = interpreter
        self.setWindowTitle("手動修正")
        self.setMinimumSize(600, 500)
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(f"background-color: {_BG}; color: {_TEXT};")
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        header = QLabel("通訳停止中 — 手動修正モード")
        header.setStyleSheet(
            f"color: {_WARN}; font-size: 13px; font-weight: bold;"
            f"padding: 4px 6px; {_raised_border(_SURFACE)}"
        )
        layout.addWidget(header)

        self.orig_edit = QLineEdit(self.english_text)
        self.orig_edit.setStyleSheet(
            f"color: {_TEXT}; font-size: 13px; padding: 6px;"
            f"background-color: {_FIELD};"
            f"border-top: 1px solid {_RAISED_D};"
            f"border-left: 1px solid {_RAISED_D};"
            f"border-bottom: 1px solid {_RAISED_L};"
            f"border-right: 1px solid {_RAISED_L};"
        )
        self.orig_edit.setPlaceholderText("原文を直接修正できます")
        layout.addWidget(self.orig_edit)

        section_label = QLabel("構文チェック")
        section_label.setStyleSheet(
            f"color: {_DIM}; font-size: 10px;"
            f"letter-spacing: 2px; padding-top: 4px;"
        )
        section_label.setFont(QFont("Menlo", 9))
        layout.addWidget(section_label)

        self.table = QTableWidget(len(self.chunks), 2)
        self.table.setHorizontalHeaderLabels(["原文", "日本語"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                {_sunken_border(_FIELD)}
                color: {_TEXT};
                gridline-color: {_SUNKEN};
                font-size: 12px;
            }}
            QTableWidget::item {{ padding: 4px; }}
            QHeaderView::section {{
                {_raised_border(_BG)}
                color: {_DIM};
                padding: 4px;
                font-size: 10px;
            }}
        """)
        for i, chunk in enumerate(self.chunks):
            en_item = QTableWidgetItem(chunk.english)
            en_item.setFlags(en_item.flags() | Qt.ItemIsEditable)
            ja_item = QTableWidgetItem(chunk.japanese)
            ja_item.setFlags(ja_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(i, 0, en_item)
            self.table.setItem(i, 1, ja_item)
        layout.addWidget(self.table)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet(
            f"color: {_TEXT}; font-size: 12px; padding: 4px;"
        )
        layout.addWidget(self.result_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)
        for label, color, handler in [
            ("再生成(R)", _BTN_SEND, self._on_rebuild),
            ("確定(Enter)", _BTN_OK,   self._on_confirm),
            ("戻る(Esc)",   _BG,       self.reject),
        ]:
            btn = _make_btn(label, color)
            btn.clicked.connect(handler)
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _get_current_chunks(self) -> list[SyntaxChunk]:
        chunks = []
        for i in range(self.table.rowCount()):
            en = self.table.item(i, 0).text()
            ja = self.table.item(i, 1).text()
            chunks.append(SyntaxChunk(english=en, japanese=ja, index=i))
        return chunks

    def _on_rebuild(self):
        # 上部の原文が書き換わっていたら、それを優先して再翻訳
        edited_orig = self.orig_edit.text().strip()
        if edited_orig and edited_orig != self.english_text:
            new_english = edited_orig
            new_japanese = self.interpreter.retranslate(new_english)
        else:
            chunks = self._get_current_chunks()
            new_english = self.interpreter.reconstruct(chunks)
            new_japanese = self.interpreter.retranslate(new_english)
        self.result_label.setText(f"修正後: {new_english}\n和訳: {new_japanese}")
        self._rebuilt_en = new_english
        self._rebuilt_ja = new_japanese

    def _on_confirm(self):
        if hasattr(self, '_rebuilt_en'):
            self.confirmed.emit(self._rebuilt_en, self._rebuilt_ja)
        else:
            # 上部の原文だけ直接修正した場合 → 再翻訳して確定
            edited_orig = self.orig_edit.text().strip()
            if edited_orig and edited_orig != self.english_text:
                new_ja = self.interpreter.retranslate(edited_orig)
                self.confirmed.emit(edited_orig, new_ja)
        self.accept()


# ---------------------------------------------------------------------------
# 定型文編集ダイアログ
# ---------------------------------------------------------------------------

class PhraseEditorDialog(QDialog):
    """定型文の追加・編集・削除を行うGUIダイアログ"""

    def __init__(self, phrases_data: dict, save_callback, parent=None):
        super().__init__(parent)
        self._data = phrases_data  # {"categories": [...]}
        self._save_cb = save_callback
        self._dirty = False
        self.setWindowTitle("📋 定型文の管理")
        self.setMinimumSize(620, 480)
        self.setStyleSheet(f"QDialog {{ background-color: {_BG}; color: {_TEXT}; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ===================== 上段: カテゴリ選択 =====================
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("カテゴリ:"))
        self._cat_combo = QComboBox()
        self._cat_combo.setStyleSheet(_EDITOR_COMBO)
        self._cat_combo.currentIndexChanged.connect(self._on_cat_changed)
        cat_row.addWidget(self._cat_combo, 1)

        add_cat_btn = QPushButton("＋ カテゴリ追加")
        add_cat_btn.setStyleSheet(_EDITOR_BTN)
        add_cat_btn.clicked.connect(self._on_add_category)
        cat_row.addWidget(add_cat_btn)

        del_cat_btn = QPushButton("－ カテゴリ削除")
        del_cat_btn.setStyleSheet(_EDITOR_BTN)
        del_cat_btn.clicked.connect(self._on_del_category)
        cat_row.addWidget(del_cat_btn)
        root.addLayout(cat_row)

        # ===================== 中段: フレーズ一覧 + 編集 =====================
        mid = QHBoxLayout()

        # --- 左: フレーズリスト ---
        left = QVBoxLayout()
        left.addWidget(QLabel("フレーズ一覧:"))
        self._phrase_list = QListWidget()
        self._phrase_list.setStyleSheet(_EDITOR_LIST)
        self._phrase_list.currentRowChanged.connect(self._on_phrase_selected)
        left.addWidget(self._phrase_list)

        list_btn_row = QHBoxLayout()
        add_ph_btn = QPushButton("＋ 追加")
        add_ph_btn.setStyleSheet(_EDITOR_BTN)
        add_ph_btn.clicked.connect(self._on_add_phrase)
        list_btn_row.addWidget(add_ph_btn)

        del_ph_btn = QPushButton("－ 削除")
        del_ph_btn.setStyleSheet(_EDITOR_BTN)
        del_ph_btn.clicked.connect(self._on_del_phrase)
        list_btn_row.addWidget(del_ph_btn)

        up_btn = QPushButton("▲")
        up_btn.setStyleSheet(_EDITOR_BTN)
        up_btn.setFixedWidth(30)
        up_btn.clicked.connect(lambda: self._on_move(-1))
        list_btn_row.addWidget(up_btn)

        down_btn = QPushButton("▼")
        down_btn.setStyleSheet(_EDITOR_BTN)
        down_btn.setFixedWidth(30)
        down_btn.clicked.connect(lambda: self._on_move(1))
        list_btn_row.addWidget(down_btn)

        list_btn_row.addStretch()
        left.addLayout(list_btn_row)
        mid.addLayout(left, 2)

        # --- 右: 編集フォーム ---
        right = QVBoxLayout()
        right.addWidget(QLabel("ラベル（メニュー表示名）:"))
        self._label_edit = QLineEdit()
        self._label_edit.setStyleSheet(_EDITOR_INPUT)
        self._label_edit.setPlaceholderText("例: 黙秘権の告知")
        self._label_edit.textChanged.connect(self._on_field_changed)
        right.addWidget(self._label_edit)

        right.addWidget(QLabel("本文（送信される日本語テキスト）:"))
        self._text_edit = QTextEdit()
        self._text_edit.setStyleSheet(_EDITOR_TEXTEDIT)
        self._text_edit.setPlaceholderText("例: あなたには黙秘権があります。...")
        self._text_edit.textChanged.connect(self._on_field_changed)
        right.addWidget(self._text_edit)

        apply_btn = QPushButton("この内容で更新")
        apply_btn.setStyleSheet(_EDITOR_BTN)
        apply_btn.clicked.connect(self._on_apply_edit)
        right.addWidget(apply_btn)

        mid.addLayout(right, 3)
        root.addLayout(mid)

        # ===================== 下段: 保存 / 閉じる =====================
        bottom = QHBoxLayout()
        bottom.addStretch()

        save_btn = QPushButton("💾 保存")
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_BTN_SEND}; color: white;
                border-top: 1px solid {_RAISED_L};
                border-left: 1px solid {_RAISED_L};
                border-bottom: 1px solid {_RAISED_D};
                border-right: 1px solid {_RAISED_D};
                padding: 5px 20px; font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {_ACCENT}; }}
        """)
        save_btn.clicked.connect(self._on_save)
        bottom.addWidget(save_btn)

        close_btn = QPushButton("閉じる")
        close_btn.setStyleSheet(_EDITOR_BTN)
        close_btn.clicked.connect(self._on_close)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        # --- 初期表示 ---
        self._populate_categories()

    # ---------- populate helpers ----------

    def _populate_categories(self):
        self._cat_combo.blockSignals(True)
        self._cat_combo.clear()
        for cat in self._data.get("categories", []):
            icon = cat.get("icon", "")
            self._cat_combo.addItem(f'{icon} {cat["name"]}')
        self._cat_combo.blockSignals(False)
        if self._cat_combo.count() > 0:
            self._cat_combo.setCurrentIndex(0)
            self._on_cat_changed(0)
        else:
            self._phrase_list.clear()
            self._clear_form()

    def _populate_phrases(self, cat_idx: int):
        self._phrase_list.blockSignals(True)
        self._phrase_list.clear()
        cats = self._data.get("categories", [])
        if 0 <= cat_idx < len(cats):
            for ph in cats[cat_idx].get("phrases", []):
                self._phrase_list.addItem(ph["label"])
        self._phrase_list.blockSignals(False)
        if self._phrase_list.count() > 0:
            self._phrase_list.setCurrentRow(0)
        else:
            self._clear_form()

    def _clear_form(self):
        self._label_edit.blockSignals(True)
        self._text_edit.blockSignals(True)
        self._label_edit.clear()
        self._text_edit.clear()
        self._label_edit.blockSignals(False)
        self._text_edit.blockSignals(False)

    def _current_cat(self):
        idx = self._cat_combo.currentIndex()
        cats = self._data.get("categories", [])
        return cats[idx] if 0 <= idx < len(cats) else None

    def _current_phrase(self):
        cat = self._current_cat()
        if not cat:
            return None
        row = self._phrase_list.currentRow()
        phrases = cat.get("phrases", [])
        return phrases[row] if 0 <= row < len(phrases) else None

    # ---------- slots ----------

    def _on_cat_changed(self, idx):
        self._populate_phrases(idx)

    def _on_phrase_selected(self, row):
        ph = self._current_phrase()
        if ph:
            self._label_edit.blockSignals(True)
            self._text_edit.blockSignals(True)
            self._label_edit.setText(ph.get("label", ""))
            self._text_edit.setPlainText(ph.get("text", ""))
            self._label_edit.blockSignals(False)
            self._text_edit.blockSignals(False)
        else:
            self._clear_form()

    def _on_field_changed(self):
        pass  # リアルタイム反映はしない（「この内容で更新」ボタンで確定）

    def _on_apply_edit(self):
        """右側フォームの内容を現在選択中のフレーズに反映"""
        ph = self._current_phrase()
        if not ph:
            return
        new_label = self._label_edit.text().strip()
        new_text = self._text_edit.toPlainText().strip()
        if not new_label:
            QMessageBox.warning(self, "入力エラー", "ラベルを入力してください。")
            return
        if not new_text:
            QMessageBox.warning(self, "入力エラー", "本文を入力してください。")
            return
        ph["label"] = new_label
        ph["text"] = new_text
        self._dirty = True
        # リスト表示も更新
        row = self._phrase_list.currentRow()
        if row >= 0:
            self._phrase_list.item(row).setText(new_label)

    def _on_add_phrase(self):
        cat = self._current_cat()
        if not cat:
            QMessageBox.information(self, "情報", "先にカテゴリを追加してください。")
            return
        label, ok = QInputDialog.getText(self, "フレーズ追加", "ラベル名:")
        if not ok or not label.strip():
            return
        new_ph = {"label": label.strip(), "text": ""}
        cat.setdefault("phrases", []).append(new_ph)
        self._dirty = True
        self._populate_phrases(self._cat_combo.currentIndex())
        self._phrase_list.setCurrentRow(self._phrase_list.count() - 1)

    def _on_del_phrase(self):
        cat = self._current_cat()
        row = self._phrase_list.currentRow()
        if not cat or row < 0:
            return
        phrases = cat.get("phrases", [])
        if 0 <= row < len(phrases):
            name = phrases[row]["label"]
            r = QMessageBox.question(
                self, "確認", f"「{name}」を削除しますか？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if r == QMessageBox.Yes:
                phrases.pop(row)
                self._dirty = True
                self._populate_phrases(self._cat_combo.currentIndex())

    def _on_move(self, direction: int):
        cat = self._current_cat()
        row = self._phrase_list.currentRow()
        if not cat or row < 0:
            return
        phrases = cat.get("phrases", [])
        new_row = row + direction
        if 0 <= new_row < len(phrases):
            phrases[row], phrases[new_row] = phrases[new_row], phrases[row]
            self._dirty = True
            self._populate_phrases(self._cat_combo.currentIndex())
            self._phrase_list.setCurrentRow(new_row)

    def _on_add_category(self):
        name, ok = QInputDialog.getText(self, "カテゴリ追加", "カテゴリ名:")
        if not ok or not name.strip():
            return
        icon, ok2 = QInputDialog.getText(self, "アイコン", "絵文字（省略可）:", text="📝")
        if not ok2:
            icon = ""
        new_cat = {"name": name.strip(), "icon": icon.strip(), "phrases": []}
        self._data.setdefault("categories", []).append(new_cat)
        self._dirty = True
        self._populate_categories()
        self._cat_combo.setCurrentIndex(self._cat_combo.count() - 1)

    def _on_del_category(self):
        idx = self._cat_combo.currentIndex()
        cats = self._data.get("categories", [])
        if idx < 0 or idx >= len(cats):
            return
        name = cats[idx]["name"]
        r = QMessageBox.question(
            self, "確認", f"カテゴリ「{name}」とその中のフレーズを全て削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if r == QMessageBox.Yes:
            cats.pop(idx)
            self._dirty = True
            self._populate_categories()

    def _on_save(self):
        self._save_cb(self._data)
        self._dirty = False
        QMessageBox.information(self, "保存完了", "定型文を保存しました。")

    def _on_close(self):
        if self._dirty:
            r = QMessageBox.question(
                self, "未保存の変更",
                "変更が保存されていません。保存しますか？",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if r == QMessageBox.Yes:
                self._on_save()
            elif r == QMessageBox.Cancel:
                return
        self.accept()


# ---------------------------------------------------------------------------
# 固有名詞辞書（グロッサリー）エディタ
# ---------------------------------------------------------------------------

class GlossaryEditorDialog(QDialog):
    """固有名詞辞書の編集ダイアログ — 人名・組織名等の訳語を登録"""

    def __init__(self, interpreter, parent=None):
        super().__init__(parent)
        self._interpreter = interpreter
        self.setWindowTitle("③ 固有名詞辞書")
        self.resize(520, 420)
        self.setStyleSheet(f"""
            QDialog {{ background-color: {_SURFACE}; }}
            QLabel {{ color: {_TEXT}; }}
            QTableWidget {{
                background-color: white; color: {_TEXT};
                gridline-color: #999; font-size: 12px;
                selection-background-color: {_ACCENT};
                selection-color: white;
            }}
            QHeaderView::section {{
                background-color: {_SURFACE}; color: {_TEXT};
                border: 1px solid #999; padding: 4px;
                font-weight: bold; font-size: 11px;
            }}
            QPushButton {{
                background-color: {_SURFACE}; color: {_TEXT};
                border-top: 1px solid {_RAISED_L}; border-left: 1px solid {_RAISED_L};
                border-bottom: 1px solid {_RAISED_D}; border-right: 1px solid {_RAISED_D};
                padding: 4px 12px; font-size: 11px;
            }}
            QPushButton:hover {{ background-color: #d8d0c0; }}
            QLineEdit {{
                background-color: white; color: {_TEXT};
                border: 1px solid #999; padding: 3px;
            }}
        """)

        layout = QVBoxLayout(self)

        # 説明ラベル
        desc = QLabel("人名・組織名など、翻訳エンジンが誤訳しやすい語句を登録します。\n"
                       "登録した語句は翻訳時に自動的に正しい訳語に置き換えられます。")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 11px; margin-bottom: 6px;")
        layout.addWidget(desc)

        # テーブル
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["日本語", "外国語（訳語）"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self._table)

        # 追加行
        add_row = QHBoxLayout()
        self._ja_input = QLineEdit()
        self._ja_input.setPlaceholderText("日本語（例: 関智幸）")
        self._foreign_input = QLineEdit()
        self._foreign_input.setPlaceholderText("外国語（例: Tomoyuki Seki）")
        add_btn = QPushButton("＋ 追加")
        add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self._ja_input)
        add_row.addWidget(self._foreign_input)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        # ボタン行
        btn_row = QHBoxLayout()
        del_btn = QPushButton("選択行を削除")
        del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()

        save_btn = QPushButton("💾 保存")
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_BTN_OK}; color: white;
                border-top: 1px solid {_RAISED_L}; border-left: 1px solid {_RAISED_L};
                border-bottom: 1px solid {_RAISED_D}; border-right: 1px solid {_RAISED_D};
                padding: 4px 16px; font-weight: bold;
            }}
        """)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        close_btn = QPushButton("閉じる")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        # データ読込
        self._populate()

    def _populate(self):
        entries = self._interpreter.glossary
        self._table.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            self._table.setItem(i, 0, QTableWidgetItem(entry.get("ja", "")))
            self._table.setItem(i, 1, QTableWidgetItem(entry.get("foreign", "")))

    def _on_add(self):
        ja = self._ja_input.text().strip()
        foreign = self._foreign_input.text().strip()
        if not ja or not foreign:
            return
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(ja))
        self._table.setItem(row, 1, QTableWidgetItem(foreign))
        self._ja_input.clear()
        self._foreign_input.clear()
        self._ja_input.setFocus()

    def _on_delete(self):
        row = self._table.currentRow()
        if row >= 0:
            self._table.removeRow(row)

    def _on_save(self):
        entries = []
        for i in range(self._table.rowCount()):
            ja_item = self._table.item(i, 0)
            foreign_item = self._table.item(i, 1)
            ja = ja_item.text().strip() if ja_item else ""
            foreign = foreign_item.text().strip() if foreign_item else ""
            if ja and foreign:
                entries.append({"ja": ja, "foreign": foreign, "type": "name"})
        self._interpreter.save_glossary(entries)
        QMessageBox.information(self, "保存完了", f"{len(entries)}件の固有名詞を保存しました。")


# ---------------------------------------------------------------------------
# 辞書検索ダイアログ
# ---------------------------------------------------------------------------

class DictionaryDialog(QDialog):
    """法律用語辞書 + 翻訳エンジンのフォールバック検索ダイアログ"""

    _result_ready = Signal(str)

    def __init__(self, interpreter, parent=None):
        super().__init__(parent)
        self.interpreter = interpreter
        self._legal_dict = self._load_legal_dict()
        self.setWindowTitle("📖 辞書検索")
        self.setMinimumSize(420, 340)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {_BG}; color: {_TEXT};
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # --- 方向選択 ---
        dir_row = QHBoxLayout()
        self._dir_group = QButtonGroup(self)
        self._rb_ja_foreign = QRadioButton("日本語 → 外国語")
        self._rb_foreign_ja = QRadioButton("外国語 → 日本語")
        self._rb_ja_foreign.setChecked(True)
        self._dir_group.addButton(self._rb_ja_foreign, 0)
        self._dir_group.addButton(self._rb_foreign_ja, 1)
        for rb in (self._rb_ja_foreign, self._rb_foreign_ja):
            rb.setStyleSheet(f"color: {_TEXT}; font-size: 12px; border: none;")
            dir_row.addWidget(rb)
        dir_row.addStretch()
        layout.addLayout(dir_row)

        # --- 検索入力行 ---
        search_row = QHBoxLayout()
        self._search_field = QLineEdit()
        self._search_field.setPlaceholderText("単語・フレーズを入力...")
        self._search_field.setStyleSheet(f"""
            QLineEdit {{
                background-color: {_FIELD}; color: {_TEXT};
                border-top: 1px solid {_RAISED_D};
                border-left: 1px solid {_RAISED_D};
                border-bottom: 1px solid {_RAISED_L};
                border-right: 1px solid {_RAISED_L};
                padding: 4px 8px; font-size: 13px;
            }}
        """)
        self._search_field.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_field)

        search_btn = QPushButton("検索")
        search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_SURFACE}; color: {_TEXT};
                border-top: 1px solid {_RAISED_L};
                border-left: 1px solid {_RAISED_L};
                border-bottom: 1px solid {_RAISED_D};
                border-right: 1px solid {_RAISED_D};
                padding: 4px 12px; font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {_ACCENT}; color: white; }}
        """)
        search_btn.clicked.connect(self._on_search)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        # --- 結果表示 ---
        self._result_area = QTextEdit()
        self._result_area.setReadOnly(True)
        self._result_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {_FIELD}; color: {_TEXT};
                border-top: 1px solid {_RAISED_D};
                border-left: 1px solid {_RAISED_D};
                border-bottom: 1px solid {_RAISED_L};
                border-right: 1px solid {_RAISED_L};
                padding: 6px; font-size: 14px; line-height: 1.5;
            }}
        """)
        self._result_area.setPlaceholderText("検索結果がここに表示されます...")
        layout.addWidget(self._result_area)

        # --- 閉じるボタン ---
        close_btn = QPushButton("閉じる")
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_SURFACE}; color: {_TEXT};
                border-top: 1px solid {_RAISED_L};
                border-left: 1px solid {_RAISED_L};
                border-bottom: 1px solid {_RAISED_D};
                border-right: 1px solid {_RAISED_D};
                padding: 4px 16px; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {_ACCENT}; color: white; }}
        """)
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    @staticmethod
    def _load_legal_dict() -> list[dict]:
        """法律用語辞書を読み込む（core.legal_dict に集約済み）"""
        from core.legal_dict import load_legal_dict
        return list(load_legal_dict())

    def _search_dict(self, query: str, ja_to_foreign: bool) -> list[dict]:
        """辞書から部分一致で検索。結果は [{ja, en, category}, ...]"""
        results = []
        q = query.lower().strip()
        for entry in self._legal_dict:
            if ja_to_foreign:
                if q in entry.get("ja", ""):
                    results.append(entry)
            else:
                if q in entry.get("en", "").lower():
                    results.append(entry)
        return results

    def _on_search(self):
        query = self._search_field.text().strip()
        if not query:
            return
        tgt = self.interpreter.target_lang
        ja_to_foreign = self._rb_ja_foreign.isChecked()
        if ja_to_foreign:
            src, dst = "ja", tgt
            direction = f"日→{tgt}"
        else:
            src, dst = tgt, "ja"
            direction = f"{tgt}→日"

        # 1. まず法律用語辞書から検索
        dict_hits = self._search_dict(query, ja_to_foreign)
        if dict_hits:
            for hit in dict_hits[:10]:  # 最大10件
                cat = hit.get("category", "")
                cat_tag = f" <span style='color:#8899aa;'>[{cat}]</span>" if cat else ""
                if ja_to_foreign:
                    self._result_area.append(
                        f"<b>[{direction}]</b> {hit['ja']}{cat_tag}<br>"
                        f"  → <b>{hit['en']}</b>"
                    )
                else:
                    self._result_area.append(
                        f"<b>[{direction}]</b> {hit['en']}{cat_tag}<br>"
                        f"  → <b>{hit['ja']}</b>"
                    )
            # カーソルを末尾に
            cursor = self._result_area.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._result_area.setTextCursor(cursor)
            return

        # 2. 辞書にない場合は翻訳エンジンにフォールバック
        self._result_area.append(f"<b>[{direction}]</b> {query}")
        self._result_area.append("  <span style='color:#8899aa;'>辞書に該当なし — 翻訳エンジンで検索中...</span>")
        self._result_area.repaint()

        try:
            self._result_ready.disconnect()
        except RuntimeError:
            pass
        self._result_ready.connect(self._show_result)

        def _run():
            try:
                result = self.interpreter.engine.translate(query, src, dst)
                self._result_ready.emit(result)
            except Exception as e:
                self._result_ready.emit(f"[エラー] {e}")

        threading.Thread(target=_run, daemon=True).start()

    @Slot(str)
    def _show_result(self, result: str):
        html = self._result_area.toHtml()
        html = html.replace(
            "辞書に該当なし — 翻訳エンジンで検索中...",
            f"辞書に該当なし — 翻訳エンジン: <b>{result}</b>"
        )
        self._result_area.setHtml(html)
        cursor = self._result_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._result_area.setTextCursor(cursor)
