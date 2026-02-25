#!/usr/bin/env python3
"""
autonomous_agent.py - 毎朝リサーチ投稿デーモン (Phase 2)

スケジュール: 毎朝 08:00
フロー: observe → think → act → reflect → notify

LLM（ハイブリッド構成 - Issue #1）:
  - Ollama / qwen3:8b : 軽量タスク優先（テーマ選定・自己評価）
  - claude-haiku-4-5  : Ollama不可時のフォールバック
  - claude-sonnet-4-6 : 複雑タスク専用（記事草稿生成）

安全設計:
  - 日次アクション上限: 50回
  - 全アクションをDiscord通知
  - 破壊的操作（git push, file delete等）は実行しない

チャンネル:
  - hub-autonomous (DISCORD_CHANNEL_ID)    : メインアクション結果の通知
  - agent-diary   (DIARY_CHANNEL_ID)       : 思考プロセス・内省・独り言（Issue #9）
  - agent-chat    (AGENT_CHAT_CHANNEL_ID)  : Admin直接対話（qwen3:8b応答、Issue #18）
"""

import os
import glob
import json
import logging
from datetime import datetime, date

import signal
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import anthropic
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.executors.pool import ThreadPoolExecutor

# ─── 設定 ──────────────────────────────────────────────────────────────────
HUB_API_URL = os.getenv("HUB_API_URL", "http://localhost:8080")
DISCORD_CHANNEL = os.getenv("DISCORD_CHANNEL_ID", "1475499842800451616")   # hub-autonomous
DIARY_CHANNEL   = os.getenv("DIARY_CHANNEL_ID",   "1475552269222154312")   # agent-diary (Issue #9)
CHAT_CHANNEL    = os.getenv("AGENT_CHAT_CHANNEL_ID", "1475867265110114379") # agent-chat (Issue #18)
AGENT_NAME = "autonomous-agent"
MAX_DAILY_ACTIONS = 50
AGENT_CHAT_DIR = "/tmp/autonomous-agent-chat"  # Go APIがここにchatメッセージを書き込む
AGENT_CHAT_PORT = int(os.getenv("AGENT_CHAT_PORT", "18400"))

# Ollama設定（Issue #1: ローカルLLM）
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_MODEL_CHAT = os.getenv("OLLAMA_MODEL_CHAT", "zono-agent:latest")

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
    """hub-autonomous チャンネルにアクション結果を通知"""
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


DIARY_EMOJI = {
    "observe":  "👀",
    "think":    "🤔",
    "act":      "✍️",
    "reflect":  "📝",
    "daily":    "🌙",
    "startup":  "🤖",
    "error":    "⚠️",
}

def post_diary(content: str, step: str = "think") -> None:
    """agent-diary チャンネルに思考プロセス・内省を投稿（Issue #9）"""
    emoji = DIARY_EMOJI.get(step, "💭")
    try:
        httpx.post(
            f"{HUB_API_URL}/api/v1/discord/reply",
            json={
                "channel_id": DIARY_CHANNEL,
                "message": f"{emoji} **[{step}]** {content}",
                "sender_name": AGENT_NAME,
            },
            timeout=10,
        )
        log.debug(f"Diary posted [{step}]: {content[:60]}")
    except Exception as e:
        log.warning(f"Diary投稿失敗: {e}")


# ─── ローカルLLM（Ollama）─────────────────────────────────────────────────

class LocalLLM:
    """Ollama ローカルLLMクライアント（Issue #1）"""

    @staticmethod
    def is_available() -> bool:
        """Ollamaサーバーが稼働中か確認"""
        try:
            r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    @staticmethod
    def generate(prompt: str, max_tokens: int = 500) -> str:
        """ローカルLLM（qwen3:8b）で推論。think:false でシンキングモード無効化"""
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "think": False,   # qwen3のシンキングモードを無効化（高速化）
                "options": {"num_predict": max_tokens, "temperature": 0.7},
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["response"].strip()


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

    # agent-diary: 観察ログ
    hn_titles = ", ".join(s["title"][:30] for s in hn_stories[:3]) if hn_stories else "なし"
    gh_names  = ", ".join(r["name"].split("/")[-1] for r in gh_repos[:3]) if gh_repos else "なし"
    post_diary(
        f"トレンド収集完了\nトピック: {topics}\n"
        f"HN注目: {hn_titles}\nGitHub注目: {gh_names}",
        step="observe",
    )
    return context


