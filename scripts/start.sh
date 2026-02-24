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
DAEMON_SESSION="hub-autonomous"        # autonomous_agent.py デーモン用 tmux セッション
LOG_DIR="$PROJECT_DIR/logs"
ENV_FILE="$PROJECT_DIR/.env.autonomous"
DAEMON_LOG="$LOG_DIR/daemon.log"

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

# =============================================================================
# デーモン管理 (autonomous_agent.py - APScheduler 常駐プロセス)
# tmux セッション: hub-autonomous
# =============================================================================

# デーモン起動コマンドを構築（op run 優先、フォールバックで .env 直接 source）
build_daemon_cmd() {
    local python_cmd="python3 $PROJECT_DIR/scripts/autonomous_agent.py"

    # .env ファイル（op ref 形式なしのプレーンな値を想定）を優先
    local env_plain="$PROJECT_DIR/.env"

    if command -v op &>/dev/null && [ -f "$ENV_FILE" ]; then
        # 1Password CLI 経由で環境変数を注入
        echo "op run --env-file='$ENV_FILE' -- $python_cmd"
    elif [ -f "$env_plain" ]; then
        # .env から直接 source して起動
        echo "bash -c 'set -a && source \"$env_plain\" && set +a && $python_cmd'"
    elif [ -f "$ENV_FILE" ]; then
        echo "bash -c 'set -a && source \"$ENV_FILE\" && set +a && $python_cmd'"
    else
        echo "$python_cmd"
    fi
}

start_daemon() {
    mkdir -p "$LOG_DIR"

    if tmux has-session -t "$DAEMON_SESSION" 2>/dev/null; then
        log_warn "デーモンセッション '$DAEMON_SESSION' は既に起動中です"
        return 0
    fi

    log_step "autonomous_agent.py デーモンを起動: tmux:$DAEMON_SESSION ..."

    # Ollama サーバーが起動していなければ起動
    if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
        log_step "Ollama サーバーを起動..."
        ollama serve >>"$LOG_DIR/ollama.log" 2>&1 &
        sleep 3
        if curl -s http://localhost:11434/api/tags &>/dev/null; then
            log_info "Ollama 起動完了"
        else
            log_warn "Ollama 起動未確認（デーモンはClaude APIフォールバックで動作します）"
        fi
    else
        log_info "Ollama 既に稼働中"
    fi

    # tmux セッション作成
    tmux new-session -d -s "$DAEMON_SESSION" -c "$PROJECT_DIR" -x 200 -y 50

    local daemon_cmd
    daemon_cmd=$(build_daemon_cmd)

    # ログリダイレクト付きで起動
    tmux send-keys -t "$DAEMON_SESSION" \
        "$daemon_cmd 2>&1 | tee -a '$DAEMON_LOG'" C-m

    sleep 2

    if tmux has-session -t "$DAEMON_SESSION" 2>/dev/null; then
        log_info "デーモン起動完了 (tmux: $DAEMON_SESSION)"
        echo ""
        echo "  アタッチ: tmux attach -t $DAEMON_SESSION"
        echo "  ログ:     tail -f $DAEMON_LOG"
        echo "  停止:     $0 daemon-stop"
    else
        log_error "デーモンの起動に失敗しました"
        exit 1
    fi
}

stop_daemon() {
    if tmux has-session -t "$DAEMON_SESSION" 2>/dev/null; then
        tmux kill-session -t "$DAEMON_SESSION"
        log_info "デーモン停止完了 ($DAEMON_SESSION)"
    else
        log_warn "デーモンセッション '$DAEMON_SESSION' は起動していません"
    fi
}

