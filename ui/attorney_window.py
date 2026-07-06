"""
PLI Attorney Console - 弁護人コンソール画面
平成初期レトロUI — 一太郎的な業務用ソフトの佇まい

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
All rights reserved.

表示モード:
  split  — QSplitter左右分割（デュアルモニタープレビュー向け）
  switch — QStackedWidget全画面切替（F3で弁護人⇔被疑者トグル）

Wave 4 リファクタリング版:
  全ロジックを SessionController に委譲。
  本ファイルは UI 構築・シグナル配線・薄いイベントハンドラのみ。
"""

import os
import time

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QLineEdit,
    QFrame, QScrollArea, QSplitter, QStackedWidget,
    QStatusBar, QDialog, QMenuBar, QMenu,
    QInputDialog, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QAction, QActionGroup

from core.interpreter import (
    Interpreter, Utterance, Speaker,
    EngineType, SUPPORTED_LANGUAGES, get_language_name,
)
from core.logging_setup import get_logger, get_log_dir, read_recent_errors
from core.recorder import Recorder, RecordMode
from core.version import __version__
from core.session_controller import SessionController
from ui.defendant_window import DefendantPanel
from ui.conversation_bubble import ConversationBubble   # noqa: F401
from ui.dialogs import (                                 # noqa: F401
    SyntaxCheckDialog, PhraseEditorDialog,
    GlossaryEditorDialog, DictionaryDialog,
)
from ui.engine_menu import EngineMenuBuilder
import ui.font_config as _font_cfg
from ui.font_config import fs as _fs  # noqa: F401

logger = get_logger(__name__)

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
            padding: 4px 14px; font-size: 11px;
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
# メインウィンドウ: 弁護人コンソール
# ---------------------------------------------------------------------------

