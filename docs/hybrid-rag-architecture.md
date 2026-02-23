# ハイブリッドRAGアーキテクチャ 詳細設計

Issue #2「ペルソナ・IPコンテキスト設計（著名人IP + 個人IP ハイブリッドRAG）」に基づく実装者向け設計ドキュメント。

---

## 1. アーキテクチャ概要

著名人の思想・著作（公開IP）と個人の発言・メモ（プライベートIP）を統合した3層ハイブリッドRAGシステム。

```
╔═══════════════════════════════════════════════════════════════════════╗
║                 ハイブリッドRAG 3層アーキテクチャ                       ║
╠═══════════════════════════════════════════════════════════════════════╣
║                                                                       ║
║  ┌───────────────────────────────────────────────────────────────┐   ║
║  │  Layer 1: PERSONA LAYER（システムプロンプト動的生成）            │   ║
║  │                                                               │   ║
║  │  ┌─────────────────────────────────────────────────────────┐ │   ║
║  │  │  ID-RAG 知識グラフ（Neo4j）からペルソナコンテキストを動的注入 │ │   ║
║  │  │                                                         │ │   ║
║  │  │  ・核心的信念・価値観・思考パターン                         │ │   ║
║  │  │  ・口調・文体の特徴                                       │ │   ║
║  │  │  ・著名人IP / 個人IP の合成スタイル                       │ │   ║
║  │  └─────────────────────────────────────────────────────────┘ │   ║
║  └───────────────────────────────────────────────────────────────┘   ║
║                              │                                        ║
║                              ▼                                        ║
║  ┌───────────────────────────────────────────────────────────────┐   ║
║  │  Layer 2: KNOWLEDGE LAYER（デュアルRAG）                       │   ║
║  │                                                               │   ║
║  │  ┌─────────────────────┐    ┌──────────────────────────────┐ │   ║
║  │  │  Private Vector DB  │    │      Public Vector DB        │ │   ║
║  │  │  （Qdrant / local） │    │  （Weaviate / Pinecone）      │ │   ║
║  │  │                     │    │                              │ │   ║
║  │  │  ・未発表メモ        │    │  ・著書（全文）               │ │   ║
║  │  │  ・個人日記          │    │  ・論文・公開記事             │ │   ║
║  │  │  ・プライベート会話   │    │  ・インタビュー               │ │   ║
║  │  │  ・Twitterアーカイブ │    │  ・SNS公開投稿               │ │   ║
║  │  └──────────┬──────────┘    └──────────────┬───────────────┘ │   ║
║  │             └──────── Semantic Router ──────┘                │   ║
║  │                            │                                 │   ║
║  │                     bge-m3 Embedding                         │   ║
║  │                     Ruri-Reranker-large                      │   ║
║  └───────────────────────────────────────────────────────────────┘   ║
║                              │                                        ║
║                              ▼                                        ║
║  ┌───────────────────────────────────────────────────────────────┐   ║
║  │  Layer 3: MEMORY LAYER（会話履歴・長期記憶）                    │   ║
║  │                                                               │   ║
║  │  ┌─────────────────────────────────────────────────────────┐ │   ║
║  │  │  Mem0: Core Memory (in-context) + Graph Memory (Neo4j)  │ │   ║
║  │  │  精度: Mem0 67% vs 従来RAG 61%（+6%）                   │ │   ║
║  │  └─────────────────────────────────────────────────────────┘ │   ║
║  └───────────────────────────────────────────────────────────────┘   ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### 各層の役割

| 層 | 名称 | 役割 | 主要コンポーネント |
|----|------|------|-----------------|
| Layer 1 | PERSONA LAYER | ペルソナ定義・文体スタイルの動的注入 | Neo4j 知識グラフ、ID-RAG |
| Layer 2 | KNOWLEDGE LAYER | Private/Public 知識の検索・統合 | Qdrant/ChromaDB、Semantic Router |
| Layer 3 | MEMORY LAYER | 会話履歴・関係性グラフの長期記憶 | Mem0、Neo4j |

---

## 2. フェーズ別実装計画

### Phase 1（現在）: Claude API + ChromaDB + ペルソナテンプレート

**目標**: ローカルLLMなしでRAGの基本動作を確立する。

```
データソース:
  Twitter アーカイブ (tweets.js)
  Obsidian Vault (Markdown)
        │
        ▼
  PII除去 (LlamaIndex PIINodePostprocessor)
        │
        ▼
  Embedding: bge-m3 (Ollama local)
        │
        ▼
  ChromaDB (local)
        │
   ┌────┴─────┐
   │  Query   │ ← ユーザー入力
   └────┬─────┘
        │
   Semantic Router（Private / Public 分類）
        │
   ChromaDB 検索 (Top-20)
        │
   Ruri-Reranker-large (Top-5)
        │
   Claude API（コンテキスト注入 + ペルソナテンプレート）
        │
   返答生成
