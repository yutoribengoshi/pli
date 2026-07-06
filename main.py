"""
PLI - Private Link Interpreter
完全オフライン AI 通訳システム

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
All rights reserved.
本ソフトウェアの開発者クレジットを削除・改変することを禁じます。

使い方:
  python main.py                    # モック + 自動表示モード（1画面→切替）
  python main.py --real             # 実モデルで起動
  python main.py --display switch   # 1画面・F3で全画面切替
  python main.py --display unified  # 1画面・左右分割
  python main.py --display dual     # 2画面モード
"""

__author__ = "関智之（東京弁護士会所属）(Tomoyuki Seki)"
__copyright__ = "Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）"
__license__ = "Proprietary"

import sys
import os
import argparse
import threading
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog
from PySide6.QtCore import Qt, QTimer, QObject, Signal

from core.logging_setup import setup_logging, get_logger
from core.version import __version__  # noqa: F401  バージョン単一ソース
from core.interpreter import Interpreter, EngineType
from core.whisper_stt import whisper_model_downloaded, download_whisper_model
from core.recorder import Recorder, RecordMode
from core.hide_mode import HideMode, HideSettings
from core.stt_listener import STTListener, ListenerState
from ui.attorney_window import AttorneyWindow
from ui.defendant_window import DefendantWindow

logger = get_logger(__name__)

_CRASH_MESSAGE = (
    "予期しないエラーが発生しました。\n"
    "ログフォルダのpli.logを添えて開発者にご連絡ください。"
)


def _install_excepthooks():
    """クラッシュ可視化: 未捕捉例外をログに記録し、可能ならダイアログ表示。

    - メインスレッド: logger.critical + QMessageBox（QApplication 起動済みの場合のみ）
    - ワーカースレッド: logger.critical のみ（ダイアログは出さない）
    """

    def _handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("未捕捉例外:\n%s", tb_text)
        try:
            if QApplication.instance() is not None:
                QMessageBox.critical(None, "PLI - エラー", _CRASH_MESSAGE)
        except Exception:
            # ダイアログ表示自体の失敗でクラッシュ処理を壊さない
            pass

    def _handle_thread_exception(args):
        if issubclass(args.exc_type, SystemExit):
            return
        tb_text = "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback))
        name = args.thread.name if args.thread else "unknown"
        logger.critical("ワーカースレッド未捕捉例外 (%s):\n%s", name, tb_text)

    sys.excepthook = _handle_exception
    threading.excepthook = _handle_thread_exception


class _ThreadBridge(QObject):
    """バックグラウンドスレッド → メインスレッドへの安全なシグナルブリッジ"""
    stt_result = Signal(str, str)       # (text, lang)
    stt_state = Signal(str)             # state.value
    stt_error = Signal(str)             # message
    whisper_dl_done = Signal(bool, str)  # (success, error_message)


