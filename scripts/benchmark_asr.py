"""
PLI 音声認識(ASR)ベンチマーク — Whisper-turbo vs Qwen3-ASR (日本語・法律文脈)

macOS の `say` で正解テキスト付きの音声を生成し、両モデルの文字誤り率(CER)を比較。
実依頼者の音声を使わないため秘匿上も安全。

Usage:
    /Users/sekitomoyuki/.pyenv/versions/3.12.2/bin/python3 scripts/benchmark_asr.py

Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）（東京弁護士会所属）(Tomoyuki Seki)
"""
import json
import os
import subprocess
import time
import unicodedata

# 法律文脈の日本語テストフレーズ（接見・取調べで実際に話される想定）
PHRASES = [
    # 基本・権利告知
    "あなたには黙秘権があります",
    "私はあなたの弁護人です",
    "答えたくない質問には答えなくて構いません",
    # 罪名・事実（同音異義・専門語）
    "被告人は強盗ではなく窃盗の罪に問われています",
    "故意ではなく過失による傷害です",
    "正当防衛が成立する余地があります",
    "覚醒剤取締法違反の被疑事実で勾留されています",
    # 手続
    "勾留期間は原則として十日間です",
    "起訴された後に保釈を請求することができます",
    "公判前整理手続が来週開かれます",
    "検察官が証拠の開示に応じました",
    # 量刑・情状
    "執行猶予が付く可能性は十分にあります",
    "被害者との示談が成立すれば不起訴も見込めます",
    "前科がないことは有利な情状として考慮されます",
    # 長文・複雑
    "あなたが取調べで述べた内容は調書に録取され署名押印を求められます",
    "黙秘権を行使するか供述するかはあなた自身が決めることができます",
    "今後の方針については次回の接見で詳しく説明します",
    "通訳人を介して正確に意思疎通を図りたいと考えています",
]

VOICES = ["Kyoko"]  # 必要なら "O-ren" 等を追加して話者バリエーション

PYBIN = "/Users/sekitomoyuki/.pyenv/versions/3.12.2/bin/python3"
AUDIO_DIR = "/tmp/pli_asr_audio"
QWEN3_ASR_REPO = "mlx-community/Qwen3-ASR-1.7B-bf16"


def normalize(s: str) -> str:
    """CER計算用の正規化: NFKC・空白除去・句読点除去"""
    s = unicodedata.normalize("NFKC", s)
    for ch in " 　、。，．・!！?？「」『』()（）\n\t":
        s = s.replace(ch, "")
    return s


def cer(ref: str, hyp: str) -> float:
    """文字誤り率（Levenshtein / 参照長）"""
    r, h = normalize(ref), normalize(hyp)
    if not r:
        return 0.0 if not h else 1.0
    # Levenshtein距離（DP）
    dp = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        prev = dp[0]
        dp[0] = i
        for j, hc in enumerate(h, 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (rc != hc))
            prev = cur
    return dp[len(h)] / len(r)


def gen_audio():
    """TTSで16kHzモノWAVを生成"""
    os.makedirs(AUDIO_DIR, exist_ok=True)
    items = []
    for vi, voice in enumerate(VOICES):
        for pi, phrase in enumerate(PHRASES):
            wav = os.path.join(AUDIO_DIR, f"v{vi}_p{pi:02d}.wav")
            if not os.path.exists(wav):
                subprocess.run(
                    ["say", "-v", voice, "-o", wav,
                     "--file-format=WAVE", "--data-format=LEI16@16000", phrase],
                    check=True,
                )
            items.append({"voice": voice, "idx": pi, "text": phrase, "wav": wav})
    return items


def run_whisper(items):
    """mlx-whisper turbo で書き起こし"""
    import mlx_whisper
    results = {}
    for it in items:
        t0 = time.time()
        r = mlx_whisper.transcribe(
            it["wav"], path_or_hf_repo="mlx-community/whisper-turbo")
        results[it["wav"]] = {
            "text": r.get("text", "").strip(),
            "sec": time.time() - t0,
        }
    return results


def run_qwen3asr(items):
    """Qwen3-ASR で書き起こし"""
    from qwen3_asr_mlx import Qwen3ASR
    model = Qwen3ASR.from_pretrained(QWEN3_ASR_REPO)
    results = {}
    for it in items:
        t0 = time.time()
        r = model.transcribe(it["wav"], language="ja")
        text = r.text if hasattr(r, "text") else str(r)
        results[it["wav"]] = {"text": text.strip(), "sec": time.time() - t0}
    return results


def main():
    print("=== テスト音声生成（macOS say, Kyoko, 16kHz mono）===")
    items = gen_audio()
    print(f"  {len(items)}本生成\n")

    print("=== Whisper-turbo 実行 ===")
    whisper = run_whisper(items)
    print("  完了\n")

    print("=== Qwen3-ASR 1.7B 実行 ===")
    qwen = run_qwen3asr(items)
    print("  完了\n")

    rows = []
    w_cer_sum = q_cer_sum = w_sec = q_sec = 0.0
    for it in items:
        ref = it["text"]
        wt = whisper[it["wav"]]
        qt = qwen[it["wav"]]
        wc, qc = cer(ref, wt["text"]), cer(ref, qt["text"])
        w_cer_sum += wc
        q_cer_sum += qc
        w_sec += wt["sec"]
        q_sec += qt["sec"]
        rows.append({
            "正解": ref,
            "Whisper": wt["text"], "W_CER": round(wc, 3), "W秒": round(wt["sec"], 2),
            "Qwen3ASR": qt["text"], "Q_CER": round(qc, 3), "Q秒": round(qt["sec"], 2),
        })

    n = len(items)
    summary = {
        "n": n,
        "whisper_mean_cer": round(w_cer_sum / n, 4),
        "qwen3asr_mean_cer": round(q_cer_sum / n, 4),
        "whisper_mean_sec": round(w_sec / n, 2),
        "qwen3asr_mean_sec": round(q_sec / n, 2),
    }

    out = {"summary": summary, "rows": rows}
    with open("/tmp/asr_benchmark.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print("結果（CER = 文字誤り率、低いほど良い）")
    print("=" * 70)
    for r in rows:
        print(f"\n正解   : {r['正解']}")
        print(f"Whisper: {r['Whisper']}  [CER={r['W_CER']} {r['W秒']}s]")
        print(f"Qwen3  : {r['Qwen3ASR']}  [CER={r['Q_CER']} {r['Q秒']}s]")
    print("\n" + "=" * 70)
    print(f"Whisper-turbo  平均CER {summary['whisper_mean_cer']}  平均{summary['whisper_mean_sec']}s/文")
    print(f"Qwen3-ASR 1.7B 平均CER {summary['qwen3asr_mean_cer']}  平均{summary['qwen3asr_mean_sec']}s/文")
    print(f"\n保存: /tmp/asr_benchmark.json")


if __name__ == "__main__":
    main()