```

**制約**:
- ローカルLLMなし（Claude API のみ）
- 個人データはローカルに保持、APIに送信するのは検索結果チャンクのみ
- ChromaDB は 100万ベクトル以下の規模に最適

**実装優先度**:
1. `scripts/rag/pii_filter.py` - PII除去パイプライン
2. `scripts/rag/vector_store.py` - ChromaDB wrapper
3. `scripts/rag/semantic_router.py` - Private/Public ルーティング
4. `scripts/rag/persona_layer.py` - ペルソナプロンプトテンプレート

---

### Phase 2（個人データ収集後）: Qdrant + Twitter/Chrome 取り込み

**目標**: 大規模個人データに対応するため ChromaDB から Qdrant に移行。

```
追加データソース:
  Twitter/X アーカイブ
  Chrome/Edge ブラウザ履歴 (SQLite)
  iPhone Safari 履歴
        │
        ▼
  データ収集パイプライン (scripts/collect/)
        │
   ┌────┴──────────────────────────────────────────┐
   │                                               │
   ▼                                               ▼
  Private DB (Qdrant self-host)        Public DB (Weaviate)
  ・未発表メモ・個人日記・会話          ・著書・論文・インタビュー
```

**ChromaDB → Qdrant 移行タイミング**:
- データ量が 100万ベクトル超を見込む時点
- 高 QPS（複数クエリ並列）が必要になった時点

---

### Phase 3（ローカルLLM後）: Neo4j + Mem0 + フル3層

**目標**: ローカル LLM (Ollama) 稼働後に完全自律・プライバシー保護構成を実現。

```
フル3層:
  Layer 1: Neo4j 知識グラフ → ペルソナコンテキスト動的生成
  Layer 2: Qdrant (Private) + Weaviate (Public) + Semantic Router
  Layer 3: Mem0 + Neo4j Graph Memory
       │
  全処理をローカルで完結（Ollama LLM + bge-m3 embedding）
```

**追加コンポーネント**:
- `Mem0 self-hosted` - 会話記憶の階層管理
- `Neo4j Community Edition` - 知識グラフ・関係性マップ
- `Ollama + Qwen2.5 7B` - ローカル LLM 推論

---

## 3. 技術スタック詳細

### 3.1 Embedding モデル

**選定: bge-m3**

| モデル | JMTEB スコア | サイズ | 特徴 |
|--------|-------------|--------|------|
| multilingual-e5-large | 80.46 | ~1.2GB | 日本語最高スコア |
| **bge-m3（選定）** | **79.74** | **~1.2GB** | **Dense + Sparse 対応、Ollama 対応** |
| ruri-v3-310m | 75.85 | ~310MB | 軽量・日本語特化 |
| nomic-embed-text | 未評価 | 274MB | 英語向け・軽量 |

bge-m3 を選定する理由:
- Dense retrieval（意味検索）と Sparse retrieval（キーワード検索）の両方に対応するハイブリッド検索が可能
- Ollama から `ollama pull bge-m3` で即座に利用可能
- 日本語 JMTEB スコアは最高クラス（第2位）

```bash
# セットアップ
ollama pull bge-m3
```

---

### 3.2 Vector DB

**Phase 1: ChromaDB**

| DB | 推奨規模 | 特徴 | Phase |
|----|---------|------|-------|
| **ChromaDB** | ~100万ベクトル | セットアップ簡単、個人用途に最適 | Phase 1 |
| **Qdrant** | 数十億まで | 大規模向け、高 QPS、ACL フィルタ対応 | Phase 2+ |
| pgvector | ~数百万 | PostgreSQL 統合 | 参考 |

```python
# ChromaDB セットアップ例
import chromadb

