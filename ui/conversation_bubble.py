"""
PLI - ConversationBubble widget
会話ログの1エントリ表示ウィジェット

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
All rights reserved.
"""

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from core.models import Speaker, Utterance
from ui.font_config import fs as _fs
import ui.font_config as _font_cfg


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


class ConversationBubble(QFrame):
    """会話ログの1エントリ"""
    # 修正・取消ボタンのシグナル
    edit_clicked = Signal(object)    # self を送出
    cancel_clicked = Signal(object)  # self を送出
    # 同音異義の差し替え: (self, 元の表記, 新しい表記) を送出
    homophone_swap = Signal(object, str, str)

    def __init__(self, utterance: Utterance, show_actions: bool = False, parent=None):
        super().__init__(parent)
        self.utterance = utterance
        self._show_actions = show_actions  # 弁護人バブルに修正/取消ボタン表示
        self._action_row = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        is_attorney = self.utterance.speaker == Speaker.ATTORNEY
        v_pad = 1 if is_attorney else 3
        layout.setContentsMargins(0, v_pad, 0, v_pad)
        layout.setSpacing(0)

        bar = QFrame()
        bar.setFixedWidth(3)
        bar.setFixedHeight(16)
        bar.setStyleSheet(
            f"background-color: {_ACCENT if is_attorney else _DEF_CLR};"
        )
        marker_layout = QVBoxLayout()
        marker_layout.setContentsMargins(0, 4 if is_attorney else 6, 0, 0)
        marker_layout.addWidget(bar)
        marker_layout.addStretch()
        layout.addLayout(marker_layout)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(8, 1 if is_attorney else 2, 4, 1 if is_attorney else 2)
        text_layout.setSpacing(0)

        tag = "弁護人" if is_attorney else "相手"
        color = _ACCENT if is_attorney else _DEF_CLR
        header = QLabel(f"{self.utterance.timestamp}  {tag}")
        header.setStyleSheet(f"color: {_DIM}; font-size: {_fs(16)}; border: none; margin: 0; padding: 0;")
        header.setFont(QFont("Menlo", max(9, int(12 * _font_cfg.font_scale))))
        text_layout.addWidget(header)

        # テキスト選択可能にするヘルパー
        def _selectable(lbl: QLabel):
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            lbl.setCursor(Qt.IBeamCursor)

        # 原文（弁護人・相手統一サイズ）
        original = QLabel(self.utterance.original)
        original.setWordWrap(True)
        original.setStyleSheet(
            f"color: {color}; font-size: {_fs(28)}; font-weight: bold;"
            f" border: none; margin: 0; padding: 0;"
        )
        _selectable(original)
        text_layout.addWidget(original)

        # 同音異義の候補チップ（接見↔石鹸 等。出現したグループ語にだけ表示）
        self._add_homophone_chips(text_layout)

        # 英語中間文（ピボット翻訳時のみ表示）
        if self.utterance.intermediate_en:
            en_label = QLabel(f"🔗 {self.utterance.intermediate_en}")
            en_label.setWordWrap(True)
            en_label.setStyleSheet(
                f"color: #8899aa; font-size: {_fs(18)}; font-style: italic;"
                f" border: none; padding-left: 4px; margin: 0; padding-top: 0; padding-bottom: 0;"
            )
            _selectable(en_label)
            text_layout.addWidget(en_label)

        if self.utterance.translated:
            translated = QLabel(self.utterance.translated)
            translated.setWordWrap(True)
            translated.setStyleSheet(
                f"color: {_DIM}; font-size: {_fs(26)}; border: none;"
                f" margin: 0; padding: 0;"
            )
            _selectable(translated)
            text_layout.addWidget(translated)
            self._translated_label = translated

        # 不明語警告（あれば）
        if self.utterance.unknown_words:
            uw_text = ", ".join(self.utterance.unknown_words)
            uw_label = QLabel(f"⚠ 不明語: {uw_text}")
            uw_label.setWordWrap(True)
            uw_label.setStyleSheet(
                f"color: #e8a040; font-size: {_fs(18)}; font-weight: bold;"
                f" border: none; margin: 0; padding: 0;"
            )
            _selectable(uw_label)
            text_layout.addWidget(uw_label)

        # 翻訳経路（小さく表示）
        if self.utterance.translation_route:
            route_label = QLabel(f"⚙ {self.utterance.translation_route}")
            route_label.setStyleSheet(
                f"color: #556677; font-size: {_fs(12)}; border: none;"
                f" margin: 0; padding: 0;"
            )
            _selectable(route_label)
            text_layout.addWidget(route_label)

        # 修正 / 取消 ボタン行（弁護人・相手 両方）
        if self._show_actions:
            self._action_row = QHBoxLayout()
            self._action_row.setSpacing(6)
            self._action_row.setContentsMargins(0, 4, 0, 0)
            edit_btn = QPushButton("修正")
            edit_btn.setFixedHeight(26)
            edit_btn.setStyleSheet(
                f"background-color: {_BTN_EDIT}; color: {_BTN_TEXT};"
                f" font-size: 12px; padding: 2px 12px; border-radius: 3px;"
            )
            edit_btn.clicked.connect(lambda: self.edit_clicked.emit(self))
            cancel_btn = QPushButton("取消")
            cancel_btn.setFixedHeight(26)
            cancel_btn.setStyleSheet(
                f"background-color: {_BTN_NG}; color: {_BTN_TEXT};"
                f" font-size: 12px; padding: 2px 12px; border-radius: 3px;"
            )
            cancel_btn.clicked.connect(lambda: self.cancel_clicked.emit(self))
            self._action_row.addWidget(edit_btn)
            self._action_row.addWidget(cancel_btn)
            self._action_row.addStretch()
            text_layout.addLayout(self._action_row)

        layout.addLayout(text_layout, stretch=1)
        self.setStyleSheet("background: transparent; border: none;")

    def _add_homophone_chips(self, text_layout):
        """原文に同音異義グループ語があれば、別候補への差し替えチップを出す。

        例: 「接見」を含む発話に「🔄 石鹸?」を出し、タップで原文の接見を石鹸に
        差し替えて再翻訳する。バイアス過剰（接見↔石鹸）もバイアス失敗（交流↔勾留）
        も同じ仕組みで1タップ訂正できる。
        """
        try:
            from core.homophones import find_homophone_candidates
            cands = find_homophone_candidates(self.utterance.original or "")
        except Exception:
            cands = []
        if not cands:
            return
        chip_row = QHBoxLayout()
        chip_row.setSpacing(4)
        chip_row.setContentsMargins(4, 0, 0, 0)
        for surface, alts in cands:
            for alt in alts:
                btn = QPushButton(f"🔄 {surface}→{alt}?")
                btn.setFixedHeight(22)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip(f"「{surface}」を「{alt}」に直して再翻訳")
                btn.setStyleSheet(
                    f"background-color: {_SURFACE}; color: {_DIM};"
                    f" font-size: 11px; padding: 1px 8px; border: 1px solid {_RAISED_D};"
                    f" border-radius: 11px;"
                )
                btn.clicked.connect(
                    lambda _=False, s=surface, a=alt: self.homophone_swap.emit(self, s, a)
                )
                chip_row.addWidget(btn)
        chip_row.addStretch()
        text_layout.addLayout(chip_row)

    def contextMenuEvent(self, event):
        """右クリック → コピー＋同音異義差し替えメニュー"""
        from PySide6.QtWidgets import QMenu, QApplication
        menu = QMenu(self)
        copy_all = menu.addAction("📋 原文＋訳文をコピー")
        copy_orig = menu.addAction("原文のみコピー")
        copy_trans = menu.addAction("訳文のみコピー")
        menu.addSeparator()
        copy_conv = menu.addAction("📋 全会話コピー")
        # 同音異義の差し替え候補
        swap_actions = {}
        try:
            from core.homophones import find_homophone_candidates
            cands = find_homophone_candidates(self.utterance.original or "")
        except Exception:
            cands = []
        if cands:
            menu.addSeparator()
            for surface, alts in cands:
                for alt in alts:
                    a = menu.addAction(f"🔄 「{surface}」を「{alt}」に直して再翻訳")
                    swap_actions[a] = (surface, alt)
        action = menu.exec(event.globalPos())
        if action in swap_actions:
            s, a = swap_actions[action]
            self.homophone_swap.emit(self, s, a)
            return
        u = self.utterance
        if action == copy_all:
            parts = [u.original]
            if u.intermediate_en:
                parts.append(u.intermediate_en)
            if u.translated:
                parts.append(u.translated)
            QApplication.clipboard().setText("\n".join(parts))
        elif action == copy_orig:
            QApplication.clipboard().setText(u.original or "")
        elif action == copy_trans:
            QApplication.clipboard().setText(u.translated or "")
        elif action == copy_conv:
            # 親ウィンドウの全会話コピーを呼ぶ
            window = self.window()
            if hasattr(window, '_copy_all_conversation'):
                window._copy_all_conversation()

    def hide_actions(self):
        """修正/取消ボタンを非表示にする（次の発言が来たとき）"""
        if self._action_row:
            for i in range(self._action_row.count()):
                w = self._action_row.itemAt(i).widget()
                if w:
                    w.setVisible(False)

    def update_translation(self, text: str):
        if hasattr(self, '_translated_label'):
            self._translated_label.setText(text)
