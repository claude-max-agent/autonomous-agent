#!/bin/bash
# =============================================================================
# autonomous-agent セットアップスクリプト
# WSL2 / 新PC 両対応
#
# Usage: ./scripts/setup.sh [--skip-ollama] [--skip-models]
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[✓]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }
log_step()  { echo -e "${BLUE}[→]${NC} $1"; }

SKIP_OLLAMA=false
SKIP_MODELS=false
for arg in "$@"; do
    case "$arg" in
        --skip-ollama) SKIP_OLLAMA=true ;;
        --skip-models) SKIP_MODELS=true ;;
    esac
done

# =============================================================================
# 1. root 確認
# =============================================================================
if [ "$EUID" -eq 0 ]; then
    log_error "root での実行は禁止です"
    exit 1
fi

echo ""
echo "======================================"
echo "  autonomous-agent セットアップ"
echo "======================================"
echo ""

# =============================================================================
# 2. 必須コマンド確認
# =============================================================================
log_step "必須コマンドを確認..."

MISSING=0
for cmd in python3 pip3 git curl; do
    if ! command -v "$cmd" &>/dev/null; then
        log_error "$cmd が見つかりません"
        MISSING=1
    fi
done

if [ "$MISSING" -eq 1 ]; then
    log_error "必須コマンドをインストールしてください:"
    echo "  sudo apt update && sudo apt install -y python3 python3-pip git curl"
    exit 1
fi

log_info "必須コマンド OK"

# Pythonバージョン確認（3.10以上推奨）
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
log_info "Python: ${PY_VERSION}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    log_warn "Python 3.10+ を推奨します (現在: ${PY_VERSION})"
fi

# =============================================================================
# 3. ディレクトリ作成
# =============================================================================
log_step "ディレクトリを作成..."

mkdir -p \
    "$PROJECT_DIR/data/raw/chrome" \
    "$PROJECT_DIR/data/raw/twitter" \
    "$PROJECT_DIR/data/processed" \
    "$PROJECT_DIR/data/embeddings/chromadb" \
    "$PROJECT_DIR/logs"

# .gitkeep を作成（空ディレクトリをgit管理）
touch "$PROJECT_DIR/data/raw/chrome/.gitkeep" 2>/dev/null || true
touch "$PROJECT_DIR/data/raw/twitter/.gitkeep" 2>/dev/null || true
touch "$PROJECT_DIR/data/processed/.gitkeep" 2>/dev/null || true
touch "$PROJECT_DIR/data/embeddings/.gitkeep" 2>/dev/null || true

log_info "ディレクトリ作成完了"

# =============================================================================
# 4. Python 依存パッケージ
# =============================================================================
log_step "Python パッケージをインストール (requirements.txt)..."

# 仮想環境を使用する場合のガイド
if [ -z "${VIRTUAL_ENV:-}" ] && [ ! -d "$PROJECT_DIR/.venv" ]; then
    log_warn "仮想環境が検出されていません。使用を推奨します:"
    echo "  python3 -m venv .venv && source .venv/bin/activate"
    echo "  (このスクリプトはシステムPythonに直接インストールを続けます)"
    echo ""
fi

pip3 install -r "$PROJECT_DIR/requirements.txt" --quiet
log_info "Python パッケージインストール完了"

# =============================================================================
# 5. Ollama インストール
# =============================================================================
if [ "$SKIP_OLLAMA" = false ]; then
    log_step "Ollama を確認..."

    if command -v ollama &>/dev/null; then
        OLLAMA_VER=$(ollama --version 2>/dev/null | head -1 || echo "unknown")
        log_info "Ollama インストール済み: ${OLLAMA_VER}"
    else
        log_step "Ollama をインストール..."
        curl -fsSL https://ollama.com/install.sh | sh
        log_info "Ollama インストール完了"
    fi

    # Ollama サーバー起動確認
    if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
        log_step "Ollama サーバーを起動..."
        ollama serve &>/dev/null &
        OLLAMA_PID=$!
        sleep 3
        if curl -s http://localhost:11434/api/tags &>/dev/null; then
            log_info "Ollama サーバー起動完了 (PID: ${OLLAMA_PID})"
        else
            log_warn "Ollama サーバーの起動を確認できませんでした。手動で起動してください: ollama serve"
        fi
    else
        log_info "Ollama サーバー稼働中"
    fi

    # =============================================================================
    # 6. モデルダウンロード
    # =============================================================================
    if [ "$SKIP_MODELS" = false ]; then
        log_step "LLM モデルを確認..."

        # qwen3:8b の確認・ダウンロード
        if ollama list 2>/dev/null | grep -q "qwen3:8b"; then
            log_info "qwen3:8b インストール済み"
        else
            log_step "qwen3:8b をダウンロード (約5GB)..."
            ollama pull qwen3:8b
            log_info "qwen3:8b ダウンロード完了"
        fi

        # 動作確認
        log_step "qwen3:8b の動作確認..."
        TEST_RESP=$(curl -s -X POST http://localhost:11434/api/generate \
            -H "Content-Type: application/json" \
            -d '{"model":"qwen3:8b","prompt":"テスト","stream":false,"think":false,"options":{"num_predict":5}}' \
            --max-time 60 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('response','ERROR'))" 2>/dev/null || echo "ERROR")

        if [ "$TEST_RESP" != "ERROR" ] && [ -n "$TEST_RESP" ]; then
            log_info "qwen3:8b 動作確認 OK"
        else
            log_warn "qwen3:8b の動作確認に失敗しました。後で確認してください"
        fi
    fi
