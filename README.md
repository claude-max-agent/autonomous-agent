# autonomous-agent

自律型常駐AIエージェント - トリガーレス自発行動の設計・実装リポジトリ

## コンセプト

Discord/cron 等の**外部トリガーなし**で、人間のように自発的にリサーチ・コード作成・GitHub プッシュを行う常駐エージェント。

「トリガーレス」= **自己トリガー**: エージェント自身が環境を観察し、やるべきことを発見・実行する。

```
while True:
    context = observe()       # 環境を観察（GitHub Issues, コード品質, トレンド等）
    plan = think(context)     # 何をすべきか判断
    result = act(plan)        # 実行（コード修正, Issue作成, レポート生成等）
    feedback = reflect(result) # 結果を自己評価
    sleep(interval)           # 次のサイクルまで待機
```

## 目的

1. **自律的なコード改善**: コード品質チェック → リファクタリング提案 → Issue/PR 自動作成
2. **GitHub Issue 自動トリアージ**: ラベル付与・優先度設定・担当割り当て
3. **技術トレンド リサーチ**: 定期的な技術調査 → レポート生成
4. **パーソナル RAG**: 個人データ（ブラウザ履歴・Twitter・Obsidian等）を活用した文脈理解
5. **CI/CD 障害の自動調査**: ビルド失敗の原因特定 → 修正PR作成

## ディレクトリ構成

```
autonomous-agent/
├── README.md                    # このファイル
├── docs/
│   ├── architecture.md          # アーキテクチャ設計
│   ├── personal-rag.md          # パーソナルRAG構成
│   ├── machine-specs.md         # マシンスペック・コスト比較
│   └── tools-frameworks.md      # ツール・フレームワーク比較
└── scripts/                     # （将来）実装コード
    └── autonomous_agent.py      # （将来）メインデーモンスクリプト
```

## 技術スタック（予定）

| コンポーネント | 技術 | 役割 |
|--------------|------|------|
| スケジューラ | Python APScheduler | 自律ループ・タスクスケジューリング |
| LLM | Claude Agent SDK / Ollama | 推論・コード生成 |
| ベクトルDB | ChromaDB | パーソナルRAG用データストア |
| 埋め込み | bge-m3 / ruri-v3 | 日本語対応セマンティック検索 |
| リランカー | Ruri-Reranker-large | 検索精度向上 |
| 通知 | claude-agent-hub Go API | Discord通知連携 |
| プロセス管理 | tmux (hub-autonomous) | デーモン管理 |

## 関連リソース

- **設計RFC**: [claude-agent-hub Issue #363](https://github.com/claude-max-agent/claude-agent-hub/issues/363)
- **claude-agent-hub**: [claude-max-agent/claude-agent-hub](https://github.com/claude-max-agent/claude-agent-hub) — 既存のマルチエージェントシステム（通知・API基盤を流用）

## ステータス

**設計フェーズ** — ソースコードの実装はまだ行っていません。ドキュメントで設計・構成を整理中です。
