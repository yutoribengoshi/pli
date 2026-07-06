# PLI ロードマップ・問題点・構成情報

> 最終更新: 2026-03-28
> 開発: 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）

---

## 1. ファイル・ディレクトリ構成

### ソースコード

```
~/dev/pli/                          ← Git リポジトリ (github.com/yutoribengoshi/pli)
├── main.py                         ← エントリポイント
├── PLI.spec                        ← PyInstaller ビルド設定
├── requirements.txt                ← Mac用依存関係
├── requirements-windows.txt        ← Windows用依存関係
├── LICENSE                         ← ライセンス（クレジット削除禁止条項付き）
├── run.sh                          ← 開発用起動スクリプト
│
├── core/                           ← コアロジック
│   ├── interpreter.py              ← 統合クラス（STT + 翻訳エンジン）
│   ├── recorder.py                 ← 音声録音・VAD
│   ├── stt_listener.py             ← リアルタイム音声認識リスナー
│   ├── hide_mode.py                ← 秘匿モード（画面隠し）
│   ├── opus_downloader.py          ← OPUS-MT モデルダウンローダー
│   └── nllb_downloader.py          ← NLLB モデルダウンローダー
│
├── ui/                             ← UI（PySide6/Qt）
│   ├── attorney_window.py          ← 弁護人画面（メイン）
│   └── defendant_window.py         ← 被疑者画面
│
├── data/
│   └── legal_dict.json             ← 法律用語辞書（4,339語）
│
├── docs/                           ← ドキュメント
│   ├── ROADMAP.md                  ← このファイル
│   ├── windows_setup.md            ← Windows版セットアップ手順
│   └── macos_release.md            ← macOSリリース手順
│
├── tests/                          ← テスト
├── scripts/                        ← ビルド・リリーススクリプト
├── assets/                         ← アイコン・entitlements等
├── dist/PLI.app                    ← ビルド済みアプリ
└── build/                          ← ビルド中間ファイル
```

### アプリ（macOS）

```
/Applications/PLI.app               ← インストール先
```

### モデルファイル

```
~/dev/pli-models/                          ← モデル格納ディレクトリ（約47GB）
├── Qwen2.5-32B-Instruct-Q6_K.gguf        ← LLMモデル（25GB）
├── nllb/
│   └── nllb-1.3b-int8/                   ← NLLB翻訳モデル（1.3GB）
├── opus/                                  ← OPUS-MT翻訳モデル群（合計21GB）
│   ├── ja-en/                             ← 日本語→英語
│   ├── en-ja/                             ← 英語→日本語（※実際はen-jap）
│   ├── zh-en/, en-zh/                     ← 中国語
│   ├── ko-en/, en-ko/                     ← 韓国語（※en-ko は NLLB fallback）
│   ├── fr-en/, en-fr/                     ← フランス語
│   ├── de-en/, en-de/                     ← ドイツ語
│   ├── es-en/, en-es/                     ← スペイン語
│   ├── ru-en/, en-ru/                     ← ロシア語
│   ├── ar-en/, en-ar/                     ← アラビア語
│   ├── vi-en/, en-vi/                     ← ベトナム語
│   ├── th-en/                             ← タイ語（→英語のみ）
│   ├── hi-en/                             ← ヒンディー語（→英語のみ）
│   ├── tr-en/, en-tr/                     ← トルコ語（※en-tr は NLLB fallback）
│   ├── pt-en/                             ← ポルトガル語（→英語のみ）
│   ├── mul-en/                            ← 多言語→英語（120言語対応）
│   └── en-mul/                            ← 英語→多言語（120言語対応）
├── font_scale.txt                         ← UI フォントサイズ設定
└── last_n_ctx.txt                         ← LLM コンテキスト長設定
```

### GitHub

```
https://github.com/yutoribengoshi/pli     ← プライベートリポジトリ
```

---

## 2. 翻訳エンジン構成

### 翻訳モード一覧

| モード | エンジン | 精度 | 速度 | VRAM/メモリ | 用途 |
|--------|---------|:----:|:----:|:----------:|------|
| **LLM** | Qwen2.5-32B (llama.cpp) | ◎ | △ | 25GB | 高精度翻訳。法律文書レベル |
| **NLLB** | NLLB-1.3B-int8 (CTranslate2) | ○ | ◎ | 1.3GB | 軽量・高速。日常会話レベル |
| **Hybrid** | OPUS-MT + NLLB + LLM | ◎◎ | ○ | 全部 | 最高精度。OPUS→NLLB→LLM段階的 |
| **Mock** | ダミーデータ | — | — | 0 | 開発・デモ用 |

### 音声認識（STT）

