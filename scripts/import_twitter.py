#!/usr/bin/env python3
"""
import_twitter.py - Twitterアーカイブインポートスクリプト (Issue #21)

tweets.js を読み込み、PII除去後に Ollama bge-m3 で埋め込みを生成し、
ChromaDB（personal_private コレクション）に格納する。

使い方:
  # 通常実行
  python scripts/import_twitter.py

  # ドライランで確認
  python scripts/import_twitter.py --dry-run

  # バッチサイズ変更
  python scripts/import_twitter.py --batch-size 200
"""

import argparse
import html
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from rag.pii_filter import mask_pii
from rag.vector_store import COLLECTION_PRIVATE

log = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw" / "twitter" / "account-main" / "data"
PROC_DIR = DATA_DIR / "processed" / "twitter"
TWEETS_JS = RAW_DIR / "tweets.js"

OLLAMA_URL = "http://localhost:11434/api/embeddings"
OLLAMA_MODEL = "bge-m3"

BATCH_SIZE = 100


def load_tweets(path: Path) -> list[dict]:
    """tweets.js をパースしてツイートリストを返す"""
    content = path.read_text(encoding="utf-8")
    # "window.YTD.tweets.part0 = " プレフィックスを除去
    prefix = "window.YTD.tweets.part0 = "
    if not content.startswith(prefix):
        raise ValueError(f"Unexpected file format: {path}")
    data = json.loads(content[len(prefix):])
    return [item["tweet"] for item in data]


def is_retweet(tweet: dict) -> bool:
    """リツイートかどうか"""
    return tweet.get("full_text", "").startswith("RT @")


def is_url_only(text: str) -> bool:
    """URL のみのテキストかどうか"""
    stripped = re.sub(r"https?://\S+", "", text).strip()
    return len(stripped) == 0


def expand_urls(tweet: dict) -> str:
    """t.co短縮URLを展開URLに置換し、HTML entitiesをデコード"""
    text = tweet.get("full_text", "")

    # entities.urls から展開URLマッピングを構築
    urls = tweet.get("entities", {}).get("urls", [])
    for url_entity in urls:
        short_url = url_entity.get("url", "")
        expanded = url_entity.get("expanded_url", "")
        if short_url and expanded:
            text = text.replace(short_url, expanded)

    # メディアURLを除去（画像・動画リンク）
    media = tweet.get("entities", {}).get("media", [])
    for m in media:
        short_url = m.get("url", "")
        if short_url:
            text = text.replace(short_url, "")

    # 残った t.co リンクを除去
    text = re.sub(r"https://t\.co/\S+", "", text)

    # HTML entities デコード
    text = html.unescape(text)

    # 末尾空白をトリム
    text = text.strip()

    return text


def classify_tweet(tweet: dict) -> str:
    """ツイートをreply/tweetに分類"""
    if tweet.get("in_reply_to_status_id_str"):
        return "reply"
    return "tweet"


def process_tweets(tweets: list[dict]) -> list[dict]:
    """ツイートをフィルタリング・正規化"""
    processed = []
    stats = {"total": len(tweets), "rt": 0, "empty": 0, "url_only": 0, "kept": 0}

    for tweet in tweets:
        # リツイート除外
        if is_retweet(tweet):
            stats["rt"] += 1
            continue

        # テキスト正規化
        text = expand_urls(tweet)

        # 空テキスト除外
        if not text:
            stats["empty"] += 1
            continue

        # URL only 除外
        if is_url_only(text):
            stats["url_only"] += 1
            continue

        # PII除去
        text = mask_pii(text)

        # メタデータ
        source_type = classify_tweet(tweet)
        created_at = tweet.get("created_at", "")

        processed.append({
            "id": tweet.get("id_str", tweet.get("id", "")),
            "text": text,
            "created_at": created_at,
            "lang": tweet.get("lang", ""),
            "source_type": source_type,
            "like_count": int(tweet.get("favorite_count", 0)),
        })
        stats["kept"] += 1

    return processed, stats