client = chromadb.PersistentClient(path="/home/zono819/autonomous-agent/data/chroma")
collection = client.get_or_create_collection(
    name="personal_rag",
    metadata={"hnsw:space": "cosine"}
)
```

**Phase 2: Qdrant（Private DB）**

Qdrant はメタデータ ACL フィルタ機能により、データ種別ごとのアクセス制御が可能。

```python
# Qdrant ACL フィルタ例
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

client = QdrantClient(url="http://localhost:6333")

# プライベートデータのみ検索
results = client.search(
    collection_name="personal_knowledge",
    query_vector=query_embedding,
    query_filter=Filter(
        must=[FieldCondition(key="access_level", match=MatchValue(value="private"))]
    ),
    limit=20
)
```

---

### 3.3 Reranker

**選定: Ruri-Reranker-large**

| モデル | JQaRA nDCG@10 | 推奨度 |
|--------|---------------|--------|
| **Ruri-Reranker-large（選定）** | **77.1** | 日本語最良 |
| Ruri-Reranker-base | 74.3 | バランス型 |
| bge-reranker-v2-m3 | 67.3 | 多言語汎用 |

日本語では Ruri-Reranker が bge-reranker に対して **+9.8ポイント** 優位。

```python
# Ruri-Reranker 使用例
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cl-nagoya/ruri-reranker-large")

# Top-20 候補を Top-5 に絞り込み
pairs = [(query, doc) for doc in candidate_docs]
scores = reranker.predict(pairs)
reranked = sorted(zip(scores, candidate_docs), reverse=True)[:5]
```

---

### 3.4 Semantic Router

**選定: aurelio-labs/semantic-router**

クエリの意図（プライベート記憶 vs 公開知識）を分類し、適切な DB にルーティングする。

```python
from semantic_router import Route, RouteLayer
from semantic_router.encoders import FastEmbedEncoder

encoder = FastEmbedEncoder(name="BAAI/bge-m3")

private_route = Route(
    name="private_memory",
    utterances=[
        "あなた自身の考えを教えて",
        "昨日言っていたこと",
        "日記に書いてあること",
        "個人的な意見は",
        "自分のメモによると",
    ]
)

public_route = Route(
    name="public_knowledge",
    utterances=[
        "著書の内容を教えて",
        "論文の主張は",
        "公開インタビューでの発言",
        "一般的な見解として",
        "研究結果によると",
    ]
)

hybrid_route = Route(
    name="hybrid",
    utterances=[
        "あなたの経験と研究を踏まえて",
        "個人的見解と公的主張を合わせると",
    ]
)

router = RouteLayer(
    encoder=encoder,
    routes=[private_route, public_route, hybrid_route]
)

def route_query(query: str) -> str:
    result = router(query)
    return result.name  # "private_memory" / "public_knowledge" / "hybrid"
```

---

### 3.5 Memory Layer (Mem0)

**選定: Mem0 self-hosted**

| 手法 | 精度 |
|------|------|
| **Mem0（選定）** | **67%** |
| 従来 RAG | 61% |
| OpenAI Memory | 52%（Mem0 論文比） |

Mem0 はコアメモリ（コンテキスト内）とグラフメモリ（Neo4j）を階層管理する。

```python
from mem0 import Memory

