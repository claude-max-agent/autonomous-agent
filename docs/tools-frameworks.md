# ツール・フレームワーク比較

## 1. 自律エージェントフレームワーク

### 比較表

| フレームワーク | GitHub | Stars | 自律ループ | 自己改善 | メモリ | ツール統合 | 特徴 |
|---------------|--------|-------|-----------|---------|--------|-----------|------|
| **Auto-GPT** | [Significant-Gravitas/AutoGPT](https://github.com/Significant-Gravitas/AutoGPT) | 170k+ | 完全自律 | ❌ | 長期記憶 | プラグイン | 先駆的だが安定性に課題 |
| **BabyAGI** | [yoheinakajima/babyagi](https://github.com/yoheinakajima/babyagi) | 20k+ | タスク自動生成 | ❌ | タスクキュー | 限定的 | シンプルなタスク駆動 |
| **SICA** | [MaximeRobeyns/self_improving_coding_agent](https://github.com/MaximeRobeyns/self_improving_coding_agent) | - | ✅ | ✅ 自己改善 | コード自体 | Git/テスト | SWE-Bench 17%→53% |
| **OpenDevin/OpenHands** | [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands) | 50k+ | ✅ | ❌ | サンドボックス | 豊富 | 開発環境統合 |
| **SWE-agent** | [princeton-nlp/SWE-agent](https://github.com/princeton-nlp/SWE-agent) | 15k+ | 部分的 | ❌ | Issue単位 | Git/エディタ | Issue→PR 自動化 |
| **Claude Agent SDK** | [Anthropic公式](https://docs.anthropic.com/en/docs/claude-code/sdk) | - | SDK | ❌ | セッション | Claude Code全機能 | 本プロジェクトで使用予定 |

### 各フレームワークの詳細

#### Auto-GPT

- **概要**: 最初の本格的な自律エージェントOSS。GPT-4を使い、目標設定→計画→実行を自律的に繰り返す
- **強み**: 170k+ Starsの巨大コミュニティ、豊富なプラグイン
- **弱み**: 安定性に課題、Claude非対応、動作が重い
- **本プロジェクトとの関係**: コンセプトは参考にするが、直接使用は見送り

#### BabyAGI

- **概要**: タスクを自律的に生成・優先順位付け・実行するシンプルなフレームワーク
- **強み**: わずか100行程度のコアロジック、理解しやすい
- **弱み**: 機能が限定的、ツール統合が不十分
- **本プロジェクトとの関係**: タスク自動生成ループのアイデアを参考

#### SICA（Self-Improving Coding Agent）

- **概要**: 自分自身のコードを改善する自己改善型コーディングエージェント
- **強み**: SWE-Bench Verified で **17% → 53%** に改善（3イテレーション）。ICLR 2025 採択
- **弱み**: コーディングタスクに特化
- **本プロジェクトとの関係**: 自己改善ループのアーキテクチャを参考

#### OpenDevin / OpenHands

- **概要**: Devin（AI ソフトウェアエンジニア）のOSSクローン
- **強み**: サンドボックス環境でのコード実行、豊富なツール統合
- **弱み**: 重量級、セットアップが複雑
- **本プロジェクトとの関係**: 将来的な統合候補

#### SWE-agent

- **概要**: GitHub Issue から自動的にPRを作成するエージェント（Princeton大学）
- **強み**: GitHub統合が優れている、Issue→PR の自動化
- **弱み**: 完全自律ではなく、Issue がトリガー
- **本プロジェクトとの関係**: CI/CD 失敗時の自動修正ユースケースで参考

#### Claude Agent SDK

- **概要**: Anthropic 公式のエージェントSDK
- **強み**: Claude Code の全機能にアクセス可能、`claude --print` で非対話実行
- **弱み**: Claude API 依存（コスト発生）
- **本プロジェクトとの関係**: **メインのLLMインターフェースとして使用予定**

---

## 2. パーソナルRAG関連ツール

### 個人データRAG OSS

| プロジェクト | GitHub | Stars | データソース | ローカル | 特徴 |
|------------|--------|-------|------------|---------|------|
| **LEANN** | [yichuan-w/LEANN](https://github.com/yichuan-w/LEANN) | 10k+ | ブラウザ/メール/チャット/SNS | ✅ | MLsys2026採択、97%ストレージ削減 |
| **mem0** | [mem0ai/mem0](https://github.com/mem0ai/mem0) | 47.8k | 会話データ | ✅ | OpenAI Memory より 26% 高精度 |
| **Quivr** | [QuivrHQ/quivr](https://github.com/QuivrHQ/quivr) | 38.9k | PDF/TXT/MD | ✅ | Opinionated RAG フレームワーク |
| **Khoj** | [khoj-ai/khoj](https://github.com/khoj-ai/khoj) | 32.6k | Notion/PDF/MD | ✅ | 個人AI検索、Obsidian連携 |

### RAG パイプラインツール

| ツール | 用途 | 本プロジェクトでの使用 |
|--------|------|---------------------|
| **ChromaDB** | ベクトルDB | パーソナルRAG のデータストア |
| **Ollama** | ローカルLLM / Embedding | ローカル推論・埋め込み生成 |
| **LlamaIndex** | RAG フレームワーク | 高度なRAGパイプライン構築 |
| **Presidio** | PII除去 | 個人情報の自動マスキング |
| **APScheduler** | Python スケジューラ | 自律ループのスケジュール管理 |

---

## 3. 実運用事例

### DeNA

- Claude Code を活用した大規模開発での自律エージェント運用
- 安全弁としての人間レビュー必須フローを維持

### potproject

- 個人開発者による自律型コーディングエージェントの実践
- GitHub Actions + Claude Code での自動改善パイプライン

### GitHub Agent HQ

- GitHub が開発中のエージェント管理フレームワーク
- Issue 駆動の自律的コード生成・PR 作成

### hyperliquid-tools（自チーム実績）

- claude-max-agent Organization 内の完全自動自己改善構成
- GitHub Actions + Claude Code によるPR自動作成→セルフマージ
- 人間の介入なしにコード改善・デプロイが稼働中

---

## 4. 本プロジェクトで使用予定のスタック

| レイヤー | 選定 | 理由 |
|----------|------|------|
| スケジューラ | **APScheduler** | Python、柔軟、軽量 |
| LLM（メイン） | **Claude Agent SDK** | 高品質な推論、claude-agent-hub と統合 |
| LLM（ローカル） | **Ollama + Qwen 2.5 7B** | 単純タスク用、API費用ゼロ |
| 埋め込み | **bge-m3** | 日本語JMTEB 79.74、Dense+Sparse対応 |
| リランカー | **Ruri-Reranker-large** | 日本語JQaRA nDCG@10 77.1 |
| ベクトルDB | **ChromaDB** | 100万ベクトルまで最適、セットアップ簡単 |
| PII除去 | **Presidio** | Microsoft製、多言語対応 |
| プロセス管理 | **tmux** | 既存 claude-agent-hub と統一 |
| 通知 | **claude-agent-hub Go API** | 既存Discord通知基盤を流用 |
