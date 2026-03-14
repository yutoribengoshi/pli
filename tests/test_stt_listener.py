import os
import tempfile
import unittest

from core.stt_listener import STTListener


class _DummySTT:
    def __init__(self):
        self.paths = []

    def transcribe(self, path):
        self.paths.append(path)
        return "hello", "en"


class STTListenerTests(unittest.TestCase):
    def test_process_speech_removes_temp_wav(self):
        engine = _DummySTT()
        listener = STTListener(stt_engine=engine)

        with tempfile.TemporaryDirectory() as tmpdir:
            listener._temp_dir = tmpdir
            listener._process_speech([b"\x00\x00" * 1600])

            self.assertEqual(len(engine.paths), 1)
            self.assertFalse(os.path.exists(engine.paths[0]))
            self.assertEqual(os.listdir(tmpdir), [])


if __name__ == "__main__":
    unittest.main()
