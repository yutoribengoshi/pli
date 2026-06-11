import os
import tempfile
import unittest

from core.stt_listener import STTListener, classify_mic_error


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


class ClassifyMicErrorTests(unittest.TestCase):
    def test_macos_permission_denied(self):
        # macOSのTCC権限拒否で典型的なPortAudioエラー
        exc = Exception("Error opening RawInputStream: Internal PortAudio error [PaErrorCode -9986]")
        self.assertEqual(classify_mic_error(exc), "mic_denied")

    def test_permission_keyword(self):
        self.assertEqual(classify_mic_error(Exception("Operation not permitted")), "mic_denied")

    def test_no_input_device(self):
        exc = Exception("Error querying device -1")
        self.assertEqual(classify_mic_error(exc), "mic_missing")
        self.assertEqual(classify_mic_error(Exception("No Default Input Device Available")), "mic_missing")

    def test_unknown_error(self):
        self.assertEqual(classify_mic_error(Exception("something exploded")), "")


if __name__ == "__main__":
    unittest.main()
