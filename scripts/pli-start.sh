#!/bin/bash
# ============================================================
# PLI ワンコマンド起動スクリプト（接見用）
#
# 使い方:
#   ./scripts/pli-start.sh              # 標準: Qwen3.5-9B（高速・推奨）
#   ./scripts/pli-start.sh quality      # 高精度: Qwen2.5-72B（要64GB）
#   ./scripts/pli-start.sh stop         # サーバー・アプリ停止
#
# llama-server を起動 → ヘルスチェック → PLIアプリを起動。
# 翻訳サーバーが落ちている間は翻訳できないため、このスクリプトが
# 起動を保証する。
#
# Copyright (c) 2025-2026 中野通り法律事務所 弁護士 関智之
# ============================================================
set -euo pipefail

PLI_DIR="$HOME/dev/pli"
MODELS_DIR="$HOME/models"
LLAMA_SERVER="/opt/homebrew/bin/llama-server"
PY="$HOME/.pyenv/versions/3.12.2/bin/python3"
PORT=8000
LOG="/tmp/pli-llama-server.log"

# --- モデル定義 ---
MODEL_FAST="$MODELS_DIR/Qwen3.5-9B-Q4_K_M.gguf"          # 5.3GB 0.5秒/文 16GB機
MODEL_QUALITY="$MODELS_DIR/Qwen2.5-72B-Instruct-Q4_K_M.gguf"  # 44GB 4-7秒/文 64GB機

cmd="${1:-fast}"

stop_all() {
    echo "停止中..."
    pkill -f "main.py --real" 2>/dev/null || true
    pkill -f "llama-server.*--port $PORT" 2>/dev/null || true
    echo "✅ 停止しました"
}

if [ "$cmd" = "stop" ]; then
    stop_all
    exit 0
fi

# モデル選択
if [ "$cmd" = "quality" ]; then
    MODEL="$MODEL_QUALITY"; CTX=4096; LABEL="Qwen2.5-72B（高精度）"
else
    MODEL="$MODEL_FAST";    CTX=4096; LABEL="Qwen3.5-9B（高速・推奨）"
fi

if [ ! -f "$MODEL" ]; then
    echo "❌ モデルが見つかりません: $MODEL"
    echo "   利用可能なモデル:"
    ls -1 "$MODELS_DIR"/*.gguf 2>/dev/null | sed 's/^/     /' || echo "     (なし)"
    exit 1
fi

# 既存サーバー停止
pkill -f "llama-server.*--port $PORT" 2>/dev/null || true
sleep 1

echo "════════════════════════════════════════"
echo " PLI 起動: $LABEL"
echo "════════════════════════════════════════"
echo "1) 翻訳サーバーを起動中（モデル読込に数分かかります）..."

PLI_LLM_PORT=$PORT "$LLAMA_SERVER" \
    --model "$MODEL" \
    --port $PORT --host 127.0.0.1 \
    --ctx-size $CTX --cache-type-k q4_0 --cache-type-v q4_0 \
    --no-mmap -np 1 -t 8 --n-gpu-layers 99 --flash-attn on \
    > "$LOG" 2>&1 &

# ヘルスチェック待ち（最大5分）
echo -n "   準備中"
for i in $(seq 1 100); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/health 2>/dev/null)" = "200" ]; then
        echo " → ✅ 準備完了"
        break
    fi
    echo -n "."
    sleep 3
done

if [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/health 2>/dev/null)" != "200" ]; then
    echo ""
    echo "❌ サーバーが起動しませんでした。ログ: $LOG"
    tail -5 "$LOG"
    exit 1
fi

echo "2) PLIアプリを起動中..."
cd "$PLI_DIR"
PLI_LLM_PORT=$PORT "$PY" main.py --real --engine llm --model "$MODEL" &

sleep 3
echo ""
echo "════════════════════════════════════════"
echo " ✅ 起動完了"
echo "════════════════════════════════════════"
echo " 翻訳: $LABEL"
echo " 音声認識: Whisper-turbo"
echo " 辞書: 法律用語4,339語"
echo ""
echo " ⚠️  このターミナルは閉じないでください"
echo "     （閉じると翻訳サーバーが止まります）"
echo ""
echo " 終了するには: ./scripts/pli-start.sh stop"
echo "────────────────────────────────────────"
echo " 免責: 本ソフトウェアの利用は自己責任です。"
echo " 機械翻訳には誤訳リスクがあります。重要な"
echo " 場面では人間の通訳人の確認を併用してください。"
echo "════════════════════════════════════════"

# サーバープロセスを前面に保持（Ctrl-Cで全停止）
trap stop_all INT TERM
wait
