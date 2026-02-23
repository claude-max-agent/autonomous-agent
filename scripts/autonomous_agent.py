#!/usr/bin/env python3
"""
autonomous_agent.py - 毎朝リサーチ投稿デーモン (Phase 1)

スケジュール: 毎朝 08:00
フロー: observe → think → act → reflect → notify

LLM:
  - claude-haiku-4-5  : 軽量タスク（トレンド収集・テーマ選定）
  - claude-sonnet-4-6 : 重要タスク（記事草稿生成・自己評価）

安全設計:
  - 日次アクション上限: 50回
  - 全アクションをDiscord通知
  - 破壊的操作（git push, file delete等）は実行しない
"""

import os
import json
import logging
from datetime import datetime, date

import httpx
import anthropic
from apscheduler.schedulers.blocking import BlockingScheduler

# ─── 設定 ──────────────────────────────────────────────────────────────────
HUB_API_URL = os.getenv("HUB_API_URL", "http://localhost:8080")
DISCORD_CHANNEL = os.getenv("DISCORD_CHANNEL_ID", "1475499842800451616")
AGENT_NAME = "autonomous-agent"
MAX_DAILY_ACTIONS = 50

# リサーチトピック（曜日で交互）
# 月・水・金 = Web3, 火・木・土 = AI, 日 = 両方
TOPICS_WEB3 = "Web3 / DeFi / HyperLiquid / オンチェーン分析"
TOPICS_AI   = "AI / LLM / エージェント技術 / Claude / RAG"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
action_count = 0


# ─── ユーティリティ ──────────────────────────────────────────────────────────

def get_today_topics() -> str:
    """曜日に応じてリサーチトピックを決定（0=月, 6=日）"""
    weekday = date.today().weekday()
    if weekday in (0, 2, 4):   # 月・水・金
        return TOPICS_WEB3
    elif weekday in (1, 3, 5): # 火・木・土
        return TOPICS_AI
    else:                       # 日曜
        return f"{TOPICS_WEB3} / {TOPICS_AI}"


def notify_discord(message: str, is_alert: bool = False) -> None:
    """Hub API 経由で Discord に通知"""
    try:
        httpx.post(
            f"{HUB_API_URL}/api/v1/discord/reply",
            json={
                "channel_id": DISCORD_CHANNEL,
                "message": message,
                "sender_name": AGENT_NAME,
            },
            timeout=10,
        )
    except Exception as e:
        log.warning(f"Discord通知失敗: {e}")


def count_action(label: str) -> bool:
    """アクション数をカウント。上限超過でFalseを返す"""
    global action_count
    action_count += 1
    if action_count > MAX_DAILY_ACTIONS:
        log.warning(f"日次アクション上限({MAX_DAILY_ACTIONS})超過。スキップ: {label}")
        notify_discord(f"⚠️ 日次アクション上限到達。本日の処理を停止します。")
        return False
    log.info(f"[action {action_count}/{MAX_DAILY_ACTIONS}] {label}")
    return True


# ─── observe ────────────────────────────────────────────────────────────────

def fetch_hn_top(n: int = 10) -> list[dict]:
    """Hacker News Top Stories を取得"""
    try:
        r = httpx.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=10,
        )
        ids = r.json()[:n]
        stories = []
        for sid in ids:
            item = httpx.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                timeout=5,
            ).json()
            if item and item.get("title"):
                stories.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "score": item.get("score", 0),
                })
        return stories
    except Exception as e:
        log.warning(f"HN取得失敗: {e}")
        return []


def fetch_github_trending(topic_hint: str) -> list[dict]:
    """GitHub Trending に近い情報を GitHub Search API で代替取得"""
    # GitHubのTrending APIは非公式のため、過去7日の高スターリポジトリで代替
    query = "ai llm agent" if "AI" in topic_hint else "defi web3 blockchain"
    try:
        r = httpx.get(
            "https://api.github.com/search/repositories",
            params={
                "q": f"{query} created:>2026-02-17",
                "sort": "stars",
                "order": "desc",
                "per_page": 5,
            },
            headers={"Accept": "application/vnd.github+json"},
            timeout=10,
        )
        repos = r.json().get("items", [])
        return [
            {
                "name": repo["full_name"],
                "description": repo.get("description", ""),
                "stars": repo["stargazers_count"],
                "url": repo["html_url"],
            }
            for repo in repos
        ]
    except Exception as e:
        log.warning(f"GitHub trending取得失敗: {e}")
        return []


def observe(topics: str) -> dict:
    """環境を観察してコンテキストを収集"""
    log.info("=== [observe] トレンド収集開始 ===")
    hn_stories = fetch_hn_top(10)
    gh_repos = fetch_github_trending(topics)
    context = {
        "date": date.today().isoformat(),
        "topics": topics,
        "hn_stories": hn_stories,
        "gh_repos": gh_repos,
    }
    log.info(f"HN: {len(hn_stories)}件, GitHub: {len(gh_repos)}件")
    return context


# ─── think ──────────────────────────────────────────────────────────────────

