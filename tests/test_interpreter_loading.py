import threading
import unittest
from unittest import mock

from core.interpreter import EngineType, Interpreter


class InterpreterLoadingTests(unittest.TestCase):
    def test_real_mode_translation_failure_sets_degraded_state(self):
        interpreter = Interpreter(mock=False, engine_type=EngineType.LLM, model_path="/tmp/missing.gguf")
        done = threading.Event()
        result = {}

        with mock.patch.object(interpreter, "_load_llm", side_effect=RuntimeError("llm failed")), \
                mock.patch("core.interpreter.WhisperSTT", return_value=object()):
            interpreter.load_models_async(
                on_ready=lambda ready, message: (
                    result.update({"ready": ready, "message": message}),
                    done.set(),
                )
            )
            self.assertTrue(done.wait(1.0))

        self.assertFalse(result["ready"])
        self.assertIn("翻訳エンジンのロード失敗", result["message"])
        self.assertFalse(interpreter.translation_ready)
        self.assertTrue(interpreter.stt_ready)
        self.assertEqual(interpreter.model_load_state, "degraded")
        self.assertFalse(interpreter._models_ready)

    def test_mock_mode_stt_failure_keeps_translation_available(self):
        interpreter = Interpreter(mock=True)
        done = threading.Event()
        result = {}

        with mock.patch("core.interpreter.WhisperSTT", side_effect=RuntimeError("stt failed")):
            interpreter.load_models_async(
                on_ready=lambda ready, message: (
                    result.update({"ready": ready, "message": message}),
                    done.set(),
                )
            )
            self.assertTrue(done.wait(1.0))

        self.assertFalse(result["ready"])
        self.assertIn("音声認識は使えません", result["message"])
        self.assertTrue(interpreter.translation_ready)
        self.assertFalse(interpreter.stt_ready)
        self.assertEqual(interpreter.model_load_state, "degraded")

    def test_hybrid_with_zero_models_sets_translation_not_ready(self):
        """P0-4回帰: HybridEngineが1モデルも積めなかったら翻訳未準備として扱う"""
        interpreter = Interpreter(mock=False, engine_type=EngineType.HYBRID)
        done = threading.Event()
        result = {}

        class _EmptyHybrid:
            is_ready = False  # NLLBなし・OPUSペアなしの状態を模擬

        def _fake_load_hybrid(on_progress):
            interpreter.engine = _EmptyHybrid()

        with mock.patch.object(interpreter, "_load_hybrid", side_effect=_fake_load_hybrid), \
                mock.patch("core.interpreter.WhisperSTT", return_value=object()):
            interpreter.load_models_async(
                on_ready=lambda ready, message: (
                    result.update({"ready": ready, "message": message}),
                    done.set(),
                )
            )
            self.assertTrue(done.wait(1.0))

        self.assertFalse(result["ready"])
        self.assertIn("翻訳モデルが未ダウンロード", result["message"])
        self.assertFalse(interpreter.translation_ready)
        self.assertTrue(interpreter.stt_ready)
        self.assertEqual(interpreter.model_load_state, "degraded")
        self.assertFalse(interpreter._models_ready)


if __name__ == "__main__":
    unittest.main()