| プラットフォーム | エンジン | モデル | GPU | 速度（2秒音声） |
|----------------|---------|-------|-----|:---------------:|
| **macOS (Apple Silicon)** | mlx-whisper | whisper-turbo | Metal | ~0.5秒 |
| **Windows (NVIDIA)** | faster-whisper | small〜large | CUDA | ~2秒 |
| **Windows (CPU only)** | faster-whisper | small | CPU (int8) | ~5秒 |

### 翻訳パイプライン（Hybridモード）

```
音声入力
  ↓
[Whisper STT] 音声→テキスト（原語）
  ↓
[法律用語辞書] legal_dict.json (4,339語) で専門用語を先に検索
  ↓
[OPUS-MT] 原語→英語 (中間翻訳)  ※対応ペアがある場合
  ↓
[中間英語表示] ← 弁護人が誤訳チェック可能
  ↓
[NLLB / LLM] 英語→対象言語 (最終翻訳)
  ↓
対象言語テキスト表示 + 読み上げ（TTS）
```

### 法律用語辞書の構成

| 出典 | エントリ数 | 内容 |
|------|:---------:|------|
| **法務省 JLT公式辞書** (v18.0) | 3,842 | 日本法令英訳辞書（japaneselawtranslation.go.jp） |
| **刑事弁護頻出用語** (手動) | 172 | 刑法各論・特別法・刑法総論 |
| **民事法用語** (手動) | 70 | 訴訟手続・保全・契約・労働・家事・倒産等 |
| **関税法・密輸用語** (手動) | 47 | 関税法罪名・密輸手口・外為法 |
| **DEA薬物スラング** (DIR-022-18) | 81 | 米国DEA公式レポート（2018年版） |
| **NIDA薬物用語** | 5 | 米国国立薬物乱用研究所 |
| **実務補充用語** (手動) | 122 | 職務質問・所持品検査・量刑用語等 |
| **合計** | **4,339** | |

### Mac vs Windows の技術的差異

| コンポーネント | Mac (Apple Silicon) | Windows (NVIDIA) | Windows (CPU only) |
|--------------|:------------------:|:----------------:|:-----------------:|
| **STT** | mlx-whisper (Metal) | faster-whisper (CUDA) | faster-whisper (CPU/int8) |
| **OPUS-MT** | CTranslate2 (CPU) | CTranslate2 (CUDA) | CTranslate2 (CPU) |
| **NLLB** | CTranslate2 (CPU) | CTranslate2 (CUDA) | CTranslate2 (CPU) |
| **LLM** | llama.cpp (Metal) | llama.cpp (CUDA) | llama.cpp (CPU) ※非実用的 |
| **秘匿モード** | Quick Look偽装 | 要実装（タスクバー制御） |
| **UI** | PySide6 (macOS native) | PySide6 (Windows native) |
| **AMD Radeon** | — | **非対応**（CTranslate2/faster-whisperがROCm未対応） |

---

## 3. 既知の問題点

### 🔴 致命的（修正必須）

| # | 問題 | 詳細 | 影響 |
|---|------|------|------|
| 1 | **Windows版未完成** | platform分岐の実装途中。hide_modeがmacOS専用 | 市場の8割に届かない |
| 2 | **ハイブリッドモード未検証** | モデルは揃ったが実際の接見環境でのE2Eテストなし | メイン機能が未確認 |
| 3 | **エラーハンドリング不足** | モデルロード失敗時のUI表示が不親切 | ユーザーが原因不明で詰まる |
| 4 | **マイク権限の自動要求なし** | macOS Sequoia以降、初回起動時に権限ダイアログが出ない場合がある | STT不可になる |

### 🟡 重要（改善必要）

| # | 問題 | 詳細 | 影響 |
|---|------|------|------|
| 5 | **初回起動が遅い** | Whisperモデル初回ダウンロード + LLMロードに数分 | 初見ユーザーが離脱 |
| 6 | **モデルサイズが大きい** | 全モデル合計47GB。配布が困難 | ダウンロード販売に向かない |
| 7 | **言語自動検出の精度** | Whisperの言語検出が短文で不安定 | 誤った言語ペアで翻訳される |
| 8 | **辞書検索が部分一致のみ** | 「覚醒」で「覚醒剤」がヒットするが、逆引き（英→日）が弱い | 辞書の使い勝手が中途半端 |
| 9 | **TTS（読み上げ）未実装** | 翻訳結果のテキスト表示のみ。音声出力がない | 被疑者が読めない場合に不便 |
| 10 | **設定画面がない** | 言語ペア・モデル選択・フォントサイズ等がCLI引数のみ | 一般ユーザーが設定変更できない |

### 🟢 改善要望（あれば嬉しい）