# 設定（Phase 3: Neo4j グラフメモリ有効）
config = {
    "graph_store": {
        "provider": "neo4j",
        "config": {
            "url": "bolt://localhost:7687",
            "username": "neo4j",
            "password": "password"
        }
    },
    "vector_store": {
        "provider": "qdrant",
        "config": {"host": "localhost", "port": 6333}
    },
    "embedder": {
        "provider": "ollama",
        "config": {"model": "bge-m3"}
    }
}

m = Memory.from_config(config)

# 会話を記憶として保存
m.add(
    messages=[
        {"role": "user", "content": "自律エージェントの設計について話したい"},
        {"role": "assistant", "content": "ReAct ループが最も汎用的です"}
    ],
    user_id="user_001"
)

# 関連記憶の検索
memories = m.search(query="エージェント設計", user_id="user_001")
```

---

### 3.6 PII Guard

**選定: LlamaIndex PIINodePostprocessor**

```python
from llama_index.core.postprocessor import PIINodePostprocessor
from llama_index.llms.ollama import Ollama

# ローカル LLM で PII 除去（外部送信ゼロ）
pii_processor = PIINodePostprocessor(
    llm=Ollama(model="qwen2.5:7b"),
    entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "LOCATION"]
)

# 補完: Microsoft Presidio によるルールベース PII 除去
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

def remove_pii(text: str) -> str:
    results = analyzer.analyze(
        text=text,
        language="en",
        entities=["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"]
    )
    return anonymizer.anonymize(text=text, analyzer_results=results).text
    # 例: "田中太郎 (090-1234-5678)" → "<PERSON> (<PHONE_NUMBER>)"
```

---

## 4. ファイル構成

```
scripts/rag/
├── __init__.py               # パッケージ初期化・公開インターフェース定義
├── persona_layer.py          # ペルソナプロンプト動的生成
├── vector_store.py           # ChromaDB / Qdrant の統一 wrapper
├── semantic_router.py        # Private / Public クエリルーティング
└── pii_filter.py             # PII 除去パイプライン（Presidio + LlamaIndex）
```

### 各ファイルの責務

#### `__init__.py`

```python
from .persona_layer import PersonaLayer
from .vector_store import VectorStore
from .semantic_router import SemanticRouter
from .pii_filter import PIIFilter

__all__ = ["PersonaLayer", "VectorStore", "SemanticRouter", "PIIFilter"]
```

#### `persona_layer.py`

ペルソナ定義をシステムプロンプトに変換する。Phase 1 はテンプレートベース、Phase 3 で Neo4j 知識グラフからの動的生成に移行。

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class PersonaConfig:
    name: str                          # ペルソナ名
    core_beliefs: list[str]            # 核心的信念・価値観
    thinking_patterns: list[str]       # 思考パターン
    speech_style: str                  # 口調・文体
    public_ip_sources: list[str]       # 参照する著名人IPの著作
    private_ip_enabled: bool = False   # 個人IPの使用可否

class PersonaLayer:
    def __init__(self, config: PersonaConfig):
        self.config = config

    def build_system_prompt(self, retrieved_context: str) -> str:
        """検索コンテキストを含むシステムプロンプトを生成"""
        return f"""あなたは {self.config.name} として応答します。

## 核心的信念・価値観
{chr(10).join(f'- {b}' for b in self.config.core_beliefs)}

## 思考パターン
{chr(10).join(f'- {p}' for p in self.config.thinking_patterns)}

## 口調・文体
{self.config.speech_style}

## 参照コンテキスト
{retrieved_context}

上記のペルソナと参照コンテキストに基づいて応答してください。"""
```

#### `vector_store.py`

