# autonomous-agent アーキテクチャ設計

> Phase 2 (2026-02-24) | Hybrid LLM + ChromaDB RAG + Discord通知

---

## 全体フロー

```mermaid
flowchart TD
    CRON["⏰ APScheduler\n毎朝 08:00 JST"]
    OBSERVE["👀 observe()\nHN / GitHub トレンド収集"]
    THINK["🤔 think()\nテーマ選定"]
    ACT["✍️ act()\nZenn記事草稿生成"]
    REFLECT["📝 reflect()\n品質自己評価"]
    NOTIFY["📣 notify()\nDiscord通知"]
    DIARY["📓 agent-diary\n思考ログ投稿"]

    CRON --> OBSERVE
    OBSERVE --> THINK
    THINK --> ACT
    ACT --> REFLECT
    REFLECT --> NOTIFY

    OBSERVE -.->|observe log| DIARY
    THINK -.->|theme| DIARY
    REFLECT -.->|score| DIARY
```

---

## LLM 使い分け（ハイブリッド構成）

```mermaid
flowchart LR
    subgraph LOCAL["🖥️ ローカル（Ollama）"]
        Q["qwen3:8b\nWSL2 / RTX3060"]
    end
    subgraph CLOUD["☁️ Claude API"]
        H["claude-haiku-4-5\nフォールバック"]
        S["claude-sonnet-4-6\n記事草稿生成"]
    end

    THINK_T["think()\nテーマ選定"] -->|優先| Q
    THINK_T -->|Ollama不可| H

    REFLECT_T["reflect()\n自己評価"] -->|優先| Q
    REFLECT_T -->|Ollama不可| H

    ACT_T["act()\n草稿生成\n（複雑・長文）"] --> S
```

| タスク | 主担当 | フォールバック | 理由 |
|--------|--------|--------------|------|
| `think` テーマ選定 | Ollama qwen3:8b | Claude Haiku | 短文・高速・ローカル処理 |
| `act` 記事草稿生成 | Claude Sonnet 4.6 | なし | 高品質な長文生成が必要 |
| `reflect` 自己評価 | Ollama qwen3:8b | Claude Haiku | JSON出力・構造化評価 |

---

## RAG パイプライン（3層構成）

```mermaid
flowchart TB
    subgraph L1["Layer 1: PERSONA"]
        P["persona_layer.py\npersona.json → System Prompt生成"]
    end
    subgraph L2["Layer 2: KNOWLEDGE"]
        SR["semantic_router.py\nPRIVATE / PUBLIC / BOTH 判定"]
        PUB["personal_public\n(ChromaDB)"]
        PRIV["personal_private\n(ChromaDB)"]
        SR -->|PUBLIC| PUB
        SR -->|PRIVATE| PRIV
        SR -->|BOTH| PUB
        SR -->|BOTH| PRIV
    end
    subgraph L3["Layer 3: MEMORY"]
        MEM["agent_memory\n(ChromaDB)\n実行ログ・評価履歴"]
    end
    subgraph EMB["Embeddings"]
        BGE["BAAI/bge-m3\n(sentence-transformers)\nローカル実行"]
    end

    QUERY["クエリ"] --> L1
    L1 --> L2
    L2 --> L3
    L3 --> RESP["RAG応答"]
    BGE -.->|ベクトル化| L2
    BGE -.->|ベクトル化| L3
```

### ChromaDB コレクション

| コレクション | 内容 | ソース |
|------------|------|--------|
| `personal_private` | Chrome閲覧履歴（PII除去済み）| `import_chrome.py` |
| `personal_public` | 公開知識・著名人IP | (将来実装) |
| `agent_memory` | 実行ログ・評価履歴 | autonomous_agent.py |

---

## Discord チャンネル構成

