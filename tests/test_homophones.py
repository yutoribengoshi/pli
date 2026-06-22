import unittest

from core.homophones import find_homophone_candidates, HOMOPHONE_GROUPS


class FindHomophoneTests(unittest.TestCase):
    def test_sekken_to_soap(self):
        # 接見 → 石鹸 を候補提示（バイアス過剰方向）
        r = dict(find_homophone_candidates("接見の予定です"))
        self.assertIn("接見", r)
        self.assertIn("石鹸", r["接見"])

    def test_koryu_bias_failure(self):
        # 交流 → 勾留・拘留 を候補提示（バイアス失敗方向）
        r = dict(find_homophone_candidates("交流期間は十日間です"))
        self.assertIn("交流", r)
        self.assertIn("勾留", r["交流"])
        self.assertIn("拘留", r["交流"])

    def test_no_candidate(self):
        self.assertEqual(find_homophone_candidates("こんにちは"), [])

    def test_empty(self):
        self.assertEqual(find_homophone_candidates(""), [])

    def test_multiple_in_sentence(self):
        r = dict(find_homophone_candidates("起訴された後に保釈を請求"))
        self.assertIn("起訴", r)
        self.assertIn("保釈", r)

    def test_surface_excluded_from_alternatives(self):
        # 出現表記は alternatives に含まれない
        for surface, alts in find_homophone_candidates("正当防衛が成立"):
            self.assertNotIn(surface, alts)

    def test_groups_wellformed(self):
        # 各グループは読み + 2語以上
        for yomi, surfaces in HOMOPHONE_GROUPS:
            self.assertTrue(yomi)
            self.assertGreaterEqual(len(surfaces), 2)


if __name__ == "__main__":
    unittest.main()
