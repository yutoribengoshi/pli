"""
回帰テスト: core/interpreter.py のモジュールレベル import time 欠落 (P0-1)

translate_defendant() と save_conversation() は time.strftime を使うため、
モジュールに import time が無いと実行時 NameError で即死する。
モックモードで両メソッドを実際に呼び、回帰を検知する。
"""

import json
import unittest

from core.interpreter import Interpreter, Speaker, Utterance


class InterpreterTimeImportTests(unittest.TestCase):
    def test_translate_defendant_mock_returns_utterance(self):
        """translate_defendant が NameError を出さず Utterance を返す"""
        interp = Interpreter(mock=True)
        interp.set_target_language("en")
        utt = interp.translate_defendant("hello")
        self.assertIsInstance(utt, Utterance)
        self.assertEqual(utt.speaker, Speaker.DEFENDANT)
        self.assertEqual(utt.original, "hello")
        self.assertTrue(utt.translated)
        # timestamp は time.strftime("%H:%M") の結果（import time 回帰の核心）
        self.assertIn(":", utt.timestamp)

    def test_save_conversation_with_one_utterance(self):
        """save_conversation が time.strftime で落ちず JSON 保存できる"""
        import tempfile
        import os

        interp = Interpreter(mock=True)
        interp.set_target_language("en")
        utt = interp.translate_defendant("I want a lawyer")
        interp.confirm_utterance(utt)
        self.assertEqual(len(interp.conversation), 1)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "conversation.json")
            interp.save_conversation(path)

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

        self.assertTrue(data["saved_at"])  # time.strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(data["target_lang"], "en")
        self.assertEqual(len(data["utterances"]), 1)
        self.assertEqual(data["utterances"][0]["original"], "I want a lawyer")


if __name__ == "__main__":
    unittest.main()
