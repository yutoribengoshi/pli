"""
PLI LLM Engine - llama-server (OpenAI互換API) ベースのLLMエンジン
Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之 (Tomoyuki Seki)
All rights reserved.
"""

import os
import subprocess
import threading
from typing import Callable, Optional

from core.logging_setup import get_logger
from core.models import SyntaxChunk
from core.lang_utils import (
    get_language_name,
    make_translate_system,
    make_syntax_check_system,
    RECONSTRUCT_SYSTEM,
)

logger = get_logger(__name__)


class LLMEngine:
    """llama-server (OpenAI互換API) ベースのLLMエンジン

    ユニバーサルソケット方式: llama-server を独立プロセスで起動し、
    HTTP API 経由で通信する。メモリはサーバー停止時に全解放。
    METIS・証拠ビューア等からも同じサーバーを共有可能。

    ティア別構成:
      Lite   (8GB):  LLMなし → NLLB + OPUS のみ
      Standard(16GB): Qwen3-8B-Q4_K_M (~5GB)
      Pro    (32GB+): Qwen3.5-35B-A3B-IQ2_M (~11GB, MoE 3B活性)
      Max    (64GB+): Qwen3-235B-A22B-Q2_K_L (~58GB, MoE 22B活性)
    """

    # ティア別モデル定義
    TIERS = {
        # --- macOS (Apple Silicon, Metal GPU, 統合メモリ) ---
        "standard": {
            "model": "Qwen3-8B-Q4_K_M.gguf",
            "min_memory_gb": 16,
            "ctx_size": 2048,
            "threads": 4,
            "gpu_layers": 99,
            "description": "Standard (16GB Mac)",
        },
        "pro": {
            "model": "Qwen3.5-35B-A3B-UD-IQ2_M.gguf",
            "min_memory_gb": 32,
            "ctx_size": 4096,
            "threads": 4,
            "gpu_layers": 99,
            "description": "Pro (32GB+ Mac, MoE 3B active)",
        },
        "max": {
            "model": "Qwen3-235B-A22B-Q2_K_L-00001-of-00002.gguf",
            "min_memory_gb": 64,
            "ctx_size": 8192,
            "threads": 4,
            "gpu_layers": 99,
            "description": "Max (64GB+ Mac, MoE 22B active)",
        },
        # --- Windows (CPU推論 or CUDA) ---
        "win_low": {
            "model": "Qwen3-4B-Q4_K_M.gguf",
            "min_memory_gb": 16,
            "ctx_size": 2048,
            "threads": 4,
            "gpu_layers": 0,
            "description": "Windows Low (16GB, CPU-only)",
        },
        "win_mid": {
            "model": "Qwen3-8B-Q4_K_M.gguf",
            "min_memory_gb": 16,
            "ctx_size": 4096,
            "threads": 6,
            "gpu_layers": 0,
            "description": "Windows Mid (16GB, AVX-512)",
        },
        "win_high": {
            "model": "Qwen3-32B-Q4_K_M.gguf",
            "min_memory_gb": 32,
            "ctx_size": 4096,
            "threads": 8,
            "gpu_layers": 0,
            "description": "Windows High (32GB+)",
        },
        "win_cuda": {
            "model": "Qwen3-8B-Q4_K_M.gguf",
            "min_memory_gb": 16,
            "ctx_size": 4096,
            "threads": 4,
            "gpu_layers": 99,
            "description": "Windows CUDA (NVIDIA GPU 8GB+)",
        },
    }

    def __init__(self, model_path: str = "", n_ctx: int = 2048,
                 api_base: str = ""):
        import json as _json
        self._json = _json
        self._model_path = model_path
        self._n_ctx = n_ctx
        if not api_base:
            # ポートは環境変数 PLI_LLM_PORT で変更可能（デフォルト 8000）
            port = os.environ.get("PLI_LLM_PORT", "8000")
            api_base = f"http://127.0.0.1:{port}"
        self._api_base = api_base.rstrip("/")
        self._server_process: Optional[subprocess.Popen] = None
        self._ready = False
        self._loading = False
        self._load_error: Optional[str] = None
        # llama-cpp-python 互換: 既存GGUFがあればフォールバック用に保持
        self._llm = None
        self._use_api = True  # デフォルトでAPI方式

    @staticmethod
    def _has_avx512() -> bool:
        """AVX-512対応チェック"""
        try:
            import cpuinfo
            flags = cpuinfo.get_cpu_info().get('flags', [])
            return 'avx512f' in flags
        except Exception:
            return False

    @staticmethod
    def _has_nvidia_gpu() -> bool:
        """NVIDIA GPU (CUDA) の利用可否"""
        try:
            import ctranslate2
            return "cuda" in ctranslate2.get_supported_compute_types("cuda")
        except Exception:
            return False

    @staticmethod
    def detect_tier() -> tuple[str, int]:
        """搭載メモリ・OS・CPU/GPUから推奨ティアを自動検出

        Returns:
            (tier_name, total_memory_gb)
        """
        import platform
        os_name = platform.system()
        total_gb = 0

        if os_name == "Darwin":
            try:
                import subprocess as sp
                result = sp.run(["sysctl", "-n", "hw.memsize"],
                                capture_output=True, text=True)
                total_gb = int(result.stdout.strip()) // (1024 ** 3)
            except Exception:
                total_gb = 16
            # macOS (Apple Silicon) — 統合メモリ、Metal GPU
            if total_gb >= 64:
                return "max", total_gb
            elif total_gb >= 32:
                return "pro", total_gb
            elif total_gb >= 16:
                return "standard", total_gb
            else:
                return "lite", total_gb

        else:
            # Windows / Linux
            try:
                import psutil
                total_gb = psutil.virtual_memory().total // (1024 ** 3)
            except ImportError:
                total_gb = 16

            # NVIDIA GPUが使えるなら最優先
            if LLMEngine._has_nvidia_gpu():
                return "win_cuda", total_gb

            # CPU推論 — RAM + AVX命令セットで判定
            avx512 = LLMEngine._has_avx512()
            if total_gb >= 32:
                return "win_high", total_gb
            elif total_gb >= 16:
                if avx512:
                    return "win_mid", total_gb  # AVX-512: Qwen3-8B OK
                else:
                    return "win_low", total_gb  # AVX2: Qwen3-4B が安全
            else:
                return "lite", total_gb

    @staticmethod
    def find_llama_server() -> Optional[str]:
        """llama-server バイナリを探す (macOS/Windows両対応)

        環境変数 PLI_MODELS_DIR が設定されていればそのディレクトリを最優先。
        """
        import shutil, platform
        env_dir = os.environ.get("PLI_MODELS_DIR")
        candidates = []
        if platform.system() == "Darwin":
            if env_dir:
                candidates.append(
                    os.path.join(os.path.expanduser(env_dir), "llama-server"))
            candidates += [
                shutil.which("llama-server"),
                "/opt/homebrew/bin/llama-server",
                "/usr/local/bin/llama-server",
                os.path.expanduser("~/pli-models/llama-server"),
            ]
        else:
            # Windows: llama-server.exe
            if env_dir:
                candidates.append(
                    os.path.join(os.path.expanduser(env_dir), "llama-server.exe"))
            candidates += [
                shutil.which("llama-server"),
                shutil.which("llama-server.exe"),
                os.path.expanduser("~/pli-models/llama-server.exe"),
                r"C:\llama.cpp\build\bin\Release\llama-server.exe",
            ]
        for c in candidates:
            if c and os.path.isfile(c) and os.access(c, os.X_OK):
                return c
        return None

    def _find_model_path(self) -> Optional[str]:
        """ティアに応じたモデルファイルを探す

        探索ディレクトリは環境変数 PLI_MODELS_DIR が設定されていればそれを優先、
        未設定なら ~/pli-models。
        """
        if self._model_path and os.path.isfile(self._model_path):
            return self._model_path
        models_dir = os.path.expanduser(
            os.environ.get("PLI_MODELS_DIR") or "~/pli-models")
        # ティア順に大きいモデルを優先探索
        for tier_name in ["max", "pro", "standard"]:
            tier = self.TIERS[tier_name]
            path = os.path.join(models_dir, tier["model"])
            if os.path.isfile(path):
                self._n_ctx = tier["ctx_size"]
                logger.info("llm: ティア検出: %s", tier["description"])
                return path
        # 既存の Qwen2.5-32B にフォールバック
        legacy = os.path.join(models_dir, "Qwen2.5-32B-Instruct-Q6_K.gguf")
        if os.path.isfile(legacy):
            logger.info("llm: レガシーモデル検出: Qwen2.5-32B-Q6_K")
            return legacy
        return None

    def start_server(self) -> bool:
        """llama-server をバックグラウンドで起動"""
        # 既にサーバーが応答するか確認
        if self._health_check():
            logger.info("llm: 既存の llama-server に接続")
            self._ready = True
            return True

        server_bin = self.find_llama_server()
        if not server_bin:
            logger.warning("llm: llama-server が見つかりません (brew install llama.cpp)")
            return False

        model_path = self._find_model_path()
        if not model_path:
            logger.warning("llm: LLMモデルファイルが見つかりません")
            return False

        # ティア情報からパラメータ取得
        tier_name, _ = self.detect_tier()
        tier_info = self.TIERS.get(tier_name, {})
        threads = str(tier_info.get("threads", 4))
        gpu_layers = tier_info.get("gpu_layers", 0)

        # llama-server 起動コマンド（メモリ最適化オプション付き）
        cmd = [
            server_bin,
            "--model", model_path,
            "--port", self._api_base.split(":")[-1],
            "--host", "127.0.0.1",
            "--ctx-size", str(self._n_ctx),
            "--cache-type-k", "q4_0",             # KVキャッシュ量子化: メモリ1/4
            "--cache-type-v", "q4_0",
            "--no-mmap",                          # F_NOCACHE相当: バッファキャッシュ回避
            "-np", "1",                           # 並列リクエスト数
            "-t", threads,                        # ティア別スレッド数
        ]
        # GPU対応時のみGPUオプション追加
        if gpu_layers > 0:
            cmd += ["--n-gpu-layers", str(gpu_layers)]
            cmd += ["--flash-attn"]                    # Flash Attention: GPUピークメモリ半減
        logger.info("llm: ティア: %s, スレッド: %s, GPU層: %s",
                    tier_name, threads, gpu_layers)
        logger.info("llm: llama-server 起動中: %s", os.path.basename(model_path))
        try:
            self._server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            logger.error("llm: llama-server 起動失敗: %s", e)
            return False

        # サーバー起動待ち（最大60秒）
        import time as _time
        for i in range(120):
            if self._server_process.poll() is not None:
                stderr = self._server_process.stderr.read().decode(errors="replace")
                self._server_process.stderr.close()
                logger.error("llm: llama-server が異常終了: %s", stderr[:500])
                return False
            if self._health_check():
                logger.info("llm: llama-server 起動完了 (%.1f秒)", (i + 1) * 0.5)
                self._ready = True
                return True
            _time.sleep(0.5)

        logger.error("llm: llama-server 起動タイムアウト (60秒)")
        self.stop_server()
        return False

    def stop_server(self):
        """llama-server を停止してメモリ解放"""
        if self._server_process is not None:
            if self._server_process.stderr:
                self._server_process.stderr.close()
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
            self._server_process = None
            self._ready = False
            logger.info("llm: llama-server 停止 → メモリ解放")

    def _health_check(self) -> bool:
        """サーバーの到達性チェック"""
        import urllib.request
        try:
            req = urllib.request.Request(f"{self._api_base}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def load_model_async(self, on_done: Optional[Callable] = None):
        """バックグラウンドでサーバー起動（API方式）またはモデルロード（レガシー）"""
        self._loading = True

        def _load():
            try:
                success = self.start_server()
                if not success:
                    # フォールバック: llama-cpp-python で直接ロード
                    model_path = self._find_model_path()
                    if model_path:
                        logger.info("llm: llama-server 不可 → llama-cpp-python にフォールバック")
                        self._use_api = False
                        from llama_cpp import Llama
                        self._llm = Llama(
                            model_path=model_path,
                            n_ctx=self._n_ctx,
                            n_gpu_layers=-1,
                            n_threads=10,
                            verbose=False,
                        )
                        self._ready = True
                        logger.info("llm: LLMモデルのロード完了 (n_ctx=%d)", self._n_ctx)
                    else:
                        self._load_error = "モデルファイルが見つかりません"
            except Exception as e:
                self._load_error = str(e)
                logger.error("llm: LLMロード失敗: %s", e)
            finally:
                self._loading = False
                if on_done:
                    on_done()

        t = threading.Thread(target=_load, daemon=True)
        t.start()

    @property
    def is_ready(self) -> bool:
        return self._ready or self._llm is not None

    def _ensure_loaded(self):
        """サーバー接続またはモデルが準備できていない場合は待機"""
        if self._ready or self._llm is not None:
            return
        if self._loading:
            import time as _time
            while self._loading:
                _time.sleep(0.1)
        if not self._ready and self._llm is None and not self._load_error:
            # 最終手段: 同期でサーバー起動を試みる
            self.start_server()

    def _chat(self, system: str, user: str, max_tokens: int = 256, stream: bool = False):
        self._ensure_loaded()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        # API方式（推奨）
        if self._use_api and self._ready:
            return self._chat_api(messages, max_tokens, stream)

        # レガシー: llama-cpp-python 直接
        if self._llm is not None:
            if stream:
                return self._llm.create_chat_completion(
                    messages=messages, max_tokens=max_tokens, temperature=0.1, stream=True
                )
            resp = self._llm.create_chat_completion(
                messages=messages, max_tokens=max_tokens, temperature=0.1
            )
            return resp["choices"][0]["message"]["content"].strip()

        raise RuntimeError("LLMモデルが利用できません")

    def _chat_api(self, messages: list, max_tokens: int = 256, stream: bool = False):
        """HTTP API 経由で llama-server に問い合わせ"""
        import urllib.request
        payload = self._json.dumps({
            "model": "local",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "stream": stream,
            # Qwen3.5/3.6 等の思考(reasoning)モデルでは思考を無効化する。
            # これがないと翻訳本文が空になり長考でタイムアウトする。
            # Qwen2.5 等の非思考モデルでは無視されるため無害。
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode()
        req = urllib.request.Request(
            f"{self._api_base}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        if stream:
            return self._stream_api(req)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = self._json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip()

    def _stream_api(self, req):
        """SSE ストリーミング応答をチャンク生成"""
        import urllib.request
        resp = urllib.request.urlopen(req, timeout=60)
        buffer = ""
        for line_bytes in resp:
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = self._json.loads(data_str)
                yield chunk
            except self._json.JSONDecodeError:
                continue
        resp.close()

    def _inject_glossary(self, text: str, src_lang: str, user_msg: str) -> str:
        """入力文に出現した法律用語の正式訳を user メッセージ先頭に注入する。

        systemプロンプトは不変に保つ（prefixキャッシュ保全＝レイテンシ対策）。
        当面 ja 起点のみ対応。辞書未配置・未マッチ・例外時は素通り。
        """
        if src_lang != "ja":
            return user_msg
        try:
            from core.legal_dict import retrieve_terms, format_glossary_for_prompt
            block = format_glossary_for_prompt(retrieve_terms(text, max_terms=8))
        except Exception:
            return user_msg
        if not block:
            return user_msg
        return f"{block}\n\n{user_msg}"

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        src_name = "日本語" if src_lang == "ja" else get_language_name(src_lang)
        tgt_name = "日本語" if tgt_lang == "ja" else get_language_name(tgt_lang)
        user_msg = f"{src_name}を{tgt_name}に翻訳:\n{text}"
        user_msg = self._inject_glossary(text, src_lang, user_msg)
        system = make_translate_system(tgt_lang)
        return self._chat(system, user_msg)

    def translate_stream(self, text: str, src_lang: str, tgt_lang: str, callback: Callable[[str], None]):
        src_name = "日本語" if src_lang == "ja" else get_language_name(src_lang)
        tgt_name = "日本語" if tgt_lang == "ja" else get_language_name(tgt_lang)
        user_msg = f"{src_name}を{tgt_name}に翻訳:\n{text}"
        user_msg = self._inject_glossary(text, src_lang, user_msg)
        system = make_translate_system(tgt_lang)
        for chunk in self._chat(system, user_msg, stream=True):
            delta = chunk["choices"][0]["delta"].get("content", "")
            if delta:
                callback(delta)

    def syntax_check(self, foreign_text: str, lang: str = "en") -> list[SyntaxChunk]:
        lang_name = get_language_name(lang)
        user_msg = f"{lang_name}文: {foreign_text}"
        system = make_syntax_check_system(lang)
        result = self._chat(system, user_msg, max_tokens=512)
        try:
            data = self._json.loads(result)
            return [
                SyntaxChunk(
                    english=item.get("original", item.get("english", "")),
                    japanese=item.get("japanese", ""),
                    index=i,
                )
                for i, item in enumerate(data)
            ]
        except (self._json.JSONDecodeError, KeyError):
            return [SyntaxChunk(english=foreign_text, japanese="[解析失敗]", index=0)]

    def reconstruct(self, chunks: list[SyntaxChunk]) -> str:
        table = "\n".join(f"{c.english} → {c.japanese}" for c in chunks)
        user_msg = f"対訳テーブル:\n{table}"
        return self._chat(RECONSTRUCT_SYSTEM, user_msg)
