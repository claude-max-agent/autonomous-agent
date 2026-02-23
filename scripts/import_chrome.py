#!/usr/bin/env python3
"""
import_chrome.py - Chrome履歴インポートスクリプト (Issue #5, #6)

Chrome の History SQLite ファイルを読み込み、PII除去後に
ChromaDB（personal_private コレクション）に格納する。

使い方:
  # デバイス名を指定して実行
  python scripts/import_chrome.py --device pc-home

  # ドライランで確認
  python scripts/import_chrome.py --device pc-home --dry-run

  # 全デバイスを一括インポート
  python scripts/import_chrome.py --all
"""

import argparse
import json
import logging
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from rag.pii_filter import filter_urls, mask_pii
from rag.vector_store import VectorStore, COLLECTION_PRIVATE

log = logging.getLogger(__name__)

DATA_DIR   = PROJECT_ROOT / "data"
RAW_DIR    = DATA_DIR / "raw" / "chrome"
PROC_DIR   = DATA_DIR / "processed" / "chrome"
CHROME_EPOCH = datetime(1601, 1, 1)

# 除外するURLプレフィックス（拡張子・内部ページ等）
SKIP_URL_PREFIXES = [
    "chrome://", "chrome-extension://", "about:", "data:", "file://",
    "devtools://",
]

# 2回以上訪問した URL のみ取り込む（ノイズ削減）
MIN_VISIT_COUNT = 2


def load_history(db_path: Path, limit: int = 5000) -> list[dict]:
    """Chrome History SQLite から訪問履歴を読み込む"""
    # ロック回避のため一時コピー
    tmp = Path("/tmp/chrome_history_import.db")
    shutil.copy(db_path, tmp)

    conn = sqlite3.connect(tmp)
    cur  = conn.cursor()

    cur.execute("""
        SELECT url, title, visit_count, last_visit_time
        FROM urls
        WHERE visit_count >= ?
        ORDER BY visit_count DESC
        LIMIT ?
    """, (MIN_VISIT_COUNT, limit))

    rows = []
    for url, title, count, ts in cur.fetchall():
        last_visit = CHROME_EPOCH + timedelta(microseconds=ts)
        rows.append({
            "url":          url,
            "title":        title or "",
            "visit_count":  count,
            "last_visit":   last_visit.isoformat(),
        })

    conn.close()
    tmp.unlink(missing_ok=True)
    return rows


def clean_entries(entries: list[dict]) -> list[dict]:
    """不要なエントリを除去・PIIをマスク"""
    cleaned = []
    for e in entries:
        url = e["url"]

        # スキップ対象
        if any(url.startswith(p) for p in SKIP_URL_PREFIXES):
            continue
        if not url.startswith(("http://", "https://")):
            continue

        # タイトルの PII マスク
        e["title"] = mask_pii(e["title"])
        cleaned.append(e)

    # PII フィルター（銀行・ログイン系 URL 除去）
    cleaned = filter_urls(cleaned, url_key="url")
    return cleaned


def entries_to_chunks(entries: list[dict], device: str) -> tuple[list[str], list[dict], list[str]]:
    """エントリをベクトルDB用チャンクに変換"""
    texts, metas, ids = [], [], []

    for e in entries:
        # テキスト: "タイトル: URL" 形式
        text = f"{e['title']}: {e['url']}" if e["title"] else e["url"]
        meta = {
            "source":      "chrome",
            "device":      device,
            "url":         e["url"],
            "visit_count": str(e["visit_count"]),
            "last_visit":  e["last_visit"],
        }
        uid = f"chrome_{device}_{abs(hash(e['url']))}"
        texts.append(text)
        metas.append(meta)
        ids.append(uid)

    return texts, metas, ids


def import_device(device: str, dry_run: bool = False) -> int:
    """指定デバイスの Chrome 履歴をインポート"""
    device_dir = RAW_DIR / device
    # History.db または History（拡張子なし）の両方に対応
    db_path = device_dir / "History.db"
    if not db_path.exists():
        db_path = device_dir / "History"

    if not db_path.exists():
        log.error(f"History file not found in: {device_dir}")
        log.info("手順: Chrome を完全終了後、以下を実行してください:")
        log.info(f'  cp "/mnt/c/Users/<User>/AppData/Local/Google/Chrome/User Data/Default/History" {device_dir}/History')
        return 0

    log.info(f"=== Importing Chrome history: {device} ({db_path}) ===")

    # 読み込み
    raw = load_history(db_path)
    log.info(f"Raw entries: {len(raw)}")

    # クリーニング
    cleaned = clean_entries(raw)
    log.info(f"After cleaning: {len(cleaned)} (removed {len(raw) - len(cleaned)})")

    if dry_run:
        log.info("[DRY RUN] 上位10件プレビュー:")
        for e in cleaned[:10]:
            print(f"  [{e['visit_count']:4d}] {e['title'][:50]} | {e['url'][:60]}")
        return len(cleaned)

    # 処理済み JSON を保存
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    proc_path = PROC_DIR / f"{device}_history.json"
    with open(proc_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    log.info(f"Saved: {proc_path}")

    # ChromaDB に格納
    texts, metas, ids = entries_to_chunks(cleaned, device)
    store = VectorStore()

    # 既存エントリを削除して再インポート（upsert 代替）
    col = store._get_collection(COLLECTION_PRIVATE)
    try:
        existing = col.get(where={"source": "chrome", "device": device})
        if existing["ids"]:
            col.delete(ids=existing["ids"])
            log.info(f"Deleted {len(existing['ids'])} existing entries for device={device}")
    except Exception as e:
        log.debug(f"Delete existing: {e}")

    added = store.add_documents(texts, metas, ids, COLLECTION_PRIVATE)
    log.info(f"Added {added} entries to ChromaDB (device={device})")

    stats = store.stats()
    log.info(f"DB stats: {stats}")
    return added


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    parser = argparse.ArgumentParser(description="Chrome履歴をChromaDBにインポート")
    parser.add_argument("--device",  default="pc-home", help="デバイス名 (例: pc-home, macbook)")
    parser.add_argument("--all",     action="store_true", help="全デバイスをインポート")
    parser.add_argument("--dry-run", action="store_true", help="インポートせずプレビューのみ")
    args = parser.parse_args()

    if args.all:
        devices = [d.name for d in RAW_DIR.iterdir() if d.is_dir()]
        log.info(f"All devices: {devices}")
        total = sum(import_device(d, args.dry_run) for d in devices)
    else:
        total = import_device(args.device, args.dry_run)

    print(f"\n完了: {total} 件インポートしました")


if __name__ == "__main__":
    main()