# ─── think ──────────────────────────────────────────────────────────────────

def think(context: dict) -> str:
    """テーマ選定: Ollama優先、Claude Haikuフォールバック（Issue #1）"""
    if not count_action("think: テーマ選定"):
        return ""

    prompt = f"""今日のリサーチテーマを1つ選定してください。

対象トピック: {context['topics']}
日付: {context['date']}

Hacker News トレンド:
{json.dumps(context['hn_stories'], ensure_ascii=False, indent=2)}

GitHub 注目リポジトリ:
{json.dumps(context['gh_repos'], ensure_ascii=False, indent=2)}

上記を踏まえ、Zenn記事として最も価値が高いと思われるテーマを1行で答えてください。
形式: 「テーマ: <テーマ名>（理由: <50字以内>）」"""

    # Ollama優先
    if LocalLLM.is_available():
        log.info(f"=== [think] テーマ選定 (ollama: {OLLAMA_MODEL}) ===")
        try:
            theme = LocalLLM.generate(prompt, max_tokens=200)
            log.info(f"選定テーマ (Ollama): {theme}")
            post_diary(f"{theme}", step="think")
            return theme
        except Exception as e:
            log.warning(f"Ollama失敗、Claude Haikuにフォールバック: {e}")

    # Claude Haiku フォールバック
    log.info("=== [think] テーマ選定 (claude-haiku-4-5) ===")
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    theme = resp.content[0].text.strip()
    log.info(f"選定テーマ (Claude): {theme}")

    # agent-diary: テーマ選定の思考プロセス
    post_diary(f"{theme}", step="think")
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
    """草稿の品質を自己評価: Ollama優先、Claude Haikuフォールバック（Issue #1）"""
    if not draft or not count_action("reflect: 自己評価"):
        return {"score": 0, "comment": "スキップ"}

    # Ollama用は短縮版（500字）、Claude用はフル版（2000字）
    draft_short = draft[:500]
    draft_full  = draft[:2000]

    prompt_ollama = f"""以下のZenn記事草稿を評価してください。

テーマ: {theme}

---
{draft_short}
---

以下の観点で100点満点で採点し、JSON形式のみで返してください:
形式: {{"coherence": N, "originality": N, "readability": N, "accuracy": N, "total": N, "comment": "一言コメント"}}"""

    prompt_claude = f"""以下のZenn記事草稿を評価してください。

テーマ: {theme}

---
{draft_full}
---

以下の観点で100点満点で採点し、JSON形式で返してください:
- coherence: 論理的一貫性（0-30）
- originality: 独自性・新規性（0-30）
- readability: 読みやすさ（0-20）
- accuracy: 技術的正確性（0-20）

形式: {{"coherence": N, "originality": N, "readability": N, "accuracy": N, "total": N, "comment": "一言コメント"}}"""

    text = ""
    # Ollama優先（短縮プロンプトで高速評価）
    if LocalLLM.is_available():
        log.info(f"=== [reflect] 自己評価 (ollama: {OLLAMA_MODEL}) ===")
        try:
            text = LocalLLM.generate(prompt_ollama, max_tokens=150)
            log.info(f"自己評価応答 (Ollama): {text[:100]}")
        except Exception as e:
            log.warning(f"Ollama失敗、Claude Haikuにフォールバック: {e}")
            text = ""

    # Claude Haiku フォールバック
    if not text:
        log.info("=== [reflect] 自己評価 (claude-haiku-4-5) ===")
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt_claude}],
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

    # agent-diary: 内省ログ
    total   = result.get("total", "?")
    comment = result.get("comment", "")
    coherence    = result.get("coherence", "?")
    originality  = result.get("originality", "?")
    readability  = result.get("readability", "?")
    accuracy     = result.get("accuracy", "?")
    post_diary(
        f"自己評価スコア: {total}/100\n"
        f"内訳: 一貫性{coherence} / 独自性{originality} / 読みやすさ{readability} / 正確性{accuracy}\n"
        f"所感: {comment}",
        step="reflect",
    )
    return result