| # | 問題 | 詳細 |
|---|------|------|
| 11 | **会話ログのエクスポート** | PDF/Word形式で接見記録を出力したい |
| 12 | **定型文テンプレート** | 黙秘権告知・権利告知の多言語テンプレート |
| 13 | **オフラインアップデート** | USB経由で辞書・モデルを更新する仕組み |
| 14 | **iPad対応** | 接見室に持ち込む端末としてiPadの需要あり |
| 15 | **多言語同時対応** | 共犯者が別言語のケース（例: 中国語 + ベトナム語） |
| 16 | **音声録音・再生** | 聞き取れなかった部分を再生したい |
| 17 | **翻訳品質フィードバック** | ユーザーが誤訳を報告→辞書に反映 |

---

## 4. 開発ロードマップ

### Phase 1: 品質安定化（1〜2ヶ月）

- [ ] ハイブリッドモードのE2Eテスト（実音声 → STT → 翻訳 → 表示）
- [ ] テスト実行（Codexが書いた4テストファイル）
- [ ] エラーハンドリング改善（モデルロード失敗時のUIメッセージ）
- [ ] マイク権限の自動要求（Info.plist + entitlements）
- [ ] 初回起動ウィザード（言語選択・モデルダウンロード進捗表示）
- [ ] 設定画面（GUI）の実装

### Phase 2: Windows版（2〜3ヶ月）

- [ ] platform分岐の完全実装（hide_mode, STT, パス解決）
- [ ] faster-whisper + CUDA動作確認
- [ ] Windows用インストーラー（NSIS or MSI）
- [ ] モデル同梱 or 初回ダウンロードの選択
- [ ] Windows CI/CD（GitHub Actions）
- [ ] CPU-onlyモードの最適化（Whisper-small固定、int8量子化）

### Phase 3: 配布・公開準備（1〜2ヶ月）

- [ ] 商標「PLI」出願（第9類・第42類）
- [ ] デモ動画制作（YouTube）
- [ ] ランディングページ作成
- [ ] 利用規約・プライバシーポリシー策定
- [ ] 決済システム導入（Stripe or Gumroad）
- [ ] モデル配布の軽量化（NLLB-onlyの軽量版パッケージ: 約3GB）

### Phase 4: 市場投入（3ヶ月〜）

- [ ] ベータテスター募集（刑弁仲間5〜10人）
- [ ] 季刊刑事弁護への寄稿
- [ ] 弁護士会CLE研修での講演
- [ ] 法テラスへの導入提案
- [ ] フィードバック反映サイクル確立

### Phase 5: 機能拡張（6ヶ月〜）

- [ ] TTS（テキスト読み上げ）実装
- [ ] 会話ログのPDF/Wordエクスポート
- [ ] 定型文テンプレート（黙秘権告知等）
- [ ] iPad版（Swift UI or Flutter）
- [ ] 翻訳品質フィードバック機能
- [ ] 薬物スラング辞書の継続拡充（DEA年次更新）
- [ ] 米国Public Defender向け英語⇔スペイン語版

---

## 5. 技術的な注意事項

### モデル選択の指針

| 使用環境 | 推奨エンジン | 理由 |
|---------|------------|------|
| M1/M2/M3 Mac (16GB+) | Hybrid | Metal加速で全モデル快適に動作 |
| M1 Mac (8GB) | NLLB | LLMはメモリ不足。NLLBなら1.3GBで収まる |
| Windows + RTX 3060+ | Hybrid | CUDA加速。VRAM 8GB以上推奨 |
| Windows + CPU only | NLLB | LLMは非実用的。NLLBのCPU動作で妥協 |
| Windows + AMD Radeon | NLLB (CPU) | ROCm非対応のためGPU使えず |

### OPUS-MT対応言語ペアの注意

| ペア | 状態 | 代替 |
|------|------|------|
| en→ko（英→韓） | HuggingFaceに存在しない | NLLB or en-mul で対応 |
| en→tr（英→土） | HuggingFaceに存在しない | NLLB or en-mul で対応 |
| en→th（英→泰） | 専用モデルなし | en-mul で対応 |
| en→hi（英→印） | 専用モデルなし | en-mul で対応 |
| en→pt（英→葡） | 専用モデルなし | en-mul で対応 |

### ビルド手順

```bash
# macOS .app ビルド
cd ~/dev/pli
pyinstaller PLI.spec --noconfirm
cp -R dist/PLI.app /Applications/

# 開発モードで起動
python main.py --real --engine hybrid
python main.py --real --engine nllb
python main.py                          # モックモード
```

---

© 2025-2026 中野通り法律事務所 弁護士 関智之（東京弁護士会所属）. All rights reserved.