class PLIApp:
    """PLI アプリケーション統合クラス"""

    def __init__(self, mock: bool = True, model_path: str = "",
                 display_mode: str = "auto", n_ctx: int = 2048,
                 engine_type: str = "llm", nllb_model_dir: str = "",
                 whisper_model: str = ""):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("PLI")
        self.app.setStyle("Fusion")

        self._display_mode = display_mode
        self._n_ctx = n_ctx
        self._engine_type_str = engine_type   # "llm" or "nllb" or "hybrid"
        self._nllb_model_dir = nllb_model_dir

        # EngineType 決定
        if mock:
            etype = EngineType.MOCK
        elif engine_type == "hybrid":
            etype = EngineType.HYBRID
        elif engine_type == "nllb":
            etype = EngineType.NLLB
        else:
            etype = EngineType.LLM

        # ----- コアコンポーネント -----
        self.interpreter = Interpreter(
            mock=mock, model_path=model_path, n_ctx=n_ctx,
            engine_type=etype, nllb_model_dir=nllb_model_dir,
            whisper_model=whisper_model,
        )
        self.recorder = Recorder()
        self.hide_mode = HideMode(HideSettings(
            wipe_log_on_hide=True,
            wipe_recording_on_hide=True,
            dummy_pdf_path="",
        ))

        # ----- 表示モード判定（ウィンドウ生成前に必要） -----
        self._effective_mode = self._resolve_display_mode()

        # view_style: switch or split
        if self._effective_mode == "switch":
            view_style = "switch"
        else:
            view_style = "split"

        # ----- ウィンドウ -----
        self.attorney = AttorneyWindow(self.interpreter, self.recorder,
                                       view_style=view_style)
        self.defendant = DefendantWindow()

        # ----- シグナル接続 -----
        self._connect_signals()

        # ----- STTリスナー -----
        self.stt_listener = STTListener(stt_engine=self.interpreter.stt)

        # スレッド安全なシグナルブリッジ（emit→メインスレッドのslotに自動配送）
        self._bridge = _ThreadBridge()
        self._bridge.stt_result.connect(self.attorney.on_stt_result)
        self._bridge.stt_state.connect(self.attorney.on_stt_state_change)
        self._bridge.stt_error.connect(self.attorney.on_stt_error)
        self._bridge.whisper_dl_done.connect(self._on_whisper_download_finished)
        self._whisper_dl_dialog = None  # ダウンロード中のQProgressDialog

        # STTリスナーのコールバック → Signal.emit（スレッド安全）
        self.stt_listener.on_result = lambda text, lang: self._bridge.stt_result.emit(text, lang)
        self.stt_listener.on_state_change = lambda state: self._bridge.stt_state.emit(state.value)
        self.stt_listener.on_error = lambda msg: self._bridge.stt_error.emit(msg)

        # ⌘5トグル → STTリスナーのstart/stop
        self.attorney.stt_toggled.connect(self._on_stt_toggled)

        # 感度・テンポ → STTリスナーのプリセット切替
        self.attorney.stt_sensitivity_changed.connect(self.stt_listener.set_sensitivity)
        self.attorney.stt_tempo_changed.connect(self.stt_listener.set_tempo)

        # LLMモデル切替 → 設定保存 & 再起動
        self.attorney.llm_model_changed.connect(self._on_llm_model_changed)
        self.attorney.llm_ctx_changed.connect(self._on_llm_ctx_changed)

        # エンジン切替 → 設定保存 & 再起動
        self.attorney.engine_type_changed.connect(self._on_engine_type_changed)
        self.attorney.nllb_model_changed.connect(self._on_nllb_model_changed)

        # NLLB/ハイブリッドモード時はUIを調整
        if etype == EngineType.NLLB:
            self.attorney.update_engine_mode(is_nllb=True)
        elif etype == EngineType.HYBRID:
            self.attorney.update_engine_mode(is_hybrid=True)

        # ----- ハイドモード コールバック -----
        self.hide_mode.set_callbacks(
            on_hide=self._on_hide,
            on_reveal=self._on_reveal,
            on_panic=self._on_panic,
        )

    def _connect_signals(self):
        """弁護人コンソール ⇔ 被疑者ディスプレイのシグナル接続"""

        # 通常メッセージ（スタンドアロンDefendantWindowへ）
        self.attorney.send_to_defendant.connect(self.defendant.on_message)

        # ストリーミング（タイプライター）
        self.attorney.stream_to_defendant.connect(self.defendant.on_stream_token)
        self.attorney.finish_defendant_stream.connect(self.defendant.finish_stream)

        # 手動修正中表示
        self.attorney.defendant_correction.connect(self.defendant.on_correction)

        # やり直し
        self.attorney.defendant_retry.connect(self.defendant.on_retry)

        # ログ上書き
        self.attorney.defendant_update_last.connect(self.defendant.on_update_last)

        # ログクリア
        self.attorney.clear_defendant.connect(self.defendant.on_clear)

        # 言語切替
        self.attorney.defendant_lang_change.connect(self.defendant.on_language_change)

        # ハイドモード
        self.attorney.request_hide.connect(self._toggle_hide)
        self.attorney.request_panic.connect(self._do_panic)

        # 埋め込みパネルトグル → DefendantWindowの表示切替
        self.attorney.embedded_panel_toggled.connect(self._on_embedded_toggled)

        # NOTE: 埋め込みDefendantPanelへのシグナル接続は
        # AttorneyWindow._connect_embedded_panel() で自動実行済み

    def _on_embedded_toggled(self, embedded: bool):
        """埋め込みパネルON → DefendantWindowを非表示
           埋め込みパネルOFF → 表示モードに応じて復帰"""
        if embedded:
            self.defendant.hide()
        else:
            if self._effective_mode == "dual":
                self.defendant.show()

    def _toggle_hide(self):
        """F1 トグル"""
        self._sync_hide_settings_from_ui()
        self.hide_mode.toggle_hide()

    def _do_panic(self):
        """F2 パニック"""
        self._sync_hide_settings_from_ui()
        self.hide_mode.panic()

    def _sync_hide_settings_from_ui(self):
        prefs = self.attorney.get_hide_preferences()
        self.hide_mode.settings.wipe_log_on_hide = bool(prefs["wipe_log_on_hide"])
        self.hide_mode.settings.wipe_recording_on_hide = bool(prefs["wipe_recording_on_hide"])
        self.hide_mode.settings.dummy_pdf_path = str(prefs["dummy_pdf_path"])

    def _on_stt_toggled(self, active: bool):
        """⌘5: STTリスナーのON/OFF"""
        if active:
            # STTエンジンが最新のものを使う（モデルロード完了後）
            self.stt_listener.stt = self.interpreter.stt
            self.stt_listener.start()
            logger.info("STTリスナー開始")
        else:
            self.stt_listener.stop()
            logger.info("STTリスナー停止")

    def _on_hide(self, settings: HideSettings):
        """ハイドモード発動時"""
        # STTも停止
        if self.stt_listener._running:
            self.stt_listener.stop()
            self.attorney._stt_active = False
            self.attorney._stt_action.setChecked(False)

        self.attorney.do_hide()
        self.defendant.do_hide()

        if settings.wipe_log_on_hide:
            self.interpreter.clear_conversation()
            self.attorney.clear_logs()
        if settings.wipe_recording_on_hide:
            self.recorder.wipe(delete_saved_files=True)

        self.interpreter.pause()

    def _on_reveal(self):
        """ハイドモード復帰時"""
        self.attorney.do_reveal()
        # dual + 埋め込みOFFの場合のみDefendantWindow復帰
        if self._effective_mode == "dual" and not self.attorney._embed_visible:
            self.defendant.do_reveal()
        self.interpreter.resume()

    def _on_panic(self):
        """パニック発動時 — 問答無用で全消去"""
        # STTも停止
        self.stt_listener.stop()
        self.attorney._stt_active = False
        self.attorney._stt_action.setChecked(False)

        self.attorney.do_hide()
        self.defendant.do_hide()

        self.attorney.wipe_all(delete_saved_recordings=True)
        self.interpreter.pause()

    def _on_llm_model_changed(self, model_path: str):
        """LLMモデル変更 → 設定保存 & アプリ再起動"""
        self._save_config(model_path=model_path)
        self._restart_app(model_path=model_path)

    def _on_llm_ctx_changed(self, n_ctx: int):
        """コンテキスト長変更 → 設定保存 & アプリ再起動"""
        self._n_ctx = n_ctx
        self._save_config(n_ctx=n_ctx)
        self._restart_app(n_ctx=n_ctx)

    def _on_engine_type_changed(self, engine_type: str):
        """翻訳エンジン変更 → 設定保存 & 再起動"""
        self._engine_type_str = engine_type
        self._save_config(engine_type=engine_type)
        self._restart_app()

    def _on_nllb_model_changed(self, model_key: str):
        """NLLBモデル変更 → エンジンもNLLBに切替 & 設定保存 & 再起動"""
        from core.nllb_downloader import get_model_dir
        nllb_dir = get_model_dir(model_key)
        self._engine_type_str = "nllb"
        self._nllb_model_dir = nllb_dir
        self._save_config(engine_type="nllb", nllb_model_key=model_key)
        self._restart_app()

    def _save_config(self, model_path: str = None, n_ctx: int = None,
                     engine_type: str = None, nllb_model_key: str = None):
        """設定ファイルに保存"""
        config_dir = os.path.expanduser("~/pli-models")
        os.makedirs(config_dir, exist_ok=True)
        if model_path:
            try:
                with open(os.path.join(config_dir, "last_model.txt"), "w") as f:
                    f.write(model_path)
                logger.info("モデル設定を保存: %s", os.path.basename(model_path))
            except Exception as e:
                logger.warning("モデル設定の保存に失敗: %s", e)
        if n_ctx:
            try:
                with open(os.path.join(config_dir, "last_n_ctx.txt"), "w") as f:
                    f.write(str(n_ctx))
                logger.info("コンテキスト長を保存: %s", n_ctx)
            except Exception as e:
                logger.warning("コンテキスト長の保存に失敗: %s", e)
        if engine_type:
            try:
                with open(os.path.join(config_dir, "last_engine.txt"), "w") as f:
                    f.write(engine_type)
                logger.info("エンジン設定を保存: %s", engine_type)
            except Exception as e:
                logger.warning("エンジン設定の保存に失敗: %s", e)
        if nllb_model_key:
            try:
                with open(os.path.join(config_dir, "last_nllb_model.txt"), "w") as f:
                    f.write(nllb_model_key)
                logger.info("NLLBモデル設定を保存: %s", nllb_model_key)
            except Exception as e:
                logger.warning("NLLBモデル設定の保存に失敗: %s", e)

    def _restart_app(self, model_path: str = None, n_ctx: int = None):
        """アプリを再起動"""
        logger.info("設定変更のためアプリを再起動します")
        import subprocess
        model_path = model_path or self.interpreter._model_path or ""
        n_ctx = self._n_ctx if n_ctx is None else n_ctx
        if getattr(sys, 'frozen', False):
            # PyInstaller凍結.app: sys.executable がアプリ本体そのもの。
            # スクリプトパスを渡すと argv[1] が未知の引数となり新プロセスが即死する
            args = [sys.executable]
        else:
            args = [sys.executable, os.path.abspath(__file__)]
        args += ["--display", self._display_mode,
                 "--engine", self._engine_type_str]
        if not self.interpreter.mock:
            args.append("--real")
        if not self.interpreter.mock and self._engine_type_str in ("nllb", "hybrid"):
            if self._nllb_model_dir:
                args += ["--nllb-dir", self._nllb_model_dir]
        if not self.interpreter.mock and self._engine_type_str in ("llm",):
            args += ["--model", model_path, "--n-ctx", str(n_ctx)]
        subprocess.Popen(args)
        self.app.quit()

    def _resolve_display_mode(self) -> str:
        """表示モードを自動判定"""
        if self._display_mode != "auto":
            return self._display_mode

        screens = self.app.screens()
        if len(screens) > 1:
            return "dual"
        else:
            return "switch"

    def run(self):
        """アプリケーション起動"""
        screens = self.app.screens()

        if self._effective_mode == "dual" and len(screens) > 1:
            # ----- デュアルモニター -----
            self.attorney.show()
            second_screen = screens[1]
            geo = second_screen.geometry()
            self.defendant.move(geo.x(), geo.y())
            self.defendant.showFullScreen()

        elif self._effective_mode == "dual":
            # ----- dual指定だがシングルモニター → 2ウィンドウ並べる -----
            self.attorney.resize(700, 600)
            self.attorney.move(50, 50)
            self.attorney.show()
            self.defendant.resize(700, 600)
            self.defendant.move(760, 50)
            self.defendant.show()

        elif self._effective_mode == "switch":
            # ----- switch: 1画面全画面切替（F3でトグル） -----
            self.attorney.resize(1000, 700)
            self.attorney.show()
            # 初期は弁護人画面を表示、F3で被疑者画面に切替
            # DefendantWindowは生成済みだが非表示

        else:
            # ----- unified: 左右分割モード -----
            self.attorney.resize(1200, 700)
            self.attorney.set_embedded_panel_visible(True)
            self.attorney.show()
            # DefendantWindowは生成済みだが非表示
            # F3でトグル、またはメニューから切替可能

        mode_label = {
            "dual":    "2画面",
            "unified": "統合(左右分割)",
            "switch":  "切替(F3で全画面切替)",
        }.get(self._effective_mode, self._effective_mode)

        logger.info("PLI - Private Link Interpreter 起動")
        logger.info("モード: %s",
                    "モック（テスト用）" if self.interpreter.mock else "実モデル")
        if not self.interpreter.mock:
            if self._engine_type_str == "hybrid":
                nllb_name = os.path.basename(self._nllb_model_dir) if self._nllb_model_dir else "(なし)"
                logger.info("エンジン: ハイブリッド (OPUS-MT + NLLB)")
                logger.info("NLLBフォールバック: %s", nllb_name)
                try:
                    from core.opus_downloader import list_downloaded
                    dl = list_downloaded()
                    logger.info("OPUS-MTペア: %d ダウンロード済み", len(dl))
                except ImportError:
                    pass
            elif self._engine_type_str == "nllb":
                nllb_name = os.path.basename(self._nllb_model_dir) if self._nllb_model_dir else "?"
                logger.info("エンジン: NLLB (CTranslate2 軽量)")
                logger.info("モデル: %s", nllb_name)
            elif self.interpreter._model_path:
                model_name = os.path.splitext(os.path.basename(self.interpreter._model_path))[0]
                logger.info("エンジン: LLM (llama.cpp)")
                logger.info("モデル: %s (n_ctx=%d)", model_name, self._n_ctx)
        logger.info("表示: %s", mode_label)

        # GUI表示後にモデルをバックグラウンドロード
        # モック時もSTT(Whisper)だけはロードする
        self.attorney.set_loading_state(True)
        QTimer.singleShot(100, self._start_model_loading)

        import atexit
        atexit.register(self.interpreter.cleanup)
        return self.app.exec()

    def _start_model_loading(self):
        """GUI表示後にモデルロードを開始（必要ならWhisperモデルの事前DLを挟む）"""
        # 実モード時: Whisper STTモデル（約1.5GB）が未DLなら、初回transcribe()での
        # 無断ダウンロード（オフライン接見先では英語例外で死ぬ）を防ぐため先に確認する
        if not self.interpreter.mock and not whisper_model_downloaded():
            self._prompt_whisper_download()
            return
        self._load_models()

    def _prompt_whisper_download(self):
        """Whisperモデル未DL時の確認ダイアログ → バックグラウンドDL"""
        ret = QMessageBox.question(
            self.attorney,
            "音声認識モデルのダウンロード",
            "音声認識モデル（約1.5GB）が未ダウンロードです。\n"
            "今すぐダウンロードしますか？\n\n"
            "（Wi-Fi環境推奨。接見先などオフライン環境では"
            "音声認識が使えません）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if ret != QMessageBox.Yes:
            # スキップ: STT初回利用時に通常のエラー表示に任せる
            self._load_models()
            return

        # 進捗ダイアログ（不定長・キャンセル不可）
        dialog = QProgressDialog(
            "音声認識モデルをダウンロード中…（約1.5GB）\n"
            "回線速度により数分かかります。", "", 0, 0, self.attorney)
        dialog.setWindowTitle("PLI - モデルダウンロード")
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.show()
        self._whisper_dl_dialog = dialog

        def _worker():
            try:
                download_whisper_model()
                self._bridge.whisper_dl_done.emit(True, "")
            except Exception as e:
                self._bridge.whisper_dl_done.emit(False, str(e))

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _on_whisper_download_finished(self, ok: bool, message: str):
        """WhisperモデルDL完了（メインスレッド・Signal経由）"""
        if self._whisper_dl_dialog is not None:
            self._whisper_dl_dialog.close()
            self._whisper_dl_dialog = None
        if ok:
            logger.info("Whisperモデルのダウンロード完了")
        else:
            logger.warning("Whisperモデルのダウンロード失敗: %s", message)
            QMessageBox.warning(
                self.attorney,
                "ダウンロード失敗",
                "音声認識モデルのダウンロードに失敗しました。\n"
                "ネットワーク接続を確認して再起動してください。\n"
                "（翻訳機能はこのまま利用できます）\n\n"
                f"詳細: {message}",
            )
        self._load_models()

    def _load_models(self):
        """モデルのバックグラウンドロード本体"""
        # スレッド間通信用の共有状態
        self._loading_done = False
        self._loading_progress = ("llm", 0.0)
        self._loading_ready = False
        self._loading_message = ""

        def on_ready(ready: bool, message: str):
            logger.info("on_ready コールバック発火")
            if self.interpreter.stt_ready:
                self.stt_listener.stt = self.interpreter.stt
            self._loading_ready = ready
            self._loading_message = message
            self._loading_done = True  # フラグでメインスレッドに通知
            self._loading_is_mock = self.interpreter.mock  # モック時はラベル変更しない

        def on_progress(phase: str, progress: float):
            self._loading_progress = (phase, progress)  # メインスレッドがポーリング

        # メインスレッドのポーリングタイマー（200ms間隔）
        self._model_poll_timer = QTimer()
        def _check_loading():
            # 進捗更新
            phase, progress = self._loading_progress
            self.attorney.set_loading_progress(phase, progress)
            # 完了チェック
            if self._loading_done:
                self._model_poll_timer.stop()
                self._model_poll_timer = None
                self.attorney.set_loading_state(
                    False,
                    ready=self._loading_ready,
                    message=self._loading_message,
                )
                logger.info("set_loading_state(False) 実行")
        self._model_poll_timer.timeout.connect(_check_loading)
        self._model_poll_timer.start(200)

        self.interpreter.load_models_async(on_ready=on_ready, on_progress=on_progress)


def main():
    # ログ基盤を最初に初期化（以降の全処理がログに残る）
    setup_logging()
    logger.info("PLI v%s 起動 (python=%s, frozen=%s)",
                __version__, sys.version.split()[0],
                getattr(sys, "frozen", False))
    _install_excepthooks()

    parser = argparse.ArgumentParser(description="PLI - Private Link Interpreter")
    parser.add_argument("--real", action="store_true", help="実モデルで起動")
    parser.add_argument("--model", type=str, default="", help="LLMモデルのパス")
    parser.add_argument("--n-ctx", type=int, default=0, help="コンテキスト長 (0=自動)")
    parser.add_argument("--engine", type=str, default="auto",
                        choices=["auto", "llm", "nllb", "hybrid"],
                        help="翻訳エンジン: auto(自動), llm(llama.cpp), nllb(軽量), hybrid(最高精度)")
    parser.add_argument("--nllb-dir", type=str, default="",
                        help="NLLBモデルディレクトリ")
    parser.add_argument("--display", type=str, default="auto",
                        choices=["auto", "dual", "unified", "switch"],
                        help="表示モード: auto(自動), dual(2画面), unified(左右分割), switch(全画面切替)")
    parser.add_argument("--whisper", type=str, default="",
                        help="Whisperモデルサイズ: tiny, base, small, medium, large-v3-turbo, large-v3")
    args = parser.parse_args()

    # .app バンドル（PyInstaller）から起動時はデフォルトで実モード
    is_frozen = getattr(sys, 'frozen', False)
    mock = not (args.real or is_frozen)
    model_path = args.model
    n_ctx = args.n_ctx
    engine_type = args.engine
    nllb_model_dir = args.nllb_dir
    config_dir = os.path.expanduser("~/pli-models")

    # --- エンジン種別の復元 ---
    if engine_type == "auto":
        engine_cfg = os.path.join(config_dir, "last_engine.txt")
        if os.path.exists(engine_cfg):
            try:
                saved_engine = Path(engine_cfg).read_text().strip()
                if saved_engine in ("llm", "nllb", "hybrid"):
                    engine_type = saved_engine
                    logger.info("前回のエンジンを使用: %s", engine_type)
            except OSError:
                pass
        if engine_type == "auto":
            engine_type = "hybrid"  # デフォルト（LLM 32Bは重すぎる）

    # --- NLLBモード ---
    if engine_type == "nllb":
        if not nllb_model_dir:
            # 前回のNLLBモデルを復元
            nllb_cfg = os.path.join(config_dir, "last_nllb_model.txt")
            if os.path.exists(nllb_cfg):
                try:
                    from core.nllb_downloader import get_model_dir, is_downloaded
                    saved_key = Path(nllb_cfg).read_text().strip()
                    if saved_key and is_downloaded(saved_key):
                        nllb_model_dir = get_model_dir(saved_key)
                        logger.info("前回のNLLBモデルを使用: %s", saved_key)
                except (ImportError, OSError):
                    pass

            if not nllb_model_dir:
                # フォールバック: ダウンロード済みの最初のNLLBモデル
                try:
                    from core.nllb_downloader import list_downloaded, get_model_dir
                    downloaded = list_downloaded()
                    if downloaded:
                        nllb_model_dir = get_model_dir(downloaded[0])
                        logger.info("検出NLLBモデル: %s", downloaded[0])
                except ImportError:
                    pass

            if not nllb_model_dir:
                logger.error("NLLBモデルが見つかりません")
                logger.info("アプリ内のメニューからNLLBモデルをダウンロードしてください")
                logger.info("LLMモードに切り替えます")
                engine_type = "llm"

    # --- ハイブリッドモード ---
    if engine_type == "hybrid":
        # NLLBフォールバックモデルの準備
        if not nllb_model_dir:
            nllb_cfg = os.path.join(config_dir, "last_nllb_model.txt")
            if os.path.exists(nllb_cfg):
                try:
                    from core.nllb_downloader import get_model_dir, is_downloaded
                    saved_key = Path(nllb_cfg).read_text().strip()
                    if saved_key and is_downloaded(saved_key):
                        nllb_model_dir = get_model_dir(saved_key)
                        logger.info("NLLBフォールバック: %s", saved_key)
                except (ImportError, OSError):
                    pass
            if not nllb_model_dir:
                try:
                    from core.nllb_downloader import list_downloaded, get_model_dir
                    downloaded = list_downloaded()
                    if downloaded:
                        nllb_model_dir = get_model_dir(downloaded[0])
                        logger.info("NLLBフォールバック検出: %s", downloaded[0])
                except ImportError:
                    pass
            if not nllb_model_dir:
                logger.warning("NLLBフォールバックモデルなし — OPUS-MTのみで動作します")

    # --- LLMモード ---
    if engine_type == "llm":
        if not model_path:
            # 前回選択したモデルを復元
            last_model_cfg = os.path.join(config_dir, "last_model.txt")
            if os.path.exists(last_model_cfg):
                with open(last_model_cfg) as f:
                    saved = f.read().strip()
                if saved and os.path.exists(saved):
                    model_path = saved
                    logger.info("前回のモデルを使用: %s", os.path.basename(model_path))

            # フォールバック: ~/pli-models/ 内の最初の .gguf
            if not model_path:
                import glob
                models_dir = os.path.expanduser("~/pli-models")
                gguf_files = sorted(glob.glob(os.path.join(models_dir, "*.gguf")))
                if gguf_files:
                    model_path = gguf_files[0]
                    logger.info("検出モデル: %s", os.path.basename(model_path))

            if not model_path or not os.path.exists(model_path):
                logger.error("LLMモデルが見つかりません")
                logger.info("~/pli-models/ にGGUFモデルを配置するか、--model でパスを指定してください")
                logger.info("モックモードで起動するには --real を外してください")
                sys.exit(1)

        # n_ctx 自動判定
        if n_ctx == 0:
            ctx_cfg = os.path.join(config_dir, "last_n_ctx.txt")
            if os.path.exists(ctx_cfg):
                try:
                    n_ctx = int(Path(ctx_cfg).read_text().strip())
                    logger.info("前回のコンテキスト長を使用: %d", n_ctx)
                except (ValueError, OSError):
                    pass
            if n_ctx == 0:
                n_ctx = _auto_n_ctx(model_path)
                logger.info("コンテキスト長を自動設定: %d", n_ctx)

    app = PLIApp(mock=mock, model_path=model_path, display_mode=args.display,
                 n_ctx=n_ctx, engine_type=engine_type, nllb_model_dir=nllb_model_dir,
                 whisper_model=args.whisper)
    sys.exit(app.run())


def _auto_n_ctx(model_path: str) -> int:
    """モデルファイルサイズからn_ctxを自動推定"""
    try:
        size_gb = os.path.getsize(model_path) / (1024 ** 3)
    except OSError:
        return 2048
    # 7B → 4096, 14B → 4096, 32B → 4096, 72B → 8192
    if size_gb > 35:   # 72B class
        return 8192
    elif size_gb > 15:  # 32B class
        return 4096
    else:               # 14B / 7B
        return 4096


if __name__ == "__main__":
    main()