def get_chromadb_collection():
    """ChromaDBコレクションを取得（既存コレクションと一貫したデフォルトef使用）"""
    import chromadb

    persist_dir = DATA_DIR / "embeddings" / "chromadb"
    persist_dir.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(persist_dir))
    # 既存の personal_private コレクション（Chrome履歴2178件）はデフォルトefで作成済み。
    # 一貫性を保つためefを指定せずデフォルト（all-MiniLM-L6-v2）を使用する。
    collection = client.get_or_create_collection(
        name=COLLECTION_PRIVATE,
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def import_tweets(processed: list[dict], batch_size: int, dry_run: bool = False) -> int:
    """処理済みツイートをChromaDBに格納"""
    if dry_run:
        log.info("[DRY RUN] 上位10件プレビュー:")
        for t in processed[:10]:
            print(f"  [{t['source_type']:5s} likes:{t['like_count']:3d}] {t['text'][:80]}")
        return len(processed)

    collection = get_chromadb_collection()

    # 既存IDを取得して冪等実行
    existing_ids = set()
    try:
        result = collection.get(where={"source": "twitter"})
        existing_ids = set(result["ids"])
        log.info(f"既存のTwitterエントリ: {len(existing_ids)}件")
    except Exception:
        pass

    added_total = 0
    skipped = 0

    for i in range(0, len(processed), batch_size):
        batch = processed[i:i + batch_size]

        # 冪等: 既存IDスキップ
        texts, metas, ids = [], [], []
        for t in batch:
            tid = f"tweet_{t['id']}"
            if tid in existing_ids:
                skipped += 1
                continue
            texts.append(t["text"])
            metas.append({
                "source": "twitter",
                "tweet_id": t["id"],
                "created_at": t["created_at"],
                "lang": t["lang"],
                "source_type": t["source_type"],
                "like_count": t["like_count"],
            })
            ids.append(tid)

        if not texts:
            continue

        collection.add(documents=texts, metadatas=metas, ids=ids)
        added_total += len(texts)

        progress = min(i + batch_size, len(processed))
        log.info(f"  進捗: {progress}/{len(processed)} (+{len(texts)}件追加)")

    return added_total, skipped


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(description="TwitterアーカイブをChromaDBにインポート")
    parser.add_argument("--dry-run", action="store_true", help="インポートせずプレビューのみ")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help=f"バッチサイズ (default: {BATCH_SIZE})")
    parser.add_argument("--tweets-js", type=Path, default=TWEETS_JS, help="tweets.js のパス")
    args = parser.parse_args()

    if not args.tweets_js.exists():
        log.error(f"tweets.js が見つかりません: {args.tweets_js}")
        sys.exit(1)

    # 読み込み
    log.info(f"=== Twitter Archive Import ===")
    log.info(f"Source: {args.tweets_js}")
    tweets = load_tweets(args.tweets_js)
    log.info(f"読み込み: {len(tweets)}件")

    # 処理
    processed, stats = process_tweets(tweets)
    log.info(f"フィルタリング結果:")
    log.info(f"  総数:      {stats['total']}")
    log.info(f"  RT除外:    {stats['rt']}")
    log.info(f"  空テキスト: {stats['empty']}")
    log.info(f"  URL only:  {stats['url_only']}")
    log.info(f"  取り込み:  {stats['kept']}")

    # 処理済みJSON保存
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    proc_path = PROC_DIR / "tweets_processed.json"
    with open(proc_path, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)
    log.info(f"処理済みデータ保存: {proc_path}")

    # インポート
    if args.dry_run:
        import_tweets(processed, args.batch_size, dry_run=True)
        print(f"\n[DRY RUN] {stats['kept']}件が取り込み対象です")
    else:
        added, skipped = import_tweets(processed, args.batch_size)
        print(f"\n=== サマリー ===")
        print(f"  新規追加: {added}件")
        print(f"  スキップ(既存): {skipped}件")
        print(f"  合計取り込み対象: {stats['kept']}件")


if __name__ == "__main__":
    main()
