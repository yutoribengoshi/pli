"""
hybrid エンジンのブラックリストペア（en-ja）の経路テスト
Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）(Tomoyuki Seki)
All rights reserved.
"""
import unittest

from core.engines.hybrid import HybridEngine


class _FakeNLLB:
    """CTranslate2 版 NLLBEngine の代役（モデルを読まない）"""

    def __init__(self, ready=True, fail=False):
        self.is_ready = ready
        self.fail = fail
        self.calls = []

    def translate(self, text, src_lang, tgt_lang):
        self.calls.append((text, src_lang, tgt_lang))
        if self.fail:
            raise RuntimeError("ct2 failure")
        return "CT2訳"


def _engine(nllb):
    eng = HybridEngine(nllb_model_dir="")
    eng._nllb_engine = nllb  # _ensure_nllb_loaded はこれを保持したまま返る
    eng._has_opus_pair = lambda s, t: False
    eng._has_multilingual = lambda d: False
    return eng


def _record_hf(eng):
    """HF 版の呼び出しを記録する（例外で落とすと Stage 1 の except に吸われて検出できない）"""
    calls = []

    def fake_hf(text, src, tgt):
        calls.append((text, src, tgt))
        return "HF訳"

    eng._translate_nllb_hf = fake_hf
    return calls


class BlacklistRouteTests(unittest.TestCase):
    def test_en_ja_prefers_ct2(self):
        nllb = _FakeNLLB()
        eng = _engine(nllb)
        hf_calls = _record_hf(eng)
        r = eng.translate_detail("Hello", "en", "ja")
        self.assertEqual(r.final_text, "CT2訳")
        self.assertEqual(r.route, "NLLB直接 (en→ja)")
        self.assertEqual(nllb.calls, [("Hello", "en", "ja")])
        self.assertEqual(hf_calls, [])

    def test_falls_back_to_hf_when_ct2_not_ready(self):
        eng = _engine(_FakeNLLB(ready=False))
        hf_calls = _record_hf(eng)
        r = eng.translate_detail("Hello", "en", "ja")
        self.assertEqual(r.final_text, "HF訳")
        self.assertEqual(r.route, "NLLB-HF直接 (en→ja)")
        self.assertEqual(len(hf_calls), 1)

    def test_falls_back_to_hf_when_ct2_raises(self):
        eng = _engine(_FakeNLLB(fail=True))
        _record_hf(eng)
        r = eng.translate_detail("Hello", "en", "ja")
        self.assertEqual(r.final_text, "HF訳")
        self.assertEqual(r.route, "NLLB-HF直接 (en→ja)")

    def test_pivot_second_leg_uses_ct2(self):
        # 外国語→en→ja のピボット後半（_do_opus_translate の en-ja）も CT2 を使う
        eng = _engine(_FakeNLLB())
        hf_calls = _record_hf(eng)
        self.assertEqual(eng._do_opus_translate("en", "ja", "Hello"), "CT2訳")
        self.assertEqual(hf_calls, [])


if __name__ == "__main__":
    unittest.main()
