# Changelog

## [0.3.0] - 2026-02-25

### Added
- `scripts/import_twitter.py`: Twitterアーカイブ（tweets.js）→ ChromaDB取り込みスクリプト (Issue #21)
  - Ollama bge-m3 による埋め込み生成
  - RT除外・URL展開・PII除去・冪等実行対応
  - バッチ処理（100件単位）＋進捗表示
- `data/persona.json`: 実際のツイートから分析した@ZONO_819のペルソナ定義 (Issue #21)
- `Modelfile`: qwen3:8b ベースのペルソナカスタムモデル定義 (Issue #22)
