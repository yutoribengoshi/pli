"""
PLI - Private Link Interpreter
完全オフライン AI 通訳システム

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
本ソフトウェアの開発者クレジットを削除・改変することを禁じます。

使い方:
  python main.py                    # モック + 自動表示モード（1画面→切替）
  python main.py --real             # 実モデルで起動
  python main.py --display switch   # 1画面・F3で全画面切替
  python main.py --display unified  # 1画面・左右分割
  python main.py --display dual     # 2画面モード
"""

__author__ = "関智之 (Tomoyuki Seki)"
__copyright__ = "Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之"
__version__ = "2.0.0"
__license__ = "Proprietary"

import sys
import os
import argparse

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer, QObject, Signal

from core.interpreter import Interpreter, EngineType
from core.recorder import Recorder, RecordMode
from core.hide_mode import HideMode, HideSettings
from core.stt_listener import STTListener, ListenerState
from ui.attorney_window import AttorneyWindow
from ui.defendant_window import DefendantWindow


class _ThreadBridge(QObject):
    """バックグラウンドスレッド → メインスレッドへの安全なシグナルブリッジ"""
    stt_result = Signal(str, str)       # (text, lang)
    stt_state = Signal(str)             # state.value
    stt_error = Signal(str)             # message


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
        self._bridge.stt_error.connect(
            lambda msg: self.attorney.status_bar.showMessage(f"STTエラー: {msg}", 5000))

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
            print("[STT] リスナー開始")
        else:
            self.stt_listener.stop()
            print("[STT] リスナー停止")

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
                print(f"[info] モデル設定を保存: {os.path.basename(model_path)}")
            except Exception as e:
                print(f"[warn] モデル設定の保存に失敗: {e}")
        if n_ctx:
            try:
                with open(os.path.join(config_dir, "last_n_ctx.txt"), "w") as f:
                    f.write(str(n_ctx))
                print(f"[info] コンテキスト長を保存: {n_ctx}")
            except Exception as e:
                print(f"[warn] コンテキスト長の保存に失敗: {e}")
        if engine_type:
            try:
                with open(os.path.join(config_dir, "last_engine.txt"), "w") as f:
                    f.write(engine_type)
                print(f"[info] エンジン設定を保存: {engine_type}")
            except Exception as e:
                print(f"[warn] エンジン設定の保存に失敗: {e}")
        if nllb_model_key:
            try:
                with open(os.path.join(config_dir, "last_nllb_model.txt"), "w") as f:
                    f.write(nllb_model_key)
                print(f"[info] NLLBモデル設定を保存: {nllb_model_key}")
            except Exception as e:
                print(f"[warn] NLLBモデル設定の保存に失敗: {e}")

    def _restart_app(self, model_path: str = None, n_ctx: int = None):
        """アプリを再起動"""
        print("[info] 設定変更のためアプリを再起動します...")
        import subprocess
        model_path = model_path or self.interpreter._model_path or ""
        n_ctx = self._n_ctx if n_ctx is None else n_ctx
        args = [sys.executable, os.path.abspath(__file__),
                "--display", self._display_mode,
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

        print("=" * 50)
        print("  PLI - Private Link Interpreter")
        print(f"  モード: {'モック（テスト用）' if self.interpreter.mock else '実モデル'}")
        if not self.interpreter.mock:
            if self._engine_type_str == "hybrid":
                nllb_name = os.path.basename(self._nllb_model_dir) if self._nllb_model_dir else "(なし)"
                print(f"  エンジン: ⚡ ハイブリッド (OPUS-MT + NLLB)")
                print(f"  NLLBフォールバック: {nllb_name}")
                try:
                    from core.opus_downloader import list_downloaded
                    dl = list_downloaded()
                    print(f"  OPUS-MTペア: {len(dl)} ダウンロード済み")
                except ImportError:
                    pass
            elif self._engine_type_str == "nllb":
                nllb_name = os.path.basename(self._nllb_model_dir) if self._nllb_model_dir else "?"
                print(f"  エンジン: NLLB (CTranslate2 軽量)")
                print(f"  モデル: {nllb_name}")
            elif self.interpreter._model_path:
                model_name = os.path.splitext(os.path.basename(self.interpreter._model_path))[0]
                print(f"  エンジン: LLM (llama.cpp)")
                print(f"  モデル: {model_name}  (n_ctx={self._n_ctx})")
        print(f"  表示: {mode_label}")
        print("  ⌘1: ハイドモード  ⌘2: パニック  ⌘3: 相手画面切替")
        print("=" * 50)

        # GUI表示後にモデルをバックグラウンドロード
        # モック時もSTT(Whisper)だけはロードする
        self.attorney.set_loading_state(True)
        QTimer.singleShot(100, self._start_model_loading)

        return self.app.exec()

    def _start_model_loading(self):
        """GUI表示後にモデルロードを開始"""
        # スレッド間通信用の共有状態
        self._loading_done = False
        self._loading_progress = ("llm", 0.0)
        self._loading_ready = False
        self._loading_message = ""

        def on_ready(ready: bool, message: str):
            print("[info] on_ready コールバック発火")
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
                print("[info] set_loading_state(False) 実行")
        self._model_poll_timer.timeout.connect(_check_loading)
        self._model_poll_timer.start(200)

        self.interpreter.load_models_async(on_ready=on_ready, on_progress=on_progress)


def main():
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
                saved_engine = open(engine_cfg).read().strip()
                if saved_engine in ("llm", "nllb", "hybrid"):
                    engine_type = saved_engine
                    print(f"[info] 前回のエンジンを使用: {engine_type}")
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
                    saved_key = open(nllb_cfg).read().strip()
                    if saved_key and is_downloaded(saved_key):
                        nllb_model_dir = get_model_dir(saved_key)
                        print(f"[info] 前回のNLLBモデルを使用: {saved_key}")
                except (ImportError, OSError):
                    pass

            if not nllb_model_dir:
                # フォールバック: ダウンロード済みの最初のNLLBモデル
                try:
                    from core.nllb_downloader import list_downloaded, get_model_dir
                    downloaded = list_downloaded()
                    if downloaded:
                        nllb_model_dir = get_model_dir(downloaded[0])
                        print(f"[info] 検出NLLBモデル: {downloaded[0]}")
                except ImportError:
                    pass

            if not nllb_model_dir:
                print("[error] NLLBモデルが見つかりません")
                print("[info] アプリ内のメニューからNLLBモデルをダウンロードしてください")
                print("[info] LLMモードに切り替えます...")
                engine_type = "llm"

    # --- ハイブリッドモード ---
    if engine_type == "hybrid":
        # NLLBフォールバックモデルの準備
        if not nllb_model_dir:
            nllb_cfg = os.path.join(config_dir, "last_nllb_model.txt")
            if os.path.exists(nllb_cfg):
                try:
                    from core.nllb_downloader import get_model_dir, is_downloaded
                    saved_key = open(nllb_cfg).read().strip()
                    if saved_key and is_downloaded(saved_key):
                        nllb_model_dir = get_model_dir(saved_key)
                        print(f"[info] NLLBフォールバック: {saved_key}")
                except (ImportError, OSError):
                    pass
            if not nllb_model_dir:
                try:
                    from core.nllb_downloader import list_downloaded, get_model_dir
                    downloaded = list_downloaded()
                    if downloaded:
                        nllb_model_dir = get_model_dir(downloaded[0])
                        print(f"[info] NLLBフォールバック検出: {downloaded[0]}")
                except ImportError:
                    pass
            if not nllb_model_dir:
                print("[warn] NLLBフォールバックモデルなし — OPUS-MTのみで動作します")

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
                    print(f"[info] 前回のモデルを使用: {os.path.basename(model_path)}")

            # フォールバック: ~/pli-models/ 内の最初の .gguf
            if not model_path:
                import glob
                models_dir = os.path.expanduser("~/pli-models")
                gguf_files = sorted(glob.glob(os.path.join(models_dir, "*.gguf")))
                if gguf_files:
                    model_path = gguf_files[0]
                    print(f"[info] 検出モデル: {os.path.basename(model_path)}")

            if not model_path or not os.path.exists(model_path):
                print("[error] LLMモデルが見つかりません")
                print("[info] ~/pli-models/ にGGUFモデルを配置するか、--model でパスを指定してください")
                print("[info] モックモードで起動するには --real を外してください")
                sys.exit(1)

        # n_ctx 自動判定
        if n_ctx == 0:
            ctx_cfg = os.path.join(config_dir, "last_n_ctx.txt")
            if os.path.exists(ctx_cfg):
                try:
                    n_ctx = int(open(ctx_cfg).read().strip())
                    print(f"[info] 前回のコンテキスト長を使用: {n_ctx}")
                except (ValueError, OSError):
                    pass
            if n_ctx == 0:
                n_ctx = _auto_n_ctx(model_path)
                print(f"[info] コンテキスト長を自動設定: {n_ctx}")

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
