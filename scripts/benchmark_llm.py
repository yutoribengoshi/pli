"""
PLI 翻訳品質ベンチマーク — llama-server 上のモデルを7言語×18フレーズで検証

Usage:
    python scripts/benchmark_llm.py --port 8003 --label "Qwen3.5-9B-Q4_K_M" --out /tmp/bench_q35_9b.json
    python scripts/benchmark_llm.py --port 8003 --label "X" --langs en,tl  # 言語を絞る

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
"""
import argparse
import json
import time
import urllib.request

TEST_PHRASES = [
    ("強盗ではなく窃盗です", "robbery vs theft"),
    ("私は無罪です", "基本主張"),
    ("故意ではなく過失です", "故意/過失"),
    ("正当防衛でした", "違法性阻却"),
    ("私は脅迫されました", "受動的事実"),
    ("私は黙秘します", "黙秘権"),
    ("弁護人と話したい", "接見交通権"),
    ("保釈を申請したい", "保釈"),
    ("通訳人をお願いします", "通訳請求"),
    ("検察官の質問に答えません", "黙秘の意思"),
    ("被害者を殴ったのは私ではありません", "否認"),
    ("ナイフは持っていませんでした", "証拠否認"),
    ("お金を奪う意思はありませんでした", "故意否認"),
    ("彼が先に殴ってきたので押し返しました", "事実経過"),
    ("怪我をさせるつもりはありませんでした", "結果認識"),
    ("被害者に謝罪したい", "情状"),
    ("家族に会いたい", "情状"),
    ("もう犯罪はしません", "更生意思"),
]

LANGUAGES = {
    "en": ("英語", "ENGLISH",
           "強盗=robbery, 窃盗=theft/larceny, 故意=intent/willful, 過失=negligence, "
           "黙秘=remain silent, 保釈=bail, 弁護人=defense counsel, 正当防衛=self-defense"),
    "zh": ("中国語(簡体字)", "SIMPLIFIED CHINESE",
           "強盗=抢劫, 窃盗=盗窃, 故意=故意, 過失=过失, 黙秘=保持沉默, 保釈=保释, "
           "弁護人=辩护人, 正当防衛=正当防卫"),
    "vi": ("ベトナム語", "VIETNAMESE",
           "強盗=cướp, 窃盗=trộm cắp, 故意=cố ý, 過失=sơ suất, 黙秘=giữ im lặng, "
           "保釈=tại ngoại, 弁護人=luật sư bào chữa, 正当防衛=tự vệ chính đáng"),
    "es": ("スペイン語", "SPANISH",
           "強盗=robo, 窃盗=hurto, 故意=dolo/intención, 過失=negligencia, "
           "黙秘=guardar silencio, 保釈=libertad bajo fianza, 弁護人=abogado defensor, "
           "正当防衛=legítima defensa"),
    "pt": ("ポルトガル語", "PORTUGUESE (Brazilian)",
           "強盗=roubo, 窃盗=furto, 故意=dolo/intenção, 過失=negligência, "
           "黙秘=permanecer em silêncio, 保釈=fiança, 弁護人=advogado de defesa, "
           "正当防衛=legítima defesa"),
    "ur": ("ウルドゥー語", "URDU (in Urdu script)",
           "強盗=ڈکیتی, 窃盗=چوری, 黙秘=خاموشی اختیار کرنا, 保釈=ضمانت, "
           "弁護人=وکیل دفاع, 故意=جان بوجھ کر, 過失=غفلت, 正当防衛=جائز دفاع"),
    "tl": ("タガログ語", "TAGALOG (FILIPINO)",
           "強盗=panghoholdap/pagnanakaw na may dahas, 窃盗=pagnanakaw, 故意=sinasadya, "
           "過失=kapabayaan, 黙秘=tumahimik, 保釈=piyansa, 弁護人=abogado/tagapagtanggol, "
           "正当防衛=lehitimong pagtatanggol-sa-sarili"),
}

SYSTEM_BACK = ("You are a professional legal interpreter. Translate the following sentence "
               "into Japanese accurately, preserving legal terminology. "
               "Output ONLY the Japanese translation, no explanation.")


def call(system: str, user: str, port: int, timeout: int = 120) -> str:
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 200,
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--label", required=True, help="モデル名ラベル")
    ap.add_argument("--out", required=True, help="結果JSON出力先")
    ap.add_argument("--langs", default="en,zh,vi,es,pt,ur,tl")
    args = ap.parse_args()

    langs = [l.strip() for l in args.langs.split(",") if l.strip() in LANGUAGES]
    all_results = {"model": args.label, "languages": {}}

    for code in langs:
        name_ja, name_en, glossary = LANGUAGES[code]
        system_to = (
            f"You are a professional legal interpreter for Japanese criminal trials. "
            f"Translate the Japanese sentence into {name_en} accurately, preserving legal "
            f"terminology ({glossary}). Output ONLY the translation, no explanation."
        )
        print(f"\n{'='*70}\n[{args.label}] {name_ja} ({code})\n{'='*70}")
        results = []
        for ja, note in TEST_PHRASES:
            try:
                t0 = time.time()
                tr = call(system_to, ja, args.port)
                t1 = time.time()
                bk = call(SYSTEM_BACK, tr, args.port)
                t2 = time.time()
                print(f"\n{ja}  [{note}]")
                print(f"  訳: {tr}")
                print(f"  逆: {bk}  ({t2-t0:.1f}s)")
                results.append({"原文": ja, "観点": note, "訳": tr, "逆訳": bk,
                                "秒": f"{t2-t0:.1f}", "順秒": f"{t1-t0:.1f}"})
            except Exception as e:
                print(f"\n{ja} ERROR: {e}")
                results.append({"原文": ja, "観点": note, "ERROR": str(e)})
        all_results["languages"][code] = {"language": name_ja, "results": results}

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n\n{'='*70}\nSUMMARY — {args.label}\n{'='*70}")
    for code, d in all_results["languages"].items():
        ok = sum(1 for r in d["results"] if "ERROR" not in r and r.get("訳", "").strip())
        avg = sum(float(r.get("秒", 0)) for r in d["results"] if "ERROR" not in r) / max(ok, 1)
        print(f"  {d['language']:12s}: {ok}/{len(d['results'])} 成功, 平均往復 {avg:.1f}s")
    print(f"\n保存: {args.out}")


if __name__ == "__main__":
    main()
