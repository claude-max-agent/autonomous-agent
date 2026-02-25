#!/usr/bin/env python3
"""
memory_manager.py - エージェントメモリ管理 (Issue #27)

会話・リサーチログをChromaDBに蓄積し、TTLベースの自動クリーンアップと
Ollamaによる週次要約生成を行う。

蓄積ルール:
  - chat     : 重要度 >= 6 の会話（TTL 90日）
  - research : 毎日の observe/think/reflect 結果（TTL 90日）
  - summary  : Ollamaが週次でchat/researchを圧縮した要約（TTL 90日）

容量管理:
  - 上限: 1000件（超過時は低importance順に削除）
  - 週次クリーンアップ: TTL切れ削除 + Ollama要約生成
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# デフォルト設定
EMBEDDINGS_DIR = Path(__file__).parent.parent / "data" / "embeddings"
COLLECTION_NAME = "agent_memory"
TTL_DAYS = 90
MAX_ENTRIES = 1000
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:8b"

JST = timezone(timedelta(hours=9))


class MemoryManager:
    """ChromaDB ベースのエージェントメモリ管理"""

    def __init__(
        self,
        persist_dir: Optional[Path] = None,
        ollama_url: str = OLLAMA_URL,
        ollama_model: str = OLLAMA_MODEL,
    ):
        self.persist_dir = persist_dir or EMBEDDINGS_DIR / "chromadb"
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self._client = None
        self._collection = None

    def _get_collection(self):
        """ChromaDB コレクションを遅延初期化"""
        if self._collection is None:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            log.info(f"ChromaDB collection '{COLLECTION_NAME}' ready: {self.persist_dir}")
        return self._collection

    @staticmethod
    def _now() -> datetime:
        return datetime.now(JST)

    @staticmethod
    def _make_id() -> str:
        return str(uuid.uuid4())

    def _build_metadata(
        self,
        entry_type: str,
        importance: float,
        topic: str = "",
    ) -> dict:
        """共通メタデータを構築"""
        now = self._now()
        return {
            "type": entry_type,
            "importance": str(importance),
            "timestamp": now.isoformat(),
            "expires_at": (now + timedelta(days=TTL_DAYS)).isoformat(),
            "topic": topic,
        }

    # ─── 蓄積 ──────────────────────────────────────────────────────

    def add_chat(
        self,
        sender: str,
        message: str,
        response: str,
        importance: float = 5.0,
    ) -> Optional[str]:
        """会話を保存（importance >= 6 のみ）"""
        if importance < 6:
            log.debug(f"chat skipped (importance={importance} < 6): {message[:50]}")
            return None

        doc_id = self._make_id()
        text = f"[chat] {sender}: {message}\n→ {response}"
        metadata = self._build_metadata("chat", importance, topic="chat")

        col = self._get_collection()
        col.add(documents=[text], metadatas=[metadata], ids=[doc_id])
        log.info(f"chat saved: id={doc_id}, importance={importance}")
        return doc_id

    def add_research(
        self,
        date: str,
        topic: str,
        theme: str,
        score: float,
        summary: str,
    ) -> str:
        """リサーチ結果を保存（reflect score → importance に変換）"""
        # score は 0-100 → importance は 0-10 に変換
        importance = round(score / 10.0, 1)

        doc_id = self._make_id()
        text = f"[research] {date} - {theme}\n{summary}"
        metadata = self._build_metadata("research", importance, topic=topic)

        col = self._get_collection()
        col.add(documents=[text], metadatas=[metadata], ids=[doc_id])
        log.info(f"research saved: id={doc_id}, importance={importance}, topic={topic}")
        return doc_id

    # ─── クリーンアップ ────────────────────────────────────────────

    def cleanup(self) -> dict:
        """TTL切れ削除 + 容量超過時の低importance削除"""
        col = self._get_collection()
        stats = {"expired_deleted": 0, "overflow_deleted": 0, "remaining": 0}

        # 1. TTL切れエントリの削除
        now_iso = self._now().isoformat()
        all_data = col.get(include=["metadatas"])

        expired_ids = []
        for i, meta in enumerate(all_data["metadatas"]):
            if meta.get("expires_at", "") < now_iso:
                expired_ids.append(all_data["ids"][i])

        if expired_ids:
            col.delete(ids=expired_ids)
            stats["expired_deleted"] = len(expired_ids)
            log.info(f"TTL切れ削除: {len(expired_ids)}件")

        # 2. 容量超過時の低importance順削除
        count = col.count()
        if count > MAX_ENTRIES:
            overflow = count - MAX_ENTRIES
            all_data = col.get(include=["metadatas"])

            # importance昇順でソート → 低い方からoverflow件削除
            indexed = list(zip(all_data["ids"], all_data["metadatas"]))
            indexed.sort(key=lambda x: float(x[1].get("importance", "0")))

            delete_ids = [item[0] for item in indexed[:overflow]]
            col.delete(ids=delete_ids)
            stats["overflow_deleted"] = len(delete_ids)
            log.info(f"容量超過削除: {len(delete_ids)}件 (上限{MAX_ENTRIES})")

        stats["remaining"] = col.count()
        log.info(f"クリーンアップ完了: {stats}")
        return stats

    # ─── 週次要約 ──────────────────────────────────────────────────

    def summarize_week(self) -> Optional[str]:
        """直近7日分のchat/researchエントリをOllamaで1件のsummaryに圧縮"""
        col = self._get_collection()

        # 直近7日のタイムスタンプ閾値
        week_ago = (self._now() - timedelta(days=7)).isoformat()

        # chat/research エントリを取得
        all_data = col.get(include=["documents", "metadatas"])
        if not all_data["ids"]:
            log.info("要約対象なし（コレクション空）")
            return None

        target_ids = []
        target_docs = []
        for i, meta in enumerate(all_data["metadatas"]):
            if meta.get("type") in ("chat", "research") and meta.get("timestamp", "") >= week_ago:
                target_ids.append(all_data["ids"][i])
                target_docs.append(all_data["documents"][i])

        if not target_docs:
            log.info("直近7日の要約対象エントリなし")
            return None

        log.info(f"要約対象: {len(target_docs)}件")

        # Ollamaで要約生成
        combined = "\n\n---\n\n".join(target_docs)
        prompt = (
            "以下はAIエージェントの直近1週間の会話ログとリサーチ結果です。\n"
            "これらを簡潔に要約してください（日本語、500字以内）。\n"
            "重要なトピック、学んだこと、傾向を中心にまとめてください。\n\n"
            f"{combined}"
        )

        try:
            resp = httpx.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": 800, "temperature": 0.5},
                },
                timeout=120,
            )
            resp.raise_for_status()
            summary_text = resp.json()["response"].strip()
        except Exception as e:
            log.error(f"Ollama要約生成失敗: {e}")
            return None

        # summary エントリを保存
        # importance は元エントリの最大値を継承
        max_importance = 0.0
        for i, meta in enumerate(all_data["metadatas"]):
            if all_data["ids"][i] in target_ids:
                max_importance = max(max_importance, float(meta.get("importance", "0")))

        doc_id = self._make_id()
        now = self._now()
        metadata = {
            "type": "summary",
            "importance": str(round(max_importance, 1)),
            "timestamp": now.isoformat(),
            "expires_at": (now + timedelta(days=TTL_DAYS)).isoformat(),
            "topic": "weekly_summary",
        }

        col.add(documents=[f"[summary] {summary_text}"], metadatas=[metadata], ids=[doc_id])
        log.info(f"週次要約保存: id={doc_id}, importance={max_importance}")

        # 圧縮後の元エントリを削除（重複防止）
        col.delete(ids=target_ids)
        log.info(f"元エントリ削除: {len(target_ids)}件")

        return doc_id

    # ─── RAG検索 ─────────────────────────────────────────────────

    def search_context(self, query: str, n_results: int = 3) -> list[dict]:
        """personal_private + agent_memory をベクトル検索してRAGコンテキストを返す"""
        import chromadb

        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self.persist_dir))

        results = []
        for col_name in ["personal_private", "agent_memory"]:
            try:
                col = self._client.get_collection(col_name)
                res = col.query(query_texts=[query], n_results=n_results)
                docs = res.get("documents", [[]])[0]
                metas = res.get("metadatas", [[]])[0]
                for doc, meta in zip(docs, metas):
                    results.append({"content": doc, "meta": meta, "collection": col_name})
            except Exception:
                pass  # コレクション未存在やエラーは無視
        return results

    # ─── ユーティリティ ────────────────────────────────────────────

    def stats(self) -> dict:
        """コレクション統計を返す"""
        col = self._get_collection()
        all_data = col.get(include=["metadatas"])
        type_counts = {"chat": 0, "research": 0, "summary": 0}
        for meta in all_data["metadatas"]:
            t = meta.get("type", "unknown")
            if t in type_counts:
                type_counts[t] += 1
        return {
            "total": col.count(),
            "by_type": type_counts,
            "persist_dir": str(self.persist_dir),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    mm = MemoryManager()
    print("Stats:", json.dumps(mm.stats(), indent=2, ensure_ascii=False))
