# パーソナルRAG構成

個人データ（ブラウザ履歴・Twitter・Obsidian等）をベクトルDBに格納し、エージェントの文脈として活用する。

## 1. 全体構成

```
┌─────────────────────────────────────────────────────────────┐
│                    データ収集パイプライン                      │
│                                                              │
│  Windows Chrome履歴 ──┐                                      │
│  Windows Edge履歴 ────┤                                      │
│  iPhone Safari履歴 ───┤──▶ PII除去 ──▶ Embedding ──▶ ChromaDB│
│  Twitter アーカイブ ──┤    (Presidio)  (bge-m3)    (ローカル)│
│  Obsidian Vault ──────┘                                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                      質問応答パイプライン                      │
│                                                              │
│  Query ──▶ Embedding ──▶ ChromaDB検索 ──▶ Reranker ──▶ LLM  │
│            (bge-m3)      (Top-20)     (Ruri-Reranker) (Top-5)│
│                                                              │
│  LLM: ローカル(Qwen2.5) or Claude API（タスク複雑度による）   │
└─────────────────────────────────────────────────────────────┘
```

## 2. データソース別の収集方法

### Chrome / Edge 履歴（Windows）

```
Chrome: C:\Users\<Username>\AppData\Local\Google\Chrome\User Data\Default\History
Edge:   C:\Users\<Username>\AppData\Local\Microsoft\Edge\User Data\Default\History
```

SQLiteの `urls` テーブル + `visits` テーブルから URL・タイトル・訪問日時・訪問回数を取得可能。

```python
# browser-history ライブラリ（推奨）
pip install browser-history
from browser_history.browsers import Chrome
c = Chrome()
outputs = c.fetch_history()
# → [(datetime, url), ...] のリスト
```

### iPhone Safari 履歴

**方法1: iMazing（有料 $39.99）**
- iPhone接続 → Safari の History → CSV/HTML エクスポート。最も簡単

**方法2: iTunes/Finder バックアップ + Python（無料）**
```python
pip install iOSbackup
from iOSbackup import iOSbackup
b = iOSbackup(udid="<DEVICE_UDID>", cleartextpassword="<password>")
safari_db = b.getFileDecryptedCopy(relativePath="HomeDomain-Library/Safari/History.db")
# → SQLiteでURL・タイトル・訪問日時を取得
```

### Twitter/X アーカイブ

**公式アーカイブ（推奨）:**
1. X.com → 設定 → アカウント → 「データのアーカイブをダウンロード」
2. 24時間以内にZIPダウンロード
3. `data/tweets.js` に全ツイートがJSON形式で格納

