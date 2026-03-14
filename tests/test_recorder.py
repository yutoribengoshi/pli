import os
import tempfile
import unittest

from core.recorder import Recorder


class RecorderTests(unittest.TestCase):
    def test_wipe_can_delete_saved_files_from_current_session(self):
        recorder = Recorder()
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder.set_save_dir(tmpdir)
            recorder._buffer.write(b"\x00\x00" * 1600)

            wav_path = recorder._save_to_file()

            self.assertTrue(wav_path)
            self.assertTrue(os.path.exists(wav_path))

            recorder.wipe(delete_saved_files=True)

            self.assertFalse(os.path.exists(wav_path))


if __name__ == "__main__":
    unittest.main()
