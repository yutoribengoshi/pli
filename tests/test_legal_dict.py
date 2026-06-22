import unittest

from core.legal_dict import (
    retrieve_terms,
    format_glossary_for_prompt,
    load_legal_dict,
)
from core.engines.llm import LLMEngine


class RetrieveTermsTests(unittest.TestCase):
    def test_longest_match_wins(self):
        # 覚醒剤取締法 が 覚醒剤 より優先され、同一スパンで覚醒剤は拾わない
        jas = [t[0] for t in retrieve_terms("覚醒剤取締法違反で逮捕された")]
        self.assertIn("覚醒剤取締法", jas)
        self.assertNotIn("覚醒剤", jas)
        self.assertIn("逮捕", jas)  # 重要カテゴリの2文字は拾う

    def test_authoritative_translation(self):
        terms = dict((t[0], t[1]) for t in retrieve_terms("覚醒剤取締法"))
        self.assertEqual(terms["覚醒剤取締法"], "Stimulant Drugs Control Act")

    def test_generic_short_word_suppressed(self):
        # 非重要カテゴリの2文字汎用語（意思・氏）は拾わない
        jas = [t[0] for t in retrieve_terms("私の意思で氏を変えた")]
        self.assertNotIn("意思", jas)
        self.assertNotIn("氏", jas)

    def test_no_match_returns_empty(self):
        self.assertEqual(retrieve_terms("こんにちは元気ですか"), [])

    def test_max_terms_cap(self):
        text = "勾留 起訴 公判 保釈 接見 黙秘 自白 弁護人 判決 量刑 執行猶予"
        self.assertLessEqual(len(retrieve_terms(text, max_terms=8)), 8)

    def test_empty_text(self):
        self.assertEqual(retrieve_terms(""), [])

    def test_dict_loaded(self):
        self.assertGreater(len(load_legal_dict()), 1000)


class FormatGlossaryTests(unittest.TestCase):
    def test_format_empty(self):
        self.assertEqual(format_glossary_for_prompt([]), "")

    def test_format_contains_arrow(self):
        block = format_glossary_for_prompt([("起訴", "indictment", "手続")])
        self.assertIn("起訴", block)
        self.assertIn("indictment", block)
        self.assertIn("→", block)


class InjectGlossaryTests(unittest.TestCase):
    def setUp(self):
        # __init__ を回避してメソッドだけ検証
        self.eng = LLMEngine.__new__(LLMEngine)

    def test_glossary_prepended_for_ja(self):
        base = "日本語を英語に翻訳:\n覚醒剤取締法"
        out = self.eng._inject_glossary("覚醒剤取締法", "ja", base)
        self.assertIn("Stimulant Drugs Control Act", out)
        self.assertTrue(out.endswith(base))  # 本文は末尾に保持

    def test_passthrough_non_ja(self):
        base = "Translate to Japanese:\nhello"
        self.assertEqual(self.eng._inject_glossary("hello", "en", base), base)

    def test_passthrough_no_match(self):
        base = "日本語を英語に翻訳:\nこんにちは"
        self.assertEqual(self.eng._inject_glossary("こんにちは", "ja", base), base)


if __name__ == "__main__":
    unittest.main()
