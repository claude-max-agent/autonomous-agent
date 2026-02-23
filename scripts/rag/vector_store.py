"""
vector_store.py - ChromaDB ベクトルストアラッパー

Phase 1: ChromaDB（ローカル）
Phase 2: Qdrant（self-host）に移行予定

コレクション:
  - personal_private : 個人プライベートデータ（Twitter, Chrome履歴）
  - personal_public  : 公開知識・著名人IP
  - agent_memory     : エージェントの作業記憶
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

EMBEDDINGS_DIR = Path(__file__).parent.parent.parent / "data" / "embeddings"

# ChromaDB のコレクション名
COLLECTION_PRIVATE = "personal_private"
COLLECTION_PUBLIC  = "personal_public"
COLLECTION_MEMORY  = "agent_memory"


class VectorStore:
    """ChromaDB ラッパー（Phase 1: ローカルDB）"""

    def __init__(self, persist_dir: Optional[Path] = None):
        self.persist_dir = persist_dir or EMBEDDINGS_DIR / "chromadb"
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collections: dict = {}

    def _get_client(self):
        """ChromaDB クライアントを遅延初期化"""
        if self._client is None:
            try:
                import chromadb
                self._client = chromadb.PersistentClient(path=str(self.persist_dir))
                log.info(f"ChromaDB initialized: {self.persist_dir}")
            except ImportError:
                raise ImportError(
                    "chromadb がインストールされていません。"
                    "`pip install chromadb` を実行してください。"
                )
        return self._client

    def _get_collection(self, name: str):
        """コレクションを取得（なければ作成）"""
        if name not in self._collections:
            client = self._get_client()
            self._collections[name] = client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collections[name]

    def add_documents(
        self,
        texts: list[str],
        metadatas: list[dict],
        ids: list[str],
        collection: str = COLLECTION_PRIVATE,
    ) -> int:
        """ドキュメントをベクトルDBに追加"""
        col = self._get_collection(collection)
        col.add(documents=texts, metadatas=metadatas, ids=ids)
        log.info(f"Added {len(texts)} docs to collection '{collection}'")
        return len(texts)

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        collection: str = COLLECTION_PRIVATE,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """類似ドキュメントを検索"""
        col = self._get_collection(collection)
        count = col.count()
        if count == 0:
            log.debug(f"Collection '{collection}' is empty, skipping query")
            return []

        kwargs = {"query_texts": [query_text], "n_results": min(n_results, count)}
        if where:
            kwargs["where"] = where

        results = col.query(**kwargs)
        docs = []
        for i, doc in enumerate(results["documents"][0]):
            docs.append({
                "text": doc,
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else None,
            })
        return docs

    def count(self, collection: str = COLLECTION_PRIVATE) -> int:
        """コレクション内のドキュメント数を返す"""
        try:
            return self._get_collection(collection).count()
        except Exception:
            return 0

    def is_empty(self, collection: str = COLLECTION_PRIVATE) -> bool:
        return self.count(collection) == 0

    def stats(self) -> dict:
        """全コレクションの統計を返す"""
        return {
            "private": self.count(COLLECTION_PRIVATE),
            "public":  self.count(COLLECTION_PUBLIC),
            "memory":  self.count(COLLECTION_MEMORY),
            "persist_dir": str(self.persist_dir),
        }


# シングルトン
_store: Optional[VectorStore] = None

def get_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    store = VectorStore()
    print("Stats:", json.dumps(store.stats(), indent=2, ensure_ascii=False))