# ─── agent-chat ハンドラ（Issue #18, #31）──────────────────────────────────

def judge_importance(sender: str, message: str, response: str) -> float:
    """Ollamaで会話の重要度を1-10で判定"""
    prompt = f"""以下の会話の重要度を1〜10で評価してください（数字のみ返答）。
重要度が高い条件: 技術的な洞察・重要な決定・個人的な関心事・将来参照する可能性

会話:
[{sender}]: {message}
[応答]: {response[:300]}

重要度（1〜10の整数のみ）:"""
    try:
        score_text = LocalLLM.generate(prompt, max_tokens=5)
        return min(10.0, max(1.0, float(score_text.strip()[:3])))
    except Exception:
        return 5.0


def chat_handler(message: str, sender: str, reply_channel_id: str) -> None:
    """agent-chat チャンネルからのメッセージを zono-agent:latest で処理して返信（Issue #31）"""
    log.info(f"💬 chat_handler: {sender}: {message[:80]}")

    prompt = (
        f"{sender} からメッセージが届きました。\n\n"
        f"メッセージ:\n{message}\n\n"
        "日本語で簡潔かつ的確に回答してください。"
    )

    try:
        if LocalLLM.is_available():
            resp = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL_CHAT,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": 800, "temperature": 0.7},
                },
                timeout=120,
            )
            resp.raise_for_status()
            response = resp.json()["response"].strip()
            llm_label = OLLAMA_MODEL_CHAT
        else:
            # Claude Haiku フォールバック
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            response = resp.content[0].text.strip()
            llm_label = "Claude Haiku (fallback)"
    except Exception as e:
        log.error(f"chat_handler LLM error: {e}")
        response = f"⚠️ エラーが発生しました: {e}"
        llm_label = "error"

    # agent-chat チャンネルに返信
    try:
        httpx.post(
            f"{HUB_API_URL}/api/v1/discord/reply",
            json={
                "channel_id": reply_channel_id,
                "message": f"💬 [{llm_label}] {response}",
                "sender_name": AGENT_NAME,
            },
            timeout=10,
        )
    except Exception as e:
        log.warning(f"chat_handler Discord返信失敗: {e}")

    post_diary(f"**{sender}**: {message[:100]}\n→ {response[:200]}", step="think")

    # MemoryManager: importance自動判定してChromaDB保存
    try:
        from memory_manager import MemoryManager
        importance = judge_importance(sender, message, response)
        log.info(f"chat importance: {importance}")
        mm = MemoryManager()
        saved = mm.add_chat(sender=sender, message=message, response=response, importance=importance)
        if saved:
            log.info(f"chat saved to agent_memory (importance={importance})")
    except Exception as e:
        log.warning(f"memory_manager.add_chat失敗: {e}")


class ChatHTTPHandler(BaseHTTPRequestHandler):
    """POST /chat を受け付けてchat_handlerに委譲するHTTPハンドラ（Issue #31）"""

    def do_POST(self):
        if self.path != "/chat":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        sender = body.get("sender", "Admin")
        content = body.get("content", "")
        channel_id = body.get("channel_id", CHAT_CHANNEL)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
        # 別スレッドで処理（レスポンスを即返す）
        threading.Thread(target=chat_handler, args=(content, sender, channel_id), daemon=True).start()

    def log_message(self, format, *args):
        log.debug(f"ChatHTTP: {format % args}")


