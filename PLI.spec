# -*- mode: python ; coding: utf-8 -*-
"""
PLI (Private Link Interpreter) — PyInstaller spec file for macOS .app
=====================================================================

Build:
    cd /path/to/pli
    pyinstaller PLI.spec

Output:
    dist/PLI.app

Notes:
    - ML models are NOT bundled (loaded at runtime from ~/pli-models/)
    - data/*.json (phrases, glossary) are bundled
    - Requires macOS 12+ with Apple Silicon for mlx-whisper
"""

import os
import re

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
ROOT_DIR = os.path.abspath(SPECPATH)


def _resolve_path(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(ROOT_DIR, path)


def _read_project_version() -> str:
    pyproject_path = _resolve_path("pyproject.toml")
    if tomllib is not None and os.path.exists(pyproject_path):
        with open(pyproject_path, "rb") as fh:
            project = tomllib.load(fh).get("project", {})
        version = project.get("version")
        if version:
            return version
    if os.path.exists(pyproject_path):
        with open(pyproject_path, "r", encoding="utf-8") as fh:
            match = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.MULTILINE)
        if match:
            return match.group(1)
    return "2.0.0"


APP_VERSION = os.environ.get("PLI_APP_VERSION", _read_project_version())
BUNDLE_IDENTIFIER = os.environ.get("PLI_BUNDLE_ID", "com.seki.pli")
CODESIGN_IDENTITY = os.environ.get("APPLE_SIGN_IDENTITY") or None
ENTITLEMENTS_FILE = os.environ.get("APPLE_ENTITLEMENTS_FILE") or None
if ENTITLEMENTS_FILE:
    ENTITLEMENTS_FILE = _resolve_path(ENTITLEMENTS_FILE)
    if not os.path.exists(ENTITLEMENTS_FILE):
        raise SystemExit(f"APPLE_ENTITLEMENTS_FILE not found: {ENTITLEMENTS_FILE}")

# Collect hidden imports for ML libraries (lazy-loaded)
hiddenimports = [
    # PySide6
    *collect_submodules('PySide6'),
    # Transformers (OPUS-MT, NLLB)
    'transformers',
    'transformers.models.marian',
    'transformers.models.marian.modeling_marian',
    'transformers.models.marian.tokenization_marian',
    'transformers.models.nllb_moe',
    'transformers.models.m2m_100',
    'tokenizers',
    'sentencepiece',
    # CTranslate2
    'ctranslate2',
    # mlx-whisper (Apple Silicon STT)
    'mlx_whisper',
    'mlx',
    'mlx.core',
    'mlx.nn',
    # HuggingFace Hub
    'huggingface_hub',
    # Audio
    'pyaudio',
    # Document export
    'docx',
    'docx.oxml',
    'docx.shared',
    'docx.enum.text',
    'docx.oxml.ns',
    # llama.cpp (optional LLM engine)
    'llama_cpp',
    # pkg_resources / setuptools dependencies
    'jaraco.text',
    'jaraco.functools',
    'jaraco.context',
    'jaraco',
    'platformdirs',
    'pkg_resources',
    *collect_submodules('pkg_resources'),
    *collect_submodules('setuptools'),
]

# Data files to bundle
import mlx
_mlx_dir = mlx.__path__[0]
datas = [
    ('data/*.json', 'data'),
    ('assets/PLI.icns', 'assets'),
    # mlx Metal shader (GPU compute) — PyInstaller doesn't auto-collect .metallib
    (os.path.join(_mlx_dir, 'lib', 'mlx.metallib'), 'mlx/lib'),
]

# Collect transformers data (tokenizer configs etc)
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
        # Exclude heavy packages not needed at runtime
        'matplotlib',
        'scipy',
        'pandas',
        'notebook',
        'jupyter',
        'IPython',
        'pytest',
        'sphinx',
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
    console=False,  # GUI app, no terminal
    disable_windowed_traceback=False,
    argv_emulation=True,  # macOS: support file open events
    target_arch='arm64',  # Apple Silicon
    codesign_identity=CODESIGN_IDENTITY,
    entitlements_file=ENTITLEMENTS_FILE,
    icon='assets/PLI.icns',
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

app = BUNDLE(
    coll,
    name='PLI.app',
    icon='assets/PLI.icns',
    bundle_identifier=BUNDLE_IDENTIFIER,
    info_plist={
        'CFBundleName': 'PLI',
        'CFBundleDisplayName': 'PLI - Private Link Interpreter',
        'CFBundleVersion': APP_VERSION,
        'CFBundleShortVersionString': APP_VERSION,
        'NSMicrophoneUsageDescription': 'PLI needs microphone access for real-time speech-to-text interpretation.',
        'NSHumanReadableCopyright': 'Copyright 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki). All rights reserved.',
        'LSMinimumSystemVersion': '12.0',
        'NSHighResolutionCapable': True,
        'LSApplicationCategoryType': 'public.app-category.productivity',
        # Retina support
        'NSPrincipalClass': 'NSApplication',
        'NSSupportsAutomaticGraphicsSwitching': True,
    },
)