ChromaDB（Phase 1）と Qdrant（Phase 2）を共通インターフェースで抽象化。

```python
from abc import ABC, abstractmethod
from typing import Literal

class BaseVectorStore(ABC):
    @abstractmethod
    def add(self, texts: list[str], metadatas: list[dict], ids: list[str]) -> None:
        ...

    @abstractmethod
    def search(self, query_embedding: list[float], top_k: int = 20,
               access_level: Literal["private", "public", "all"] = "all") -> list[dict]:
        ...

class ChromaVectorStore(BaseVectorStore):
    """Phase 1: ChromaDB wrapper"""
    def __init__(self, persist_path: str, collection_name: str):
        import chromadb
        self.client = chromadb.PersistentClient(path=persist_path)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add(self, texts, metadatas, ids):
        self.collection.add(documents=texts, metadatas=metadatas, ids=ids)

    def search(self, query_embedding, top_k=20, access_level="all"):
        where = {"access_level": access_level} if access_level != "all" else None
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where
        )
        return [
            {"text": doc, "metadata": meta, "distance": dist}
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0]
            )
        ]

def get_vector_store(phase: int = 1, **kwargs) -> BaseVectorStore:
    """フェーズに応じた VectorStore を返すファクトリ関数"""
    if phase == 1:
        return ChromaVectorStore(**kwargs)
    elif phase >= 2:
        # Phase 2: QdrantVectorStore（未実装）
        raise NotImplementedError("Qdrant は Phase 2 で実装")
```

#### `semantic_router.py`

```python
from semantic_router import Route, RouteLayer
from semantic_router.encoders import FastEmbedEncoder
from typing import Literal

RouteName = Literal["private_memory", "public_knowledge", "hybrid"]

class SemanticRouter:
    def __init__(self):
        encoder = FastEmbedEncoder(name="BAAI/bge-m3")
        routes = [
            Route(
                name="private_memory",
                utterances=[
                    "あなた自身の考えを教えて", "個人的な意見は",
                    "日記に書いてあること", "自分のメモによると",
                ]
            ),
            Route(
                name="public_knowledge",
                utterances=[
                    "著書の内容を教えて", "論文の主張は",
                    "公開インタビューでの発言", "研究結果によると",
                ]
            ),
            Route(
                name="hybrid",
                utterances=[
                    "個人的見解と研究を踏まえて",
                    "あなたの経験と公的主張を合わせると",
                ]
            ),
        ]
        self.layer = RouteLayer(encoder=encoder, routes=routes)

    def route(self, query: str) -> RouteName:
        result = self.layer(query)
        return result.name if result.name else "public_knowledge"
```

#### `pii_filter.py`

```python
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

class PIIFilter:
    def __init__(self):
        self.analyzer = AnalyzerEngine()
        self.anonymizer = AnonymizerEngine()
        self.entities = [
            "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
            "CREDIT_CARD", "LOCATION", "URL"
        ]

    def filter(self, text: str) -> str:
        """PII を匿名化トークンに置換して返す"""
        results = self.analyzer.analyze(
            text=text,
            language="en",
            entities=self.entities
        )
        if not results:
            return text
        return self.anonymizer.anonymize(
            text=text,
            analyzer_results=results
        ).text

    def is_safe_url(self, url: str) -> bool:
        """インデックス化から除外すべき URL を検査"""
        import re
        EXCLUDE_PATTERNS = [
            r"bank\.", r"mail\.google", r"login\.",
            r"password", r"auth", r"account\.", r"secure\."
        ]
        return not any(re.search(p, url) for p in EXCLUDE_PATTERNS)
```

---

## 5. データフロー

### クエリ処理フロー（完全版）

