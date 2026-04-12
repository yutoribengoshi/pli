"""
PLI テスト — SessionController + AttorneyWindow

SessionController のロジックテスト（翻訳キュー、シリアル実行、セッション無効化）と
AttorneyWindow の UI テスト（送信ブロック、clear_logs）を分離。
"""

import os
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.interpreter import EngineType, Interpreter, Speaker, Utterance
from core.recorder import Recorder
from core.session_controller import SessionController


# ===================================================================
#  SessionController ロジックテスト（UI 非依存）
# ===================================================================


class SessionControllerTests(unittest.TestCase):
    """SessionController の翻訳パイプラインロジックをテスト"""

    def test_translations_are_processed_serially(self):
        """翻訳ジョブが直列に処理されることを確認"""
        interpreter = Interpreter(mock=True)
        ctrl = SessionController(interpreter, Recorder())

        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()
        results = []

        def fake_translate(text: str) -> Utterance:
            if text == "first":
                first_started.set()
                release_first.wait(1.0)
            elif text == "second":
                second_started.set()
            return Utterance(
                speaker=Speaker.ATTORNEY,
                original=text,
                translated=f"{text}-translated",
                timestamp="12:34",
            )

        def on_translated(request_id: int, utt: Utterance):
            results.append(utt)
            interpreter.conversation.append(utt)

        ctrl.set_callbacks(on_manual_attorney_translated=on_translated)

        with mock.patch.object(ctrl, "translate_attorney_text", side_effect=fake_translate):
            ctrl.start_translation_worker()

            ctrl.enqueue_translation_job("manual_attorney", "first")
            self.assertTrue(first_started.wait(1.0))

            ctrl.enqueue_translation_job("manual_attorney", "second")
            self.assertFalse(second_started.wait(0.1))

            release_first.set()
            ctrl._translation_queue.join()

        self.assertEqual(
            [utt.original for utt in interpreter.conversation[-2:]],
            ["first", "second"],
        )
        ctrl.stop_translation_worker()

    def test_invalidate_drops_inflight_results(self):
        """セッション無効化により進行中の翻訳結果が破棄されることを確認"""
        interpreter = Interpreter(mock=True)
        ctrl = SessionController(interpreter, Recorder())
        started = threading.Event()
        release = threading.Event()
        results = []

        def fake_translate(text: str) -> Utterance:
            started.set()
            release.wait(1.0)
            return Utterance(
                speaker=Speaker.ATTORNEY,
                original=text,
                translated="translated",
                timestamp="12:34",
            )

        def on_translated(request_id: int, utt: Utterance):
            results.append(utt)

        ctrl.set_callbacks(on_manual_attorney_translated=on_translated)

        with mock.patch.object(ctrl, "translate_attorney_text", side_effect=fake_translate):
            ctrl.start_translation_worker()

            ctrl.enqueue_translation_job("manual_attorney", "stale")
            self.assertTrue(started.wait(1.0))

            ctrl.invalidate_translation_jobs()
            release.set()
            ctrl._translation_queue.join()

        self.assertEqual(results, [])
        self.assertEqual(interpreter.conversation, [])
        ctrl.stop_translation_worker()

    def test_invalidate_drops_inflight_errors(self):
        """セッション無効化により進行中のエラーも破棄されることを確認"""
        interpreter = Interpreter(mock=True)
        ctrl = SessionController(interpreter, Recorder())
        started = threading.Event()
        release = threading.Event()
        errors = []

        def fake_translate(_: str) -> Utterance:
            started.set()
            release.wait(1.0)
            raise RuntimeError("boom")

        def on_failed(request_id: int, error: str):
            errors.append(error)

        ctrl.set_callbacks(on_manual_attorney_failed=on_failed)

        with mock.patch.object(ctrl, "translate_attorney_text", side_effect=fake_translate):
            ctrl.start_translation_worker()

            ctrl.enqueue_translation_job("manual_attorney", "stale-error")
            self.assertTrue(started.wait(1.0))

            ctrl.invalidate_translation_jobs()
            release.set()
            ctrl._translation_queue.join()

        self.assertEqual(errors, [])
        ctrl.stop_translation_worker()

    def test_ensure_translation_available_blocks_when_not_ready(self):
        """翻訳エンジン未準備時に ensure_translation_available が False を返すことを確認"""
        interpreter = Interpreter(mock=False, engine_type=EngineType.LLM, model_path="/tmp/missing.gguf")
        interpreter._translation_ready = False
        interpreter._model_load_state = "error"
        interpreter._model_load_error = "翻訳エンジンのロード失敗: missing"

        ctrl = SessionController(interpreter, Recorder())
        messages = []
        ctrl.set_callbacks(on_translation_not_available=lambda msg: messages.append(msg))

        result = ctrl.ensure_translation_available()
        self.assertFalse(result)
        self.assertEqual(len(messages), 1)


# ===================================================================
#  AttorneyWindow UI テスト（公開 API 経由）
# ===================================================================


class AttorneyWindowUITests(unittest.TestCase):
    """AttorneyWindow の UI 動作を公開 API 経由でテスト"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _drain_events(self, cycles: int = 5):
        for _ in range(cycles):
            self._app.processEvents()

    def test_send_is_blocked_when_translation_not_ready(self):
        """翻訳エンジン未準備時に送信がブロックされることを確認（UI観点）"""
        from ui.attorney_window import AttorneyWindow

        interpreter = Interpreter(mock=False, engine_type=EngineType.LLM, model_path="/tmp/missing.gguf")
        interpreter._translation_ready = False
        interpreter._model_load_state = "error"
        interpreter._model_load_error = "翻訳エンジンのロード失敗: missing"

        window = AttorneyWindow(interpreter, Recorder())
        window.input_field.setText("テスト")

        window._on_send_attorney()

        self.assertEqual(len(interpreter.conversation), 0)

    def test_clear_logs_resets_ui_state(self):
        """clear_logs が UI 状態をリセットすることを確認"""
        from ui.attorney_window import AttorneyWindow

        interpreter = Interpreter(mock=True)
        window = AttorneyWindow(interpreter, Recorder())

        window.clear_logs()
        self._drain_events()

        self.assertEqual(window.log_layout.count(), 0)


if __name__ == "__main__":
    unittest.main()
