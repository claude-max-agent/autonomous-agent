#!/usr/bin/env python3
"""
memory_cleanup.py - メモリクリーンアップバッチ (Issue #27)

単独実行可能なクリーンアップスクリプト。
cron等で毎週日曜 03:00 JST に実行することを想定。

処理内容:
  1. TTL切れエントリの削除
  2. 容量超過時の低importance順削除
  3. 直近7日分のchat/researchをOllamaで週次要約に圧縮

実行例:
  python scripts/memory_cleanup.py
  python scripts/memory_cleanup.py --cleanup-only   # 要約なし
  python scripts/memory_cleanup.py --summarize-only  # クリーンアップなし
"""

import argparse
import logging
import sys
from pathlib import Path

# scripts/ ディレクトリからの相対importを可能にする
sys.path.insert(0, str(Path(__file__).parent))

from memory_manager import MemoryManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="エージェントメモリ クリーンアップバッチ")
    parser.add_argument("--cleanup-only", action="store_true", help="TTL/容量クリーンアップのみ（要約なし）")
    parser.add_argument("--summarize-only", action="store_true", help="週次要約のみ（クリーンアップなし）")
    args = parser.parse_args()

    mm = MemoryManager()

    log.info("=== メモリクリーンアップ開始 ===")
    log.info(f"実行前: {mm.stats()}")

    # クリーンアップ
    if not args.summarize_only:
        stats = mm.cleanup()
        log.info(f"クリーンアップ結果: {stats}")

    # 週次要約
    if not args.cleanup_only:
        summary_id = mm.summarize_week()
        if summary_id:
            log.info(f"週次要約作成完了: id={summary_id}")
        else:
            log.info("週次要約: 対象なし or Ollama未稼働")

    log.info(f"実行後: {mm.stats()}")
    log.info("=== メモリクリーンアップ完了 ===")


if __name__ == "__main__":
    main()
