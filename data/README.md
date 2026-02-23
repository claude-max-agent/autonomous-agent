# data/

個人データのローカルストレージ。**全データはgit管理対象外**（.gitignoreで除外済み）。

## ディレクトリ構成

```
data/
├── raw/                    # 生データ（変換前）
│   ├── twitter/            # Twitterアーカイブ
│   │   ├── account-main/   # メインアカウント (@username)
│   │   │   └── data/       # アーカイブZIP展開先
│   │   └── account-sub/    # サブアカウント
│   │       └── data/
│   └── chrome/             # Chrome閲覧履歴
│       ├── pc-home/        # ホームPC（WSL2）
│       │   └── History.db  # Chromeの History SQLiteコピー
│       └── pc-work/        # 会社PC
│           └── History.db
│
├── processed/              # 前処理済みデータ（JSON）
│   ├── twitter/
│   │   └── <account>_tweets_clean.json
│   └── chrome/
│       └── <device>_history.json
│
└── embeddings/             # ベクトルDB（ChromaDB等）
    └── personal_rag/       # 個人RAGのベクトルストア
```

## デバイス・アカウントの追加方法

### 新しいTwitterアカウントを追加
```bash
mkdir -p data/raw/twitter/<account-name>
# アーカイブZIPを展開してここに配置
```

### 新しいデバイスを追加
```bash
mkdir -p data/raw/chrome/<device-name>
# Chromeの History ファイルをコピーしてここに配置
# Windows例: cp "/mnt/c/Users/<User>/AppData/Local/Google/Chrome/User Data/Default/History" data/raw/chrome/<device-name>/History.db
```

## インポート手順

```bash
# Twitter アーカイブ前処理
python scripts/import_twitter.py --account account-main

# Chrome 履歴インポート
python scripts/import_chrome.py --device pc-home

# 全データ再インデックス（RAG）
python scripts/reindex.py
```

## 注意事項

- `data/raw/` はgit管理外。バックアップは別途行うこと
- `data/embeddings/` はスクリプトから再生成可能（gitに含めない）
- アーカイブファイルは定期的に更新すること（Twitter: 月1回推奨）
