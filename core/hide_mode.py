"""
PLI Stealth Hide Mode - F1/F2 による即時隠蔽・消去機能
"""

import os
import sys
import subprocess
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class HideSettings:
    """ハイドモード設定"""
    wipe_log_on_hide: bool = True      # F1でログ消去するか
    wipe_recording_on_hide: bool = True # F1で録音消去するか
    dummy_pdf_path: str = ""            # ダミー表示用PDFのパス


class HideMode:
    """ステルスハイドモード管理"""

    def __init__(self, settings: Optional[HideSettings] = None):
        self.settings = settings or HideSettings()
        self.is_hidden = False
        self._on_hide: Optional[Callable] = None
        self._on_reveal: Optional[Callable] = None
        self._on_panic: Optional[Callable] = None
        self._dummy_process = None
        self._dummy_mode = ""

    def set_callbacks(self, on_hide=None, on_reveal=None, on_panic=None):
        self._on_hide = on_hide
        self._on_reveal = on_reveal
        self._on_panic = on_panic

    # ----- F1: ハイドモード（カスタマイズ可） -----

    def toggle_hide(self):
        """F1キーで呼ばれる"""
        if self.is_hidden:
            self.reveal()
        else:
            self.hide()

    def hide(self):
        """ステルスハイド発動"""
        self.is_hidden = True

        # ダミーアプリ表示
        self._close_dummy()
        self._show_dummy()

        # Dockから隠す（macOS固有）
        self._hide_from_dock()

        if self._on_hide:
            self._on_hide(self.settings)

    def reveal(self):
        """ハイドモード解除"""
        self.is_hidden = False

        # ダミーを閉じる
        self._close_dummy()

        # Dockに復帰
        self._show_in_dock()

        if self._on_reveal:
            self._on_reveal()

    # ----- F2: パニックボタン（全消去） -----

    def panic(self):
        """F2キーで呼ばれる - 問答無用で全消去"""
        self.is_hidden = True
        self._close_dummy()
        self._show_dummy()
        self._hide_from_dock()

        if self._on_panic:
            self._on_panic()

    # ----- macOS 固有の制御 -----

    def _hide_from_dock(self):
        """DockとCmd+Tabからアプリを除外"""
        try:
            self._set_process_visibility(False)
        except Exception:
            pass

    def _show_in_dock(self):
        """Dockにアプリを復帰"""
        try:
            self._set_process_visibility(True)
        except Exception:
            pass

    def _set_process_visibility(self, visible: bool):
        names = self._candidate_process_names()
        if not names:
            return
        quoted_names = ", ".join(f'"{name}"' for name in names)
        target_visible = "true" if visible else "false"
        script = (
            'tell application "System Events"\n'
            f'  repeat with procName in {{{quoted_names}}}\n'
            '    if exists process (contents of procName) then\n'
            f'      set visible of process (contents of procName) to {target_visible}\n'
            '      exit repeat\n'
            '    end if\n'
            '  end repeat\n'
            'end tell'
        )
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=2)

    def _candidate_process_names(self) -> list[str]:
        names: list[str] = []
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app and app.applicationName():
                names.append(app.applicationName())
        except Exception:
            pass

        exe_name = os.path.splitext(os.path.basename(sys.executable))[0]
        if exe_name:
            names.append(exe_name)
        if exe_name.lower().startswith("python"):
            names.append("Python")
        names.append("PLI")

        unique: list[str] = []
        for name in names:
            if name and name not in unique:
                unique.append(name)
        return unique

    def _show_dummy(self):
        """ダミーアプリを前面に表示"""
        pdf_path = self.settings.dummy_pdf_path
        if pdf_path and os.path.exists(pdf_path):
            try:
                self._dummy_process = subprocess.Popen(
                    ["qlmanage", "-p", pdf_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._dummy_mode = "quicklook"
                return
            except Exception:
                pass

        # PDFが未設定、またはQuick Look起動に失敗した場合はFinderを前面に
        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "Finder" to activate'],
                capture_output=True, timeout=2
            )
            self._dummy_mode = "finder"
        except Exception:
            self._dummy_mode = ""

    def _close_dummy(self):
        """ダミーアプリを閉じる"""
        if self._dummy_process:
            try:
                self._dummy_process.terminate()
                self._dummy_process.wait(timeout=2)
            except Exception:
                try:
                    self._dummy_process.kill()
                except Exception:
                    pass
            self._dummy_process = None
        self._dummy_mode = ""
