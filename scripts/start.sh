#!/bin/bash

# Autonomous Agent - Startup Script
# Usage: ./scripts/start.sh [start|stop|restart|status|attach|watch|logs]
#
# 環境変数注入: op run --env-file=.env.autonomous 経由で ANTHROPIC_API_KEY を注入
# Claude Max プランを使用して tmux セッションで自律エージェントを起動する

# NOTE: set -e を意図的に使用しない
# (nohup / バックグラウンド実行時に予期しない終了を防ぐため)

# root での実行禁止
if [ "$EUID" -eq 0 ] || [ -n "$SUDO_USER" ]; then
    echo "ERROR: Do not run as root/sudo!"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SESSION_NAME="autonomous-agent"
LOG_DIR="$PROJECT_DIR/logs"
ENV_FILE="$PROJECT_DIR/.env.autonomous"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

STARTUP_LOG="$LOG_DIR/startup.log"

log_info()  { echo -e "${GREEN}[✓]${NC} $1"; echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $1" >> "$STARTUP_LOG" 2>/dev/null || true; }
log_warn()  { echo -e "${YELLOW}[!]${NC} $1"; echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] $1" >> "$STARTUP_LOG" 2>/dev/null || true; }
log_error() { echo -e "${RED}[✗]${NC} $1"; echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $1" >> "$STARTUP_LOG" 2>/dev/null || true; }
log_step()  { echo -e "${BLUE}[→]${NC} $1"; echo "[$(date '+%Y-%m-%d %H:%M:%S')] [STEP] $1" >> "$STARTUP_LOG" 2>/dev/null || true; }

ensure_dirs() {
    mkdir -p "$LOG_DIR"
}

check_prereqs() {
    local missing=0

    if ! command -v tmux &>/dev/null; then
        log_error "tmux not installed"
        missing=1
    fi

    if ! command -v claude &>/dev/null; then
        log_error "Claude Code not installed"
        missing=1
    fi

    if [ ! -f "$ENV_FILE" ]; then
        log_warn ".env.autonomous not found (create from .env.autonomous.example)"
        log_warn "  cp .env.autonomous.example .env.autonomous"
        log_warn "  # ANTHROPIC_API_KEY を設定してください"
    fi

    return $missing
}

# op run が使える場合は op run 経由で環境変数を注入、使えない場合は .env.autonomous を直接 source
build_claude_cmd() {
    local base_cmd="claude --dangerously-skip-permissions"

    if command -v op &>/dev/null && [ -f "$ENV_FILE" ]; then
        # 1Password CLI 経由: op ref や op:// 形式の値を解決してから実行
        echo "op run --env-file='$ENV_FILE' -- $base_cmd"
    elif [ -f "$ENV_FILE" ]; then
        # op が使えない場合は直接 source して実行
        log_warn "1Password CLI (op) not found. Using .env.autonomous directly."
        set -a
        # shellcheck disable=SC1090
        source "$ENV_FILE"
        set +a
        echo "$base_cmd"
    else
        echo "$base_cmd"
    fi
}

start_agent() {
    ensure_dirs
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Startup ===" > "$STARTUP_LOG"

    check_prereqs || { log_error "Prerequisites check failed"; exit 1; }

    # 既存セッションを終了
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

    log_step "Creating tmux session: $SESSION_NAME ..."
    tmux new-session -d -s "$SESSION_NAME" -c "$PROJECT_DIR" -x 220 -y 50
    tmux rename-window -t "$SESSION_NAME:0" "agent"

    # 環境変数のセット
    tmux send-keys -t "$SESSION_NAME:0" "export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1" C-m
    tmux send-keys -t "$SESSION_NAME:0" "cd $PROJECT_DIR" C-m
    sleep 0.5

    # .env.autonomous を source（op 未使用時のフォールバック）
    if [ -f "$ENV_FILE" ] && ! command -v op &>/dev/null; then
        tmux send-keys -t "$SESSION_NAME:0" "set -a && source '$ENV_FILE' && set +a" C-m
        sleep 0.3
    fi

    # Claude 起動コマンドを構築
    local claude_cmd
    claude_cmd=$(build_claude_cmd)

    local init_message="あなたは autonomous-agent です。docs/architecture.md を読んで設計を理解してください。現在は Phase 0 です。Admin からの指示を待機してください。"

    log_step "Starting Claude Code agent..."
    tmux send-keys -t "$SESSION_NAME:0" "$claude_cmd '$init_message'" C-m

    # 起動待機
    log_step "Waiting for Claude Code to start..."
    local retries=30
    local ready=false
    while [ $retries -gt 0 ] && [ "$ready" = "false" ]; do
        local pane_content
        pane_content=$(tmux capture-pane -t "$SESSION_NAME:0" -p -S -5 2>/dev/null) || true
        if echo "$pane_content" | grep -qiE "(bypass|claude|>|╭─)" 2>/dev/null; then
            ready=true
        else
            sleep 2
            ((retries--))
        fi
    done

    if [ "$ready" = "true" ]; then
        log_info "Autonomous Agent started!"
    else
        log_warn "Agent may not have started properly (timeout). Check: tmux attach -t $SESSION_NAME"
    fi

    echo ""
    echo "======================================"
    log_info "Autonomous Agent is running"
    echo "======================================"
    echo ""
    echo "  Attach:  tmux attach -t $SESSION_NAME"
    echo "  Watch:   tmux attach -t $SESSION_NAME -r"
    echo "  Stop:    $0 stop"
    echo "  Log:     $0 logs"
    echo ""
}

stop_agent() {
    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        tmux kill-session -t "$SESSION_NAME"
        log_info "Autonomous Agent stopped"
    else
        log_warn "Session '$SESSION_NAME' not running"
    fi
}

show_status() {
    echo ""
    echo "=== Autonomous Agent Status ==="
    echo ""

    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        log_info "tmux session: $SESSION_NAME (running)"
        tmux list-panes -t "$SESSION_NAME" -F "  Pane #{pane_index}: #{pane_current_command}" 2>/dev/null
    else
        log_warn "tmux session: not running"
    fi

    echo ""
    echo "  Project: $PROJECT_DIR"
    echo "  Env:     $ENV_FILE"
    echo "  Log:     $STARTUP_LOG"
    echo ""
}

show_logs() {
    if [ -f "$STARTUP_LOG" ]; then
        tail -50 "$STARTUP_LOG"
    else
        log_warn "No startup log found"
    fi
}

show_usage() {
    cat <<EOF
Autonomous Agent Control Script

Usage: $0 <command>

Commands:
  start     Start the autonomous agent (tmux session: $SESSION_NAME)
  stop      Stop the agent
  restart   Stop and restart
  status    Show session status
  attach    Attach to agent tmux session (full control)
  watch     Watch agent session read-only
  logs      Show startup logs

Environment:
  .env.autonomous  API キーなどの環境変数ファイル
                   op run --env-file=.env.autonomous 経由で注入される

Examples:
  $0 start          # エージェント起動
  $0 stop           # エージェント停止
  $0 attach         # tmux セッションにアタッチ
  $0 status         # 状態確認
EOF
}

# Main
case "${1:-}" in
    start)
        start_agent
        ;;
    stop)
        stop_agent
        ;;
    restart)
        stop_agent
        sleep 1
        start_agent
        ;;
    status)
        show_status
        ;;
    attach)
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            tmux attach -t "$SESSION_NAME"
        else
            log_error "Session not running. Run: $0 start"
        fi
        ;;
    watch)
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            log_info "Attaching in read-only mode (Ctrl+b d to detach)"
            tmux attach -t "$SESSION_NAME" -r
        else
            log_error "Session not running. Run: $0 start"
        fi
        ;;
    logs)
        show_logs
        ;;
    *)
        show_usage
        ;;
esac
