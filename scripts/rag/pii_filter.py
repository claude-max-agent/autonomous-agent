"""
pii_filter.py - PII（個人識別情報）除去フィルター

Chrome履歴・テキストデータからセンシティブな情報を除去する。
LlamaIndex PIINodePostprocessor のシンプル代替実装。
"""

import re
from urllib.parse import urlparse

# ─── 除外URLパターン ─────────────────────────────────────────────────────────

EXCLUDE_URL_PATTERNS = [
    # 金融・銀行
    r"bank\.", r"banking\.", r"pay\.", r"payment", r"checkout",
    r"smbc\.", r"mufg\.", r"mizuho\.", r"rakuten-bank", r"sbi-sec",
    # 認証・ログイン
    r"login\.", r"signin", r"sign-in", r"auth\.", r"oauth",
    r"accounts\.google", r"account\.microsoft", r"id\.apple",
    # メール・メッセージ
    r"mail\.google", r"outlook\.live", r"outlook\.com/mail",
    r"mail\.yahoo", r"icloud\.com/mail",
    # パスワード管理
    r"password", r"1password", r"lastpass", r"bitwarden",
    # 医療・健康
    r"medical\.", r"hospital\.", r"clinic\.", r"pharmacy",
    # プライベート・内部URL
    r"localhost", r"192\.168\.", r"10\.\d+\.\d+\.", r"172\.\d+\.",
    r"internal\.", r"intranet\.",
]

EXCLUDE_DOMAINS = {
    "accounts.google.com",
    "myaccount.google.com",
    "security.google.com",
    "id.apple.com",
    "appleid.apple.com",
    "login.microsoftonline.com",
    "1password.com",
    "lastpass.com",
}

# ─── テキスト内PII除去パターン ────────────────────────────────────────────────

PII_TEXT_PATTERNS = [
    # メールアドレス
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
    # 日本の電話番号
    (r'0[789]0[-\s]?\d{4}[-\s]?\d{4}', '[PHONE]'),
    (r'0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4}', '[PHONE]'),
    # クレジットカード番号（簡易）
    (r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '[CARD]'),
    # 郵便番号
    (r'\b\d{3}-\d{4}\b', '[POSTAL]'),
    # マイナンバー（12桁）
    (r'\b\d{4}\s?\d{4}\s?\d{4}\b', '[ID]'),
]


# ─── URL フィルター ───────────────────────────────────────────────────────────

def is_sensitive_url(url: str) -> bool:
    """URLがセンシティブかどうかを判定"""
    url_lower = url.lower()

    # ドメイン除外リスト
    try:
        domain = urlparse(url).netloc.lower()
        if domain in EXCLUDE_DOMAINS:
            return True
    except Exception:
        pass

    # パターンマッチング
    for pattern in EXCLUDE_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return True

    return False


def filter_urls(entries: list[dict], url_key: str = "url") -> list[dict]:
    """URLリストからセンシティブなエントリを除去"""
    filtered = [e for e in entries if not is_sensitive_url(e.get(url_key, ""))]
    removed = len(entries) - len(filtered)
    if removed > 0:
        import logging
        logging.getLogger(__name__).info(f"PII filter: {removed}件のセンシティブURLを除去")
    return filtered


# ─── テキスト PII マスキング ──────────────────────────────────────────────────

def mask_pii(text: str) -> str:
    """テキスト内のPII（メール・電話番号等）をマスキング"""
    for pattern, replacement in PII_TEXT_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def filter_tweets(tweets: list[dict], text_key: str = "text") -> list[dict]:
    """ツイートリストのPIIをマスキング"""
    return [
        {**t, text_key: mask_pii(t.get(text_key, ""))}
        for t in tweets
    ]


# ─── テスト ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_urls = [
        "https://www.google.com",
        "https://accounts.google.com/login",
        "https://pay.example.com/checkout",
        "https://github.com/trending",
        "https://mail.google.com/mail/u/0/",
        "https://zenn.dev/articles",
    ]
    print("=== URL Filter Test ===")
    for url in test_urls:
        status = "EXCLUDED" if is_sensitive_url(url) else "OK"
        print(f"  [{status}] {url}")

    test_texts = [
        "連絡先: test@example.com",
        "電話: 090-1234-5678",
        "普通のテキスト",
    ]
    print("\n=== PII Masking Test ===")
    for text in test_texts:
        print(f"  原文: {text}")
        print(f"  処理後: {mask_pii(text)}")
