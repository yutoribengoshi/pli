"""話者判定 decide_is_attorney のテスト。

テストケースは2026-07-06の実接見ログ（386発話）で実際に誤判定された
パターンから採取。Whisper langの誤爆（約10%）に対し文字種判定が
正しく話者を決定することを検証する。
"""
import unittest

from core.session_controller import decide_is_attorney


class ScriptBasedDecisionTests(unittest.TestCase):
    """文字種主導の判定 — Whisper langが誤っていても正しく判定できること"""

    def test_japanese_misdetected_as_english(self):
        # 実接見で最多の事故: 先生の日本語がlang=enと誤検出→相手扱い→逆翻訳
        self.assertTrue(decide_is_attorney(
            "長い間接見に来れなくてごめんなさい", "en", "en"))

    def test_japanese_misdetected_as_korean(self):
        self.assertTrue(decide_is_attorney("黙秘権があります", "ko", "en"))

    def test_japanese_misdetected_as_spanish(self):
        self.assertTrue(decide_is_attorney(
            "保釈請求の準備をしています", "es", "en"))

    def test_english_correctly_defendant(self):
        self.assertFalse(decide_is_attorney(
            "I want to see my family", "en", "en"))

    def test_english_misdetected_as_portuguese(self):
        # 相手の英語がlang=ptと誤検出されても文字種で相手と判定
        self.assertFalse(decide_is_attorney(
            "He stood up in an agitated manner", "pt", "en"))

    def test_short_japanese(self):
        self.assertTrue(decide_is_attorney("はい", "en", "en"))

    def test_short_english(self):
        self.assertFalse(decide_is_attorney("Yes", "ja", "en"))

    def test_empty_falls_back_to_lang(self):
        self.assertTrue(decide_is_attorney("", "ja", "en"))
        self.assertFalse(decide_is_attorney("", "en", "en"))

    def test_mixed_ja_dominant(self):
        # 日本語文中の英単語（法律用語の引用等）
        self.assertTrue(decide_is_attorney(
            "これはrobberyではなくtheftです", "en", "en"))


class ChineseTargetTests(unittest.TestCase):
    """相手言語=中国語: 漢字共有のためかな有無で判定"""

    def test_japanese_with_kana(self):
        self.assertTrue(decide_is_attorney("勾留されています", "zh", "zh"))

    def test_chinese_no_kana(self):
        self.assertFalse(decide_is_attorney("我想见家人", "zh", "zh"))

    def test_pure_kanji_defers_to_whisper(self):
        # かなゼロの純漢字はWhisper langに委ねる（稀ケース）
        self.assertTrue(decide_is_attorney("勾留延長", "ja", "zh"))
        self.assertFalse(decide_is_attorney("保释申请", "zh", "zh"))


class NonLatinTargetTests(unittest.TestCase):
    """相手言語が非ラテン文字（ウルドゥー語等）でも動くこと"""

    def test_urdu_defendant(self):
        self.assertFalse(decide_is_attorney(
            "میں اپنے خاندان سے ملنا چاہتا ہوں", "ur", "ur"))

    def test_japanese_attorney_with_urdu_target(self):
        self.assertTrue(decide_is_attorney("ご家族に伝えます", "ur", "ur"))


if __name__ == "__main__":
    unittest.main()