show_daemon_status() {
    echo ""
    echo "=== Daemon Status (autonomous_agent.py) ==="
    echo ""

    if tmux has-session -t "$DAEMON_SESSION" 2>/dev/null; then
        log_info "tmux: $DAEMON_SESSION (running)"
        tmux list-panes -t "$DAEMON_SESSION" -F "  Pane #{pane_index}: #{pane_current_command}" 2>/dev/null
    else
        log_warn "tmux: $DAEMON_SESSION (not running)"
    fi

    # Ollama 確認
    if curl -s http://localhost:11434/api/tags &>/dev/null; then
        log_info "Ollama: running"
    else
        log_warn "Ollama: not running"
    fi

    echo ""
    echo "  Log: $DAEMON_LOG"
    if [ -f "$DAEMON_LOG" ]; then
        echo ""
        echo "  --- 最新ログ (5行) ---"
        tail -5 "$DAEMON_LOG" | sed 's/^/  /'
    fi
    echo ""
}

install_cron() {
    # @reboot エントリを crontab に追加
    local daemon_cmd
    daemon_cmd=$(build_daemon_cmd)
    local cron_entry="@reboot sleep 10 && tmux new-session -d -s '$DAEMON_SESSION' -c '$PROJECT_DIR' \"$daemon_cmd 2>&1 | tee -a '$DAEMON_LOG'\""

    if crontab -l 2>/dev/null | grep -q "$DAEMON_SESSION"; then
        log_warn "crontab に既に @reboot エントリが存在します"
        crontab -l | grep "$DAEMON_SESSION"
    else
        (crontab -l 2>/dev/null; echo "$cron_entry") | crontab -
        log_info "@reboot cron エントリを追加しました:"
        echo "  $cron_entry"
    fi
}

remove_cron() {
    if crontab -l 2>/dev/null | grep -q "$DAEMON_SESSION"; then
        crontab -l | grep -v "$DAEMON_SESSION" | crontab -
        log_info "crontab から @reboot エントリを削除しました"
    else
        log_warn "crontab に該当エントリが見つかりません"
    fi
}

show_usage() {
    cat <<EOF
Autonomous Agent Control Script

Usage: $0 <command>

=== Claude Code エージェント管理 ===
  start          Claude Code エージェント起動 (tmux: $SESSION_NAME)
  stop           Claude Code エージェント停止
  restart        再起動
  status         状態確認
  attach         tmux セッションにアタッチ（フル制御）
  watch          tmux セッションを読み取り専用で監視
  logs           起動ログ表示

=== デーモン管理 (autonomous_agent.py) ===
  daemon-start   Python デーモン起動 (tmux: $DAEMON_SESSION)
  daemon-stop    Python デーモン停止
  daemon-restart Python デーモン再起動
  daemon-status  Python デーモン状態確認
  daemon-logs    デーモンログ表示 (tail -f)
  daemon-attach  デーモン tmux セッションにアタッチ

=== cron 管理 (@reboot 自動起動) ===
  cron-install   @reboot cron エントリを追加（OS起動時に自動起動）
  cron-remove    @reboot cron エントリを削除

Environment:
  .env.autonomous  op run 経由で API キーを注入
  .env             op 未使用時のフォールバック

Examples:
  $0 daemon-start          # デーモン起動
  $0 daemon-stop           # デーモン停止
  $0 daemon-status         # 状態確認
  $0 cron-install          # OS起動時に自動起動を有効化
  $0 daemon-logs           # ログをリアルタイム表示
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
    daemon-start)
        start_daemon
        ;;
    daemon-stop)
        stop_daemon
        ;;
    daemon-restart)
        stop_daemon
        sleep 1
        start_daemon
        ;;
    daemon-status)
        show_daemon_status
        ;;
    daemon-logs)
        if [ -f "$DAEMON_LOG" ]; then
            tail -f "$DAEMON_LOG"
        else
            log_warn "ログファイルがありません: $DAEMON_LOG"
        fi
        ;;
    daemon-attach)
        if tmux has-session -t "$DAEMON_SESSION" 2>/dev/null; then
            tmux attach -t "$DAEMON_SESSION"
        else
            log_error "デーモン未起動。Run: $0 daemon-start"
        fi
        ;;
    cron-install)
        install_cron
        ;;
    cron-remove)
        remove_cron
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