class AttorneyWindow(QMainWindow):
    """弁護人コンソール メインウィンドウ — UIのみ、ロジックは SessionController"""

    # --- Signals (public — main.py が接続) ---
    send_to_defendant = Signal(str, str)
    stream_to_defendant = Signal(str)
    finish_defendant_stream = Signal()
    defendant_correction = Signal()
    defendant_retry = Signal()
    defendant_update_last = Signal(str)
    defendant_lang_change = Signal(str)
    request_hide = Signal()
    request_reveal = Signal()
    request_panic = Signal()
    clear_defendant = Signal()
    embedded_panel_toggled = Signal(bool)
    stt_result = Signal(str, str)
    stt_toggled = Signal(bool)
    stt_sensitivity_changed = Signal(str)
    stt_tempo_changed = Signal(str)
    llm_model_changed = Signal(str)
    llm_ctx_changed = Signal(int)
    engine_type_changed = Signal(str)
    nllb_model_changed = Signal(str)
    opus_download_requested = Signal(str)

    # --- Internal signals (background thread → main thread) ---
    _defendant_translated = Signal(object)
    _attorney_translated = Signal(object)
    _manual_attorney_translated = Signal(int, object)
    _manual_attorney_failed = Signal(int, str)
    _attorney_translation_failed = Signal(str, str)
    _interpreter_stream_token_ready = Signal(object, str)
    _interpreter_utterance_ready = Signal(object)

    # ===================================================================
    #  __init__
    # ===================================================================

    def __init__(self, interpreter: Interpreter, recorder: Recorder,
                 view_style: str = "split"):
        super().__init__()
        self.interpreter = interpreter
        self.recorder = recorder

        # --- SessionController ---
        self.controller = SessionController(interpreter, recorder)
        self._wire_controller_callbacks()

        # --- UI state ---
        self._pending_utterance: Utterance | None = None
        self._pending_is_attorney: bool = False
        self._current_attorney_bubble: ConversationBubble | None = None
        self._last_attorney_bubble: ConversationBubble | None = None
        self._last_defendant_bubble: ConversationBubble | None = None
        self._editing_def_bubble: ConversationBubble | None = None
        self._pending_attorney_bubbles: dict[int, ConversationBubble] = {}
        self._dummy_pdf_path = ""
        self._embed_visible = False
        self._view_style = view_style
        self._mic_error_dialog_shown = False  # マイク案内ダイアログはセッション中1回だけ

        self._defendant_panel = DefendantPanel()

        self.setWindowTitle("PLI — Private Link Interpreter")
        self.setMinimumSize(700, 600)

        self._setup_ui()
        self._setup_menubar()
        self._setup_shortcuts()
        self._connect_embedded_panel()
        self._connect_internal_signals()

        self.controller.start_translation_worker()

    # ===================================================================
    #  Controller ↔ Signal wiring
    # ===================================================================

    def _wire_controller_callbacks(self):
        """SessionController コールバック → Qt Signal 変換"""
        self.controller.set_callbacks(
            on_status_message=lambda msg, ms: None,  # overridden after status_bar created
            on_manual_attorney_translated=lambda rid, utt: self._manual_attorney_translated.emit(rid, utt),
            on_manual_attorney_failed=lambda rid, err: self._manual_attorney_failed.emit(rid, err),
            on_attorney_translated=lambda utt: self._attorney_translated.emit(utt),
            on_attorney_translation_failed=lambda txt, err: self._attorney_translation_failed.emit(txt, err),
            on_defendant_translated=lambda utt: self._defendant_translated.emit(utt),
            on_interpreter_stream_token=lambda utt, tok: self._interpreter_stream_token_ready.emit(utt, tok),
            on_interpreter_utterance=lambda utt: self._interpreter_utterance_ready.emit(utt),
            on_stt_toggled=lambda active: self.stt_toggled.emit(active),
            on_stt_sensitivity_changed=lambda p: self.stt_sensitivity_changed.emit(p),
            on_stt_tempo_changed=lambda p: self.stt_tempo_changed.emit(p),
            on_send_to_defendant=lambda kind, text: self.send_to_defendant.emit(kind, text),
            on_stream_to_defendant=lambda tok: self.stream_to_defendant.emit(tok),
            on_finish_defendant_stream=lambda: self.finish_defendant_stream.emit(),
            on_clear_defendant=lambda: self.clear_defendant.emit(),
            on_rec_mode_change=lambda mode: self._sync_rec_mode_ui(mode),
            on_translation_not_available=lambda msg: (
                self.status_bar.showMessage(msg, 6000) if hasattr(self, 'status_bar') else None
            ),
        )
        self.controller.setup_interpreter_callbacks()

    def _connect_internal_signals(self):
        """Internal signals: background thread → main thread slot"""
        self._defendant_translated.connect(self._on_defendant_translated)
        self._attorney_translated.connect(self._on_attorney_translated)
        self._manual_attorney_translated.connect(self._on_manual_attorney_translated)
        self._manual_attorney_failed.connect(self._on_manual_attorney_failed)
        self._attorney_translation_failed.connect(self._on_attorney_translation_failed)
        self._interpreter_stream_token_ready.connect(self._on_interpreter_stream_token)
        self._interpreter_utterance_ready.connect(self._on_interpreter_utterance)

    # ===================================================================
    #  Properties
    # ===================================================================

    @property
    def defendant_panel(self) -> DefendantPanel:
        return self._defendant_panel

    @property
    def _stt_active(self):
        return self.controller.stt_active

    @_stt_active.setter
    def _stt_active(self, value):
        self.controller._stt_active = value

    @property
    def _session_count(self):
        return self.controller.session_count

    # ===================================================================
    #  UI construction
    # ===================================================================

    def _setup_ui(self):
        self.setStyleSheet(f"background-color: {_BG};")
        central = QWidget()
        self.setCentralWidget(central)
        outer_layout = QVBoxLayout(central)
        outer_layout.setSpacing(0)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self._stealth_stack = QStackedWidget()
        self._is_stealth = False

        # --- Real content ---
        real_content = QWidget()
        real_content.setStyleSheet(f"background-color: {_BG};")
        real_layout = QVBoxLayout(real_content)
        real_layout.setSpacing(0)
        real_layout.setContentsMargins(0, 0, 0, 0)

        # --- Attorney content ---
        attorney_widget = QWidget()
        attorney_widget.setStyleSheet(f"background-color: {_BG};")
        main_layout = QVBoxLayout(attorney_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QFrame()
        toolbar.setFixedHeight(28)
        toolbar.setStyleSheet(f"{_raised_border(_SURFACE)} padding: 2px 8px;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 0, 8, 0)
        tb_layout.setSpacing(4)
        self._mode_label = QLabel("MOCK")
        self._mode_label.setFont(QFont("Menlo", 9))
        self._mode_label.setStyleSheet(f"color: {_DIM}; font-size: 10px; border: none;")
        tb_layout.addWidget(self._mode_label)
        self._loading_label = QLabel("")
        self._loading_label.setFont(QFont("Menlo", 9))
        self._loading_label.setStyleSheet(f"color: {_WARN}; font-size: 10px; font-weight: bold; border: none;")
        tb_layout.addWidget(self._loading_label)
        tb_layout.addStretch()
        self._lang_label = QLabel("English")
        self._lang_label.setFont(QFont("Menlo", 9))
        self._lang_label.setStyleSheet(f"color: {_ACCENT}; font-size: 10px; font-weight: bold; border: none;")
        tb_layout.addWidget(self._lang_label)
        main_layout.addWidget(toolbar)

        # --- Conversation log ---
        log_frame = QFrame()
        log_frame.setStyleSheet(f"{_sunken_border(_FIELD)} margin: 4px 6px;")
        log_inner = QVBoxLayout(log_frame)
        log_inner.setContentsMargins(0, 0, 0, 0)
        log_toolbar = QHBoxLayout()
        log_toolbar.setContentsMargins(8, 2, 8, 0)
        log_toolbar.addStretch()
        copy_all_btn = QPushButton("📋 全会話コピー")
        copy_all_btn.setToolTip("会話ログ全体をクリップボードにコピー")
        copy_all_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {_SURFACE}; color: {_DIM}; font-size: 11px;
                padding: 2px 10px; border: 1px solid {_RAISED_D}; border-radius: 3px; }}
            QPushButton:hover {{ background-color: {_RAISED_L}; color: {_TEXT}; }}
        """)
        copy_all_btn.clicked.connect(self._copy_all_conversation)
        log_toolbar.addWidget(copy_all_btn)
        log_inner.addLayout(log_toolbar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: {_FIELD}; }}
            QScrollBar:vertical {{ background: {_SURFACE}; width: 14px; border-left: 1px solid {_RAISED_D}; }}
            QScrollBar::handle:vertical {{ {_raised_border(_BG)} min-height: 20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 14px; {_raised_border(_BG)} }}
        """)
        self.log_container = QWidget()
        self.log_container.setStyleSheet(f"background-color: {_FIELD};")
        self.log_layout = QVBoxLayout(self.log_container)
        self.log_layout.setAlignment(Qt.AlignTop)
        self.log_layout.setSpacing(0)
        self.log_layout.setContentsMargins(8, 4, 8, 4)
        self.scroll_area.setWidget(self.log_container)
        log_inner.addWidget(self.scroll_area)
        main_layout.addWidget(log_frame, stretch=1)

        # --- Approval panel ---
        self.approval_frame = QFrame()
        self.approval_frame.setStyleSheet(f"{_raised_border(_SURFACE)} margin: 0 6px;")
        self.approval_frame.setVisible(False)
        approval_layout = QVBoxLayout(self.approval_frame)
        approval_layout.setContentsMargins(10, 8, 10, 8)
        approval_layout.setSpacing(6)
        self.appr_header = QLabel("相手の発言 — 確認")
        self.appr_header.setStyleSheet(f"color: {_WARN}; font-size: 11px; font-weight: bold; border: none;")
        self.appr_header.setFont(QFont("Menlo", 9))
        approval_layout.addWidget(self.appr_header)
        self.pending_label = QLabel("")
        self.pending_label.setWordWrap(True)
        self.pending_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.pending_label.setCursor(Qt.IBeamCursor)
        self.pending_label.setStyleSheet(f"color: {_TEXT}; font-size: 12px; padding: 4px; {_sunken_border(_FIELD)}")
        approval_layout.addWidget(self.pending_label)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self.ok_btn = _make_btn("OK (O)", _BTN_OK)
        self.ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(self.ok_btn)
        self.retry_btn = _make_btn("やり直し (R)", _BTN_NG)
        self.retry_btn.clicked.connect(self._on_retry)
        btn_row.addWidget(self.retry_btn)
        self.edit_btn = _make_btn("手動修正 (E)", _BTN_EDIT)
        self.edit_btn.clicked.connect(self._on_manual_edit)
        btn_row.addWidget(self.edit_btn)
        btn_row.addStretch()
        approval_layout.addLayout(btn_row)
        main_layout.addWidget(self.approval_frame)

        # --- Input area ---
        input_frame = QFrame()
        input_frame.setStyleSheet(f"{_raised_border(_SURFACE)} margin: 2px 6px 4px 6px;")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(8, 6, 8, 6)
        input_layout.setSpacing(4)
        self._phrase_btn = QPushButton("① 定型文")
        self._phrase_btn.setToolTip("定型文テンプレート")
        self._phrase_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {_ACCENT}; color: white;
                border-top: 1px solid {_RAISED_L}; border-left: 1px solid {_RAISED_L};
                border-bottom: 1px solid {_RAISED_D}; border-right: 1px solid {_RAISED_D};
                padding: 3px 8px; font-size: 11px; font-weight: bold; }}
            QPushButton:hover {{ background-color: #2a4a7a; }}
        """)
        self._phrase_btn.clicked.connect(self._on_phrase_menu)
        input_layout.addWidget(self._phrase_btn)
        self._dict_btn = QPushButton("② 辞書")
        self._dict_btn.setToolTip("辞書検索")
        self._dict_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {_BTN_OK}; color: white;
                border-top: 1px solid {_RAISED_L}; border-left: 1px solid {_RAISED_L};
                border-bottom: 1px solid {_RAISED_D}; border-right: 1px solid {_RAISED_D};
                padding: 3px 8px; font-size: 11px; font-weight: bold; }}
            QPushButton:hover {{ background-color: #4a7a54; }}
        """)
        self._dict_btn.clicked.connect(self._on_dict_dialog)
        input_layout.addWidget(self._dict_btn)
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("日本語を入力してEnter...")
        self._input_normal_style = f"""
            QLineEdit {{ background-color: {_FIELD}; color: {_TEXT};
                border-top: 1px solid {_RAISED_D}; border-left: 1px solid {_RAISED_D};
                border-bottom: 1px solid {_RAISED_L}; border-right: 1px solid {_RAISED_L};
                padding: 4px 8px; font-size: 13px;
                selection-background-color: {_ACCENT}; selection-color: white; }}
        """
        self._input_stt_style = f"""
            QLineEdit {{ background-color: #fffde0; color: {_TEXT};
                border: 2px solid #c8a830; padding: 3px 7px; font-size: 13px;
                selection-background-color: {_ACCENT}; selection-color: white; }}
        """
        self.input_field.setStyleSheet(self._input_normal_style)
        self.input_field.returnPressed.connect(self._on_send_attorney)
        input_layout.addWidget(self.input_field)
        send_btn = _make_btn("送信", _BTN_SEND)
        send_btn.clicked.connect(self._on_send_attorney)
        input_layout.addWidget(send_btn)
        main_layout.addWidget(input_frame)

        # --- Layout mode ---
        self._attorney_widget = attorney_widget
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setStyleSheet(f"QSplitter::handle {{ background: {_RAISED_D}; width: 3px; }}")
        self._splitter.addWidget(attorney_widget)
        self._splitter.addWidget(self._defendant_panel)
        if self._view_style == "switch":
            self._switch_state = 0
            self._defendant_panel.setVisible(False)
            self._splitter.setStretchFactor(0, 1)
            self._splitter.setStretchFactor(1, 1)
        else:
            self._defendant_panel.setVisible(False)
            self._splitter.setStretchFactor(0, 3)
            self._splitter.setStretchFactor(1, 2)
        real_layout.addWidget(self._splitter)

        # --- Stealth ---
        stealth_widget = self._create_stealth_widget()
        self._stealth_stack.addWidget(real_content)
        self._stealth_stack.addWidget(stealth_widget)
        self._stealth_stack.setCurrentIndex(0)
        outer_layout.addWidget(self._stealth_stack)

        # --- Status bar ---
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{ background-color: {_BG}; color: {_DIM}; font-size: 10px;
                border-top: 1px solid {_RAISED_D}; padding: 1px 4px; }}
            QStatusBar::item {{ border: none; }}
        """)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("待機中")

        # Rewire controller status callback now that status_bar exists
        self.controller._cb_status_message = lambda msg, ms: self.status_bar.showMessage(msg, ms)
        self.controller._cb_translation_not_available = lambda msg: self.status_bar.showMessage(msg, 6000)

        self._stt_mode_label = QLabel("")
        self._stt_mode_label.setFont(QFont("Menlo", 9))
        self._stt_mode_label.setStyleSheet(f"color: {_DIM}; font-size: 10px; padding: 0 6px; border-left: 1px solid {_RAISED_D};")
        self._stt_mode_label.setVisible(False)
        self.status_bar.addPermanentWidget(self._stt_mode_label)

        self._session_label = QLabel(f"Session #{self.controller.session_count:02d}")
        self._session_label.setStyleSheet(f"color: {_DIM}; font-size: 10px; padding: 0 6px; border-left: 1px solid {_RAISED_D}; border-right: 1px solid {_RAISED_L};")
        self._session_label.setFont(QFont("Menlo", 9))
        self.status_bar.addPermanentWidget(self._session_label)

        self.rec_size_label = QLabel("")
        self.rec_size_label.setStyleSheet(f"color: {_WARN}; font-size: 10px; padding: 0 6px; border-left: 1px solid {_RAISED_D};")
        self.rec_size_label.setFont(QFont("Menlo", 9))
        self.status_bar.addPermanentWidget(self.rec_size_label)

        self._rec_timer = QTimer()
        self._rec_timer.timeout.connect(self._update_rec_size)
        self._rec_timer.start(1000)

    # ===================================================================
    #  Menubar
    # ===================================================================

    def _setup_menubar(self):
        menubar = self.menuBar()
        menubar.setStyleSheet(f"""
            QMenuBar {{ background-color: {_SURFACE}; color: {_TEXT}; font-size: 12px;
                border-bottom: 1px solid {_RAISED_D}; padding: 1px 2px; }}
            QMenuBar::item {{ padding: 3px 8px; }}
            QMenuBar::item:selected {{ background: {_ACCENT}; color: white; }}
            QMenu {{ background-color: {_SURFACE}; color: {_TEXT}; font-size: 12px;
                border: 1px solid {_RAISED_D}; padding: 2px 0; }}
            QMenu::item {{ padding: 4px 20px 4px 10px; }}
            QMenu::item:selected {{ background-color: {_ACCENT}; color: white; }}
            QMenu::separator {{ height: 1px; background: {_RAISED_D}; margin: 2px 4px; }}
        """)

        # --- 言語(L) ---
        lang_menu = menubar.addMenu("言語(&L)")
        self._lang_action_group = QActionGroup(self)
        self._lang_action_group.setExclusive(True)
        try:
            from core.opus_downloader import OPUS_MODELS
            _opus_direct = set()
            for key in OPUS_MODELS:
                parts = key.split("-")
                if len(parts) == 2:
                    _opus_direct.update(parts)
            _opus_direct.discard("en")
            _opus_direct.discard("ja")
        except Exception:
            _opus_direct = set()
        tier_order = {"◎": 0, "○": 1, "△": 2}
        sorted_langs = sorted(SUPPORTED_LANGUAGES.items(), key=lambda x: (tier_order.get(x[1]["tier"], 9), x[1]["name"]))
        current_tier = None
        for code, info in sorted_langs:
            tier = info["tier"]
            if current_tier is not None and tier != current_tier:
                lang_menu.addSeparator()
            current_tier = tier
            route_tag = " [英語経由]" if (code != "en" and code not in _opus_direct) else ""
            label = f'{info["tier"]} {info["name"]}（{info["native"]}）{route_tag}'
            action = QAction(label, self, checkable=True)
            if code == "en":
                action.setChecked(True)
            action.triggered.connect(lambda checked, c=code: self._on_language_change(c))
            self._lang_action_group.addAction(action)
            lang_menu.addAction(action)

        # --- 表示(V) ---
        view_menu = menubar.addMenu("表示(&V)")
        if self._view_style == "switch":
            self._embed_action = QAction("相手画面に切替  ⌘3", self)
        else:
            self._embed_action = QAction("相手画面を埋め込み  ⌘3", self, checkable=True)
        self._embed_action.triggered.connect(self._toggle_embedded_panel)
        view_menu.addAction(self._embed_action)

        # --- セッション(S) ---
        session_menu = menubar.addMenu("セッション(&S)")
        for label, handler in [
            ("💾 記録を保存 (JSON)(&J)", self._on_save_json),
            ("📝 記録をエクスポート (テキスト)(&T)", self._on_save_text),
        ]:
            act = QAction(label, self)
            act.triggered.connect(handler)
            session_menu.addAction(act)
        session_menu.addSeparator()
        end_action = QAction("セッション終了(&E)", self)
        end_action.triggered.connect(self._on_end_session)
        session_menu.addAction(end_action)
        session_menu.addSeparator()
        hide_action = QAction("画面を隠す  ⌘1", self)
        hide_action.triggered.connect(self._on_f1)
        session_menu.addAction(hide_action)
        panic_action = QAction("緊急消去    ⌘2", self)
        panic_action.triggered.connect(self._on_f2)
        session_menu.addAction(panic_action)

        # --- 録音(R) ---
        rec_menu = menubar.addMenu("録音(&R)")
        self._rec_action_group = QActionGroup(self)
        self._rec_action_group.setExclusive(True)
        for label, mode, checked in [("OFF", RecordMode.OFF, True),
                                      ("一時録音（揮発）", RecordMode.VOLATILE, False),
                                      ("録音保存", RecordMode.SAVE, False)]:
            act = QAction(label, self, checkable=True)
            act.setChecked(checked)
            act.triggered.connect(lambda _, m=mode: self._on_rec_mode(m))
            self._rec_action_group.addAction(act)
            rec_menu.addAction(act)

        # --- 音声認識(M) ---
        stt_menu = menubar.addMenu("音声認識(&M)")
        self._stt_action = QAction("🎤 マイクON  Space", self, checkable=True)
        self._stt_action.triggered.connect(self._toggle_stt)
        stt_menu.addAction(self._stt_action)
        stt_menu.addSeparator()
        self._stt_lang_group = QActionGroup(self)
        for label, mode in [("自動判定 (AUTO)  ⌘6", "auto"), ("弁護人として入力  ⌘7", "attorney"),
                             ("相手の発言として入力  ⌘8", "defendant")]:
            act = QAction(label, self, checkable=True)
            if mode == "auto":
                act.setChecked(True)
            act.triggered.connect(lambda _, m=mode: self._set_stt_lang_mode(m))
            self._stt_lang_group.addAction(act)
            stt_menu.addAction(act)
        stt_menu.addSeparator()
        sens_menu = stt_menu.addMenu("🎚 マイク感度")
        self._sens_group = QActionGroup(self)
        for key, label in [("ultra", "超高感度（ガラス越し・ささやき声）"),
                           ("high", "高感度（小声でも拾う）"), ("normal", "標準"),
                           ("low", "低感度（ノイズ環境）")]:
            act = QAction(label, self, checkable=True)
            if key == "normal":
                act.setChecked(True)
            act.triggered.connect(lambda _, k=key: self.controller.set_stt_sensitivity(k))
            self._sens_group.addAction(act)
            sens_menu.addAction(act)
        tempo_menu = stt_menu.addMenu("🗣 発話テンポ")
        self._tempo_group = QActionGroup(self)
        for key, label in [("slow", "ゆっくり（無音長め判定）"), ("normal", "標準"), ("fast", "早口（短い間も区切らない）")]:
            act = QAction(label, self, checkable=True)
            if key == "normal":
                act.setChecked(True)
            act.triggered.connect(lambda _, k=key: self.controller.set_stt_tempo(k))
            self._tempo_group.addAction(act)
            tempo_menu.addAction(act)

        # --- テスト(T) ---
        test_menu = menubar.addMenu("テスト(&T)")
        def_sim = QAction("相手の発言を入力...  ⌘D", self)
        def_sim.triggered.connect(self._on_simulate_defendant)
        test_menu.addAction(def_sim)

        # --- ヘルプ(H) ---
        help_menu = menubar.addMenu("ヘルプ(&H)")
        shortcut_help = QAction("ショートカット一覧  ⌘/", self)
        shortcut_help.triggered.connect(self._show_shortcut_help)
        help_menu.addAction(shortcut_help)
        help_menu.addSeparator()
        open_log_action = QAction("ログフォルダを開く", self)
        open_log_action.triggered.connect(self._on_open_log_folder)
        help_menu.addAction(open_log_action)
        support_info_action = QAction("サポート情報をコピー", self)
        support_info_action.triggered.connect(self._on_copy_support_info)
        help_menu.addAction(support_info_action)
        help_menu.addSeparator()
        about_action = QAction("PLI について...", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        # --- 設定(O) ---
        settings_menu = menubar.addMenu("設定(&O)")
        font_menu = settings_menu.addMenu("🔤 フォントサイズ")
        font_group = QActionGroup(self)
        font_group.setExclusive(True)
        for label, scale in [("小 (×0.7)", 0.7), ("やや小 (×0.85)", 0.85), ("標準 (×1.0)", 1.0),
                              ("やや大 (×1.2)", 1.2), ("大 (×1.5)", 1.5), ("特大 (×2.0)", 2.0)]:
            act = QAction(label, self, checkable=True)
            if abs(scale - _font_cfg.font_scale) < 0.01:
                act.setChecked(True)
            act.triggered.connect(lambda _, s=scale: self._set_font_scale(s))
            font_group.addAction(act)
            font_menu.addAction(act)
        settings_menu.addSeparator()
        self._engine_menu_builder = EngineMenuBuilder(self.interpreter, parent=self)
        self._engine_menu_builder.build_model_menu(settings_menu)
        self._engine_menu_builder.build_engine_menu(settings_menu)
        self._engine_menu_builder.engine_changed.connect(self.engine_type_changed)
        self._engine_menu_builder.model_changed.connect(self.llm_model_changed)
        self._engine_menu_builder.ctx_changed.connect(self.llm_ctx_changed)
        self._engine_menu_builder.nllb_model_changed.connect(self.nllb_model_changed)
        settings_menu.addSeparator()
        self._hide_wipe_log = QAction("隠す時にログも消去", self, checkable=True)
        self._hide_wipe_log.setChecked(True)
        settings_menu.addAction(self._hide_wipe_log)
        self._hide_wipe_rec = QAction("隠す時に録音も消去", self, checkable=True)
        self._hide_wipe_rec.setChecked(True)
        settings_menu.addAction(self._hide_wipe_rec)
        settings_menu.addSeparator()
        edit_phrases = QAction("📋 定型文を編集", self)
        edit_phrases.triggered.connect(self._on_edit_phrases)
        settings_menu.addAction(edit_phrases)
        edit_glossary = QAction("📖 固有名詞辞書を編集", self)
        edit_glossary.triggered.connect(self._on_edit_glossary)
        settings_menu.addAction(edit_glossary)
        settings_menu.addSeparator()
        dummy_action = QAction("ダミーPDFを選択...", self)
        dummy_action.triggered.connect(self._on_select_dummy_pdf)
        settings_menu.addAction(dummy_action)

    # ===================================================================
    #  Shortcuts
    # ===================================================================

    def _setup_shortcuts(self):
        for key, handler in [
            ("Ctrl+1", self._on_f1), ("Ctrl+2", self._on_f2),
            ("Ctrl+3", self._toggle_embedded_panel), ("Ctrl+5", self._toggle_stt),
            ("Ctrl+6", lambda: self._set_stt_lang_mode("auto")),
            ("Ctrl+7", lambda: self._set_stt_lang_mode("attorney")),
            ("Ctrl+8", lambda: self._set_stt_lang_mode("defendant")),
            ("Ctrl+D", self._on_simulate_defendant), ("Ctrl+/", self._show_shortcut_help),
        ]:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(handler)

    # ===================================================================
    #  Embedded panel
    # ===================================================================

    def _connect_embedded_panel(self):
        self.send_to_defendant.connect(self._defendant_panel.on_message)
        self.stream_to_defendant.connect(self._defendant_panel.on_stream_token)
        self.finish_defendant_stream.connect(self._defendant_panel.finish_stream)
        self.defendant_correction.connect(self._defendant_panel.on_correction)
        self.defendant_retry.connect(self._defendant_panel.on_retry)
        self.defendant_update_last.connect(self._defendant_panel.on_update_last)
        self.defendant_lang_change.connect(self._defendant_panel.on_language_change)
        self.clear_defendant.connect(self._defendant_panel.on_clear)

    def _toggle_embedded_panel(self):
        if self._is_stealth:
            return
        if self._view_style == "switch":
            self._switch_state = (self._switch_state + 1) % 3
            s = self._switch_state
            self._attorney_widget.setVisible(s != 1)
            self._defendant_panel.setVisible(s != 0)
            labels = {0: ("相手画面に切替  ⌘3", "弁護人画面", False),
                      1: ("左右分割  ⌘3", "相手画面を表示中", True),
                      2: ("弁護人画面に戻る  ⌘3", "左右分割表示", True)}
            text, msg, vis = labels[s]
            self._embed_action.setText(text)
            self.status_bar.showMessage(msg)
            self._embed_visible = vis
        else:
            self._embed_visible = not self._embed_visible
            self._defendant_panel.setVisible(self._embed_visible)
            self._embed_action.setChecked(self._embed_visible)
            if self._embed_visible:
                if self.width() < 1100:
                    self.resize(1200, self.height())
                self.status_bar.showMessage("相手画面: 埋め込み表示")
            else:
                self.status_bar.showMessage("相手画面: 非表示")
        self.embedded_panel_toggled.emit(self._embed_visible)

    def set_embedded_panel_visible(self, visible: bool):
        self._embed_visible = visible
        if self._view_style == "switch":
            if visible:
                self._switch_state = 2
                self._attorney_widget.setVisible(True)
                self._defendant_panel.setVisible(True)
                self._embed_action.setText("弁護人画面に戻る  ⌘3")
            else:
                self._switch_state = 0
                self._attorney_widget.setVisible(True)
                self._defendant_panel.setVisible(False)
                self._embed_action.setText("相手画面に切替  ⌘3")
        else:
            self._defendant_panel.setVisible(visible)
            self._embed_action.setChecked(visible)

    # ===================================================================
    #  Send / receive (thin wrappers delegating to controller)
    # ===================================================================

    def _on_send_attorney(self):
        text = self.input_field.text().strip()
        if not text:
            return
        if not self.controller.ensure_translation_available():
            return
        self.input_field.clear()
        self.input_field.setStyleSheet(self._input_normal_style)
        self.status_bar.showMessage("翻訳中...")
        utt = Utterance(speaker=Speaker.ATTORNEY, original=text, timestamp=time.strftime("%H:%M"))
        utt.translated = "(翻訳中...)"
        bubble = ConversationBubble(utt, show_actions=True)
        bubble.edit_clicked.connect(self._on_bubble_edit)
        bubble.cancel_clicked.connect(self._on_bubble_cancel)
        bubble.homophone_swap.connect(self._on_homophone_swap)
        self.log_layout.addWidget(bubble)
        self._last_attorney_bubble = bubble
        self._scroll_to_bottom()
        job = self.controller.enqueue_translation_job("manual_attorney", text)
        self._pending_attorney_bubbles[job.job_id] = bubble

    def _drop_pending_attorney_request(self, bubble: ConversationBubble):
        remove_key = None
        for rid, pb in self._pending_attorney_bubbles.items():
            if pb is bubble:
                remove_key = rid
                break
        if remove_key is not None:
            self._pending_attorney_bubbles.pop(remove_key, None)
            self.controller.cancel_translation_job(remove_key)

    @Slot(int, object)
    def _on_manual_attorney_translated(self, request_id: int, utt: Utterance):
        bubble = self._pending_attorney_bubbles.pop(request_id, None)
        if not bubble:
            return
        utt.confirmed = True
        self.interpreter.conversation.append(utt)
        bubble.utterance = utt
        bubble.update_translation(utt.translated)
        self._last_attorney_bubble = bubble
        self._scroll_to_bottom()
        self.send_to_defendant.emit("attorney_start", utt.original)
        self.stream_to_defendant.emit(utt.translated)
        self.finish_defendant_stream.emit()
        self.status_bar.showMessage("送信済み — バブル上で修正/取消可能")

    @Slot(int, str)
    def _on_manual_attorney_failed(self, request_id: int, message: str):
        bubble = self._pending_attorney_bubbles.pop(request_id, None)
        if not bubble:
            return
        bubble.utterance.translated = f"(翻訳エラー: {message})"
        bubble.update_translation(bubble.utterance.translated)
        self.status_bar.showMessage(f"翻訳エラー: {message}", 7000)

    def _on_attorney_translated(self, utt):
        utt.confirmed = True
        self.interpreter.conversation.append(utt)
        bubble = ConversationBubble(utt, show_actions=True)
        bubble.edit_clicked.connect(self._on_bubble_edit)
        bubble.cancel_clicked.connect(self._on_bubble_cancel)
        bubble.homophone_swap.connect(self._on_homophone_swap)
        self.log_layout.addWidget(bubble)
        self._last_attorney_bubble = bubble
        self._scroll_to_bottom()
        self.send_to_defendant.emit("attorney_start", utt.original)
        self.stream_to_defendant.emit(utt.translated)
        self.finish_defendant_stream.emit()
        self.status_bar.showMessage("送信済み — バブル上で修正/取消可能")

    @Slot(str, str)
    def _on_attorney_translation_failed(self, text: str, message: str):
        utt = Utterance(speaker=Speaker.ATTORNEY, original=text,
                        translated=f"(翻訳エラー: {message})", timestamp=time.strftime("%H:%M"))
        bubble = ConversationBubble(utt, show_actions=True)
        bubble.edit_clicked.connect(self._on_bubble_edit)
        bubble.cancel_clicked.connect(self._on_bubble_cancel)
        bubble.homophone_swap.connect(self._on_homophone_swap)
        self.log_layout.addWidget(bubble)
        self._last_attorney_bubble = bubble
        self._scroll_to_bottom()
        self.status_bar.showMessage(f"翻訳エラー: {message}", 7000)

    def _on_defendant_translated(self, utt):
        utt.confirmed = True
        self.interpreter.conversation.append(utt)
        bubble = ConversationBubble(utt, show_actions=True)
        bubble.edit_clicked.connect(self._on_def_bubble_edit)
        bubble.cancel_clicked.connect(self._on_def_bubble_cancel)
        self.log_layout.addWidget(bubble)
        self._last_defendant_bubble = bubble
        self._scroll_to_bottom()
        self.send_to_defendant.emit("defendant_confirmed", utt.original)
        self.status_bar.showMessage("相手の発言を追加 — バブル上で修正/取消可能")

    @Slot(object, str)
    def _on_interpreter_stream_token(self, utt: Utterance, token: str):
        self.stream_to_defendant.emit(token)
        if self._current_attorney_bubble:
            self._current_attorney_bubble.update_translation(utt.translated)

    @Slot(object)
    def _on_interpreter_utterance(self, utt: Utterance):
        if self._current_attorney_bubble:
            self._current_attorney_bubble.utterance = utt
            self._current_attorney_bubble.update_translation(utt.translated)
            self._current_attorney_bubble = None
        self.finish_defendant_stream.emit()
        self.status_bar.showMessage("待機中")

    # ===================================================================
    #  Bubble edit / cancel
    # ===================================================================

    def _on_bubble_edit(self, bubble):
        utt = bubble.utterance
        self._drop_pending_attorney_request(bubble)
        if utt in self.interpreter.conversation:
            self.interpreter.conversation.remove(utt)
        bubble.setParent(None)
        bubble.deleteLater()
        if self._last_attorney_bubble is bubble:
            self._last_attorney_bubble = None
        self.send_to_defendant.emit("clear_last", "")
        self.input_field.setText(utt.original)
        self.input_field.setFocus()
        self.input_field.selectAll()
        self.status_bar.showMessage("文字起こしを修正してEnterで再送信")

    def _on_bubble_cancel(self, bubble):
        utt = bubble.utterance
        self._drop_pending_attorney_request(bubble)
        if utt in self.interpreter.conversation:
            self.interpreter.conversation.remove(utt)
        bubble.setParent(None)
        bubble.deleteLater()
        if self._last_attorney_bubble is bubble:
            self._last_attorney_bubble = None
        self.send_to_defendant.emit("clear_last", "")
        self.status_bar.showMessage("取り消しました")

    def _on_homophone_swap(self, bubble, surface: str, alt: str):
        """同音異義の差し替え: 原文の surface を alt に直して入力欄へ。

        既存の修正経路を再利用し、差し替えたテキストを入力欄にプリフィルする。
        弁護人がEnterで確定すれば再翻訳される（最終確認は人間に委ねる安全方式）。
        """
        utt = bubble.utterance
        swapped = (utt.original or "").replace(surface, alt)
        self._drop_pending_attorney_request(bubble)
        if utt in self.interpreter.conversation:
            self.interpreter.conversation.remove(utt)
        bubble.setParent(None)
        bubble.deleteLater()
        if self._last_attorney_bubble is bubble:
            self._last_attorney_bubble = None
        self.send_to_defendant.emit("clear_last", "")
        self.input_field.setText(swapped)
        self.input_field.setFocus()
        self.status_bar.showMessage(f"「{surface}」→「{alt}」に直しました。Enterで再送信")

    def _on_def_bubble_edit(self, bubble):
        self._editing_def_bubble = bubble
        self.interpreter.pause()
        self.defendant_correction.emit()
        chunks = self.interpreter.syntax_check(bubble.utterance.original)
        dialog = SyntaxCheckDialog(bubble.utterance.original, chunks, self.interpreter, self)
        dialog.confirmed.connect(self._on_def_syntax_confirmed)
        if dialog.exec() == QDialog.Rejected:
            self._editing_def_bubble = None
            self.interpreter.resume()

    def _on_def_syntax_confirmed(self, new_english: str, new_japanese: str):
        bubble = self._editing_def_bubble
        if bubble and bubble.utterance:
            bubble.utterance.original = new_english
            bubble.utterance.translated = new_japanese
            bubble.update_translation(new_japanese)
            self.defendant_update_last.emit(new_english)
        self._editing_def_bubble = None
        self.interpreter.resume()
        self.status_bar.showMessage("相手の発言を修正しました")

    def _on_def_bubble_cancel(self, bubble):
        utt = bubble.utterance
        if utt in self.interpreter.conversation:
            self.interpreter.conversation.remove(utt)
        bubble.setParent(None)
        bubble.deleteLater()
        if self._last_defendant_bubble is bubble:
            self._last_defendant_bubble = None
        self.send_to_defendant.emit("clear_last", "")
        self.status_bar.showMessage("相手の発言を取り消しました")

    # ===================================================================
    #  Approval panel
    # ===================================================================

    def _on_ok(self):
        if not self._pending_utterance:
            return
        utt = self._pending_utterance
        if self._pending_is_attorney:
            utt.confirmed = True
            self.interpreter.conversation.append(utt)
            bubble = ConversationBubble(utt)
            self.log_layout.addWidget(bubble)
            self._scroll_to_bottom()
            self.send_to_defendant.emit("attorney_start", utt.original)
            self.stream_to_defendant.emit(utt.translated)
            self.finish_defendant_stream.emit()
        else:
            self.interpreter.confirm_utterance(utt)
            bubble = ConversationBubble(utt)
            self.log_layout.addWidget(bubble)
            self._scroll_to_bottom()
            self.send_to_defendant.emit("defendant_confirmed", utt.original)
        self._pending_utterance = None
        self._pending_is_attorney = False
        self.approval_frame.setVisible(False)
        self.status_bar.showMessage("待機中")

    def _on_retry(self):
        was_attorney = self._pending_is_attorney
        self._pending_utterance = None
        self._pending_is_attorney = False
        self.approval_frame.setVisible(False)
        if not was_attorney:
            self.defendant_retry.emit()
        self.status_bar.showMessage("再発話待ち")

    def _on_manual_edit(self):
        if not self._pending_utterance:
            return
        if self._pending_is_attorney:
            self.input_field.setText(self._pending_utterance.original)
            self.input_field.setFocus()
            self.input_field.selectAll()
            self._pending_utterance = None
            self._pending_is_attorney = False
            self.approval_frame.setVisible(False)
            self.status_bar.showMessage("文字起こしを修正してEnterで再送信")
            return
        self.interpreter.pause()
        self.defendant_correction.emit()
        english = self._pending_utterance.original
        chunks = self.interpreter.syntax_check(english)
        dialog = SyntaxCheckDialog(english, chunks, self.interpreter, self)
        dialog.confirmed.connect(self._on_syntax_confirmed)
        if dialog.exec() == QDialog.Rejected:
            self.interpreter.resume()

    def _on_syntax_confirmed(self, new_english: str, new_japanese: str):
        if self._pending_utterance:
            self._pending_utterance.original = new_english
            self._pending_utterance.translated = new_japanese
            self._pending_utterance.confirmed = True
            bubble = ConversationBubble(self._pending_utterance)
            self.log_layout.addWidget(bubble)
            self._scroll_to_bottom()
            self.defendant_update_last.emit(new_english)
        self._pending_utterance = None
        self.approval_frame.setVisible(False)
        self.interpreter.resume()
        self.status_bar.showMessage("待機中")

    # ===================================================================
    #  STT (thin wrappers → controller)
    # ===================================================================

    def _toggle_stt(self):
        was_active = self.controller.stt_active
        result = self.controller.toggle_stt()
        self._stt_action.setChecked(result)
        if result:
            self._stt_action.setText("🎤 マイクOFF  Space")
            self.input_field.setPlaceholderText("🎤 マイク待機中… / 日本語を入力してEnter")
            self._update_stt_mode_label()
        elif was_active:
            self._stt_action.setText("🎤 マイクON  Space")
            self.input_field.setPlaceholderText("日本語を入力してEnter...")
            self.input_field.setStyleSheet(self._input_normal_style)
            self._stt_mode_label.setVisible(False)

    def _set_stt_lang_mode(self, mode: str):
        self.controller.set_stt_lang_mode(mode)
        for action in self._stt_lang_group.actions():
            if mode == "auto" and "AUTO" in action.text():
                action.setChecked(True)
            elif mode == "attorney" and "弁護人" in action.text():
                action.setChecked(True)
            elif mode == "defendant" and "相手" in action.text():
                action.setChecked(True)
        self._update_stt_mode_label()

    def on_stt_result(self, text: str, lang: str):
        self.controller.on_stt_result(text, lang)

    def on_stt_state_change(self, state_name: str):
        self.controller.on_stt_state_change(state_name)
        if not self.controller.stt_active:
            return
        placeholders = {"listening": "🎤 発話検出中...", "processing": "🎤 音声認識処理中...",
                         "idle": "🎤 マイク待機中… / 日本語を入力してEnter"}
        if state_name in placeholders:
            self.input_field.setPlaceholderText(placeholders[state_name])

    @Slot(str)
    def on_stt_error(self, message: str):
        """STTリスナーのエラー受信（main.py のブリッジ経由）

        stt_listener が分類した構造化コード（mic_denied / mic_missing）は
        日本語の案内ダイアログで対処方法を示す。それ以外は従来どおり
        ステータスバーに表示する。
        """
        if message in ("mic_denied", "mic_missing"):
            label = ("マイクが使用できません（権限がありません）"
                     if message == "mic_denied" else "マイクが見つかりません")
            self.status_bar.showMessage(label, 8000)
            if self._mic_error_dialog_shown:
                return
            self._mic_error_dialog_shown = True
            self._show_mic_error_dialog(message)
        else:
            self.status_bar.showMessage(f"STTエラー: {message}", 5000)

    def _show_mic_error_dialog(self, code: str):
        """マイク権限拒否/デバイス無しの案内ダイアログ（セッション中1回だけ）"""
        import sys
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("マイクが使用できません")
        open_settings_btn = None
        if code == "mic_denied":
            box.setText(
                "PLIにマイクの使用が許可されていません。\n"
                "[システム設定を開く] を押して、プライバシーとセキュリティ > マイク で "
                "PLI を許可してください。許可後、アプリを再起動してください。"
            )
            if sys.platform == "darwin":
                open_settings_btn = box.addButton("システム設定を開く", QMessageBox.ActionRole)
        else:  # mic_missing
            box.setText(
                "マイクが見つかりません。\n"
                "マイクが接続されているか確認してから、もう一度マイクをONにしてください。"
            )
        box.addButton("閉じる", QMessageBox.RejectRole)
        box.exec()
        if open_settings_btn is not None and box.clickedButton() is open_settings_btn:
            import subprocess
            try:
                subprocess.Popen([
                    "open",
                    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
                ])
            except OSError as e:
                self.status_bar.showMessage(f"システム設定を開けませんでした: {e}", 5000)

    def _update_stt_mode_label(self):
        if not self.controller.stt_active:
            self._stt_mode_label.setVisible(False)
            return
        mode = self.controller.stt_lang_mode
        mode_text = {"auto": "🎤 AUTO", "attorney": "🎤 弁護人", "defendant": "🎤 相手"}
        self._stt_mode_label.setText(mode_text.get(mode, "🎤"))
        self._stt_mode_label.setVisible(True)
        colors = {"attorney": _ACCENT, "defendant": _DEF_CLR}
        color = colors.get(mode, _DIM)
        bold = "font-weight: bold;" if mode != "auto" else ""
        self._stt_mode_label.setStyleSheet(
            f"color: {color}; font-size: 10px; {bold} padding: 0 6px; border-left: 1px solid {_RAISED_D};")

    # ===================================================================
    #  Misc actions (menu handlers)
    # ===================================================================

    def _on_simulate_defendant(self):
        text, ok = QInputDialog.getText(self, "相手の発言（テスト）", "外国語で入力:")
        if ok and text.strip():
            self.controller.process_defendant_speech(text.strip())

    def _on_language_change(self, lang_code: str):
        self.interpreter.set_target_language(lang_code)
        lang_name = get_language_name(lang_code)
        self.status_bar.showMessage(f"言語: {lang_name}")
        self.setWindowTitle(f"PLI — {lang_name}")
        self._lang_label.setText(lang_name)
        self.defendant_lang_change.emit(lang_code)

    def _on_rec_mode(self, mode: RecordMode):
        self.controller.set_rec_mode(mode)
        if mode == RecordMode.OFF:
            self.rec_size_label.setText("")

    def _sync_rec_mode_ui(self, mode: RecordMode):
        """Controller側の実モードにメニュー表示を同期（録音開始失敗時のOFF戻し等）"""
        order = [RecordMode.OFF, RecordMode.VOLATILE, RecordMode.SAVE]
        if hasattr(self, '_rec_action_group') and mode in order:
            actions = self._rec_action_group.actions()
            if len(actions) == len(order):
                actions[order.index(mode)].setChecked(True)
        if mode == RecordMode.OFF and hasattr(self, 'rec_size_label'):
            self.rec_size_label.setText("")

    def _update_rec_size(self):
        self.controller.update_rec_size()
        if self.recorder.mode != RecordMode.OFF:
            size = self.recorder.get_buffer_size_mb()
            self.rec_size_label.setText(f"{size:.1f}MB")
        else:
            self.rec_size_label.setText("")

    def _on_f1(self):
        self.request_hide.emit()

    def _on_f2(self):
        self.request_panic.emit()

    def _on_save_json(self):
        if not self.interpreter.conversation:
            QMessageBox.information(self, "保存", "保存する会話がありません。")
            return
        default_name = f"pli_record_{time.strftime('%Y%m%d_%H%M%S')}.json"
        path, _ = QFileDialog.getSaveFileName(self, "会話記録を保存 (JSON)", default_name, "JSON Files (*.json);;All Files (*)")
        if path:
            try:
                self.controller.save_conversation_json(path)
            except Exception as e:
                QMessageBox.warning(self, "保存エラー", str(e))

    def _on_save_text(self):
        if not self.interpreter.conversation:
            QMessageBox.information(self, "エクスポート", "保存する会話がありません。")
            return
        default_name = f"pli_record_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "会話記録をエクスポート (テキスト)", default_name, "Text Files (*.txt);;All Files (*)")
        if path:
            try:
                self.controller.save_conversation_text(path)
            except Exception as e:
                QMessageBox.warning(self, "エクスポートエラー", str(e))

    def _on_end_session(self):
        self.controller.end_session()
        self.clear_logs()
        if self._session_label:
            self._session_label.setText(f"Session #{self.controller.session_count:02d}")

    def _on_select_dummy_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "ダミー表示用PDFを選択", "", "PDF Files (*.pdf)")
        if path:
            self._dummy_pdf_path = path
            self.status_bar.showMessage(f"ダミーPDFを設定: {os.path.basename(path)}", 3000)

    def get_hide_preferences(self) -> dict[str, object]:
        return {
            "wipe_log_on_hide": self._hide_wipe_log.isChecked() if hasattr(self, "_hide_wipe_log") else True,
            "wipe_recording_on_hide": self._hide_wipe_rec.isChecked() if hasattr(self, "_hide_wipe_rec") else True,
            "dummy_pdf_path": self._dummy_pdf_path,
        }

    def update_engine_mode(self, is_nllb: bool = False, is_hybrid: bool = False):
        no_syntax = is_nllb or is_hybrid
        self.edit_btn.setEnabled(not no_syntax)
        if is_nllb:
            self.edit_btn.setToolTip("NLLBモードでは構文チェックを利用できません")
        elif is_hybrid:
            self.edit_btn.setToolTip("ハイブリッドモードでは構文チェックを利用できません")
        else:
            self.edit_btn.setToolTip("")

    # ===================================================================
    #  Phrases / glossary / dictionary
    # ===================================================================

    def _on_phrase_menu(self):
        from ui.translation_panel import TranslationPanel
        panel = TranslationPanel()
        data = panel._load_phrases()
        del panel
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {_SURFACE}; color: {_TEXT}; font-size: 12px;
                border: 1px solid {_RAISED_D}; padding: 2px 0; }}
            QMenu::item {{ padding: 4px 20px 4px 10px; }}
            QMenu::item:selected {{ background-color: {_ACCENT}; color: white; }}
            QMenu::separator {{ height: 1px; background: {_RAISED_D}; margin: 2px 4px; }}
        """)
        for cat in data.get("categories", []):
            icon = cat.get("icon", "")
            sub = menu.addMenu(f'{icon} {cat["name"]}')
            sub.setStyleSheet(menu.styleSheet())
            for ph in cat.get("phrases", []):
                action = sub.addAction(ph["label"])
                action.triggered.connect(lambda _, t=ph["text"]: self._send_phrase(t))
        menu.exec(self._phrase_btn.mapToGlobal(self._phrase_btn.rect().bottomLeft()))

    def _send_phrase(self, text: str):
        self.input_field.setText(text)
        self._on_send_attorney()

    def _on_edit_phrases(self):
        from ui.translation_panel import TranslationPanel
        panel = TranslationPanel()
        data = panel._load_phrases()
        def save_cb(d):
            panel._save_phrases(d)
            self.status_bar.showMessage("定型文を保存しました")
        dlg = PhraseEditorDialog(data, save_cb, self)
        dlg.exec()

    def _on_edit_glossary(self):
        GlossaryEditorDialog(self.interpreter, self).exec()

    def _on_dict_dialog(self):
        DictionaryDialog(self.interpreter, self).exec()

    # ===================================================================
    #  Font
    # ===================================================================

    def _set_font_scale(self, scale: float):
        _font_cfg.set_scale(scale)
        self._rebuild_log_bubbles()
        if hasattr(self, '_defendant_panel') and self._defendant_panel:
            self._defendant_panel.refresh_fonts()
        self.status_bar.showMessage(f"フォントサイズ: ×{scale}", 3000)

    def _rebuild_log_bubbles(self):
        while self.log_layout.count():
            item = self.log_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._last_attorney_bubble = None
        self._last_defendant_bubble = None
        for utt in self.interpreter.conversation:
            bubble = ConversationBubble(utt, show_actions=True)
            if utt.speaker == Speaker.ATTORNEY:
                bubble.edit_clicked.connect(self._on_bubble_edit)
                bubble.cancel_clicked.connect(self._on_bubble_cancel)
                bubble.homophone_swap.connect(self._on_homophone_swap)
                self._last_attorney_bubble = bubble
            else:
                bubble.edit_clicked.connect(self._on_def_bubble_edit)
                bubble.cancel_clicked.connect(self._on_def_bubble_cancel)
                self._last_defendant_bubble = bubble
            self.log_layout.addWidget(bubble)
        self._scroll_to_bottom()

    # ===================================================================
    #  Loading state
    # ===================================================================

    def set_loading_state(self, loading: bool, ready: bool = True, message: str = ""):
        is_mock = self.interpreter.mock
        if loading:
            self._loading_got_real_progress = False
            self._loading_dots = 0
            if is_mock:
                self._loading_phase = "Whisper"
                self._loading_label.setText("⏳ Whisper読込中")
                self._mode_label.setText("MOCK")
            else:
                self._loading_phase = {EngineType.LLM: "LLM", EngineType.NLLB: "NLLB",
                                        EngineType.HYBRID: "Hybrid"}.get(self.interpreter._engine_type, "LLM")
                self._loading_label.setText(f"⏳ {self._loading_phase}読込中")
                self._mode_label.setText("REAL")
            self.status_bar.showMessage("モデル読込中 — 音声認識は準備完了後に利用可能")
            self._loading_anim_timer = QTimer()
            self._loading_anim_timer.timeout.connect(self._animate_loading)
            self._loading_anim_timer.start(600)
        else:
            if hasattr(self, '_loading_anim_timer') and self._loading_anim_timer:
                self._loading_anim_timer.stop()
                self._loading_anim_timer = None
            if ready:
                self._loading_label.setText("")
                self._mode_label.setText("MOCK ✓" if is_mock else "REAL ✓")
                self.status_bar.showMessage("✓ モデル準備完了 — 翻訳・音声認識が利用可能", 5000)
            else:
                if self.interpreter.translation_ready and not self.interpreter.stt_ready:
                    self._loading_label.setText("⚠ STT不可")
                    self._mode_label.setText("MOCK !" if is_mock else "REAL !")
                else:
                    self._loading_label.setText("⚠ 読込失敗")
                    self._mode_label.setText("ERROR")
                self.status_bar.showMessage(message or "モデルの読込に失敗しました", 8000)

    def _animate_loading(self):
        if getattr(self, '_loading_got_real_progress', False):
            return
        self._loading_dots = (self._loading_dots + 1) % 4
        self._loading_label.setText(f"⏳ {getattr(self, '_loading_phase', 'LLM')}読込中{'.' * self._loading_dots}")

    def set_loading_progress(self, phase: str, progress: float):
        pct = int(progress * 100)
        phase_name = {"llm": "LLM", "nllb": "NLLB", "hybrid": "Hybrid", "stt": "Whisper"}.get(phase, phase.upper())
        self._loading_phase = phase_name
        if phase != "stt":
            if progress > 0.0:
                self._loading_got_real_progress = True
                self._loading_label.setText(f"⏳ {phase_name} {pct}%")
                self.status_bar.showMessage(f"{phase_name}モデル読込中… {pct}%")
        else:
            self._loading_got_real_progress = False
            if progress < 1.0:
                self._loading_label.setText("⏳ Whisper読込中…")
                self.status_bar.showMessage("音声認識モデル読込中…")
            else:
                self._loading_label.setText("✓ 準備完了")
                self.status_bar.showMessage("✓ 全モデル準備完了", 3000)

    # ===================================================================
    #  Stealth / hide mode
    # ===================================================================

    def _create_stealth_widget(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background-color: #ffffff;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        editor = QTextEdit()
        editor.setStyleSheet('QTextEdit { background-color: #ffffff; color: #333333; font-family: "Hiragino Mincho ProN", serif; font-size: 13px; border: none; padding: 20px; }')
        editor.setPlainText(
            "令和6年度　第3回定例会議事録（案）\n\n"
            "日時：令和6年12月20日（金）14:00～15:30\n場所：第2会議室\n出席者：田中部長、山田課長、佐藤主任、鈴木\n\n"
            "1. 前回議事録の確認\n　前回の議事録について特に修正なく承認された。\n\n"
            "2. 年末年始の業務体制について\n　12月28日（土）から1月5日（日）まで休業とする。\n　緊急連絡先は田中部長の携帯電話とする。\n\n"
            "3. 来期の予算案について\n　各部門の概算要求を1月末までに取りまとめる。\n　詳細は別途配布の資料を参照のこと。\n\n4. その他\n　特になし。\n\n以上")
        layout.addWidget(editor)
        return w

    def do_hide(self):
        self._is_stealth = True
        self._saved_title = self.windowTitle()
        if self._view_style == "switch":
            self._saved_switch_state = self._switch_state
            self._attorney_widget.setVisible(True)
            self._defendant_panel.setVisible(False)
            self._switch_state = 0
        self._stealth_stack.setCurrentIndex(1)
        self.setWindowTitle("メモ帳")
        self.menuBar().setVisible(False)
        self.status_bar.setVisible(False)

    def do_reveal(self):
        self._is_stealth = False
        self._stealth_stack.setCurrentIndex(0)
        if self._view_style == "switch" and hasattr(self, '_saved_switch_state'):
            s = self._saved_switch_state
            self._switch_state = s
            self._attorney_widget.setVisible(s != 1)
            self._defendant_panel.setVisible(s != 0)
        self.setWindowTitle(getattr(self, '_saved_title', "PLI — Private Link Interpreter"))
        self.menuBar().setVisible(True)
        self.status_bar.setVisible(True)
        self.raise_()
        self.activateWindow()

    # ===================================================================
    #  Clear / wipe
    # ===================================================================

    def clear_logs(self):
        self.controller.invalidate_translation_jobs()
        self._pending_utterance = None
        self._pending_is_attorney = False
        self._current_attorney_bubble = None
        self._pending_attorney_bubbles.clear()
        self._last_attorney_bubble = None
        self._last_defendant_bubble = None
        self._editing_def_bubble = None
        self.approval_frame.setVisible(False)
        while self.log_layout.count():
            item = self.log_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.clear_defendant.emit()

    def wipe_all(self, delete_saved_recordings: bool = False):
        self.controller.wipe_all(delete_saved_recordings)
        self.clear_logs()

    # ===================================================================
    #  Key events
    # ===================================================================

    def keyPressEvent(self, event):
        focused = self.focusWidget()
        in_text_field = focused and (focused == self.input_field or isinstance(focused, QTextEdit))
        if self.approval_frame.isVisible() and not in_text_field:
            if event.key() == Qt.Key_O:
                self._on_ok(); return
            elif event.key() == Qt.Key_R:
                self._on_retry(); return
            elif event.key() == Qt.Key_E:
                self._on_manual_edit(); return
        if event.key() == Qt.Key_Space:
            if in_text_field:
                super().keyPressEvent(event); return
            self._toggle_stt(); return
        if not in_text_field and event.text() and event.text().isprintable():
            self.input_field.setFocus()
            self.input_field.keyPressEvent(event); return
        super().keyPressEvent(event)

    def _scroll_to_bottom(self):
        sb = self.scroll_area.verticalScrollBar()
        # 呼び出し時点（新コンテンツで最大値が伸びる前）で最下部付近にいたかを判定。
        # 先生が上にスクロールして過去ログを読んでいる時は追従しない
        # （チャットアプリ標準の「stick to bottom」挙動）。
        was_at_bottom = (sb.maximum() - sb.value()) <= 120
        if not was_at_bottom:
            return

        def _do_scroll():
            sb.setValue(sb.maximum())
        QTimer.singleShot(50, _do_scroll)
        QTimer.singleShot(200, _do_scroll)

    def _copy_all_conversation(self):
        from PySide6.QtWidgets import QApplication as _QApp
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
        if lines:
            _QApp.clipboard().setText("\n".join(lines))
            self.status_bar.showMessage("📋 全会話をコピーしました", 3000)
        else:
            self.status_bar.showMessage("コピーする会話がありません", 3000)

    # ===================================================================
    #  Help dialogs
    # ===================================================================

    def _on_open_log_folder(self):
        """ヘルプ > ログフォルダを開く"""
        import subprocess
        import sys as _sys
        log_dir = get_log_dir()
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            if _sys.platform == "darwin":
                subprocess.Popen(["open", str(log_dir)])
            elif os.name == "nt":
                os.startfile(str(log_dir))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(log_dir)])
            self.status_bar.showMessage(f"ログフォルダを開きました: {log_dir}", 3000)
        except Exception as e:
            logger.error("ログフォルダを開けません: %s", e)
            QMessageBox.warning(
                self, "PLI",
                f"ログフォルダを開けませんでした。\n場所: {log_dir}\n\n詳細: {e}")

    def _build_support_info(self) -> str:
        """サポート情報テキストを組み立てる（発話内容は一切含めない）"""
        import platform as _platform
        lines = [f"PLI バージョン: {__version__}"]

        # OS情報
        if _platform.system() == "Darwin":
            lines.append(f"macOS: {_platform.mac_ver()[0]} ({_platform.machine()})")
        else:
            lines.append(f"OS: {_platform.platform()}")

        # メモリ・ティア
        try:
            from core.engines.llm import LLMEngine
            tier_name, total_gb = LLMEngine.detect_tier()
            lines.append(f"RAM: {total_gb}GB (ティア: {tier_name})")
        except Exception as e:
            lines.append(f"RAM: 取得失敗 ({e})")

        # 現在のエンジン状態
        itp = self.interpreter
        lines.append(f"現在のエンジン: {type(itp.engine).__name__} "
                     f"(state={itp.model_load_state}, "
                     f"翻訳ready={itp.translation_ready}, "
                     f"STT ready={itp.stt_ready})")
        if itp.model_load_error:
            lines.append(f"ロードエラー: {itp.model_load_error}")

        # モデルダウンロード状況
        lines.append("--- モデルダウンロード状況 ---")
        try:
            from core.whisper_stt import whisper_model_downloaded
            lines.append(f"Whisper STT: "
                         f"{'ダウンロード済み' if whisper_model_downloaded() else '未ダウンロード'}")
        except Exception as e:
            lines.append(f"Whisper STT: 確認失敗 ({e})")
        try:
            from core.nllb_downloader import list_downloaded as _nllb_dl
            nllb = _nllb_dl()
            lines.append(f"NLLB: {', '.join(nllb) if nllb else 'なし'}")
        except Exception as e:
            lines.append(f"NLLB: 確認失敗 ({e})")
        try:
            from core.opus_downloader import (
                list_downloaded as _opus_dl,
                list_downloaded_multilingual as _opus_mul,
            )
            pairs = _opus_dl()
            muls = _opus_mul()
            lines.append(f"OPUS-MT: {len(pairs)}ペア "
                         f"({', '.join(pairs) if pairs else 'なし'})")
            if muls:
                lines.append(f"OPUS-MT マルチリンガル: {', '.join(muls)}")
        except Exception as e:
            lines.append(f"OPUS-MT: 確認失敗 ({e})")
        try:
            import glob as _glob
            ggufs = sorted(_glob.glob(os.path.expanduser("~/pli-models/*.gguf")))
            names = [os.path.basename(g) for g in ggufs]
            lines.append(f"LLM (GGUF): {', '.join(names) if names else 'なし'}")
        except Exception as e:
            lines.append(f"LLM (GGUF): 確認失敗 ({e})")

        # 直近のエラーログ（発話本文はログ自体に含まれない設計）
        lines.append("--- 直近のERRORログ (最大5件) ---")
        errors = read_recent_errors(5)
        if errors:
            lines.extend(errors)
        else:
            lines.append("(なし)")
        return "\n".join(lines)

    def _on_copy_support_info(self):
        """ヘルプ > サポート情報をコピー"""
        from PySide6.QtWidgets import QApplication as _QApp
        try:
            info = self._build_support_info()
        except Exception as e:
            logger.error("サポート情報の生成に失敗: %s", e)
            QMessageBox.warning(self, "PLI",
                                f"サポート情報の生成に失敗しました。\n詳細: {e}")
            return
        _QApp.clipboard().setText(info)
        self.status_bar.showMessage(
            "📋 サポート情報をコピーしました（接見内容は含まれません）", 5000)

    def _show_about(self):
        QMessageBox.about(self, "PLI について",
            "<div style='text-align:center;'>"
            "<h2 style='color:#1a3a6a;'>PLI — Private Link Interpreter</h2>"
            "<p style='font-size:13px;'>完全オフライン AI 通訳システム</p>"
            f"<p style='font-size:13px;'>Version {__version__}</p><hr>"
            "<p style='font-size:12px; color:#666;'>開発</p>"
            "<p style='font-size:14px; font-weight:bold; color:#1a3a6a;'>中野通り法律事務所<br>弁護士  関  智之</p><hr>"
            "<p style='font-size:10px; color:#999;'>"
            "Copyright &copy; 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）<br>All rights reserved.<br><br>"
            "法律用語辞書: 法務省 JLT v18.0 + DEA DIR-022-18</p><hr>"
            "<p style='font-size:10px; color:#8a3a1a; text-align:left;'>"
            "<b>免責事項:</b> 本ソフトウェアは現状有姿（AS IS）で提供され、"
            "利用は完全に利用者の自己責任です。機械翻訳には誤訳のリスクが常に存在し、"
            "誤訳・誤動作に起因する一切の損害（依頼者への不利益・訴訟結果への影響を含む）"
            "について開発者は責任を負いません。重要な場面では必ず人間の通訳人による"
            "確認を併用してください。本ソフトウェアは弁護人の業務を補助する道具であり、"
            "通訳人を代替するものではありません。</p></div>")

    def _show_shortcut_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("ショートカット一覧")
        dlg.setMinimumSize(420, 400)
        dlg.setStyleSheet(f"background-color: {_BG}; color: {_TEXT};")
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        title = QLabel("PLI キーボードショートカット")
        title.setStyleSheet(f"color: {_ACCENT}; font-size: 14px; font-weight: bold; padding-bottom: 8px; border: none;")
        layout.addWidget(title)
        shortcuts = [
            ("基本操作", [("Enter", "入力した文章を送信"), ("Space", "マイクON/OFF（入力欄以外で）")]),
            ("画面制御", [("⌘1", "画面を隠す"), ("⌘2", "緊急消去"), ("⌘3", "相手画面の切替")]),
            ("音声認識", [("⌘5", "マイクON/OFF"), ("⌘6", "AUTO"), ("⌘7", "弁護人入力"), ("⌘8", "相手入力")]),
            ("承認パネル", [("O", "OK"), ("R", "やり直し"), ("E", "手動修正")]),
            ("その他", [("⌘D", "相手の発言をシミュレート"), ("⌘/", "このヘルプ")]),
        ]
        for section_title, items in shortcuts:
            sec = QLabel(section_title)
            sec.setStyleSheet(f"color: {_DIM}; font-size: 10px; letter-spacing: 2px; padding-top: 6px; border: none;")
            sec.setFont(QFont("Menlo", 9))
            layout.addWidget(sec)
            for key, desc in items:
                row = QHBoxLayout()
                row.setSpacing(12)
                kl = QLabel(key)
                kl.setFixedWidth(70)
                kl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                kl.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: bold; font-family: Menlo; border: none; background-color: {_SURFACE}; padding: 2px 6px; border-top: 1px solid {_RAISED_L}; border-left: 1px solid {_RAISED_L}; border-bottom: 1px solid {_RAISED_D}; border-right: 1px solid {_RAISED_D};")
                dl = QLabel(desc)
                dl.setStyleSheet(f"color: {_TEXT}; font-size: 12px; border: none;")
                row.addWidget(kl)
                row.addWidget(dl, stretch=1)
                layout.addLayout(row)
        layout.addStretch()
        close_btn = _make_btn("閉じる (Esc)", _BG)
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)
        dlg.exec()