```mermaid
flowchart LR
    AGENT["autonomous-agent"]

    subgraph CHANNELS["Discord"]
        MAIN["hub-autonomous\n1475499842800451616\nアクション結果"]
        DIARY_CH["agent-diary\n1475552269222154312\n思考ログ・内省"]
    end

    HUB_API["Hub API\nlocalhost:8080\n/api/v1/discord/reply"]

    AGENT -->|"✅ 完了通知\n⚠️ エラー通知"| HUB_API
    AGENT -->|"👀🤔✍️📝🌙 思考ログ"| HUB_API
    HUB_API --> MAIN
    HUB_API --> DIARY_CH
```

| チャンネル | 目的 | 投稿タイミング |
|-----------|------|-------------|
| `hub-autonomous` | Admin向けアクション結果 | 開始・完了・エラー時 |
| `agent-diary` | 思考プロセス記録 | observe/think/reflect/daily/startup |

---

## データフロー

```mermaid
flowchart LR
    subgraph INPUT["入力データ"]
        HN["Hacker News\nTop Stories API"]
        GH["GitHub Search API\n高スターリポジトリ"]
        CHROME["Chrome履歴\nSQLite → import_chrome.py"]
        TW["Twitterアーカイブ\n(将来実装)"]
    end

    subgraph PROCESSING["処理"]
        PII["PII フィルター\npii_filter.py\n59パターン除去"]
        EMB2["埋め込み変換\nbge-m3"]
        DB["ChromaDB\ndata/embeddings/chromadb/"]
    end

    subgraph OUTPUT["出力"]
        DRAFT["Zenn記事草稿\n(Markdown)"]
        DISCORD2["Discord通知"]
    end

    HN --> PROCESSING
    GH --> PROCESSING
    CHROME --> PII --> EMB2 --> DB
    TW --> PII

    PROCESSING --> DRAFT
    DRAFT --> DISCORD2
```

---

## ディレクトリ構成

```
autonomous-agent/
├── scripts/
│   ├── autonomous_agent.py    # メインデーモン（APScheduler）
│   ├── import_chrome.py       # Chrome履歴インポーター
│   ├── start.sh               # 起動スクリプト（tmux）
│   └── rag/
│       ├── __init__.py
│       ├── persona_layer.py   # Layer 1: ペルソナプロンプト生成
│       ├── vector_store.py    # ChromaDBラッパー
│       ├── semantic_router.py # Layer 2: PRIVATE/PUBLIC ルーティング
│       ├── pii_filter.py      # PII除去（59パターン）
│       └── embeddings.py      # sentence-transformers ラッパー
│
├── data/
│   ├── raw/
│   │   ├── chrome/<device>/   # Chrome SQLite (gitignore対象)
│   │   └── twitter/<account>/ # Twitterアーカイブ (gitignore対象)
│   ├── processed/             # 前処理済みデータ (gitignore対象)
│   ├── embeddings/chromadb/   # ChromaDB永続化 (gitignore対象)
│   └── persona.json           # ペルソナ設定 (任意)
│
├── docs/
│   ├── ARCHITECTURE.md        # このファイル
│   ├── hybrid-rag-architecture.md
│   ├── machine-specs.md
│   └── ...
│
├── logs/                      # 実行ログ (gitignore対象)
├── requirements.txt
└── .env                       # API キー等 (gitignore対象)
```

---

## 実行タイミング・アクション上限

| 設定 | 値 |
|------|-----|
| 実行スケジュール | 毎朝 08:00 JST (APScheduler) |
| 日次アクション上限 | 50回 |
| 起動方式 | `tmux` セッション（`scripts/start.sh`）|
| テスト実行 | `RUN_NOW=1 python3 scripts/autonomous_agent.py` |

---

## Phase ロードマップ

| Phase | 状態 | 内容 |
|-------|------|------|
| Phase 1 | ✅ 完了 | Claude APIのみ、observe→think→act→reflect基本ループ |
| Phase 2 | ✅ 完了 | Ollama qwen3:8b 統合、ハイブリッドLLM |
| Phase 3 | 🔜 予定 | Twitterアーカイブ追加、RAG本格活用 |
| Modelfile | ⏳ データ蓄積後 | ペルソナ統合カスタムモデル作成（Issue #13）|
