"""
PLI RecordingBar - 録音モード表示バー
コンパクトな水平バー: モードアイコン + バッファサイズ表示

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QMenu,
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QAction, QActionGroup, QMouseEvent

from core.recorder import RecordMode


# ---------------------------------------------------------------------------
# スタイル定数 — 平成初期レトロ（attorney_window.py準拠）
# ---------------------------------------------------------------------------

_BG       = "#d6d2c8"
_SURFACE  = "#e8e4da"
_SUNKEN   = "#c4c0b4"
_RAISED_L = "#f2eee6"
_RAISED_D = "#9e9a8e"
_TEXT     = "#1a1a10"
_DIM      = "#6a6658"
_WARN     = "#8a3a1a"
_ACCENT   = "#1a3a6a"

# モード別の表示設定
_MODE_CONFIG = {
    RecordMode.OFF: {
        "icon": "\u25cb",          # ○
        "label": "OFF",
        "color": _DIM,
        "bg": _SUNKEN,
    },
    RecordMode.VOLATILE: {
        "icon": "\u25cf",          # ●
        "label": "REC \u63ee\u767a",    # REC 揮発
        "color": _WARN,
        "bg": "#e8dcd0",
    },
    RecordMode.SAVE: {
        "icon": "\u25cf",          # ●
        "label": "REC \u4fdd\u5b58",    # REC 保存
        "color": "#aa2020",
        "bg": "#e8d0d0",
    },
}


class RecordingBar(QWidget):
    """録音モード表示バー

    Signals:
        mode_changed(RecordMode): モード変更時に発火
    Slots:
        update_size(str): バッファサイズ文字列を更新
        set_mode(RecordMode): 外部からモード設定
    """

    mode_changed = Signal(object)  # RecordMode

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._current_mode = RecordMode.OFF

        self._setup_ui()
        self._apply_mode_style()

    # ----- UI構築 -----

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(4)

        # モードアイコン
        self._icon_label = QLabel()
        self._icon_label.setFont(QFont("Menlo", 10))
        self._icon_label.setFixedWidth(14)
        self._icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon_label)

        # モードテキスト
        self._mode_label = QLabel()
        self._mode_label.setFont(QFont("Menlo", 9))
        layout.addWidget(self._mode_label)

        # バッファサイズ
        self._size_label = QLabel("")
        self._size_label.setFont(QFont("Menlo", 9))
        self._size_label.setStyleSheet(
            f"color: {_WARN}; font-size: 10px; padding: 0 4px;"
            f"border-left: 1px solid {_RAISED_D};"
        )
        layout.addWidget(self._size_label)

        layout.addStretch()
        self.setFixedHeight(20)
        self.setCursor(Qt.PointingHandCursor)

    # ----- スタイル適用 -----

    def _apply_mode_style(self):
        cfg = _MODE_CONFIG[self._current_mode]
        self._icon_label.setText(cfg["icon"])
        self._icon_label.setStyleSheet(f"color: {cfg['color']};")
        self._mode_label.setText(cfg["label"])
        self._mode_label.setStyleSheet(f"color: {cfg['color']}; font-size: 10px;")
        self.setStyleSheet(
            f"background-color: {cfg['bg']};"
            f"border-top: 1px solid {_RAISED_D};"
            f"border-bottom: 1px solid {_RAISED_L};"
        )
        # サイズ表示はOFF時にクリア
        if self._current_mode == RecordMode.OFF:
            self._size_label.setText("")

    # ----- コンテキストメニュー -----

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._show_mode_menu(event.globalPosition().toPoint())
        else:
            super().mousePressEvent(event)

    def _show_mode_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {_SURFACE}; color: {_TEXT};"
            f"  border: 1px solid {_RAISED_D}; font-size: 11px; }}"
            f"QMenu::item:selected {{ background-color: {_ACCENT}; color: white; }}"
        )
        group = QActionGroup(self)
        group.setExclusive(True)

        for mode, cfg in _MODE_CONFIG.items():
            action = QAction(f"{cfg['icon']} {cfg['label']}", self, checkable=True)
            action.setChecked(mode == self._current_mode)
            action.triggered.connect(lambda checked, m=mode: self._select_mode(m))
            group.addAction(action)
            menu.addAction(action)

        menu.exec(pos)

    def _select_mode(self, mode: RecordMode):
        if mode != self._current_mode:
            self._current_mode = mode
            self._apply_mode_style()
            self.mode_changed.emit(mode)

    # ----- Public API / Slots -----

    @Slot(str)
    def update_size(self, size_text: str):
        """バッファサイズ表示を更新する"""
        if self._current_mode != RecordMode.OFF:
            self._size_label.setText(size_text)
        else:
            self._size_label.setText("")

    @Slot(object)
    def set_mode(self, mode: RecordMode):
        """外部からモードを設定する（シグナルは発火しない）"""
        self._current_mode = mode
        self._apply_mode_style()

    @property
    def current_mode(self) -> RecordMode:
        return self._current_mode

    # ----- メニューバー統合ヘルパー -----

    def create_menu_actions(self, menubar) -> QMenu:
        """メニューバーに録音メニューを追加して返す

        attorney_window._setup_menubar() から呼び出す想定:
            rec_bar.create_menu_actions(menubar)
        """
        rec_menu = menubar.addMenu("録音(&R)")
        action_group = QActionGroup(self)
        action_group.setExclusive(True)

        rec_off = QAction("OFF", self, checkable=True)
        rec_off.setChecked(True)
        rec_off.triggered.connect(lambda: self._select_mode(RecordMode.OFF))
        action_group.addAction(rec_off)
        rec_menu.addAction(rec_off)

        rec_volatile = QAction("一時録音（揮発）", self, checkable=True)
        rec_volatile.triggered.connect(lambda: self._select_mode(RecordMode.VOLATILE))
        action_group.addAction(rec_volatile)
        rec_menu.addAction(rec_volatile)

        rec_save = QAction("録音保存", self, checkable=True)
        rec_save.triggered.connect(lambda: self._select_mode(RecordMode.SAVE))
        action_group.addAction(rec_save)
        rec_menu.addAction(rec_save)

        self._menu_action_group = action_group
        return rec_menu
