# PLI メモリ高速化提案

> 作成: 2026-03-28
> 参考: [mac-code](https://github.com/walter-grace/mac-code) — Apple Silicon向けLLMメモリ最適化

---

## 1. 現状の問題

```
現在の LLMEngine (interpreter.py L441-516):
├ llama-cpp-python でモデルをプロセス内にロード
├ Qwen2.5-32B Q6_K → 25GB 常駐
├ n_gpu_layers=-1 → 全層GPU
├ PLI終了までメモリ解放されない
├ 他アプリ（METIS・証拠ビューア）とモデル共有不可
└ 8GB/16GB Mac では動作不可能
```

## 2. 解決策: ユニバーサルソケット方式

### アーキテクチャ

```
PLI.app (UI + STT + OPUS + NLLB)
    ↓ HTTP API (OpenAI互換)
    ↓ localhost:8000/v1/chat/completions
llama-server (独立プロセス、共有可能)
    ├ METIS からも利用可能
    ├ 証拠ビューアからも利用可能
    └ 停止すればメモリ全解放
```

### ティア別構成

| ティア | メモリ | モデル | サイズ | 速度目安 |
|--------|--------|--------|--------|----------|
| **Lite** (8GB) | LLMなし | NLLB + OPUS のみ | 2GB | 即時 |
| **Standard** (16GB) | Qwen3-8B Q4_K_M | 小型LLM | 5GB | ~30 tok/s |
| **Pro** (32GB+) | Qwen3.5-35B-A3B IQ2_M | MoE 3B活性 | 11GB | ~60 tok/s |
| **Max** (64GB+) | Qwen3-235B-A22B Q2_K_L | MoE 22B活性 | 58GB | ~10 tok/s |

## 3. mac-code 技術の適用

[mac-code](https://github.com/walter-grace/mac-code) の3つのコア技術を llama-server の起動オプションで適用:

### 3.1 F_NOCACHE (ダイレクトI/O)

```
mac-code の手法:
  fcntl(fd, F_NOCACHE, 1)  → macOSバッファキャッシュをバイパス
  → OSが勝手にRAMにキャッシュしない → メモリ節約

llama-server での適用:
  --no-mmap  → F_NOCACHE相当。SSDから直接読み込み
  → 16GB Macでも25GBモデルのバッファキャッシュでスワップ地獄にならない
```

### 3.2 MoE Expert Sniper (選択的エキスパートロード)

```
mac-code の手法:
  MoEモデルの256個のエキスパートのうち、推論に必要な8個だけをSSDから読む
  → 35Bモデルでも実際に使うのは3Bだけ

llama-server での適用:
  llama.cpp が MoE アーキテクチャを自動検出して最適化
  Qwen3.5-35B-A3B: 256 experts → 8 active per token
  Qwen3-235B-A22B: 128 experts → 8 active per token
  → GPU転送量が劇的に減る → 速度向上
```

### 3.3 KVキャッシュ量子化

```
mac-code の手法:
  KVキャッシュをFP16→Q4に圧縮 → メモリ1/4

llama-server での適用:
  --cache-type-k q4_0 --cache-type-v q4_0
  → ctx-size 4096 で KVキャッシュ ~22MB (通常 ~90MB)
  → 翻訳用途は短文なのでctx-size小さくて問題なし
```

### 3.4 Flash Attention

```
  --flash-attn on
  → attention計算のピークメモリを半減
  → Apple Silicon Metal で最適化済み
```

## 4. 起動コマンド（ティア別）

### Standard (16GB Mac)
```bash
llama-server \
  --model ~/pli-models/Qwen3-8B-Q4_K_M.gguf \
  --port 8000 --host 127.0.0.1 \
  --flash-attn on \
  --ctx-size 2048 \
  --cache-type-k q4_0 --cache-type-v q4_0 \
  --n-gpu-layers 99 \
  --no-mmap \
  -np 1 -t 4
```

### Pro (32GB+ Mac)
```bash
llama-server \
  --model ~/pli-models/Qwen3.5-35B-A3B-UD-IQ2_M.gguf \
  --port 8000 --host 127.0.0.1 \
  --flash-attn on \
  --ctx-size 4096 \
  --cache-type-k q4_0 --cache-type-v q4_0 \
  --n-gpu-layers 99 \
  --no-mmap \
  -np 1 -t 4
```

### Max (64GB+ Mac)
```bash
llama-server \
  --model ~/models/Q2_K_L/Qwen3-235B-A22B-Q2_K_L-00001-of-00002.gguf \
  --port 8000 --host 127.0.0.1 \
  --flash-attn on \
  --ctx-size 8192 \
  --cache-type-k q4_0 --cache-type-v q4_0 \
  --n-gpu-layers 99 \
  --no-mmap \
  -np 1 -t 4
```

## 5. 実装: LLMEngine の書き換え

### 変更ファイル: `core/interpreter.py`

現在の `LLMEngine` クラス (L441-516) を HTTP API クライアントに置き換える。

```python
# Before (現状): llama-cpp-python でプロセス内ロード
from llama_cpp import Llama
self._llm = Llama(model_path=..., n_gpu_layers=-1)
resp = self._llm.create_chat_completion(messages=..., max_tokens=256)

# After (提案): HTTP API コール (OpenAI互換)
import urllib.request, json

def _chat(self, system, user, max_tokens=256):
    payload = json.dumps({
        "model": "local",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(
        f"{self._api_base}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()
```

### 主な変更点

1. **`LLMEngine.__init__`**: `model_path` → `api_base` (デフォルト `http://127.0.0.1:8000`)
2. **`LLMEngine._chat`**: `self._llm.create_chat_completion()` → HTTP POST
3. **`LLMEngine.is_ready`**: ヘルスチェック `GET /health` で判定
4. **`LLMEngine.load_model_async`**: サーバー起動確認に変更（モデルロード不要）
5. **`LLMEngine._ensure_loaded`**: サーバー到達性チェックに変更
6. **ストリーミング対応**: SSE (Server-Sent Events) で `stream=True` 対応
7. **フォールバック**: サーバー未起動時は NLLB にフォールバック

### 依存関係の変更

```
削除: llama-cpp-python (ビルドが面倒、メモリ常駐)
追加: なし (urllib.request は標準ライブラリ)
```

→ requirements.txt から `llama-cpp-python` を削除可能
→ ビルドサイズ縮小、PyInstallerの互換性問題も解消

## 6. PLI配布パッケージ構成

```
PLI Lite (無料、8GB Mac対応):
  PLI.app          → 翻訳UI + STT
  NLLB-1.3B-int8   → 1.3GB
  OPUS-MTモデル群   → 言語ペア選択式 (各0.3-1GB)
  合計: ~3GB

PLI Pro (有料、16GB+ Mac対応):
  PLI Lite の全内容 +
  llama-server バイナリ  → ~50MB
  Qwen3-8B-Q4_K_M.gguf  → ~5GB
  自動起動スクリプト      → llama-server をバックグラウンド起動
  合計: ~8GB

PLI Max (自分用 / パワーユーザー):
  PLI Pro の全内容 +
  大型モデルは手動ダウンロード指示
  → Qwen3.5-35B-A3B or Qwen3-235B
```

## 7. 検証済みベンチマーク (M3 Max 64GB)

```
Qwen3.5-35B-A3B IQ2_M (11GB):
  プロンプト処理: 63 tok/s
  生成速度:       61 tok/s
  GPU使用:        全41層オフロード (Metal)
  VRAM使用:       10.5GB / 49GB利用可能
  KVキャッシュ:   22.5MB (q4_0)
  メモリ残り:     ~38GB (Claude Code等と余裕で共存)
```

## 8. 実装優先順位

1. **LLMEngine を HTTP API 方式に書き換え** ← 最優先
2. **llama-server 自動起動/停止の仕組み** (PLI起動時にサーバー起動、終了時に停止)
3. **ティア自動検出** (搭載メモリでモデル推奨)
4. **設定画面に「モデルサーバーURL」設定追加**
5. **llama-cpp-python 依存を削除、requirements.txt 更新**

---

## 9. Windows / Intel 対応

### 問題: Windowsモバイルの制約

```
Apple Silicon (統合メモリ):
  CPU/GPU が同じ64GBメモリを共有 → 全部使える

Windows ノート (分離メモリ):
  RAM 16GB + VRAM 0GB (iGPU) → GPUが使えない
  RAM 16GB + VRAM 4-6GB (dGPU) → VRAM小さい、RAM別計上
  → CPU推論が前提になるケースが多い
```

### 9.1 CPU世代別の最適化

Intel CPUのAVX命令セットがLLM推論速度を決定する。

| Intel世代 | 年代 | AVX | 推論速度目安 (Qwen3-8B Q4) | 推奨モデル |
|-----------|------|-----|---------------------------|-----------|
| 第4-5世代 (Haswell/Broadwell) | 2013-2015 | AVX2 | ~3 tok/s | NLLB+OPUSのみ |
| 第6-8世代 (Skylake〜Coffee Lake) | 2015-2018 | AVX2 | 5-8 tok/s | Qwen3-4B |
| 第9-10世代 (Coffee Lake〜Comet Lake) | 2018-2020 | AVX2 | 6-10 tok/s | Qwen3-4B〜8B |
| 第11世代 (Tiger Lake) | 2020-2021 | **AVX-512** | 8-12 tok/s (**2倍速**) | Qwen3-8B |
| 第12世代以降 (Alder Lake〜) | 2022- | AVX2 (※) | 12-18 tok/s | Qwen3-8B〜14B |

※ 第12世代以降はAVX-512がP-coreでは無効化。ただしDDR5・高コア数で補う。

### 9.2 RAM別ティア (Windows)

| RAM | 利用可能メモリ | モデル | サイズ | 備考 |
|-----|--------------|--------|--------|------|
| **8GB** | ~4GB | LLMなし (NLLB+OPUS) | 2GB | スワップ回避が最優先 |
| **16GB** | ~11GB | Qwen3-4B Q4_K_M | 2.5GB | 安定・高速 |
| | | Qwen3-8B Q4_K_M | 5GB | 推奨 (AVX-512あれば快適) |
| **32GB** | ~26GB | Qwen3-14B Q4_K_M | 9GB | 高品質 |
| | | Qwen3-32B Q4_K_M | 20GB | Sonnet級の翻訳品質 |
| **64GB** | ~56GB | Qwen3-72B Q4_K_M | 43GB | CPU推論で遅い(3-5 tok/s)が動く |

### 9.3 自動検出ロジック

PLI起動時にハードウェアを自動検出し、最適なモデルとパラメータを選択する。

```python
import platform, psutil

def detect_optimal_config():
    """ハードウェア自動検出 → 最適LLM構成を返す"""
    os_name = platform.system()
    ram_gb = psutil.virtual_memory().total // (1024**3)

    if os_name == "Darwin":
        # macOS (Apple Silicon) — 統合メモリ、Metal GPU
        if ram_gb >= 64:
            return TierConfig.MAX      # Qwen3-235B or 35B
        elif ram_gb >= 32:
            return TierConfig.PRO      # Qwen3.5-35B-A3B
        elif ram_gb >= 16:
            return TierConfig.STANDARD # Qwen3-8B
        else:
            return TierConfig.LITE     # NLLB+OPUSのみ

    elif os_name == "Windows":
        # Windows — CPU世代とRAMで判定
        avx512 = _has_avx512()

        if ram_gb >= 32:
            if avx512:
                return TierConfig.WIN_HIGH    # Qwen3-32B, AVX-512最適化
            else:
                return TierConfig.WIN_HIGH    # Qwen3-14B〜32B
        elif ram_gb >= 16:
            if avx512:
                return TierConfig.WIN_MID     # Qwen3-8B
            else:
                return TierConfig.WIN_MID     # Qwen3-4B
        else:
            return TierConfig.LITE            # NLLB+OPUSのみ

def _has_avx512():
    """AVX-512対応チェック"""
    try:
        import cpuinfo
        flags = cpuinfo.get_cpu_info().get('flags', [])
        return 'avx512f' in flags
    except:
        return False
```

### 9.4 llama-server 起動コマンド (Windows)

#### Windows 16GB + AVX2 (第6-10世代 Core i5/i7)
```bash
llama-server.exe ^
  --model %USERPROFILE%\pli-models\Qwen3-4B-Q4_K_M.gguf ^
  --port 8000 --host 127.0.0.1 ^
  --ctx-size 2048 ^
  --cache-type-k q4_0 --cache-type-v q4_0 ^
  --no-mmap ^
  -np 1 -t 4
```

#### Windows 16GB + AVX-512 (第11世代 Tiger Lake)
```bash
llama-server.exe ^
  --model %USERPROFILE%\pli-models\Qwen3-8B-Q4_K_M.gguf ^
  --port 8000 --host 127.0.0.1 ^
  --ctx-size 4096 ^
  --cache-type-k q4_0 --cache-type-v q4_0 ^
  --no-mmap ^
  -np 1 -t 6
```

#### Windows 32GB (Core i7 第8世代以降)
```bash
llama-server.exe ^
  --model %USERPROFILE%\pli-models\Qwen3-32B-Q4_K_M.gguf ^
  --port 8000 --host 127.0.0.1 ^
  --ctx-size 4096 ^
  --cache-type-k q4_0 --cache-type-v q4_0 ^
  --no-mmap ^
  -np 1 -t 8
```

#### Windows + NVIDIA GPU (VRAM 8GB+)
```bash
llama-server.exe ^
  --model %USERPROFILE%\pli-models\Qwen3-8B-Q4_K_M.gguf ^
  --port 8000 --host 127.0.0.1 ^
  --flash-attn ^
  --ctx-size 4096 ^
  --cache-type-k q4_0 --cache-type-v q4_0 ^
  --n-gpu-layers 99 ^
  -np 1 -t 4
```

### 9.5 Windows固有の最適化

```
--no-mmap:
  Windows でも有効。CreateFileMapping を使わず直接読み込み。
  → ページキャッシュ肥大化を防止、他アプリへの影響を軽減。

--threads (-t):
  Windows ノートは発熱がボトルネック。
  物理コア数の 70% に制限する（例: 8コア→6スレッド）。
  → サーマルスロットリング回避で実効速度が上がる。

Large Pages (オプション):
  管理者権限で Large Pages を有効化すると TLB ミスが減る。
  → 大型モデル (32B+) で 5-10% の速度向上。
  設定: secpol.msc → ローカルポリシー → メモリ内のページのロック → ユーザー追加

NUMA対応 (デスクトップ/ワークステーション):
  Xeon / Threadripper では NUMA ノードを意識したスレッド割り当てが有効。
  → PLI配布レベルでは不要、パワーユーザー向けオプション。
```

### 9.6 接見室での現実的な使い方

```
接見の流れ（Windows CPU-only ノート、16GB RAM）:

被疑者発話 → Whisper STT (small, CPU) → 2-5秒
  ↓
テキスト → OPUS-MT 即時翻訳 → 0.3秒（画面表示）
  ↓
同時にバックグラウンドで LLM が高精度翻訳を生成 → 3-8秒
  ↓
LLM結果が来たら画面を差し替え or 並列表示

→ 弁護人は OPUS-MT の即時結果で会話を続けつつ、
  LLM の高精度結果で誤訳を確認できる。
→ CPU推論の遅さは「2段階表示」で体感を補う。
```

---

## 参考リンク

- [mac-code](https://github.com/walter-grace/mac-code) — F_NOCACHE + Expert Sniper
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/examples/server) — OpenAI互換API
- [Apple M3 Max specs](https://support.apple.com/ja-jp/117736) — 400GB/sメモリ帯域

---

(c) 2026 中野通り法律事務所 弁護士 関智之
