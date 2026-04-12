"""
PLI STT Control Widget - 音声認識コントロール
平成初期レトロUI — 一太郎的な業務用ソフトの佇まい

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.

AttorneyWindow から抽出した STT 制御ウィジェット:
  - マイクON/OFFトグル + 状態表示ラベル
  - 言語モード切替 (auto / attorney / defendant)
  - マイク感度プリセット (high / normal / low)
  - 発話テンポプリセット (slow / normal / fast)
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel,
    QMenu,
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QAction, QActionGroup


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
_BTN_TEXT = "#f0ece0"

_BTN_STT_ON = (
    f"QPushButton {{"
    f"  background-color: {_BTN_NG}; color: {_BTN_TEXT};"
    f"  border-top: 1px solid {_RAISED_L};"
    f"  border-left: 1px solid {_RAISED_L};"
    f"  border-bottom: 1px solid {_RAISED_D};"
    f"  border-right: 1px solid {_RAISED_D};"
    f"  padding: 2px 10px; font-size: 11px;"
    f"}}"
    f"QPushButton:pressed {{"
    f"  border-top: 1px solid {_RAISED_D};"
    f"  border-left: 1px solid {_RAISED_D};"
    f"  border-bottom: 1px solid {_RAISED_L};"
    f"  border-right: 1px solid {_RAISED_L};"
    f"}}"
)

_BTN_STT_OFF = (
    f"QPushButton {{"
    f"  background-color: {_ACCENT}; color: {_BTN_TEXT};"
    f"  border-top: 1px solid {_RAISED_L};"
    f"  border-left: 1px solid {_RAISED_L};"
    f"  border-bottom: 1px solid {_RAISED_D};"
    f"  border-right: 1px solid {_RAISED_D};"
    f"  padding: 2px 10px; font-size: 11px;"
    f"}}"
    f"QPushButton:pressed {{"
    f"  border-top: 1px solid {_RAISED_D};"
    f"  border-left: 1px solid {_RAISED_D};"
    f"  border-bottom: 1px solid {_RAISED_L};"
    f"  border-right: 1px solid {_RAISED_L};"
    f"}}"
)

_MODE_STYLE_AUTO = (
    f"color: {_DIM}; font-size: 10px; padding: 0 6px;"
    f"border-left: 1px solid {_RAISED_D};"
)
_MODE_STYLE_ATTORNEY = (
    f"color: {_ACCENT}; font-size: 10px; font-weight: bold; padding: 0 6px;"
    f"border-left: 1px solid {_RAISED_D};"
)
_MODE_STYLE_DEFENDANT = (
    f"color: {_DEF_CLR}; font-size: 10px; font-weight: bold; padding: 0 6px;"
    f"border-left: 1px solid {_RAISED_D};"
)


# ---------------------------------------------------------------------------
# STTControl ウィジェット
# ---------------------------------------------------------------------------

class STTControl(QWidget):
    """音声認識コントロール: トグルボタン + モード表示 + 設定メニュー

    Signals:
        stt_toggled(bool)         : マイクON/OFF
        sensitivity_changed(str)  : 感度プリセット (high/normal/low)
        tempo_changed(str)        : テンポプリセット (slow/normal/fast)
        lang_mode_changed(str)    : 言語モード (auto/attorney/defendant)
    """

    stt_toggled = Signal(bool)
    sensitivity_changed = Signal(str)
    tempo_changed = Signal(str)
    lang_mode_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._stt_active = False
        self._stt_lang_mode = "auto"
        self._models_ready = False

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI構築
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # トグルボタン
        self._toggle_btn = QPushButton("🎤 マイクON")
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setStyleSheet(_BTN_STT_OFF)
        self._toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn)

        # モード表示ラベル
        self._mode_label = QLabel("")
        self._mode_label.setFont(QFont("Menlo", 9))
        self._mode_label.setStyleSheet(_MODE_STYLE_AUTO)
        self._mode_label.setVisible(False)
        layout.addWidget(self._mode_label)

        # 設定メニューボタン（右クリックまたはクリックで展開）
        self._menu_btn = QPushButton("▼")
        self._menu_btn.setFixedWidth(24)
        self._menu_btn.setCursor(Qt.PointingHandCursor)
        self._menu_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {_SURFACE}; color: {_DIM};"
            f"  border-top: 1px solid {_RAISED_L};"
            f"  border-left: 1px solid {_RAISED_L};"
            f"  border-bottom: 1px solid {_RAISED_D};"
            f"  border-right: 1px solid {_RAISED_D};"
            f"  padding: 2px; font-size: 9px;"
            f"}}"
        )
        self._menu_btn.clicked.connect(self._show_menu)
        layout.addWidget(self._menu_btn)

        self._build_menu()

    def _build_menu(self):
        """設定メニュー構築"""
        self._menu = QMenu(self)

        # 言語モード
        self._lang_group = QActionGroup(self)
        lang_auto = QAction("自動判定 (AUTO)", self, checkable=True)
        lang_auto.setChecked(True)
        lang_auto.triggered.connect(lambda: self._set_lang_mode("auto"))
        lang_atty = QAction("弁護人として入力", self, checkable=True)
        lang_atty.triggered.connect(lambda: self._set_lang_mode("attorney"))
        lang_def = QAction("相手の発言として入力", self, checkable=True)
        lang_def.triggered.connect(lambda: self._set_lang_mode("defendant"))
        for a in (lang_auto, lang_atty, lang_def):
            self._lang_group.addAction(a)
            self._menu.addAction(a)

        # マイク感度
        self._menu.addSeparator()
        sens_menu = self._menu.addMenu("🎚 マイク感度")
        self._sens_group = QActionGroup(self)
        self._sens_presets = {
            "high":   "高感度（小声でも拾う）",
            "normal": "標準",
            "low":    "低感度（ノイズ環境）",
        }
        for key, label in self._sens_presets.items():
            act = QAction(label, self, checkable=True)
            if key == "normal":
                act.setChecked(True)
            act.triggered.connect(lambda checked, k=key: self._set_sensitivity(k))
            self._sens_group.addAction(act)
            sens_menu.addAction(act)

        # 発話テンポ
        tempo_menu = self._menu.addMenu("🗣 発話テンポ")
        self._tempo_group = QActionGroup(self)
        self._tempo_presets = {
            "slow":   "ゆっくり（無音長め判定）",
            "normal": "標準",
            "fast":   "早口（短い間も区切らない）",
        }
        for key, label in self._tempo_presets.items():
            act = QAction(label, self, checkable=True)
            if key == "normal":
                act.setChecked(True)
            act.triggered.connect(lambda checked, k=key: self._set_tempo(k))
            self._tempo_group.addAction(act)
            tempo_menu.addAction(act)

    def _show_menu(self):
        """設定メニューを表示"""
        pos = self._menu_btn.mapToGlobal(self._menu_btn.rect().bottomLeft())
        self._menu.popup(pos)

    # ------------------------------------------------------------------
    # トグル
    # ------------------------------------------------------------------

    def _on_toggle(self):
        """マイクON/OFF トグル"""
        if not self._stt_active and not self._models_ready:
            return  # モデル未準備時はONにさせない

        self._stt_active = not self._stt_active

        if self._stt_active:
            self._toggle_btn.setText("🎤 マイクOFF")
            self._toggle_btn.setStyleSheet(_BTN_STT_ON)
            self._update_mode_label()
        else:
            self._toggle_btn.setText("🎤 マイクON")
            self._toggle_btn.setStyleSheet(_BTN_STT_OFF)
            self._mode_label.setVisible(False)

        self.stt_toggled.emit(self._stt_active)

    # ------------------------------------------------------------------
    # 言語モード
    # ------------------------------------------------------------------

    def _set_lang_mode(self, mode: str):
        """言語モード切替: auto / attorney / defendant"""
        self._stt_lang_mode = mode
        # ラジオボタン同期
        for action in self._lang_group.actions():
            if mode == "auto" and "AUTO" in action.text():
                action.setChecked(True)
            elif mode == "attorney" and "弁護人" in action.text():
                action.setChecked(True)
            elif mode == "defendant" and "相手" in action.text():
                action.setChecked(True)
        self._update_mode_label()
        self.lang_mode_changed.emit(mode)

    # ------------------------------------------------------------------
    # 感度・テンポ
    # ------------------------------------------------------------------

    def _set_sensitivity(self, preset: str):
        """マイク感度プリセット切替"""
        self.sensitivity_changed.emit(preset)

    def _set_tempo(self, preset: str):
        """発話テンポプリセット切替"""
        self.tempo_changed.emit(preset)

    # ------------------------------------------------------------------
    # 状態表示
    # ------------------------------------------------------------------

    def _update_mode_label(self):
        """モード表示ラベル更新"""
        if not self._stt_active:
            self._mode_label.setVisible(False)
            return
        mode_text = {
            "auto":      "🎤 AUTO",
            "attorney":  "🎤 弁護人",
            "defendant": "🎤 相手",
        }
        self._mode_label.setText(mode_text.get(self._stt_lang_mode, "🎤"))
        self._mode_label.setVisible(True)

        if self._stt_lang_mode == "attorney":
            self._mode_label.setStyleSheet(_MODE_STYLE_ATTORNEY)
        elif self._stt_lang_mode == "defendant":
            self._mode_label.setStyleSheet(_MODE_STYLE_DEFENDANT)
        else:
            self._mode_label.setStyleSheet(_MODE_STYLE_AUTO)

    # ------------------------------------------------------------------
    # Public slots
    # ------------------------------------------------------------------

    @Slot(str)
    def update_state(self, state_name: str):
        """STTリスナーの状態変更 (listening / processing / idle)

        呼び出し元がステータスバーやプレースホルダの更新を
        行う場合は stt_toggled / state シグナルを監視すること。
        """
        if not self._stt_active:
            return
        # ボタンテキストで状態をフィードバック
        if state_name == "listening":
            self._toggle_btn.setText("🎤 発話検出中...")
        elif state_name == "processing":
            self._toggle_btn.setText("🎤 認識処理中...")
        elif state_name == "idle":
            self._toggle_btn.setText("🎤 マイクOFF")

    @Slot(bool)
    def set_enabled(self, enabled: bool):
        """モデル準備状態に応じた有効/無効切替"""
        self._models_ready = enabled
        self._toggle_btn.setEnabled(enabled)
        self._menu_btn.setEnabled(enabled)
        if not enabled:
            self._toggle_btn.setText("🎤 準備中…")

    # ------------------------------------------------------------------
    # プロパティ（読み取り用）
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """STTが現在アクティブかどうか"""
        return self._stt_active

    @property
    def lang_mode(self) -> str:
        """現在の言語モード (auto / attorney / defendant)"""
        return self._stt_lang_mode
