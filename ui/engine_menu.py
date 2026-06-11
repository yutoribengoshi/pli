"""
PLI Engine/Model Selection Menu Builder
エンジン・モデル選択メニューの構築ヘルパー

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""

from __future__ import annotations

import glob
import os
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenuBar, QMenu, QMessageBox, QProgressDialog

if TYPE_CHECKING:
    from core.interpreter import Interpreter


# ---------------------------------------------------------------------------
# モデル名 → 人間向けラベル
# ---------------------------------------------------------------------------

_MODEL_LABELS = {
    # 72B — 64GB RAM向け
    "Qwen2.5-72B-Instruct-Q5_K_M": "⭐ Qwen2.5 72B Q5_K_M（最高品質・RAM 52GB〜）",
    "Qwen2.5-72B-Instruct-Q4_K_M": "⭐ Qwen2.5 72B Q4_K_M（高品質・RAM 42GB〜）",
    "Qwen2.5-72B-Instruct-Q3_K_M": "Qwen2.5 72B Q3_K_M（RAM 32GB〜）",
    # 32B — 32GB RAM向け
    "Qwen2.5-32B-Instruct-Q8_0":   "Qwen2.5 32B Q8_0  （ほぼ無劣化・RAM 34GB〜）",
    "Qwen2.5-32B-Instruct-Q6_K":   "Qwen2.5 32B Q6_K  （高品質・RAM 24GB〜）",
    "Qwen2.5-32B-Instruct-Q5_K_M": "Qwen2.5 32B Q5_K_M（推奨・RAM 21GB〜）",
    "Qwen2.5-32B-Instruct-Q4_K_M": "Qwen2.5 32B Q4_K_M（軽量・RAM 18GB〜）",
    "Qwen2.5-32B-Instruct-Q3_K_M": "Qwen2.5 32B Q3_K_M（最軽量・RAM 15GB〜）",
    # 14B — 16GB RAM向け
    "Qwen2.5-14B-Instruct-Q6_K":   "Qwen2.5 14B Q6_K  （16GB向け・高品質）",
    "Qwen2.5-14B-Instruct-Q5_K_M": "Qwen2.5 14B Q5_K_M（16GB向け・推奨）",
    "Qwen2.5-14B-Instruct-Q4_K_M": "Qwen2.5 14B Q4_K_M（16GB向け・軽量）",
    # 7B — 8GB RAM向け
    "Qwen2.5-7B-Instruct-Q6_K":    "Qwen2.5 7B  Q6_K  （8GB向け・高速）",
    "Qwen2.5-7B-Instruct-Q5_K_M":  "Qwen2.5 7B  Q5_K_M（8GB向け）",
}

_CTX_PRESETS = [
    (2048,  "2K  （省メモリ）"),
    (4096,  "4K  （標準）"),
    (8192,  "8K  （長い会話向け）"),
    (16384, "16K （大容量メモリ向け）"),
]


# ---------------------------------------------------------------------------
# EngineMenuBuilder — メニュー構築ヘルパー（QWidget ではない）
# ---------------------------------------------------------------------------

class EngineMenuBuilder(QObject):
    """翻訳エンジン / LLMモデル選択メニューを構築するヘルパー。

    QWidget ではなく QObject を継承。QMenuBar に対してメニュー項目を追加し、
    選択変更時にシグナルを発行する。
    """

    # --- 外部に通知するシグナル ---
    engine_changed = Signal(str)      # "llm" / "nllb" / "hybrid"
    model_changed = Signal(str)       # GGUF ファイルパス
    ctx_changed = Signal(int)         # コンテキスト長
    nllb_model_changed = Signal(str)  # NLLBモデルキー

    # --- 内部シグナル：ダウンロードスレッド → メインスレッド GUI 更新 ---
    # Qt の GUI 操作はメインスレッド限定。ワーカースレッドはこれらを
    # emit するだけにし、QueuedConnection 経由でメインスレッドのスロットが
    # QProgressDialog の更新・クローズとメニュー再構築を行う。
    _dl_progress = Signal(int)        # ダウンロード進捗（0-100 %）
    _dl_label = Signal(str)           # 進捗ダイアログのラベル文言
    _dl_finished = Signal(bool, str)  # (成功フラグ, メッセージ)

    def __init__(self, interpreter: Interpreter, parent: QObject | None = None):
        super().__init__(parent)
        self.interpreter = interpreter

        # 内部状態 — build 時に初期化
        self._model_menu: QMenu | None = None
        self._model_group: QActionGroup | None = None
        self._ctx_group: QActionGroup | None = None
        self._engine_group: QActionGroup | None = None
        self._engine_llm_action: QAction | None = None
        self._engine_nllb_action: QAction | None = None
        self._engine_hybrid_action: QAction | None = None
        self._nllb_menu: QMenu | None = None
        self._nllb_group: QActionGroup | None = None
        self._opus_menu: QMenu | None = None

        # ダウンロード中の進捗ダイアログと、完了時に再構築するメニュー種別
        # （メインスレッドからのみ読み書きする）
        self._dl_dialog: QProgressDialog | None = None
        self._dl_rebuild: str | None = None  # "nllb" / "opus"

        # ワーカースレッド発のシグナルをメインスレッドのスロットへ接続
        self._dl_progress.connect(
            self._on_dl_progress, Qt.ConnectionType.QueuedConnection)
        self._dl_label.connect(
            self._on_dl_label, Qt.ConnectionType.QueuedConnection)
        self._dl_finished.connect(
            self._on_dl_finished, Qt.ConnectionType.QueuedConnection)

    # =====================================================================
    #  Public API
    # =====================================================================

    def build_engine_menu(self, menubar: QMenuBar) -> QMenu:
        """「翻訳エンジン」サブメニューを *menubar* に追加して返す。"""
        menu = menubar.addMenu("🔧 翻訳エンジン")
        self._engine_group = QActionGroup(self)
        self._engine_group.setExclusive(True)

        from core.interpreter import EngineType
        current_engine = getattr(self.interpreter, '_engine_type', EngineType.MOCK)

        self._engine_llm_action = QAction("LLM (llama.cpp) — GPU加速", self, checkable=True)
        if current_engine in (EngineType.LLM, EngineType.MOCK):
            self._engine_llm_action.setChecked(True)
        self._engine_llm_action.triggered.connect(lambda: self._on_engine_select("llm"))
        self._engine_group.addAction(self._engine_llm_action)
        menu.addAction(self._engine_llm_action)

        self._engine_nllb_action = QAction("NLLB (軽量) — 8GB対応", self, checkable=True)
        if current_engine == EngineType.NLLB:
            self._engine_nllb_action.setChecked(True)
        self._engine_nllb_action.triggered.connect(lambda: self._on_engine_select("nllb"))
        self._engine_group.addAction(self._engine_nllb_action)
        menu.addAction(self._engine_nllb_action)

        self._engine_hybrid_action = QAction(
            "⚡ ハイブリッド (最高精度) — 32GB以上推奨", self, checkable=True)
        if current_engine == EngineType.HYBRID:
            self._engine_hybrid_action.setChecked(True)
        self._engine_hybrid_action.triggered.connect(lambda: self._on_engine_select("hybrid"))
        self._engine_group.addAction(self._engine_hybrid_action)
        menu.addAction(self._engine_hybrid_action)

        # NLLB モデルサブメニュー
        self._nllb_menu = menu.addMenu("🌐 NLLBモデル")
        self._nllb_group = QActionGroup(self)
        self._nllb_group.setExclusive(True)
        self._populate_nllb_models()

        # OPUS-MT ペアサブメニュー
        self._opus_menu = menu.addMenu("🔤 OPUS-MT言語ペア")
        self._populate_opus_models()

        return menu

    def build_model_menu(self, menubar: QMenuBar) -> QMenu:
        """「LLMモデル」「コンテキスト長」サブメニューを *menubar* に追加して返す。"""
        self._model_menu = menubar.addMenu("🤖 LLMモデル")
        self._model_group = QActionGroup(self)
        self._model_group.setExclusive(True)
        self._scan_and_populate_models()

        # コンテキスト長
        ctx_menu = menubar.addMenu("📏 コンテキスト長")
        self._ctx_group = QActionGroup(self)
        self._ctx_group.setExclusive(True)
        current_ctx = getattr(self.interpreter, '_n_ctx', 2048)
        for val, label in _CTX_PRESETS:
            act = QAction(label, self, checkable=True)
            if val == current_ctx:
                act.setChecked(True)
            act.triggered.connect(lambda checked, v=val: self._on_ctx_select(v))
            self._ctx_group.addAction(act)
            ctx_menu.addAction(act)

        return self._model_menu

    def update_engine_mode(self, is_nllb: bool = False, is_hybrid: bool = False):
        """NLLB/ハイブリッドモード時に呼ばれるUIヒント。

        AttorneyWindow 側で edit_btn 等の制御に使うため、
        ここでは何もしない（呼び出し元で直接ボタン制御する設計）。
        外部から呼ばれた場合に例外を出さないようスタブとして残す。
        """
        # 実際のボタン制御は AttorneyWindow._apply_engine_mode() に委譲
        pass

    # =====================================================================
    #  LLM モデル選択
    # =====================================================================

    def _scan_and_populate_models(self):
        """~/pli-models/ をスキャンしてモデルメニューを構築"""
        models_dir = os.path.expanduser("~/pli-models")
        gguf_files = sorted(glob.glob(os.path.join(models_dir, "*.gguf")))

        current = getattr(self.interpreter, '_model_path', '') or ''

        if not gguf_files:
            no_model = QAction("（モデルが見つかりません）", self)
            no_model.setEnabled(False)
            self._model_menu.addAction(no_model)
            return

        for path in gguf_files:
            stem = os.path.splitext(os.path.basename(path))[0]
            label = _MODEL_LABELS.get(stem, stem)
            act = QAction(label, self, checkable=True)
            if path == current or (
                current and os.path.basename(current) == os.path.basename(path)
            ):
                act.setChecked(True)
            act.triggered.connect(
                lambda checked, p=path, s=stem: self._on_model_select(p, s))
            self._model_group.addAction(act)
            self._model_menu.addAction(act)

        self._model_menu.addSeparator()
        rescan = QAction("🔄 モデルを再スキャン", self)
        rescan.triggered.connect(self._rescan_models)
        self._model_menu.addAction(rescan)

    def _on_model_select(self, path: str, stem: str):
        """モデル選択時"""
        parent_widget = self._find_parent_widget()
        reply = QMessageBox.question(
            parent_widget, "モデル切替",
            f"LLMモデルを切り替えます。\n\n"
            f"  {_MODEL_LABELS.get(stem, stem)}\n\n"
            f"アプリを再起動して反映します。よろしいですか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            self.model_changed.emit(path)
        else:
            self._rescan_models()

    def _rescan_models(self):
        """モデルメニューを再構築"""
        self._model_menu.clear()
        self._model_group = QActionGroup(self)
        self._model_group.setExclusive(True)
        self._scan_and_populate_models()

    # =====================================================================
    #  コンテキスト長
    # =====================================================================

    def _on_ctx_select(self, n_ctx: int):
        """コンテキスト長選択時"""
        parent_widget = self._find_parent_widget()
        reply = QMessageBox.question(
            parent_widget, "コンテキスト長変更",
            f"コンテキスト長を {n_ctx:,} トークンに変更します。\n"
            f"アプリを再起動して反映します。よろしいですか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            self.ctx_changed.emit(n_ctx)
        else:
            current_ctx = getattr(self.interpreter, '_n_ctx', 2048)
            for act in self._ctx_group.actions():
                for val, label in _CTX_PRESETS:
                    if label == act.text() and val == current_ctx:
                        act.setChecked(True)

    # =====================================================================
    #  翻訳エンジン選択
    # =====================================================================

    def _on_engine_select(self, engine_type: str):
        """翻訳エンジン選択時"""
        labels = {
            "llm": "LLM (llama.cpp)",
            "nllb": "NLLB (軽量)",
            "hybrid": "ハイブリッド (最高精度)",
        }
        label = labels.get(engine_type, engine_type)
        parent_widget = self._find_parent_widget()
        reply = QMessageBox.question(
            parent_widget, "翻訳エンジン変更",
            f"翻訳エンジンを {label} に変更します。\n"
            f"アプリを再起動して反映します。よろしいですか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            self.engine_changed.emit(engine_type)
        else:
            from core.interpreter import EngineType
            current = getattr(self.interpreter, '_engine_type', EngineType.MOCK)
            if current == EngineType.NLLB:
                self._engine_nllb_action.setChecked(True)
            elif current == EngineType.HYBRID:
                self._engine_hybrid_action.setChecked(True)
            else:
                self._engine_llm_action.setChecked(True)

    # =====================================================================
    #  NLLB モデル
    # =====================================================================

    def _populate_nllb_models(self):
        """NLLBモデルメニューを構築"""
        self._nllb_menu.clear()
        try:
            from core.nllb_downloader import NLLB_MODELS, is_downloaded, check_dependencies
            deps_ok, _ = check_dependencies()
        except ImportError:
            act = QAction("(nllb_downloader 読込エラー)", self)
            act.setEnabled(False)
            self._nllb_menu.addAction(act)
            return

        current_nllb = getattr(self.interpreter, '_nllb_model_dir', '')

        for key, info in NLLB_MODELS.items():
            downloaded = is_downloaded(key)
            label = info["label"]
            if downloaded:
                label = f"✅ {label}"
            else:
                label = f"⬇️ {label}  ({info['size_gb']:.1f}GB DL)"

            act = QAction(label, self, checkable=True)
            if downloaded and current_nllb and key in current_nllb:
                act.setChecked(True)
            if not deps_ok and not downloaded:
                act.setEnabled(False)
            act.triggered.connect(
                lambda checked, k=key, dl=downloaded: self._on_nllb_select(k, dl))
            self._nllb_group.addAction(act)
            self._nllb_menu.addAction(act)

        if not deps_ok:
            self._nllb_menu.addSeparator()
            dep_info = QAction(
                "⚠️ pip install ctranslate2 transformers sentencepiece", self)
            dep_info.setEnabled(False)
            self._nllb_menu.addAction(dep_info)

    def _on_nllb_select(self, model_key: str, already_downloaded: bool):
        """NLLBモデル選択時"""
        from core.nllb_downloader import NLLB_MODELS, is_downloaded, download_model

        parent_widget = self._find_parent_widget()

        if not already_downloaded:
            info = NLLB_MODELS[model_key]
            reply = QMessageBox.question(
                parent_widget, "NLLBモデルダウンロード",
                f"{info['label']}\n"
                f"サイズ: {info['size_gb']:.1f}GB\n"
                f"ダウンロードしますか？（時間がかかります）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                self._populate_nllb_models()
                return

            progress = QProgressDialog(
                "NLLBモデルをダウンロード中...", "キャンセル", 0, 100, parent_widget)
            progress.setWindowTitle("ダウンロード")
            # キャンセルボタンは snapshot_download を実際には中断できない
            # （飾りでユーザーを欺くだけ）ため表示しない
            progress.setCancelButton(None)
            progress.setMinimumDuration(0)
            progress.setValue(0)

            self._dl_dialog = progress
            self._dl_rebuild = "nllb"

            # ワーカースレッドからの GUI 直接操作は禁止。シグナル emit のみ。
            def _do_download():
                try:
                    def on_progress(ratio):
                        self._dl_progress.emit(int(ratio * 100))
                    download_model(model_key, on_progress=on_progress)
                    self._dl_progress.emit(100)
                    self._dl_finished.emit(True, "")
                except Exception as e:
                    self._dl_finished.emit(False, f"NLLBダウンロード失敗: {e}")

            threading.Thread(target=_do_download, daemon=True).start()
            progress.exec()

            if not is_downloaded(model_key):
                return

        self.nllb_model_changed.emit(model_key)

    # =====================================================================
    #  OPUS-MT
    # =====================================================================

    def _populate_opus_models(self):
        """OPUS-MT言語ペアメニューを構築"""
        self._opus_menu.clear()
        try:
            from core.opus_downloader import OPUS_MODELS, is_downloaded, check_dependencies
            deps_ok, _ = check_dependencies()
        except ImportError:
            act = QAction("(opus_downloader 読込エラー)", self)
            act.setEnabled(False)
            self._opus_menu.addAction(act)
            return

        sorted_keys = sorted(
            OPUS_MODELS.keys(),
            key=lambda k: (OPUS_MODELS[k].get("priority", 99), k))

        current_priority = None
        for key in sorted_keys:
            info = OPUS_MODELS[key]
            if current_priority is not None and info.get("priority", 99) != current_priority:
                self._opus_menu.addSeparator()
            current_priority = info.get("priority", 99)

            downloaded = is_downloaded(key)
            label = info["label"]
            if downloaded:
                label = f"✅ {label}"
            else:
                label = f"⬇️ {label}  (~{info['ram_gb']:.1f}GB)"

            act = QAction(label, self)
            if not downloaded and deps_ok:
                act.triggered.connect(
                    lambda checked, k=key: self._on_opus_download(k))
            elif not deps_ok:
                act.setEnabled(False)
            else:
                act.setEnabled(True)
                act.setCheckable(True)
                act.setChecked(True)
            self._opus_menu.addAction(act)

        # マルチリンガルモデル
        self._opus_menu.addSeparator()
        mul_header = QAction("🌍 マルチリンガル（少数言語対応）", self)
        mul_header.setEnabled(False)
        self._opus_menu.addAction(mul_header)

        try:
            from core.opus_downloader import OPUS_MULTILINGUAL
            for mkey, minfo in OPUS_MULTILINGUAL.items():
                m_downloaded = is_downloaded(mkey)
                m_label = minfo["label"]
                if m_downloaded:
                    m_label = f"✅ {m_label}"
                else:
                    m_label = f"⬇️ {m_label}  (~{minfo['ram_gb']:.1f}GB)"
                m_act = QAction(m_label, self)
                if not m_downloaded and deps_ok:
                    m_act.triggered.connect(
                        lambda checked, k=mkey: self._on_opus_download(k))
                elif not deps_ok:
                    m_act.setEnabled(False)
                else:
                    m_act.setEnabled(True)
                    m_act.setCheckable(True)
                    m_act.setChecked(True)
                self._opus_menu.addAction(m_act)
        except ImportError:
            pass

        # 一括ダウンロード
        self._opus_menu.addSeparator()
        dl_all = QAction("📥 対象言語の全ペアをDL...", self)
        dl_all.triggered.connect(self._on_opus_download_all)
        if not deps_ok:
            dl_all.setEnabled(False)
        self._opus_menu.addAction(dl_all)

        # 統計情報
        downloaded_count = sum(1 for k in OPUS_MODELS if is_downloaded(k))
        try:
            from core.opus_downloader import OPUS_MULTILINGUAL as _MUL
            mul_count = sum(1 for k in _MUL if is_downloaded(k))
            stat_text = (
                f"({downloaded_count}/{len(OPUS_MODELS)} ペア"
                f" + {mul_count}/{len(_MUL)} マルチリンガル DL済み)")
        except ImportError:
            stat_text = f"({downloaded_count}/{len(OPUS_MODELS)} ペアDL済み)"
        stat = QAction(stat_text, self)
        stat.setEnabled(False)
        self._opus_menu.addAction(stat)

        if not deps_ok:
            self._opus_menu.addSeparator()
            dep_info = QAction(
                "⚠️ pip install ctranslate2 transformers sentencepiece huggingface_hub",
                self)
            dep_info.setEnabled(False)
            self._opus_menu.addAction(dep_info)

    def _on_opus_download(self, pair_key: str):
        """個別OPUS-MTペア or マルチリンガルモデルのダウンロード"""
        from core.opus_downloader import OPUS_MODELS, OPUS_MULTILINGUAL, download_model, is_downloaded

        if pair_key in OPUS_MODELS:
            info = OPUS_MODELS[pair_key]
        elif pair_key in OPUS_MULTILINGUAL:
            info = OPUS_MULTILINGUAL[pair_key]
        else:
            return

        parent_widget = self._find_parent_widget()
        reply = QMessageBox.question(
            parent_widget, "OPUS-MTモデルダウンロード",
            f"{info['label']}\n"
            f"RAM: ~{info['ram_gb']:.1f}GB\n"
            f"ダウンロード＆変換しますか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        progress = QProgressDialog(
            f"OPUS-MT [{pair_key}] ダウンロード中...", "キャンセル",
            0, 100, parent_widget)
        progress.setWindowTitle("ダウンロード")
        # キャンセルボタンは実際にはダウンロードを中断できないため表示しない
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        self._dl_dialog = progress
        self._dl_rebuild = "opus"

        # ワーカースレッドからの GUI 直接操作は禁止。シグナル emit のみ。
        def _do_download():
            try:
                def on_progress(ratio):
                    self._dl_progress.emit(int(ratio * 100))
                download_model(pair_key, on_progress=on_progress)
                self._dl_progress.emit(100)
                self._dl_finished.emit(True, "")
            except Exception as e:
                self._dl_finished.emit(False, f"OPUS-MT ダウンロード失敗: {e}")

        threading.Thread(target=_do_download, daemon=True).start()
        progress.exec()

    def _on_opus_download_all(self):
        """対象言語の関連ペアを一括ダウンロード"""
        from core.opus_downloader import (
            list_available_for_lang, OPUS_MODELS, is_downloaded,
            download_pairs_for_lang, estimate_ram_for_lang,
        )

        tgt = getattr(self.interpreter, 'target_lang', 'en')
        pairs = list_available_for_lang(tgt)
        not_downloaded = [p for p in pairs if not is_downloaded(p)]

        parent_widget = self._find_parent_widget()

        if not not_downloaded:
            QMessageBox.information(
                parent_widget, "OPUS-MT",
                f"言語 [{tgt}] の全ペアはダウンロード済みです。")
            return

        ram_est = estimate_ram_for_lang(tgt)
        reply = QMessageBox.question(
            parent_widget, "OPUS-MT 一括ダウンロード",
            f"言語 [{tgt}] の関連ペア {len(not_downloaded)}個をダウンロードします。\n"
            f"（全ペアロード時 RAM ~{ram_est:.1f}GB）\n\n続行しますか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        progress = QProgressDialog(
            f"OPUS-MT [{tgt}] 一括ダウンロード中...", "キャンセル",
            0, 100, parent_widget)
        progress.setWindowTitle("一括ダウンロード")
        # キャンセルボタンは実際にはダウンロードを中断できないため表示しない
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        self._dl_dialog = progress
        self._dl_rebuild = "opus"

        # ワーカースレッドからの GUI 直接操作は禁止。シグナル emit のみ。
        def _do_download():
            try:
                def on_progress(pair_key, ratio):
                    self._dl_label.emit(f"OPUS-MT [{pair_key}] ダウンロード中...")
                    self._dl_progress.emit(int(ratio * 100))
                download_pairs_for_lang(tgt, on_progress=on_progress)
                self._dl_progress.emit(100)
                self._dl_finished.emit(True, "")
            except Exception as e:
                self._dl_finished.emit(False, f"OPUS-MT一括ダウンロード失敗: {e}")

        threading.Thread(target=_do_download, daemon=True).start()
        progress.exec()

    # =====================================================================
    #  ダウンロード進捗 — メインスレッドスロット（QueuedConnection 経由）
    # =====================================================================

    def _on_dl_progress(self, percent: int):
        """進捗更新スロット。メインスレッドで実行される。"""
        if self._dl_dialog is not None:
            self._dl_dialog.setValue(percent)

    def _on_dl_label(self, text: str):
        """進捗ダイアログのラベル更新スロット。メインスレッドで実行される。"""
        if self._dl_dialog is not None:
            self._dl_dialog.setLabelText(text)

    def _on_dl_finished(self, success: bool, message: str):
        """ダウンロード完了スロット。メインスレッドで実行される。

        ダイアログを確実に閉じ（キャンセルボタン非表示のため、失敗時に
        ここで閉じないとモーダルが残り続ける）、対応するメニューを再構築する。
        """
        if not success and message:
            print(f"[error] {message}")

        dlg = self._dl_dialog
        self._dl_dialog = None
        if dlg is not None:
            dlg.close()

        rebuild = self._dl_rebuild
        self._dl_rebuild = None
        if rebuild == "nllb":
            self._populate_nllb_models()
        elif rebuild == "opus":
            self._populate_opus_models()

    # =====================================================================
    #  ユーティリティ
    # =====================================================================

    def _find_parent_widget(self):
        """QMessageBox / QProgressDialog に渡す親ウィジェットを探す。"""
        from PySide6.QtWidgets import QWidget
        obj = self.parent()
        while obj is not None:
            if isinstance(obj, QWidget):
                return obj
            obj = obj.parent()
        return None
