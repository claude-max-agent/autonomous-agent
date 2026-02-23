"""
semantic_router.py - Private/Public DB ルーティング

aurelio-labs/semantic-router の軽量代替実装（Phase 1）。
Phase 2 以降で本家 semantic-router に置き換え予定。

ルーティング方針:
  - "自分自身", "私が", "昨日", "日記", "ツイート" → PRIVATE
  - "著書", "論文", "一般的に", "世間では"         → PUBLIC
  - その他 → BOTH（両方から検索してマージ）
"""

import re
import logging
from enum import Enum

log = logging.getLogger(__name__)


class Route(Enum):
    PRIVATE = "private"   # 個人プライベートデータ
    PUBLIC  = "public"    # 公開知識・著名人IP
    BOTH    = "both"      # 両方から検索


# ─── ルーティングキーワード定義 ───────────────────────────────────────────────

PRIVATE_KEYWORDS = [
    # 一人称・自己言及
    r"私(が|は|の|を|に|で|も|って|的|自身)",
    r"自分(が|は|の|を|に|で|も|って|的|自身)",
    r"僕(が|は|の|を|に|で|も|って)",
    r"俺(が|は|の|を|に|で|も|って)",
    # 個人記録
    r"(昨日|今日|先週|先月|今週|最近|去年)(の|は|に|も)",
    r"日記",
    r"メモ",
    r"ツイート",
    r"つぶやい",
    r"書いた(こと|もの)",
    r"覚えてる",
    r"いつも(の|は|思って)",
    r"(好き|嫌い)な(もの|こと|ん)",
    # 個人的な感想・意見
    r"(思う|感じ|考え)(た|てる|てた|ている)",
    r"個人的(に|な)",
]

PUBLIC_KEYWORDS = [
    # 公開知識
    r"著書",
    r"論文",
    r"研究",
    r"(公開|発表)(した|の)",
    r"インタビュー",
    r"一般的(に|な)",
    r"世間(で|では|の)",
    r"ニュース",
    r"記事",
    r"資料",
    # 有名人・著名人
    r"(の|が)(言って|発言|主張|提唱)",
]


def route(query: str) -> Route:
    """クエリを解析してルーティング先を決定"""
    private_score = sum(
        1 for p in PRIVATE_KEYWORDS if re.search(p, query)
    )
    public_score = sum(
        1 for p in PUBLIC_KEYWORDS if re.search(p, query)
    )

    log.debug(f"Route scores — private: {private_score}, public: {public_score}")

    if private_score > public_score:
        return Route.PRIVATE
    elif public_score > private_score:
        return Route.PUBLIC
    else:
        return Route.BOTH


def route_and_search(
    query: str,
    vector_store,
    n_results: int = 5,
) -> list[dict]:
    """ルーティングして対応するDBを検索、結果を返す"""
    from .vector_store import COLLECTION_PRIVATE, COLLECTION_PUBLIC

    destination = route(query)
    log.info(f"Query routed to: {destination.value} | '{query[:60]}'")

    results = []
    if destination in (Route.PRIVATE, Route.BOTH):
        private_docs = vector_store.query(query, n_results, COLLECTION_PRIVATE)
        for doc in private_docs:
            doc["source"] = "private"
        results.extend(private_docs)

    if destination in (Route.PUBLIC, Route.BOTH):
        public_docs = vector_store.query(query, n_results, COLLECTION_PUBLIC)
        for doc in public_docs:
            doc["source"] = "public"
        results.extend(public_docs)

    # 距離スコアでソート（昇順 = 類似度高い順）
    results.sort(key=lambda x: x.get("distance") or 1.0)
    return results[:n_results]


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_queries = [
        "私が最近興味を持っていること",
        "論文で発表されている最新のRAG手法",
        "エージェントの実装方法",
        "昨日ツイートした内容",
        "一般的なLLMの使い方",
    ]
    print("=== Routing Test ===")
    for q in test_queries:
        r = route(q)
        print(f"  [{r.value:8s}] {q}")