def start_chat_http_server():
    """チャットHTTPサーバーをデーモンスレッドで起動"""
    server = HTTPServer(("localhost", AGENT_CHAT_PORT), ChatHTTPHandler)
    log.info(f"Chat HTTP server listening on localhost:{AGENT_CHAT_PORT}")
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def poll_chat_messages() -> None:
    """agent-chat ディレクトリの未処理メッセージを処理する（APScheduler定期ジョブ）"""
    if not os.path.isdir(AGENT_CHAT_DIR):
        return

    files = sorted(glob.glob(f"{AGENT_CHAT_DIR}/chat-*.json"))
    if not files:
        return

    log.info(f"💬 chat poll: {len(files)} 件のメッセージ")
    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            sender     = data.get("sender", "Admin")
            content    = data.get("content", "")
            channel_id = data.get("channel_id", CHAT_CHANNEL)

            if content:
                chat_handler(content, sender, channel_id)

            os.remove(fpath)
        except Exception as e:
            log.error(f"chat poll error ({fpath}): {e}")
            try:
                os.remove(fpath)   # 壊れたファイルは削除して進む
            except Exception:
                pass


# ─── メインタスク ────────────────────────────────────────────────────────────

def daily_research():
    """毎朝08:00に実行されるメインタスク。
    全体をtry/exceptで囲み、未処理例外によるスレッドプール崩壊を防止。"""
    global action_count
    try:
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

        # MemoryManager: リサーチログを蓄積
        score = evaluation.get("total", "?")
        try:
            from memory_manager import MemoryManager
            mm = MemoryManager()
            # reflect scoreをimportanceに変換（100点満点→10点満点）
            importance = min(10.0, max(1.0, score / 10.0)) if isinstance(score, (int, float)) else 5.0
            mm.add_research(date=today, topic=topics, theme=theme, score=score if isinstance(score, (int, float)) else 0, summary=evaluation.get("comment", ""))
        except Exception as e:
            log.warning(f"memory_manager.add_research失敗: {e}")

        # notify
        comment = evaluation.get("comment", "")
        notify_discord(
            f"✅ 本日のリサーチ投稿完了\n"
            f"テーマ: {theme}\n"
            f"品質スコア: {score}/100（{comment}）\n\n"
            f"---\n{draft[:1500]}\n\n"
            f"{'...(続き省略)' if len(draft) > 1500 else ''}"
        )
        log.info(f"=== 毎朝リサーチ完了: スコア{score} ===")

        # agent-diary: 日次まとめ
        post_diary(
            f"本日のリサーチ完了\n"
            f"テーマ: {theme}\n"
            f"品質スコア: {score}/100\n"
            f"所感: {comment}\n"
            f"明日への改善点: {'独自考察を増やす' if isinstance(score, int) and score < 80 else 'このクオリティを維持'}",
            step="daily",
        )
    except Exception as e:
        log.error(f"daily_research 未処理例外: {e}", exc_info=True)
        try:
            notify_discord(f"⚠️ daily_research で未処理例外が発生: {e}", is_alert=True)
        except Exception:
            pass


# ─── ヘルスチェック ─────────────────────────────────────────────────────────

def weekly_memory_cleanup():
    """週次メモリクリーンアップ: TTL切れ削除 + Ollama要約生成"""
    from memory_manager import MemoryManager
    try:
        mm = MemoryManager()
        mm.cleanup()
        mm.summarize_week()
        log.info("週次メモリクリーンアップ完了")
    except Exception as e:
        log.error(f"週次メモリクリーンアップ失敗: {e}")


def scheduler_heartbeat():
    """スケジューラの生存確認（5分ごと）。スレッド数をログに記録。"""
    thread_count = threading.active_count()
    log.info(f"💓 heartbeat: threads={thread_count}, pid={os.getpid()}")