fi

# =============================================================================
# 7. .env ファイルの作成
# =============================================================================
log_step ".env ファイルを確認..."

ENV_FILE="$PROJECT_DIR/.env"
ENV_EXAMPLE="$PROJECT_DIR/.env.example"

if [ -f "$ENV_FILE" ]; then
    log_info ".env 既存のファイルを使用"
else
    if [ -f "$ENV_EXAMPLE" ]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        log_warn ".env を .env.example からコピーしました"
        log_warn "ANTHROPIC_API_KEY を設定してください:"
        echo "  nano $ENV_FILE"
    else
        # .env.example がなければ最低限のテンプレートを作成
        cat > "$ENV_FILE" <<'ENVEOF'
# autonomous-agent 環境変数
# このファイルは .gitignore 対象です

# Anthropic API キー (必須)
ANTHROPIC_API_KEY=your_api_key_here

# Hub API URL (claude-agent-hub が稼働している場合)
HUB_API_URL=http://localhost:8080

# Discord チャンネルID (Hub API経由で通知)
DISCORD_CHANNEL_ID=1475499842800451616
DIARY_CHANNEL_ID=1475552269222154312

# Ollama 設定
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
ENVEOF
        log_warn ".env を作成しました。ANTHROPIC_API_KEY を設定してください:"
        echo "  nano $ENV_FILE"
    fi
fi

# ANTHROPIC_API_KEY チェック
if grep -q "your_api_key_here" "$ENV_FILE" 2>/dev/null; then
    log_warn "⚠️  ANTHROPIC_API_KEY が未設定です:"
    echo "  nano $ENV_FILE"
fi

# =============================================================================
# 8. ChromaDB 初期化確認
# =============================================================================
log_step "ChromaDB の確認..."

python3 -c "
import chromadb
client = chromadb.PersistentClient(path='$PROJECT_DIR/data/embeddings/chromadb')
cols = client.list_collections()
print(f'  ChromaDB OK ({len(cols)} collections)')
" 2>/dev/null && log_info "ChromaDB 正常" || log_warn "ChromaDB の初期化に問題がある可能性があります"

# =============================================================================
# 9. tmux 確認
# =============================================================================
log_step "tmux を確認..."
if command -v tmux &>/dev/null; then
    log_info "tmux: $(tmux -V)"
else
    log_warn "tmux が見つかりません。インストールしてください:"
    echo "  sudo apt install -y tmux"
fi

# =============================================================================
# 完了
# =============================================================================
echo ""
echo "======================================"
log_info "セットアップ完了！"
echo "======================================"
echo ""
echo "  次のステップ:"
echo ""

if grep -q "your_api_key_here" "$ENV_FILE" 2>/dev/null; then
    echo "  1. API キーを設定:"
    echo "     nano $ENV_FILE"
    echo ""
fi

echo "  2. エージェントを起動:"
echo "     ./scripts/start.sh start"
echo ""
echo "  3. テスト実行 (1回だけ即時実行):"
echo "     source .env && RUN_NOW=1 python3 scripts/autonomous_agent.py"
echo ""
echo "  4. Chrome履歴をインポート (オプション):"
echo "     # data/raw/chrome/<device-name>/ に History ファイルを配置後:"
echo "     python3 scripts/import_chrome.py"
echo ""
echo "  詳細: docs/ARCHITECTURE.md"
echo ""
