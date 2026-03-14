import os
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.interpreter import EngineType, Interpreter, Speaker, Utterance
from core.recorder import Recorder
from ui.attorney_window import AttorneyWindow


class AttorneyWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _drain_events(self, cycles: int = 5):
        for _ in range(cycles):
            self._app.processEvents()

    def test_send_is_blocked_when_translation_not_ready(self):
        interpreter = Interpreter(mock=False, engine_type=EngineType.LLM, model_path="/tmp/missing.gguf")
        interpreter._translation_ready = False
        interpreter._model_load_state = "error"
        interpreter._model_load_error = "翻訳エンジンのロード失敗: missing"

        window = AttorneyWindow(interpreter, Recorder())
        window.input_field.setText("テスト")

        window._on_send_attorney()

        self.assertEqual(window.log_layout.count(), 0)

    def test_manual_translations_are_processed_serially(self):
        interpreter = Interpreter(mock=True)
        window = AttorneyWindow(interpreter, Recorder())
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()

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

        with mock.patch.object(window, "_translate_attorney_text", side_effect=fake_translate):
            window.input_field.setText("first")
            window._on_send_attorney()
            self.assertTrue(first_started.wait(1.0))

            window.input_field.setText("second")
            window._on_send_attorney()
            self.assertFalse(second_started.wait(0.1))

            release_first.set()
            window._translation_queue.join()
            self._drain_events()

        self.assertEqual(
            [utt.original for utt in interpreter.conversation[-2:]],
            ["first", "second"],
        )
        self.assertEqual(window.log_layout.count(), 2)

    def test_clear_logs_invalidates_inflight_translation_results(self):
        interpreter = Interpreter(mock=True)
        window = AttorneyWindow(interpreter, Recorder())
        started = threading.Event()
        release = threading.Event()

        def fake_translate(text: str) -> Utterance:
            started.set()
            release.wait(1.0)
            return Utterance(
                speaker=Speaker.ATTORNEY,
                original=text,
                translated="translated",
                timestamp="12:34",
            )

        with mock.patch.object(window, "_translate_attorney_text", side_effect=fake_translate):
            window.input_field.setText("stale")
            window._on_send_attorney()
            self.assertTrue(started.wait(1.0))

            window.clear_logs()
            release.set()
            window._translation_queue.join()
            self._drain_events()

        self.assertEqual(interpreter.conversation, [])
        self.assertEqual(window.log_layout.count(), 0)
        self.assertEqual(window._pending_attorney_bubbles, {})

    def test_clear_logs_drops_inflight_translation_errors(self):
        interpreter = Interpreter(mock=True)
        window = AttorneyWindow(interpreter, Recorder())
        started = threading.Event()
        release = threading.Event()

        def fake_translate(_: str) -> Utterance:
            started.set()
            release.wait(1.0)
            raise RuntimeError("boom")

        with mock.patch.object(window, "_translate_attorney_text", side_effect=fake_translate):
            window.input_field.setText("stale-error")
            window._on_send_attorney()
            self.assertTrue(started.wait(1.0))

            window.clear_logs()
            release.set()
            window._translation_queue.join()
            self._drain_events()

        self.assertEqual(window.log_layout.count(), 0)
        self.assertEqual(window._pending_attorney_bubbles, {})


if __name__ == "__main__":
    unittest.main()