# ─── エントリポイント ────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("autonomous_agent 起動")

    # Ollama可用性チェック（Issue #1）
    if LocalLLM.is_available():
        log.info(f"✅ Ollama 利用可能: {OLLAMA_URL} / モデル: {OLLAMA_MODEL}")
        llm_status = f"🧠 LLM: Ollama ({OLLAMA_MODEL}) + Claude Sonnet (ハイブリッド)"
        post_diary(f"Ollama ({OLLAMA_MODEL}) が利用可能です。ローカルLLMで軽量タスクを実行します。", step="startup")
    else:
        log.warning(f"⚠️ Ollama 利用不可。Claude APIのみで動作します。")
        llm_status = "🧠 LLM: Claude API のみ（Ollama未起動）"
        post_diary("Ollama が利用不可のため、Claude APIのみで動作します。", step="startup")

    # スケジュール設定: INTERVAL_MINUTES 環境変数が設定されていればインターバル実行
    interval_minutes = os.getenv("INTERVAL_MINUTES")

    # APScheduler: 明示的なExecutor設定でスレッドプール崩壊を防止
    executors = {
        "default": ThreadPoolExecutor(max_workers=10),
    }
    job_defaults = {
        "coalesce": True,          # 複数misfireを1回に統合
        "max_instances": 1,         # 同一ジョブの同時実行防止
        "misfire_grace_time": 300,  # 5分以内のmisfireは実行を許可
    }
    scheduler = BlockingScheduler(
        timezone="Asia/Tokyo",
        executors=executors,
        job_defaults=job_defaults,
    )

    if interval_minutes:
        interval_minutes = int(interval_minutes)
        scheduler.add_job(
            daily_research,
            trigger="interval",
            minutes=interval_minutes,
            id="daily_research",
            name=f"{interval_minutes}分ごとリサーチ（テスト）",
        )
        schedule_desc = f"⏱️ {interval_minutes}分間隔（テストモード）"
        log.info(f"スケジューラ起動: {interval_minutes}分ごと（テストモード）")
    else:
        scheduler.add_job(
            daily_research,
            trigger="cron",
            hour=8,
            minute=0,
            id="daily_research",
            name="毎朝リサーチ投稿",
        )
        schedule_desc = "📅 毎朝 08:00 JST"
        log.info("スケジューラ起動: 毎朝 08:00 JST")

    # agent-chat ポーリング: 30秒ごとに未処理メッセージをチェック（Issue #18）
    scheduler.add_job(
        poll_chat_messages,
        trigger="interval",
        seconds=30,
        id="poll_chat",
        name="agent-chat ポーリング",
    )
    log.info("agent-chat ポーリング: 30秒間隔で起動")

    # 週次メモリクリーンアップ: 毎週日曜03:00 JST
    scheduler.add_job(
        weekly_memory_cleanup,
        trigger="cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="memory_cleanup",
        name="週次メモリクリーンアップ",
    )
    log.info("週次メモリクリーンアップ: 毎週日曜 03:00 JST")

    # ヘルスチェック: 5分ごとにスレッド数をログ出力
    scheduler.add_job(
        scheduler_heartbeat,
        trigger="interval",
        minutes=5,
        id="heartbeat",
        name="スケジューラ heartbeat",
    )
    log.info("heartbeat: 5分間隔で起動")

    # Chat HTTP サーバー起動（Go APIからのチャットを受け付ける）
    start_chat_http_server()
    log.info(f"チャットAPIサーバー起動: localhost:{AGENT_CHAT_PORT}")

    notify_discord(f"🤖 autonomous_agent が起動しました。{schedule_desc} にリサーチを実行します。\n{llm_status}\n💬 agent-chat: 30秒ポーリングで対話受付中\n🌐 Chat API: localhost:{AGENT_CHAT_PORT}")
    post_diary("起動しました。思考ログをここに記録していきます。", step="startup")

    # 起動時に即時実行するオプション（テスト用）
    if os.getenv("RUN_NOW") == "1":
        log.info("RUN_NOW=1 検出: 即時実行します")
        daily_research()

    # シグナルハンドラ: graceful shutdown
    def handle_signal(signum, frame):
        log.info(f"シグナル {signum} 受信、スケジューラ停止中...")
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, handle_signal)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("autonomous_agent 停止")
        notify_discord("🛑 autonomous_agent が停止しました。")
        post_diary("停止します。またね。", step="startup")