```
[ユーザー入力クエリ]
        │
        ▼
┌───────────────────────────────────────────────────────┐
│  Step 1: ルーティング判定（semantic_router.py）         │
│  → "private_memory" / "public_knowledge" / "hybrid"   │
└───────────────────┬───────────────────────────────────┘
                    │
        ┌───────────▼───────────┐
        │                       │
        ▼                       ▼
  Private DB のみ         Public DB のみ
  (access_level=private)  (access_level=public)
        │                       │
        └──────────┬────────────┘
                   │  (hybrid の場合は両方)
                   ▼
┌───────────────────────────────────────────────────────┐
│  Step 2: ベクトル検索（vector_store.py）               │
│  bge-m3 で query を embedding → Top-20 取得           │
└───────────────────┬───────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Step 3: リランキング                                   │
│  Ruri-Reranker-large で Top-20 → Top-5 に絞り込み      │
└───────────────────┬───────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Step 4: 会話記憶の取得（Layer 3 / Mem0）              │
│  過去の会話履歴・関係性グラフから関連記憶を検索          │
└───────────────────┬───────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Step 5: ペルソナプロンプト生成（persona_layer.py）     │
│  RAG 検索結果 + 記憶 → ペルソナ付きシステムプロンプト   │
└───────────────────┬───────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Step 6: LLM 推論                                      │
│  Phase 1: Claude API（Claude Sonnet 4.6）              │
│  Phase 3: Ollama（Qwen2.5 7B）← ローカル完結           │
└───────────────────┬───────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Step 7: 記憶の更新（Mem0）                            │
│  今回の会話を Layer 3 に保存 → 次回以降の文脈に活用     │
└───────────────────────────────────────────────────────┘
                    │
                    ▼
           [レスポンス返却]
```

### データ収集フロー（インデックス構築）

```
[生データ]                       [処理]                    [格納]
Twitter アーカイブ ──┐
Obsidian Vault ──────┤
Chrome 履歴 ─────────┼──▶ PII除去 ──▶ bge-m3 embedding ──▶ ChromaDB
Edge 履歴 ───────────┤   (pii_filter.py)                   (private)
iPhone Safari ───────┘

著書 PDF ────────────┐
公開論文 ────────────┤──▶ チャンク分割 ──▶ bge-m3 embedding ──▶ ChromaDB
インタビュー記事 ─────┘                                         (public)
```

---

## 6. プライバシー設計

### データ分類とローカル処理ルール

| データ種別 | 分類 | 推論環境 | 格納 DB | API 送信 |
|-----------|------|---------|---------|---------|
| 個人日記・未発表メモ | Private | Ollama（local） | Private DB のみ | 禁止 |
| Twitter プライベート DM | Private | Ollama（local） | Private DB のみ | 禁止 |
| Twitter 公開ツイート | Public | Claude API 可 | Public DB | PII除去済みのみ |
| 著書・論文 | Public | Claude API 可 | Public DB | 可 |
| ブラウザ履歴 | Private | Ollama（local） | Private DB のみ | 禁止 |

### 完全ローカル構成（Phase 3 以降）

```
個人データ → PII除去（Presidio）→ Ollama embedding（bge-m3）→ ChromaDB/Qdrant（local）
                                                                        │
                 ┌──────────────────────────────────────────────────────┘
                 ▼
          Ollama LLM（Qwen2.5 7B）← 推論もローカル完結
```

### Claude API 使用時のデータ最小化（Phase 1）

1. **Embedding はローカルで生成**: bge-m3（Ollama）で embedding → API に raw データを送らない
2. **検索結果のみ送信**: ChromaDB 検索結果の Top-3 〜 5 チャンクのみ API に送信
3. **PII 除去済みコンテキストのみ送信**: Presidio + PIINodePostprocessor でフィルタ後に送信
4. **Anthropic のデータ保持ポリシー**: デフォルトで 30 日後に自動削除

### アクセス制御

```python
# Qdrant メタデータ ACL の例（Phase 2+）
{
    "id": "doc_001",
    "text": "...",
    "metadata": {
        "source": "twitter_archive",
        "access_level": "private",    # "private" | "public"
        "created_at": "2024-01-15",
        "data_type": "tweet"
    }
}
```

