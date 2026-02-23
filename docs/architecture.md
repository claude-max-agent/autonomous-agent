# アーキテクチャ設計

## 1. 自律ループ設計パターン

### 概要

自律エージェントの核心は「**自己トリガーのデーモンループ**」。外部からのイベント（Discord メッセージ、cron ジョブ等）を待つのではなく、エージェント自身が環境を観察し行動を決定する。

### パターン比較

| パターン | 概要 | 適性 |
|----------|------|------|
| **ReAct Loop** | Reasoning + Acting を交互に繰り返す | 汎用的・最も標準的 |
| **Reflection Loop** | 出力を自己評価し改善する | 品質重視のタスク |
| **PRA Cycle** | Plan → Reflect → Act の3フェーズ | 計画段階での慎重な判断 |
| **Evaluate-Select-Revise** | 複数候補を生成→評価→選択→改善 | 創造的タスク |

### 推奨: ReAct Loop + Reflection

```
┌─────────────────────────────────────────────────┐
│              Autonomous Agent Loop               │
│                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ Observe  │───▶│  Think   │───▶│   Act    │  │
│  │          │    │(Reason)  │    │          │  │
│  │ - GitHub │    │- 優先度  │    │- Issue   │  │
│  │ - コード  │    │- 実行計画│    │- PR作成  │  │
│  │ - トレンド│    │- リスク  │    │- 通知    │  │
│  └──────────┘    └──────────┘    └──────────┘  │
│       ▲                               │         │
│       │          ┌──────────┐         │         │
│       └──────────│ Reflect  │◀────────┘         │
│                  │          │                    │
│                  │- 結果評価│                    │
│                  │- 改善点  │                    │
│                  └──────────┘                    │
│                       │                          │
│                  ┌──────────┐                    │
│                  │  Sleep   │                    │
│                  │(interval)│                    │
│                  └──────────┘                    │
└─────────────────────────────────────────────────┘
```

### 動機生成メカニズム

エージェントが「何をすべきか」を自発的に発見するための仕組み:

| メカニズム | 概要 | 実装例 |
|-----------|------|--------|
| **Curiosity-driven (ICM)** | 予測誤差が大きい領域を探索 | 新しいGitHub Issueの自動発見 |
| **Epistemic Curiosity** | 知識の不足・矛盾を検出 | コードカバレッジの低い領域を特定 |
| **Empowerment-based** | 環境への影響力を最大化 | 最もインパクトのある改善を選択 |
| **Goal-setting (Autotelic)** | 自分で目標を設定 | 週次の技術レポート自動生成 |

### 参考論文

- **[What Do LLM Agents Do When Left Alone?](https://arxiv.org/html/2509.21224v1)**: LLMエージェントを自律的に放置した場合の行動パターン分析。暴走リスクと安全弁の重要性を示す

---

## 2. システム構成

### 推奨構成: Python APScheduler デーモン + Claude Agent SDK

```
tmux: hub-autonomous
  └─ Python APScheduler デーモン (scripts/autonomous_agent.py)
       │
       ├─ [cron] コード品質チェック（毎日 9:00）
       │    └─ Claude Agent SDK → analyze → POST /api/v1/notify
       │
       ├─ [interval] GitHub Issue トリアージ（30分間隔）
       │    └─ Claude Agent SDK → gh api → ラベル付与
       │
       ├─ [cron] 技術トレンドリサーチ（毎週月曜）
       │    └─ Claude Agent SDK → WebSearch → レポート生成
       │
       └─ [webhook] CI/CD 失敗時の自動調査
            └─ Claude Agent SDK → ログ分析 → 修正PR作成
```

### claude-agent-hub との連携

```
┌──────────────────────────────────────────────┐
│            autonomous-agent                   │
│  (Python APScheduler + Claude Agent SDK)      │
└──────────────┬───────────────────────────────┘
               │ HTTP
┌──────────────▼───────────────────────────────┐
│          claude-agent-hub Go API              │
│  ├─ POST /api/v1/notify      → Discord通知   │
│  ├─ POST /api/v1/discord/reply → Discord返信 │
│  └─ GET  /api/v1/teams        → チーム状態   │
└──────────────────────────────────────────────┘
```

既存の claude-agent-hub インフラ（Go API Server、Discord 通知、tmux 管理）をそのまま流用し、新規作成は `autonomous_agent.py`（約100行）のみ。

### 最小実装イメージ

```python
# scripts/autonomous_agent.py（概念設計）
from apscheduler.schedulers.blocking import BlockingScheduler
import subprocess, requests

API_BASE = "http://localhost:8080/api/v1"

def code_quality_check():
    """定期コード品質チェック → Issue自動作成"""
    result = subprocess.run(
        ["claude", "--print", "-p", "リポジトリのコード品質を分析し改善点をリストアップ"],
        capture_output=True, text=True
    )
    # 結果をDiscord通知
    requests.post(f"{API_BASE}/notify", json={
        "title": "コード品質レポート",
        "message": result.stdout[:2000],
        "sender_name": "autonomous-agent"
    })

def issue_triage():
    """GitHub Issue 自動トリアージ"""
    result = subprocess.run(
        ["claude", "--print", "-p", "未ラベルのIssueを分類しラベルを提案"],
        capture_output=True, text=True
    )
    # 結果に基づきラベル付与

scheduler = BlockingScheduler()
scheduler.add_job(code_quality_check, 'cron', hour=9)
scheduler.add_job(issue_triage, 'interval', minutes=30)
scheduler.start()
```

---

## 3. 安全設計

### 暴走防止メカニズム

| 安全弁 | 説明 |
|--------|------|
| **Admin 承認フロー維持** | 自律行動の結果は Issue/PR として提出。マージは人間が判断 |
| **日次アクション上限** | 1日あたりの最大アクション数を制限（例: 50回） |
| **破壊的操作の禁止** | ファイル削除、force push、本番環境操作を完全禁止 |
| **実行ログの可視化** | 全アクションを Discord 通知でリアルタイム共有 |
| **緊急停止** | tmux kill-session で即座にデーモン停止可能 |

### "What Do LLM Agents Do When Left Alone?" からの教訓

論文が指摘するリスク:
1. **無意味な繰り返し行動**: 明確な目標がないと同じタスクを繰り返す → 目標キューの設計で回避
2. **スコープ拡大**: 小さなタスクが際限なく拡大する → 1アクションの制限時間・トークン上限を設定
3. **環境への過干渉**: 不要な変更を加えてしまう → read-only モードをデフォルトに、書き込みは明示的に許可

---

## 4. ユースケース詳細

| # | ユースケース | スケジュール | 出力 | 優先度 |
|---|-------------|-------------|------|--------|
| 1 | コード品質チェック・リファクタリング提案 | 毎日 9:00 | GitHub Issue | 高 |
| 2 | GitHub Issue 自動トリアージ | 30分間隔 | ラベル付与 | 高 |
| 3 | 技術トレンド リサーチ・レポート | 毎週月曜 | Discord レポート | 中 |
| 4 | CI/CD 失敗の自動調査・修正PR | webhook | PR 自動作成 | 中 |
| 5 | パーソナルRAG更新（データ収集） | 毎日深夜 | ChromaDB 更新 | 低 |
