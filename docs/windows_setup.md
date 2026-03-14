# PLI - Windows 開発環境セットアップガイド

PLI (Private Link Interpreter) を Windows 上で開発・実行するための手順書です。

PLI は元々 macOS (Apple Silicon) 向けに開発されており、音声認識エンジン (mlx-whisper) やハイドモード (osascript) 等に macOS 固有のコードが含まれます。本ガイドでは、Windows で動作させるために必要な変更点と手順を説明します。

---

## 1. 必要なソフトウェア

### 必須

| ソフトウェア | バージョン | 用途 |
|-------------|-----------|------|
| Python | 3.12 推奨 (3.10以上) | ランタイム |
| Git | 最新版 | リポジトリ管理 |
| Visual Studio Build Tools | 2022 | PyAudio のビルドに必要 |

### 推奨（NVIDIA GPU がある場合）

| ソフトウェア | バージョン | 用途 |
|-------------|-----------|------|
| CUDA Toolkit | 12.x | GPU 加速 (faster-whisper, ctranslate2) |
| cuDNN | 9.x (CUDA 12対応版) | GPU 加速ライブラリ |

### インストール手順

#### Python 3.12

1. [python.org](https://www.python.org/downloads/) から Python 3.12 をダウンロード
2. インストーラーを実行し、**「Add Python to PATH」にチェック**を入れてインストール
3. 確認:
   ```
   python --version
   ```

#### Git

1. [git-scm.com](https://git-scm.com/download/win) からダウンロード
2. デフォルト設定でインストール

#### Visual Studio Build Tools

PyAudio のビルドに C++ コンパイラが必要です。

1. [Visual Studio Build Tools 2022](https://visualstudio.microsoft.com/ja/visual-cpp-build-tools/) をダウンロード
2. インストーラーで **「C++ によるデスクトップ開発」** にチェックしてインストール

#### CUDA Toolkit (NVIDIA GPU がある場合のみ)

1. [NVIDIA CUDA Toolkit](https://developer.nvidia.com/cuda-toolkit) からダウンロード
2. インストール後、環境変数を確認:
   ```
   nvcc --version
   ```

---

## 2. リポジトリのクローン

```powershell
cd C:\dev
git clone https://github.com/yutoribengoshi/pli.git
cd pli
```

---

## 3. 仮想環境の作成

```powershell
python -m venv .venv
.venv\Scripts\activate
```

仮想環境を有効化すると、プロンプトの先頭に `(.venv)` が表示されます。

> 以降のコマンドはすべて仮想環境を有効化した状態で実行してください。

---

## 4. 依存関係のインストール（Windows版）

### macOS 版との違い

| macOS (オリジナル) | Windows (代替) | 理由 |
|-------------------|---------------|------|
| `mlx-whisper` | `faster-whisper` | mlx は Apple Silicon 専用。faster-whisper は CTranslate2 ベースで CUDA/CPU 対応 |

### インストール

Windows 用の依存関係ファイルを使用します:

```powershell
pip install -r requirements-windows.txt
```

#### PyAudio のインストールに失敗する場合

PyAudio は PortAudio の C ライブラリに依存しているため、ビルドに失敗することがあります。以下の方法を試してください:

**方法 1: pipwin を使用**
```powershell
pip install pipwin
pipwin install pyaudio
```

**方法 2: 公式ビルド済みホイールを使用**

[Unofficial Windows Binaries](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio) から Python バージョンに合ったホイール (.whl) をダウンロードしてインストール:
```powershell
pip install PyAudio-0.2.14-cp312-cp312-win_amd64.whl
```

#### LLM エンジン（オプション）

LLM モードを使用する場合:
```powershell
pip install llama-cpp-python>=0.2.0
```

NVIDIA GPU を使用する場合は CUDA 対応版:
```powershell
set CMAKE_ARGS=-DGGML_CUDA=on
pip install llama-cpp-python --force-reinstall --no-cache-dir
```

---

## 5. コード修正（macOS 固有部分の対応）

Windows で動作させるには、以下の macOS 固有コードを修正する必要があります。

### 5.1 音声認識エンジン (STT) の差し替え

`core/interpreter.py` の `WhisperSTT` クラスは `mlx_whisper` を使用しています。Windows では `faster-whisper` に置き換える必要があります。

`WhisperSTT` クラス (1307行目付近) を以下のように修正するか、条件分岐を追加します:

```python
import sys

class WhisperSTT:
    """STTエンジン — プラットフォームに応じて自動選択"""

    def __init__(self):
        if sys.platform == "darwin":
            # macOS: mlx-whisper (Apple Silicon GPU加速)
            import mlx_whisper
            self._backend = "mlx"
            self._mlx_whisper = mlx_whisper
            self._repo = "mlx-community/whisper-turbo"
        else:
            # Windows/Linux: faster-whisper (CUDA/CPU)
            from faster_whisper import WhisperModel
            self._backend = "faster"
            self._model = WhisperModel(
                "large-v3-turbo",
                device="cuda",       # GPU がない場合は "cpu"
                compute_type="int8", # GPU: "float16", CPU: "int8"
            )

    def transcribe(self, audio_path: str) -> tuple[str, str]:
        if self._backend == "mlx":
            result = self._mlx_whisper.transcribe(
                audio_path,
                path_or_hf_repo=self._repo,
            )
            text = result.get("text", "")
            lang = result.get("language", "ja")
            return text.strip(), lang
        else:
            segments, info = self._model.transcribe(audio_path)
            text = "".join(seg.text for seg in segments)
            return text.strip(), info.language
```

### 5.2 ハイドモード (hide_mode.py) の対応

`core/hide_mode.py` は macOS 固有の機能（osascript, Dock制御, Quick Look）を使用しています。Windows では以下の修正が必要です:

- `_hide_from_dock()` / `_show_in_dock()`: Windows ではタスクバーからの非表示は Qt のウィンドウフラグで制御
- `_show_dummy()`: `qlmanage` / Finder の代わりに、エクスプローラーや別のアプリケーションを起動
- `_set_process_visibility()`: `osascript` の代わりに Win32 API を使用

最低限の対応として、macOS 固有の部分を `sys.platform` でガードします:

```python
def _hide_from_dock(self):
    if sys.platform != "darwin":
        return  # Windows では何もしない（Qt側で制御）
    # ... 既存のmacOSコード ...

def _show_dummy(self):
    if sys.platform != "darwin":
        return  # Windows では何もしない
    # ... 既存のmacOSコード ...
```

---

## 6. モデルのダウンロード

PLI はモデルファイルを `~/pli-models/` ディレクトリ (Windows: `C:\Users\<ユーザー名>\pli-models\`) に格納します。

### 6.1 Whisper モデル（音声認識）

faster-whisper は初回実行時に自動ダウンロードしますが、事前にダウンロードすることもできます:

```python
from faster_whisper import WhisperModel
model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
```

利用可能なモデルサイズ:

| モデル | サイズ | 精度 | 速度 |
|-------|-------|------|------|
| `tiny` | ~75MB | 低 | 最速 |
| `base` | ~140MB | 中低 | 速い |
| `small` | ~460MB | 中 | 普通 |
| `medium` | ~1.5GB | 中高 | やや遅い |
| `large-v3-turbo` | ~1.6GB | 高 | 普通（推奨） |
| `large-v3` | ~3GB | 最高 | 遅い |

### 6.2 NLLB モデル（翻訳エンジン）

PLI のアプリ内メニューからダウンロードできます。または手動で:

```python
from core.nllb_downloader import download_model

# 推奨: NLLB-200 3.3B int8 (約3.5GB, RAM ~5GB必要)
download_model("nllb-3.3b-int8")

# 軽量版: NLLB-200 1.3B int8 (約1.5GB, RAM ~3GB必要)
download_model("nllb-1.3b-int8")
```

保存先: `~/pli-models/nllb/`

### 6.3 OPUS-MT モデル（翻訳エンジン: ハイブリッドモード）

ハイブリッドモード使用時、OPUS-MT の言語ペアモデルが必要です。アプリ内のメニューからダウンロードできます。

対応言語ペアの例:
- 日本語 ↔ 英語: `Helsinki-NLP/opus-mt-ja-en`, `Helsinki-NLP/opus-mt-en-jap`
- 中国語 ↔ 英語: `Helsinki-NLP/opus-mt-zh-en`, `Helsinki-NLP/opus-mt-en-zh`
- 韓国語 ↔ 英語: `Helsinki-NLP/opus-mt-ko-en`, `Helsinki-NLP/opus-mt-en-ko`
- その他: フランス語, ドイツ語, スペイン語, ポルトガル語, ロシア語, アラビア語, ベトナム語, タイ語, ヒンディー語, トルコ語

保存先: `~/pli-models/opus/`

### 6.4 LLM モデル（オプション）

LLM モードを使用する場合は GGUF 形式のモデルを配置します:

```
~/pli-models/
  ├── your-model.gguf
  ├── nllb/
  └── opus/
```

---

## 7. 起動方法

### モックモード（テスト用・モデル不要）

```powershell
python main.py
```

### 実モデルモード

```powershell
# ハイブリッドモード（推奨: OPUS-MT + NLLBフォールバック）
python main.py --real --engine hybrid

# NLLBモード（軽量）
python main.py --real --engine nllb

# LLMモード
python main.py --real --engine llm --model C:\Users\<ユーザー名>\pli-models\model.gguf
```

### 表示モード

```powershell
# 自動判定（デュアルモニター時は2画面、シングル時は切替）
python main.py --display auto

# 1画面・F3で全画面切替
python main.py --display switch

# 1画面・左右分割
python main.py --display unified

# 2画面モード
python main.py --display dual
```

### 操作キー

| キー | 機能 |
|------|------|
| Ctrl+1 | ハイドモード（非表示・復帰トグル） |
| Ctrl+2 | パニックボタン（全消去） |
| Ctrl+3 | 被疑者画面の表示切替 |
| Ctrl+5 | STT（音声認識）ON/OFF |
| F3 | 全画面切替（switchモード時） |

> macOS では Cmd キーを使用しますが、Windows では Ctrl キーに読み替えてください。

---

## 8. ビルド方法（.exe 化）

### 8.1 PyInstaller のインストール

```powershell
pip install pyinstaller>=6.0 Pillow>=10.0
```

### 8.2 Windows 用 spec ファイルの作成

プロジェクトルートに `PLI-windows.spec` を作成します。既存の `PLI.spec` は macOS 用（BUNDLE, .app, .icns, arm64）のため、Windows 用に修正が必要です:

```python
# -*- mode: python ; coding: utf-8 -*-
"""
PLI (Private Link Interpreter) - PyInstaller spec file for Windows .exe
"""

import os
import re

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))

def _read_project_version() -> str:
    pyproject_path = os.path.join(ROOT_DIR, "pyproject.toml")
    if tomllib is not None and os.path.exists(pyproject_path):
        with open(pyproject_path, "rb") as fh:
            project = tomllib.load(fh).get("project", {})
        version = project.get("version")
        if version:
            return version
    return "2.0.0"

APP_VERSION = os.environ.get("PLI_APP_VERSION", _read_project_version())

hiddenimports = [
    *collect_submodules('PySide6'),
    'transformers',
    'transformers.models.marian',
    'transformers.models.marian.modeling_marian',
    'transformers.models.marian.tokenization_marian',
    'transformers.models.nllb_moe',
    'transformers.models.m2m_100',
    'tokenizers',
    'sentencepiece',
    'ctranslate2',
    # Windows: faster-whisper (mlx_whisper は除外)
    'faster_whisper',
    'huggingface_hub',
    'pyaudio',
    'docx',
    'docx.oxml',
    'docx.shared',
    'docx.enum.text',
    'docx.oxml.ns',
    'llama_cpp',
    'jaraco.text',
    'jaraco.functools',
    'jaraco.context',
    'jaraco',
    'platformdirs',
    'pkg_resources',
    *collect_submodules('pkg_resources'),
    *collect_submodules('setuptools'),
]

datas = [
    ('data/*.json', 'data'),
]

# アイコンファイル（.ico を用意する必要あり）
icon_file = 'assets/PLI.ico' if os.path.exists('assets/PLI.ico') else None

datas += collect_data_files('transformers', include_py_files=False)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'scipy', 'pandas',
        'notebook', 'jupyter', 'IPython',
        'pytest', 'sphinx',
        'mlx', 'mlx_whisper',  # macOS 専用を除外
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PLI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI アプリのためコンソール非表示
    disable_windowed_traceback=False,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PLI',
)
```

### 8.3 アイコンの準備

macOS 用の `.icns` は Windows では使用できません。`.ico` ファイルを用意します:

```powershell
# Pillow を使って変換（PNG がある場合）
python -c "from PIL import Image; Image.open('assets/PLI.png').save('assets/PLI.ico', format='ICO', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
```

### 8.4 ビルド実行

```powershell
pyinstaller PLI-windows.spec
```

出力先: `dist\PLI\PLI.exe`

---

## 9. トラブルシューティング

### Q: `ModuleNotFoundError: No module named 'mlx_whisper'`
A: Windows では `mlx-whisper` は動作しません。`core/interpreter.py` の `WhisperSTT` クラスを `faster-whisper` を使うように修正してください（セクション 5.1 参照）。

### Q: PyAudio のインストールに失敗する
A: Visual Studio Build Tools がインストールされているか確認してください。それでも失敗する場合は `pipwin install pyaudio` を試してください。

### Q: CUDA が認識されない
A: 以下を確認してください:
- CUDA Toolkit がインストールされている
- `nvcc --version` が動作する
- `nvidia-smi` でGPUが表示される
- ctranslate2 が CUDA 対応版であること

### Q: ハイドモード（F1）が動作しない
A: `core/hide_mode.py` は macOS の `osascript` を使用しています。Windows 用の実装が必要です（セクション 5.2 参照）。最低限 `sys.platform` チェックによるガードを入れることでクラッシュを防げます。

### Q: 文字化けが発生する
A: コンソール出力の文字化けは以下で解消できます:
```powershell
chcp 65001
set PYTHONIOENCODING=utf-8
python main.py
```

---

## 10. macOS 版との主な差異まとめ

| 項目 | macOS | Windows |
|------|-------|---------|
| STT エンジン | mlx-whisper (Metal GPU) | faster-whisper (CUDA/CPU) |
| GPU 加速 | Apple Silicon (Metal) | NVIDIA CUDA |
| ハイドモード | osascript + Dock制御 | 要カスタム実装 |
| ダミー表示 | Quick Look (qlmanage) | 要カスタム実装 |
| ビルド成果物 | .app (BUNDLE) | .exe (COLLECT) |
| アイコン | .icns | .ico |
| ショートカット | Cmd+数字 | Ctrl+数字 |
| 設定ディレクトリ | ~/pli-models/ | C:\Users\<user>\pli-models\ |
