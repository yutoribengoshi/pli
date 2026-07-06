"""Whisper幻覚フィルタのテスト。

ケースは2026-07-06の実接見ログですり抜けを確認した実例から採取。
"""
import unittest

from core.stt_listener import is_hallucination_text, STTListener


class HallucinationTextTests(unittest.TestCase):
    def test_fullwidth_period_variant(self):
        # 旧実装のバグ: ASCII "." しか剥がさず全角句点付きがすり抜けた
        self.assertTrue(is_hallucination_text("ご視聴ありがとうございました。"))

    def test_arigatou_silence_hallucination(self):
        # 無音時の定番幻覚（実接見で29件混入）
        self.assertTrue(is_hallucination_text("ありがとうございました。"))
        self.assertTrue(is_hallucination_text("ありがとうございます"))

    def test_single_char_repetition(self):
        # 「場場場場…」型
        self.assertTrue(is_hallucination_text("場" * 40))

    def test_word_repetition_slide(self):
        # 「スライドスライド…」型（周期4文字×3回以上。実接見で発生）
        self.assertTrue(is_hallucination_text("スライド" * 3))
        self.assertTrue(is_hallucination_text("スライド" * 10))

    def test_word_repetition_english(self):
        self.assertTrue(is_hallucination_text("slide slide slide slide"))

    def test_real_speech_not_filtered(self):
        # 実発話は除外しない
        self.assertFalse(is_hallucination_text("黙秘権を行使します"))
        self.assertFalse(is_hallucination_text("I want to see my family"))
        self.assertFalse(is_hallucination_text("ありがとうございました、助かりました"))

    def test_two_repeats_not_filtered(self):
        # 2回繰り返しは実発話であり得る（「わかりましたわかりました」）
        self.assertFalse(is_hallucination_text("わかりましたわかりました"))

    def test_short_text_filtered(self):
        self.assertTrue(is_hallucination_text("あ"))
        self.assertTrue(is_hallucination_text(""))


class SensitivityPresetTests(unittest.TestCase):
    def test_ultra_preset_lowers_floor(self):
        lis = STTListener()
        lis._ambient_energy = 50  # 静かな接見室
        lis.set_sensitivity("ultra")
        # 床80 > 50×1.1=55 → 閾値80（旧実装は床200で小声を弾いていた）
        self.assertEqual(lis._energy_threshold, 80)
        self.assertEqual(lis._sensitivity_preset, "ultra")

    def test_normal_preset_floor(self):
        lis = STTListener()
        lis._ambient_energy = 50
        lis.set_sensitivity("normal")
        self.assertEqual(lis._energy_threshold, 200)

    def test_invalid_preset_ignored(self):
        lis = STTListener()
        lis.set_sensitivity("bogus")
        self.assertEqual(lis._sensitivity_preset, "normal")


if __name__ == "__main__":
    unittest.main()
