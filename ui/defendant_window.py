"""
PLI Defendant Display - 被疑者側ディスプレイ（表示専用）
平成初期レトロUI — クリーム地に紺と緑、一太郎的な佇まい
13インチポータブルモニター向け

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
All rights reserved.

DefendantPanel(QWidget) — 表示ロジック本体（埋め込み可）
DefendantWindow(QMainWindow) — スタンドアロンウィンドウ（Panelのラッパー）
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QScrollArea,
)
from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtGui import QFont

from ui.font_config import fs as _fs

# ---------------------------------------------------------------------------
# 被疑者向けステータスメッセージ（多言語）
# ---------------------------------------------------------------------------

STATUS_MESSAGES = {
    "en": {
        "verifying":  "Verifying with your attorney...",
        "confirmed":  "Confirmed",
        "retry":      "Could not understand. Please say that again.",
        "correcting": "Your attorney is correcting the translation.\nPlease wait...",
        "corrected":  "Corrected and confirmed",
        "attorney":   "Attorney:",
        "you_said":   "You said:",
        "ready":      "Ready",
        "interpreting": "Interpreting...",
        "waiting":    "Waiting for attorney...",
        "speak":      "Waiting for you to speak...",
    },
    "zh": {
        "verifying":  "律师正在确认翻译...",
        "confirmed":  "已确认",
        "retry":      "未能理解，请重新说一次。",
        "correcting": "律师正在修改翻译。\n请稍候...",
        "corrected":  "已修正并确认",
        "attorney":   "律师：",
        "you_said":   "你说的：",
        "ready":      "就绪",
        "interpreting": "正在翻译...",
        "waiting":    "等待律师确认...",
        "speak":      "等待您发言...",
    },
    "ko": {
        "verifying":  "변호사가 번역을 확인 중입니다...",
        "confirmed":  "확인됨",
        "retry":      "이해하지 못했습니다. 다시 말씀해 주세요.",
        "correcting": "변호사가 번역을 수정 중입니다.\n잠시 기다려 주세요...",
        "corrected":  "수정 확인 완료",
        "attorney":   "변호사:",
        "you_said":   "당신이 말한 것:",
        "ready":      "준비",
        "interpreting": "통역 중...",
        "waiting":    "변호사 확인 대기 중...",
        "speak":      "발언을 기다리고 있습니다...",
    },
    "vi": {
        "verifying":  "Luật sư đang xác nhận bản dịch...",
        "confirmed":  "Đã xác nhận",
        "retry":      "Không hiểu được. Xin hãy nói lại.",
        "correcting": "Luật sư đang sửa bản dịch.\nXin vui lòng đợi...",
        "corrected":  "Đã sửa và xác nhận",
        "attorney":   "Luật sư:",
        "you_said":   "Bạn đã nói:",
        "ready":      "Sẵn sàng",
        "interpreting": "Đang phiên dịch...",
        "waiting":    "Đang chờ luật sư...",
        "speak":      "Đang chờ bạn nói...",
    },
    "pt": {
        "verifying":  "Seu advogado está verificando a tradução...",
        "confirmed":  "Confirmado",
        "retry":      "Não foi possível entender. Por favor, repita.",
        "correcting": "Seu advogado está corrigindo a tradução.\nPor favor, aguarde...",
        "corrected":  "Corrigido e confirmado",
        "attorney":   "Advogado:",
        "you_said":   "Você disse:",
        "ready":      "Pronto",
        "interpreting": "Interpretando...",
        "waiting":    "Aguardando advogado...",
        "speak":      "Aguardando sua fala...",
    },
    "es": {
        "verifying":  "Su abogado está verificando la traducción...",
        "confirmed":  "Confirmado",
        "retry":      "No se pudo entender. Por favor, repita.",
        "correcting": "Su abogado está corrigiendo la traducción.\nPor favor, espere...",
        "corrected":  "Corregido y confirmado",
        "attorney":   "Abogado:",
        "you_said":   "Usted dijo:",
        "ready":      "Listo",
        "interpreting": "Interpretando...",
        "waiting":    "Esperando al abogado...",
        "speak":      "Esperando que hable...",
    },
    "tl": {
        "verifying":  "Bini-verify ng iyong abogado...",
        "confirmed":  "Na-confirm na",
        "retry":      "Hindi naintindihan. Pakiulit po.",
        "correcting": "Itinatama ng abogado ang pagsasalin.\nMaghintay po...",
        "corrected":  "Naitama at na-confirm na",
        "attorney":   "Abogado:",
        "you_said":   "Sinabi mo:",
        "ready":      "Handa na",
        "interpreting": "Nagsasalin...",
        "waiting":    "Naghihintay sa abogado...",
        "speak":      "Naghihintay sa iyong sasabihin...",
    },
    "ne": {
        "verifying":  "तपाईंको वकिलले अनुवाद जाँच गर्दै हुनुहुन्छ...",
        "confirmed":  "पुष्टि भयो",
        "retry":      "बुझिएन। कृपया फेरि भन्नुहोस्।",
        "correcting": "वकिलले अनुवाद सच्याउँदै हुनुहुन्छ।\nकृपया पर्खनुहोस्...",
        "corrected":  "सच्याइयो र पुष्टि गरियो",
        "attorney":   "वकिल:",
        "you_said":   "तपाईंले भन्नुभयो:",
        "ready":      "तयार",
        "interpreting": "अनुवाद गर्दै...",
        "waiting":    "वकिलको पुष्टि पर्खँदै...",
        "speak":      "तपाईंको कुरा पर्खँदै...",
    },
}


def _get_msg(lang: str, key: str) -> str:
    """指定言語のステータスメッセージを取得（未対応言語はen fallback）"""
    msgs = STATUS_MESSAGES.get(lang, STATUS_MESSAGES["en"])
    return msgs.get(key, STATUS_MESSAGES["en"].get(key, key))


# ---------------------------------------------------------------------------
# スタイル定数 — 平成初期レトロ（明るいクリーム地）
# ---------------------------------------------------------------------------

_BG       = "#d6d2c8"
_SURFACE  = "#e8e4da"
_SUNKEN   = "#c4c0b4"
_RAISED_L = "#f2eee6"
_RAISED_D = "#9e9a8e"
_FIELD    = "#fffff4"
_TEXT     = "#1a1a10"
_DIM      = "#6a6658"
_ATT_CLR  = "#1a3a6a"
_DEF_CLR  = "#2a6a30"
_WARN     = "#8a3a1a"
_BANNER_OK   = "#d0e8d0"
_BANNER_WAIT = "#d0d8e8"
_BANNER_WARN = "#e8dcc0"


class MessageEntry(QFrame):
    """会話ログの1エントリ（被疑者側表示）"""

    def __init__(self, speaker: str, text: str, lang: str = "en", parent=None):
        super().__init__(parent)
        self.speaker = speaker
        self._full_text = text
        self._current_text = ""
        self._char_index = 0
        self._lang = lang
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        is_attorney = self.speaker == "attorney"

        # 左色帯マーカー
        bar = QFrame()
        bar.setFixedWidth(4)
        bar.setStyleSheet(
            f"background-color: {_ATT_CLR if is_attorney else _DEF_CLR};"
            f"border: none;"
        )
        layout.addWidget(bar)

        # テキスト部
        text_widget = QWidget()
        text_widget.setStyleSheet(
            f"background-color: {_FIELD};"
            f"border-top: 1px solid {_RAISED_D};"
            f"border-bottom: 1px solid {_RAISED_L};"
        )
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(14, 10, 14, 10)
        text_layout.setSpacing(4)

        if is_attorney:
            label = _get_msg(self._lang, "attorney")
            color = _ATT_CLR
        else:
            label = _get_msg(self._lang, "you_said")
            color = _DEF_CLR

        header = QLabel(f"  {label}")
        header.setStyleSheet(
            f"color: {color}; font-size: {_fs(16)}; font-weight: bold; border: none;"
        )
        header.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        header.setCursor(Qt.IBeamCursor)
        text_layout.addWidget(header)

        self.text_label = QLabel("")
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.text_label.setCursor(Qt.IBeamCursor)
        self.text_label.setStyleSheet(
            f"color: {_TEXT}; font-size: {_fs(28)}; line-height: 1.6;"
            f"padding-left: 4px; border: none;"
        )
        text_layout.addWidget(self.text_label)

        layout.addWidget(text_widget, stretch=1)
        self.setStyleSheet("background: transparent; border: none;")

    def refresh_font(self):
        """フォントスケール変更時に再適用"""
        self.text_label.setStyleSheet(
            f"color: {_TEXT}; font-size: {_fs(28)}; line-height: 1.6;"
            f"padding-left: 4px; border: none;"
        )

    def set_text_immediate(self, text: str):
        self._full_text = text
        self._current_text = text
        self.text_label.setText(text)

    def start_typewriter(self, text: str = None):
        if text:
            self._full_text = text
        self._current_text = ""
        self._char_index = 0
        self.text_label.setText("")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._type_next)
        self._timer.start(30)

    def _type_next(self):
        if self._char_index < len(self._full_text):
            self._current_text += self._full_text[self._char_index]
            self.text_label.setText(self._current_text + "_")
            self._char_index += 1
        else:
            self.text_label.setText(self._current_text)
            self._timer.stop()

    def append_token(self, token: str):
        self._current_text += token
        self._full_text = self._current_text
        self.text_label.setText(self._current_text + "_")

    def finish_stream(self):
        self.text_label.setText(self._current_text)

    def update_text(self, text: str):
        self._full_text = text
        self._current_text = text
        self.text_label.setText(text)


# ---------------------------------------------------------------------------
# DefendantPanel — 表示ロジック本体（QWidget、埋め込み可能）
# ---------------------------------------------------------------------------

class DefendantPanel(QWidget):
    """被疑者ディスプレイの表示ロジック（ウィジェット版）
    AttorneyWindow内のスプリッターにも埋め込める。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[MessageEntry] = []
        self._current_stream_entry: MessageEntry | None = None
        self._status_banner: QLabel | None = None
        self._lang = "en"
        self._setup_ui()

    def _setup_ui(self):
        self.setStyleSheet(f"background-color: {_BG};")

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # ----- 会話ログエリア（凹みフレーム） -----
        log_frame = QFrame()
        log_frame.setStyleSheet(
            f"background-color: {_FIELD};"
            f"border-top: 1px solid {_RAISED_D};"
            f"border-left: 1px solid {_RAISED_D};"
            f"border-bottom: 1px solid {_RAISED_L};"
            f"border-right: 1px solid {_RAISED_L};"
            f"margin: 4px 6px;"
        )
        log_inner = QVBoxLayout(log_frame)
        log_inner.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{ border: none; background-color: {_FIELD}; }}
            QScrollBar:vertical {{
                background: {_SURFACE}; width: 14px;
                border-left: 1px solid {_RAISED_D};
            }}
            QScrollBar::handle:vertical {{
                background-color: {_BG};
                border-top: 1px solid {_RAISED_L};
                border-left: 1px solid {_RAISED_L};
                border-bottom: 1px solid {_RAISED_D};
                border-right: 1px solid {_RAISED_D};
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 14px;
                background-color: {_BG};
                border-top: 1px solid {_RAISED_L};
                border-left: 1px solid {_RAISED_L};
                border-bottom: 1px solid {_RAISED_D};
                border-right: 1px solid {_RAISED_D};
            }}
        """)
        self.log_container = QWidget()
        self.log_container.setStyleSheet(f"background-color: {_FIELD};")
        self.log_layout = QVBoxLayout(self.log_container)
        self.log_layout.setAlignment(Qt.AlignTop)
        self.log_layout.setSpacing(2)
        self.log_layout.setContentsMargins(12, 8, 12, 8)
        self.scroll_area.setWidget(self.log_container)
        log_inner.addWidget(self.scroll_area)
        main_layout.addWidget(log_frame, stretch=1)

        # ----- ステータスバー -----
        status_frame = QFrame()
        status_frame.setFixedHeight(26)
        status_frame.setStyleSheet(
            f"background-color: {_SURFACE};"
            f"border-top: 1px solid {_RAISED_L};"
            f"border-left: 1px solid {_RAISED_L};"
            f"border-bottom: 1px solid {_RAISED_D};"
            f"border-right: 1px solid {_RAISED_D};"
            f"margin: 0 6px 4px 6px;"
        )
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(10, 0, 10, 0)

        self.status_label = QLabel("Ready")
        self.status_label.setFont(QFont("Menlo", 10))
        self.status_label.setStyleSheet(
            f"color: {_DIM}; font-size: 11px; border: none;"
        )
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()

        self.session_label = QLabel("PLI")
        self.session_label.setFont(QFont("Menlo", 10))
        self.session_label.setStyleSheet(
            f"color: {_DIM}; font-size: 11px; border: none;"
        )
        status_layout.addWidget(self.session_label)

        main_layout.addWidget(status_frame)

    # ----- Slots -----

    @Slot(str)
    def on_language_change(self, lang_code: str):
        self._lang = lang_code

    @Slot(str, str)
    def on_message(self, msg_type: str, text: str):
        L = self._lang
        if msg_type == "attorney_start":
            entry = MessageEntry("attorney", "", lang=L)
            self.log_layout.addWidget(entry)
            self._entries.append(entry)
            self._current_stream_entry = entry
            self.status_label.setText(_get_msg(L, "interpreting"))
            self.status_label.setStyleSheet(
                f"color: {_ATT_CLR}; font-size: 11px; border: none;"
            )
            self._scroll_to_bottom()

        elif msg_type == "defendant_echo":
            entry = MessageEntry("defendant", text, lang=L)
            entry.set_text_immediate(text)
            self.log_layout.addWidget(entry)
            self._entries.append(entry)
            self._show_status_banner(
                _get_msg(L, "verifying"), _BANNER_WAIT, _ATT_CLR
            )
            self.status_label.setText(_get_msg(L, "waiting"))
            self.status_label.setStyleSheet(
                f"color: {_WARN}; font-size: 11px; border: none;"
            )
            self._scroll_to_bottom()

        elif msg_type == "clear_last":
            # 弁護人が修正/取消 → 最後のエントリを除去
            if self._entries:
                last = self._entries.pop()
                last.setParent(None)
                last.deleteLater()
            if self._current_stream_entry:
                self._current_stream_entry = None

        elif msg_type == "defendant_confirmed":
            self._remove_status_banner()
            self._show_status_banner(
                _get_msg(L, "confirmed"), _BANNER_OK, _DEF_CLR
            )
            self.status_label.setText(_get_msg(L, "ready"))
            self.status_label.setStyleSheet(
                f"color: {_DIM}; font-size: 11px; border: none;"
            )
            QTimer.singleShot(3000, self._remove_status_banner)

    @Slot(str)
    def on_stream_token(self, token: str):
        if self._current_stream_entry:
            self._current_stream_entry.append_token(token)
            self._scroll_to_bottom()

    def finish_stream(self):
        if self._current_stream_entry:
            self._current_stream_entry.finish_stream()
            self._current_stream_entry = None
            self.status_label.setText(_get_msg(self._lang, "ready"))

    @Slot()
    def on_correction(self):
        L = self._lang
        self._remove_status_banner()
        self._show_status_banner(
            _get_msg(L, "correcting"), _BANNER_WARN, _WARN
        )
        self.status_label.setText("Correction")
        self.status_label.setStyleSheet(
            f"color: {_WARN}; font-size: 11px; font-weight: bold; border: none;"
        )
        self._scroll_to_bottom()

    @Slot()
    def on_retry(self):
        L = self._lang
        self._remove_status_banner()
        entry = MessageEntry("attorney", "", lang=L)
        entry.set_text_immediate(_get_msg(L, "retry"))
        self.log_layout.addWidget(entry)
        self._entries.append(entry)
        self._scroll_to_bottom()
        self.status_label.setText(_get_msg(L, "speak"))
        self.status_label.setStyleSheet(
            f"color: {_WARN}; font-size: 11px; border: none;"
        )

    @Slot(str)
    def on_update_last(self, new_text: str):
        L = self._lang
        self._remove_status_banner()
        for entry in reversed(self._entries):
            if entry.speaker == "defendant":
                entry.update_text(new_text)
                break
        self._show_status_banner(
            _get_msg(L, "corrected"), _BANNER_OK, _DEF_CLR
        )
        self.status_label.setText(_get_msg(L, "ready"))
        self.status_label.setStyleSheet(
            f"color: {_DIM}; font-size: 11px; border: none;"
        )
        self._scroll_to_bottom()
        QTimer.singleShot(3000, self._remove_status_banner)

    @Slot()
    def on_clear(self):
        self._remove_status_banner()
        while self.log_layout.count():
            item = self.log_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._entries.clear()
        self._current_stream_entry = None
        self.status_label.setText(_get_msg(self._lang, "ready"))
        self.status_label.setStyleSheet(
            f"color: {_DIM}; font-size: 11px; border: none;"
        )

    def refresh_fonts(self):
        """フォントスケール変更時 — 全エントリのフォントを再適用"""
        for entry in self._entries:
            entry.refresh_font()

    # ----- 内部 -----

    def _show_status_banner(self, text: str, bg_color: str, text_color: str):
        self._remove_status_banner()
        banner = QLabel(text)
        banner.setAlignment(Qt.AlignCenter)
        banner.setWordWrap(True)
        banner.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        banner.setCursor(Qt.IBeamCursor)
        banner.setStyleSheet(
            f"background-color: {bg_color}; color: {text_color};"
            f"font-size: {_fs(18)}; font-weight: bold;"
            f"padding: 12px;"
            f"border-top: 1px solid {_RAISED_L};"
            f"border-left: 1px solid {_RAISED_L};"
            f"border-bottom: 1px solid {_RAISED_D};"
            f"border-right: 1px solid {_RAISED_D};"
            f"margin: 6px 0px;"
        )
        banner.setObjectName("status_banner")
        self.log_layout.addWidget(banner)
        self._status_banner = banner

    def _remove_status_banner(self):
        if hasattr(self, '_status_banner') and self._status_banner:
            self._status_banner.deleteLater()
            self._status_banner = None

    def _scroll_to_bottom(self):
        QTimer.singleShot(100, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))


# ---------------------------------------------------------------------------
# DefendantWindow — スタンドアロンウィンドウ（DefendantPanelのラッパー）
# ---------------------------------------------------------------------------

class DefendantWindow(QMainWindow):
    """被疑者側ディスプレイ（表示専用・操作UIなし）"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Private Link Interpreter")
        self.setMinimumSize(800, 600)

        self._panel = DefendantPanel()
        self.setCentralWidget(self._panel)

    # --- パネルへのプロキシ（外部API互換性維持） ---

    @property
    def panel(self) -> DefendantPanel:
        return self._panel

    @Slot(str)
    def on_language_change(self, lang_code: str):
        self._panel.on_language_change(lang_code)

    @Slot(str, str)
    def on_message(self, msg_type: str, text: str):
        self._panel.on_message(msg_type, text)

    @Slot(str)
    def on_stream_token(self, token: str):
        self._panel.on_stream_token(token)

    def finish_stream(self):
        self._panel.finish_stream()

    @Slot()
    def on_correction(self):
        self._panel.on_correction()

    @Slot()
    def on_retry(self):
        self._panel.on_retry()

    @Slot(str)
    def on_update_last(self, new_text: str):
        self._panel.on_update_last(new_text)

    @Slot()
    def on_clear(self):
        self._panel.on_clear()

    def do_hide(self):
        self.hide()

    def do_reveal(self):
        self.show()
        self.raise_()