---

## 7. 参考論文・リソース

### 主要論文

| 論文 | 著者・機関 | 概要 | 本プロジェクトへの関連 |
|------|-----------|------|---------------------|
| [ID-RAG (ECAI 2025)](https://arxiv.org/abs/2509.25299) | MIT Media Lab | アイデンティティ知識グラフによるペルソナ維持 | Layer 1 の設計基盤 |
| [PersonaAI (2025)](https://arxiv.org/abs/2503.15489) | - | RAGベース個人AIアバター（検索精度91%） | Layer 2 の設計基盤 |
| [RAGRouter (NeurIPS 2025)](https://arxiv.org/abs/2505.23052) | - | RAG-Aware ルーティング戦略 | Semantic Router の設計 |
| [Mem0 (2025)](https://arxiv.org/abs/2504.19413) | Mem0 AI | グラフメモリ階層化（精度67%） | Layer 3 の設計基盤 |
| [CharacterBot (2025)](https://arxiv.org/abs/2502.12988) | - | スタイル転換マッチング0.937 | ペルソナ文体制御の参考 |

### OSS リソース

| リポジトリ | 用途 |
|-----------|------|
| [aurelio-labs/semantic-router](https://github.com/aurelio-labs/semantic-router) | Semantic Router 本体 |
| [mem0ai/mem0](https://github.com/mem0ai/mem0) | Memory Layer 本体 |
| [langchain-ai/twitter-finetune](https://github.com/langchain-ai/twitter-finetune) | Twitter データ取り込みパイプライン参考 |
| [yichuan-w/LEANN](https://github.com/yichuan-w/LEANN) | 個人データ RAG（MLsys2026、97% ストレージ削減） |
| [microsoft/presidio](https://github.com/microsoft/presidio) | PII 除去エンジン |
| [cl-nagoya/ruri](https://huggingface.co/cl-nagoya/ruri-reranker-large) | Ruri-Reranker-large（日本語最良リランカー） |

### 関連 Issue

| Issue | タイトル | 関連フェーズ |
|-------|---------|------------|
| [claude-agent-hub #363](https://github.com/claude-max-agent/claude-agent-hub/issues/363) | 情報のIP化調査 | 設計背景 |
| [autonomous-agent #5](https://github.com/claude-max-agent/autonomous-agent/issues/5) | パーソナルRAGセットアップ | Phase 1 実装 |
| [autonomous-agent #6](https://github.com/claude-max-agent/autonomous-agent/issues/6) | 個人データ収集・前処理パイプライン | Phase 2 実装 |

---

## 8. 実装チェックリスト

### Phase 1 完了条件

- [ ] `scripts/rag/pii_filter.py` - Presidio による PII 除去
- [ ] `scripts/rag/vector_store.py` - ChromaDB wrapper
- [ ] `scripts/rag/semantic_router.py` - Private/Public ルーティング
- [ ] `scripts/rag/persona_layer.py` - ペルソナテンプレート定義
- [ ] Twitter アーカイブのインデックス化スクリプト
- [ ] Obsidian Vault のインデックス化スクリプト
- [ ] エンドツーエンドのクエリ応答テスト

### Phase 2 完了条件

- [ ] ChromaDB → Qdrant 移行
- [ ] Chrome/Edge 履歴の収集・インデックス化パイプライン
- [ ] Private/Public 分離インデックス構築
- [ ] ACL フィルタのテスト

### Phase 3 完了条件

- [ ] Ollama + Qwen2.5 7B セットアップ
- [ ] Mem0 self-hosted 環境構築
- [ ] Neo4j Community Edition セットアップ
- [ ] ID-RAG スタイルの知識グラフ構築
- [ ] 完全ローカル動作の確認（外部 API 依存ゼロ）
