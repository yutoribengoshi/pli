"""
PLI - ConversationLog widget
会話ログ表示・操作の自己完結ウィジェット

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QScrollArea, QPushButton, QMenu, QApplication,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QAction

from core.models import Speaker, Utterance
from ui.conversation_bubble import ConversationBubble
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


def _sunken_border(bg=_SUNKEN):
    return (
        f"background-color: {bg};"
        f"border-top: 1px solid {_RAISED_D};"
        f"border-left: 1px solid {_RAISED_D};"
        f"border-bottom: 1px solid {_RAISED_L};"
        f"border-right: 1px solid {_RAISED_L};"
    )


def _raised_border(bg=_SURFACE):
    return (
        f"background-color: {bg};"
        f"border-top: 1px solid {_RAISED_L};"
        f"border-left: 1px solid {_RAISED_L};"
        f"border-bottom: 1px solid {_RAISED_D};"
        f"border-right: 1px solid {_RAISED_D};"
    )


# ---------------------------------------------------------------------------
# ConversationLog — スクロール可能な会話バブルログ
# ---------------------------------------------------------------------------

class ConversationLog(QWidget):
    """会話ログ表示ウィジェット: スクロール領域 + バブル + ツールバー"""

    # 親ウィンドウが接続するシグナル
    bubble_edit = Signal(ConversationBubble)
    bubble_cancel = Signal(ConversationBubble)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_attorney_bubble: ConversationBubble | None = None
        self._last_defendant_bubble: ConversationBubble | None = None
        self._setup_ui()

    # -----------------------------------------------------------------
    # UI構築
    # -----------------------------------------------------------------

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        log_frame = QFrame()
        log_frame.setStyleSheet(
            f"{_sunken_border(_FIELD)} margin: 4px 6px;"
        )
        log_inner = QVBoxLayout(log_frame)
        log_inner.setContentsMargins(0, 0, 0, 0)

        # ログ上部ツールバー（全コピーボタン）
        log_toolbar = QHBoxLayout()
        log_toolbar.setContentsMargins(8, 2, 8, 0)
        log_toolbar.addStretch()
        copy_all_btn = QPushButton("📋 全会話コピー")
        copy_all_btn.setToolTip("会話ログ全体をクリップボードにコピー")
        copy_all_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {_SURFACE}; color: {_DIM};
                font-size: 11px; padding: 2px 10px;
                border: 1px solid {_RAISED_D}; border-radius: 3px;
            }}
            QPushButton:hover {{ background-color: {_RAISED_L}; color: {_TEXT}; }}
        """)
        copy_all_btn.clicked.connect(self._copy_all_conversation)
        log_toolbar.addWidget(copy_all_btn)
        log_inner.addLayout(log_toolbar)

        # スクロールエリア
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: {_FIELD}; }}
            QScrollBar:vertical {{
                background: {_SURFACE}; width: 14px;
                border-left: 1px solid {_RAISED_D};
            }}
            QScrollBar::handle:vertical {{
                {_raised_border(_BG)} min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 14px; {_raised_border(_BG)}
            }}
        """)
        self.log_container = QWidget()
        self.log_container.setStyleSheet(f"background-color: {_FIELD};")
        self.log_layout = QVBoxLayout(self.log_container)
        self.log_layout.setAlignment(Qt.AlignTop)
        self.log_layout.setSpacing(0)
        self.log_layout.setContentsMargins(8, 4, 8, 4)
        self.scroll_area.setWidget(self.log_container)

        # 右クリックコンテキストメニュー
        self.scroll_area.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scroll_area.customContextMenuRequested.connect(
            self._show_context_menu,
        )

        log_inner.addWidget(self.scroll_area)
        outer.addWidget(log_frame, stretch=1)

    # -----------------------------------------------------------------
    # 公開メソッド
    # -----------------------------------------------------------------

    def add_bubble(self, utterance: Utterance, *, show_actions: bool = True) -> ConversationBubble:
        """Utteranceからバブルを追加し、edit/cancelシグナルを中継接続して返す"""
        bubble = ConversationBubble(utterance, show_actions=show_actions)
        if utterance.speaker == Speaker.ATTORNEY:
            bubble.edit_clicked.connect(self._on_bubble_edit)
            bubble.cancel_clicked.connect(self._on_bubble_cancel)
            self._last_attorney_bubble = bubble
        else:
            bubble.edit_clicked.connect(self._on_bubble_edit)
            bubble.cancel_clicked.connect(self._on_bubble_cancel)
            self._last_defendant_bubble = bubble
        self.log_layout.addWidget(bubble)
        self._scroll_to_bottom()
        return bubble

    def clear_all(self):
        """全バブルを削除"""
        while self.log_layout.count():
            item = self.log_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._last_attorney_bubble = None
        self._last_defendant_bubble = None

    def get_all_text(self) -> str:
        """全会話をテキストとして取得"""
        lines = []
        for i in range(self.log_layout.count()):
            widget = self.log_layout.itemAt(i).widget()
            if not isinstance(widget, ConversationBubble):
                continue
            u = widget.utterance
            tag = "弁護人" if u.speaker == Speaker.ATTORNEY else "相手"
            lines.append(f"[{u.timestamp}] {tag}: {u.original}")
            if u.intermediate_en:
                lines.append(f"  (EN) {u.intermediate_en}")
            if u.translated:
                lines.append(f"  → {u.translated}")
            lines.append("")
        return "\n".join(lines)

    def rebuild_bubbles(self, conversation: list[Utterance]):
        """フォントサイズ変更後など、会話履歴から全バブルを再構築"""
        self.clear_all()
        for utt in conversation:
            self.add_bubble(utt, show_actions=True)

    @property
    def last_attorney_bubble(self) -> ConversationBubble | None:
        return self._last_attorney_bubble

    @last_attorney_bubble.setter
    def last_attorney_bubble(self, value):
        self._last_attorney_bubble = value

    @property
    def last_defendant_bubble(self) -> ConversationBubble | None:
        return self._last_defendant_bubble

    @last_defendant_bubble.setter
    def last_defendant_bubble(self, value):
        self._last_defendant_bubble = value

    # -----------------------------------------------------------------
    # スクロール
    # -----------------------------------------------------------------

    def _scroll_to_bottom(self):
        def _do_scroll():
            sb = self.scroll_area.verticalScrollBar()
            sb.setValue(sb.maximum())
        QTimer.singleShot(50, _do_scroll)
        QTimer.singleShot(200, _do_scroll)

    def scroll_to_bottom(self):
        """外部から呼び出し可能な公開版"""
        self._scroll_to_bottom()

    # -----------------------------------------------------------------
    # バブルイベント中継
    # -----------------------------------------------------------------

    def _on_bubble_edit(self, bubble: ConversationBubble):
        """バブルの「修正」→ 親ウィンドウへシグナル中継"""
        self.bubble_edit.emit(bubble)

    def _on_bubble_cancel(self, bubble: ConversationBubble):
        """バブルの「取消」→ 親ウィンドウへシグナル中継"""
        self.bubble_cancel.emit(bubble)

    def remove_bubble(self, bubble: ConversationBubble):
        """指定バブルをログから除去"""
        bubble.setParent(None)
        bubble.deleteLater()
        if self._last_attorney_bubble is bubble:
            self._last_attorney_bubble = None
        if self._last_defendant_bubble is bubble:
            self._last_defendant_bubble = None

    # -----------------------------------------------------------------
    # クリップボード
    # -----------------------------------------------------------------

    def _copy_all_conversation(self):
        """会話ログ全体をクリップボードにコピー"""
        text = self.get_all_text()
        if text.strip():
            QApplication.clipboard().setText(text)
        return bool(text.strip())

    # -----------------------------------------------------------------
    # 右クリック コンテキストメニュー
    # -----------------------------------------------------------------

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {_SURFACE}; color: {_TEXT};
                border: 1px solid {_RAISED_D};
                font-size: 12px; padding: 4px;
            }}
            QMenu::item:selected {{
                background-color: {_ACCENT}; color: white;
            }}
        """)

        copy_action = QAction("📋 全会話コピー", self)
        copy_action.triggered.connect(self._copy_all_conversation)
        menu.addAction(copy_action)

        clear_action = QAction("🗑 ログクリア", self)
        clear_action.triggered.connect(self.clear_all)
        menu.addAction(clear_action)

        menu.exec(self.scroll_area.mapToGlobal(pos))