便利なパーサー: [twitter-archive-parser](https://github.com/timhutton/twitter-archive-parser)（Markdown/HTML変換、t.co URL展開対応）

### Obsidian Vault

既存OSSが成熟:

| プロジェクト | Stars | 特徴 |
|------------|-------|------|
| [Smart Connections](https://github.com/brianpetro/obsidian-smart-connections) | 4,600 | ローカル埋め込み、完全オフライン |
| [obsidian-copilot](https://github.com/logancyang/obsidian-copilot) | 6,200 | Ollama対応、PDF/EPUB/YouTube対応 |
| [obsidian-Smart2Brain](https://github.com/your-papa/obsidian-Smart2Brain) | 991 | 階層的ツリー要約 |

## 3. 注目OSS: LEANN

**[LEANN](https://github.com/yichuan-w/LEANN)** — MLsys2026 採択論文、GitHub Stars 10,000+

- **唯一のブラウザ履歴・チャット・メール対応OSS**
- 対応データ: ブラウザ履歴、Apple Mail、WeChat/iMessage、ChatGPT/Claude会話、Slack/Twitter（MCP経由）
- **実証ベンチマーク**: ストレージ97%削減（201GB→6GB for 6000万チャンク）、90% top-3 recall を2秒以内で達成
- 完全ローカル動作、Ollama対応

## 4. 推奨処理パイプライン

### 埋め込みモデル（日本語対応・ローカル）

| モデル | JMTEB日本語 | サイズ | 推奨度 |
|--------|------------|--------|--------|
| **multilingual-e5-large** | 80.46 | ~1.2GB | 日本語最高スコア |
| **bge-m3** | 79.74 | ~1.2GB | 日本語に強い、Dense+Sparse対応 |
| ruri-v3-310m | 75.85 | ~310MB | 軽量・日本語特化 |
| nomic-embed-text | 未評価 | 274MB | 英語向け・軽量 |

```bash
ollama pull bge-m3  # 日本語データには bge-m3 推奨
```

### リランカー（日本語対応）

| モデル | JQaRA nDCG@10 | 推奨度 |
|--------|---------------|--------|
| **Ruri-Reranker-large** | **77.1** | 日本語最良 |
| Ruri-Reranker-base | 74.3 | バランス |
| bge-reranker-v2-m3 | 67.3 | 多言語汎用 |

日本語では Ruri-Reranker が bge-reranker に対して **+9.8ポイント** 優位。

### ベクトルDB

| DB | 推奨規模 | 特徴 |
|----|---------|------|
| **ChromaDB** | ~100万ベクトル | 個人用途に最適、セットアップ簡単 |
| Qdrant | 数十億まで | 大規模向け、高QPS |
| pgvector | ~数百万 | PostgreSQL統合 |

個人データRAGは100万ベクトル以下が見込まれるため **ChromaDB** を推奨。

### チャンク戦略

| 戦略 | 適性 | 改善効果 |
|------|------|---------|
| **Sentence Window Retrieval** | 推奨 | コンテキスト関連スコア +12.5% |
| 固定サイズ（512トークン） | 簡易 | ベースライン |
| クエリタイプ別動的チャンキング | 高精度 | Recall +9% |

## 5. プライバシー・セキュリティ

### 完全ローカル構成（外部送信ゼロ）

RTX 3060 + Ollama を使えば、データが一切外部に送信されない構成が可能:

```
データ → PII除去(Presidio) → Ollama embedding(ローカル) → ChromaDB(ローカル) → Ollama LLM(ローカル)
```

### PII（個人識別情報）の自動除去

```python
pip install presidio-analyzer presidio-anonymizer
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

# "田中太郎 (090-1234-5678)" → "<PERSON> (<PHONE_NUMBER>)"
result = anonymizer.anonymize(
    text=text,
    analyzer_results=analyzer.analyze(
        text=text, language="en",
        entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"]
    )
)
```

### インデックス化から除外すべきURL

```python
EXCLUDE_PATTERNS = [r"bank\.", r"mail\.google", r"login\.", r"password", r"auth"]
```

### Claude API 使用時のデータ最小化

1. embedding はローカル（Ollama）で生成 → ChromaDB に格納
2. 検索結果のみ Claude に送信（Top-3チャンク程度に絞る）
3. PII 除去済みのコンテキストのみ送信
4. Anthropic API データは30日後に自動削除（デフォルトポリシー）

## 6. 実装ロードマップ案

| フェーズ | 内容 | 工数目安 |
|---------|------|---------|
| **Phase 1** | Twitter アーカイブ → ChromaDB 投入 | 小（パーサー既存） |
| **Phase 2** | Chrome/Edge 履歴 → ChromaDB 投入 | 小（SQLite読み取り） |
| **Phase 3** | 既存 RAG（simple_rag.py）との統合 | 中 |
| **Phase 4** | iPhone Safari 履歴の取得・投入 | 中（バックアップ必要） |
| **Phase 5** | PII除去パイプライン統合 | 中 |

**最小構成:** Twitter アーカイブ + Chrome 履歴 → ChromaDB → Ollama で質問応答。数時間で動作可能。
