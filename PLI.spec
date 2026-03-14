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

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

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
datas = [
    ('data/*.json', 'data'),
    ('assets/PLI.icns', 'assets'),
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
    codesign_identity=None,
    entitlements_file=None,
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
    bundle_identifier='com.seki.pli',
    info_plist={
        'CFBundleName': 'PLI',
        'CFBundleDisplayName': 'PLI - Private Link Interpreter',
        'CFBundleVersion': '2.0.0',
        'CFBundleShortVersionString': '2.0.0',
        'NSMicrophoneUsageDescription': 'PLI needs microphone access for real-time speech-to-text interpretation.',
        'NSHumanReadableCopyright': 'Copyright 2025 Tomoyuki Seki. All rights reserved.',
        'LSMinimumSystemVersion': '12.0',
        'NSHighResolutionCapable': True,
        'LSApplicationCategoryType': 'public.app-category.productivity',
        # Retina support
        'NSPrincipalClass': 'NSApplication',
        'NSSupportsAutomaticGraphicsSwitching': True,
    },
)
