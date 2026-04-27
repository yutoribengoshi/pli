# NOTICE — 第三者ソフトウェア・データの帰属表示

PLI (Private Link Interpreter) は、以下のオープンソースソフトウェア・公開データを利用しています。各々の著作権・ライセンスに従ってご利用ください。

---

## ソフトウェアコンポーネント

### UI フレームワーク
- **PySide6 (Qt for Python)** — LGPL v3
  - © The Qt Company Ltd.
  - https://www.qt.io/qt-for-python

### 音声認識
- **OpenAI Whisper** — MIT License
  - © 2022 OpenAI
  - https://github.com/openai/whisper
- **mlx-whisper** — MIT License
  - © 2024 Apple Inc.
  - https://github.com/ml-explore/mlx-examples
- **faster-whisper** — MIT License
  - © Guillaume Klein
  - https://github.com/SYSTRAN/faster-whisper

### 機械翻訳
- **NLLB-200 (No Language Left Behind)** — CC-BY-NC 4.0
  - © Meta Platforms, Inc.
  - https://github.com/facebookresearch/fairseq/tree/nllb
  - 学術論文: https://arxiv.org/abs/2207.04672
- **OPUS-MT (Helsinki-NLP)** — CC-BY 4.0
  - © Jörg Tiedemann (University of Helsinki)
  - https://github.com/Helsinki-NLP/Opus-MT

### LLM (大規模言語モデル)
- **Qwen2.5-Instruct (Qwen Team, Alibaba Cloud)** — Apache License 2.0
  - © 2024 Alibaba Group
  - https://github.com/QwenLM/Qwen2.5
- **Qwen3-Swallow (Tokyo Institute of Technology Swallow Team)** — Apache License 2.0
  - 東京工業大学 Swallow チーム
  - https://swallow-llm.github.io/

### LLM 実行エンジン
- **llama.cpp** — MIT License
  - © Georgi Gerganov
  - https://github.com/ggerganov/llama.cpp
- **ggml** — MIT License
  - © Georgi Gerganov
  - https://github.com/ggerganov/ggml

### Python ライブラリ
- **transformers (Hugging Face)** — Apache License 2.0
  - © Hugging Face, Inc.
  - https://github.com/huggingface/transformers
- **ctranslate2 (OpenNMT)** — MIT License
  - © OpenNMT
  - https://github.com/OpenNMT/CTranslate2
- **sentencepiece** — Apache License 2.0
  - © Google Inc.
  - https://github.com/google/sentencepiece
- **PyAudio** — MIT License
  - © Hubert Pham
  - https://github.com/jleb/pyaudio
- **sounddevice** — MIT License
  - © Matthias Geier
  - https://github.com/spatialaudio/python-sounddevice

---

## 法律用語辞書（データ）

### 法務省 日本法令翻訳辞書 (JLT)
- 出典: https://www.japaneselawtranslation.go.jp/en/dicts
- バージョン: 18.0
- 収録語: 約 3,769 語
- ライセンス: 法務省の利用規約に従う
- PLIはJLT辞書をCSV形式から取り込み、法律用語の機械翻訳補正に使用しています。

### DEA 薬物スラング辞書
- 出典: DEA Intelligence Report DIR-022-18
  "Slang Terms and Code Words: A Reference for Law Enforcement Personnel"
  (Drug Enforcement Administration, July 2018)
- 収録語: 約 81 語
- ライセンス: 米国政府著作物（パブリックドメイン）
- 用途: 薬物事件における隠語・スラングの翻訳補正

### NIDA 薬物用語
- 出典: National Institute on Drug Abuse (NIH)
- https://nida.nih.gov/drug-topics/commonly-used-drugs-charts
- ライセンス: 米国政府著作物（パブリックドメイン）

### 関 智之 弁護士による手動追加用語（約 570 語）
- 出典: 関 智之 弁護士による刑事弁護現場用語の手動編纂
- 内容: 刑法罪名、特別法罪名、関税法、入管法、刑事訴訟手続用語等
- ライセンス: 関 智之 弁護士の編集著作物。PLIプロジェクト内での非営利利用は自由

---

## モデル重み（ダウンロード時に取得）

PLIは以下のモデル重みをHuggingFaceからダウンロードして利用します。各々のライセンスをご確認ください。

| モデル | ライセンス | 出典 |
|--------|-----------|------|
| facebook/nllb-200-distilled-600M | CC-BY-NC 4.0 | https://huggingface.co/facebook/nllb-200-distilled-600M |
| facebook/nllb-200-distilled-1.3B | CC-BY-NC 4.0 | https://huggingface.co/facebook/nllb-200-distilled-1.3B |
| facebook/nllb-200-3.3B | CC-BY-NC 4.0 | https://huggingface.co/facebook/nllb-200-3.3B |
| Helsinki-NLP/opus-mt-* | CC-BY 4.0 | https://huggingface.co/Helsinki-NLP |
| mlx-community/whisper-turbo | MIT | https://huggingface.co/mlx-community/whisper-turbo |
| Qwen/Qwen2.5-72B-Instruct (GGUF) | Apache 2.0 | https://huggingface.co/Qwen/Qwen2.5-72B-Instruct |

**重要：NLLB-200 は CC-BY-NC（非商用）ライセンスのため、商用利用時にはMeta社への確認が必要です。**

---

## 謝辞

本プロジェクトは以下の研究・開発コミュニティの成果に立脚しています：
- OpenAI（音声認識Whisper）
- Meta AI Research（NLLB-200 多言語翻訳）
- Helsinki-NLP（OPUS-MT 言語ペア専用翻訳）
- Alibaba Qwen Team（Qwen2.5 LLM）
- 東京工業大学 Swallow チーム（日本語特化LLM）
- ggerganov 氏（llama.cpp）
- Hugging Face（transformers ライブラリ・モデルハブ）
- 法務省（日本法令翻訳辞書）
- 米国麻薬取締局（薬物スラング辞書）

これらのソフトウェア・データの公開・共有がなければ、本ソフトウェアは実現しませんでした。深く感謝いたします。

---

© 2025-2026 中野通り法律事務所 弁護士 関 智之. All rights reserved.

NO WARRANTY. USE AT YOUR OWN RISK.