def think(context: dict) -> str:
    """Claude Haiku でテーマを選定"""
    if not count_action("think: テーマ選定"):
        return ""

    log.info("=== [think] テーマ選定 (claude-haiku-4-5) ===")
    prompt = f"""今日のリサーチテーマを1つ選定してください。

対象トピック: {context['topics']}
日付: {context['date']}

Hacker News トレンド:
{json.dumps(context['hn_stories'], ensure_ascii=False, indent=2)}

GitHub 注目リポジトリ:
{json.dumps(context['gh_repos'], ensure_ascii=False, indent=2)}

上記を踏まえ、Zenn記事として最も価値が高いと思われるテーマを1行で答えてください。
形式: 「テーマ: <テーマ名>（理由: <50字以内>）」"""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    theme = resp.content[0].text.strip()
    log.info(f"選定テーマ: {theme}")
    return theme


# ─── act ────────────────────────────────────────────────────────────────────

def act(theme: str, context: dict) -> str:
    """Claude Sonnet で Zenn 記事草稿を生成"""
    if not theme or not count_action("act: 記事草稿生成"):
        return ""

    log.info("=== [act] 記事草稿生成 (claude-sonnet-4-6) ===")
    prompt = f"""以下のテーマでZenn技術記事の草稿を生成してください。

テーマ: {theme}
日付: {context['date']}

参考情報:
{json.dumps(context['hn_stories'][:5], ensure_ascii=False, indent=2)}

要件:
- Zennのmarkdown形式（frontmatter付き）
- 文字数: 1500〜2500字程度
- 対象読者: エンジニア（Web3/AI領域）
- 独自の考察・意見を含める
- published: false で下書き状態に

frontmatterのtopicsは実際のZennタグ名（英小文字）を使うこと。"""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    draft = resp.content[0].text.strip()
    log.info(f"草稿生成完了: {len(draft)}文字")
    return draft


# ─── reflect ────────────────────────────────────────────────────────────────

def reflect(draft: str, theme: str) -> dict:
    """草稿の品質を自己評価"""
    if not draft or not count_action("reflect: 自己評価"):
        return {"score": 0, "comment": "スキップ"}

    log.info("=== [reflect] 自己評価 (claude-haiku-4-5) ===")
    prompt = f"""以下のZenn記事草稿を評価してください。

テーマ: {theme}

---
{draft[:2000]}
---

以下の観点で100点満点で採点し、JSON形式で返してください:
- coherence: 論理的一貫性（0-30）
- originality: 独自性・新規性（0-30）
- readability: 読みやすさ（0-20）
- accuracy: 技術的正確性（0-20）

形式: {{"coherence": N, "originality": N, "readability": N, "accuracy": N, "total": N, "comment": "一言コメント"}}"""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    try:
        # JSONブロックを抽出
        start = text.find("{")
        end = text.rfind("}") + 1
        result = json.loads(text[start:end])
    except Exception:
        result = {"total": 0, "comment": "評価パース失敗", "raw": text}
    log.info(f"自己評価: {result}")
    return result


# ─── メインタスク ────────────────────────────────────────────────────────────

def daily_research():
    """毎朝08:00に実行されるメインタスク"""
    global action_count
    action_count = 0  # 日次リセット

    today = date.today().isoformat()
    topics = get_today_topics()
    log.info(f"=== 毎朝リサーチ開始: {today} / テーマ: {topics} ===")
    notify_discord(f"🌅 毎朝リサーチ開始\n日付: {today}\nトピック: {topics}")

    # observe
    context = observe(topics)

    # think
    theme = think(context)
    if not theme:
        notify_discord("⚠️ テーマ選定に失敗しました。本日の処理を中断します。", is_alert=True)
        return

    # act
    draft = act(theme, context)
    if not draft:
        notify_discord("⚠️ 記事草稿生成に失敗しました。", is_alert=True)
        return

    # reflect
    evaluation = reflect(draft, theme)

    # notify
    score = evaluation.get("total", "?")
    comment = evaluation.get("comment", "")
    notify_discord(
        f"✅ 本日のリサーチ投稿完了\n"
        f"テーマ: {theme}\n"
        f"品質スコア: {score}/100（{comment}）\n\n"
        f"---\n{draft[:1500]}\n\n"
        f"{'...(続き省略)' if len(draft) > 1500 else ''}"
    )
    log.info(f"=== 毎朝リサーチ完了: スコア{score} ===")


# ─── エントリポイント ────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("autonomous_agent 起動")
    notify_discord("🤖 autonomous_agent が起動しました。毎朝 08:00 にリサーチを実行します。")

    scheduler = BlockingScheduler(timezone="Asia/Tokyo")
    scheduler.add_job(
        daily_research,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_research",
        name="毎朝リサーチ投稿",
    )

    # 起動時に即時実行するオプション（テスト用）
    if os.getenv("RUN_NOW") == "1":
        log.info("RUN_NOW=1 検出: 即時実行します")
        daily_research()

    log.info("スケジューラ起動: 毎朝 08:00 JST")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("autonomous_agent 停止")
        notify_discord("🛑 autonomous_agent が停止しました。")
