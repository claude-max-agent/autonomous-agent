"""
persona_layer.py - ペルソナプロンプト生成（Layer 1）

エージェントが「Adminのコピー」として振る舞うための
システムプロンプトを動的生成する。

Phase 1: ハードコードされたペルソナテンプレート
Phase 2: RAGから実際のAdmin発言を引っ張って動的生成
Phase 3: ID-RAG知識グラフ (Neo4j) から注入
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

PERSONA_CONFIG_PATH = Path(__file__).parent.parent.parent / "data" / "persona.json"


# ─── デフォルトペルソナテンプレート（Phase 1 暫定） ──────────────────────────

DEFAULT_PERSONA = {
    "name": "Admin",
    "interests": [
        "Web3 / DeFi / HyperLiquid / オンチェーン分析",
        "AI / LLM / エージェント技術",
        "自律型AIエージェント開発",
        "Zenn・note への技術記事執筆",
    ],
    "writing_style": {
        "tone": "論理的・簡潔・実用重視",
        "format": "Markdown、箇条書き多用、コードブロック付き",
        "language": "日本語（技術用語は英語混じり）",
    },
    "values": [
        "実際に動くものを作ることを優先",
        "複雑な理論より実装可能なシンプルな解決策を好む",
        "AIエージェントが自律的に価値を生み出す未来を目指す",
    ],
    "context_sources": [],  # Phase 2以降でRAGから動的に追加
}


def load_persona() -> dict:
    """ペルソナ設定を読み込む（ファイルがあれば優先）"""
    if PERSONA_CONFIG_PATH.exists():
        with open(PERSONA_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_PERSONA


def save_persona(persona: dict) -> None:
    """ペルソナ設定を保存"""
    PERSONA_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PERSONA_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(persona, f, ensure_ascii=False, indent=2)
    log.info(f"Persona saved: {PERSONA_CONFIG_PATH}")


def build_system_prompt(
    task: str = "daily_research",
    rag_context: Optional[list[dict]] = None,
    persona: Optional[dict] = None,
) -> str:
    """
    タスクとRAGコンテキストを元にシステムプロンプトを生成

    Args:
        task: タスク種別 ("daily_research", "article_writing", "reflection")
        rag_context: RAGから取得した関連ドキュメント（Phase 2以降）
        persona: ペルソナ設定（Noneの場合はデフォルト）
    """
    p = persona or load_persona()

    interests_str = "\n".join(f"  - {i}" for i in p.get("interests", []))
    values_str    = "\n".join(f"  - {v}" for v in p.get("values", []))
    style         = p.get("writing_style", {})

    # RAGコンテキストがあれば追加
    rag_section = ""
    if rag_context:
        rag_section = "\n\n## 参照コンテキスト（過去の発言・記録）\n"
        for i, doc in enumerate(rag_context[:5], 1):
            src = doc.get("metadata", {}).get("source", "unknown")
            rag_section += f"\n[{i}] ({src})\n{doc['text'][:300]}\n"

    # タスク固有の指示
    task_instructions = {
        "daily_research": (
            "今日のリサーチ・記事執筆タスクを実行してください。"
            "Adminの興味関心と文体に沿った、読者に価値を届けるコンテンツを生成してください。"
        ),
        "article_writing": (
            "Zenn/note向けの記事を執筆してください。"
            "Adminの文体・価値観を反映した、実用的で読みやすい記事を書いてください。"
        ),
        "reflection": (
            "本日の行動を振り返り、改善点と明日への学びを整理してください。"
            "Adminの視点で、率直かつ建設的な内省を行ってください。"
        ),
    }.get(task, "タスクを実行してください。")

    prompt = f"""あなたは {p.get('name', 'Admin')} のデジタルコピーとして動作するAIエージェントです。

## ペルソナプロフィール

**興味・関心領域:**
{interests_str}

**価値観・スタンス:**
{values_str}

**文体・表現スタイル:**
  - トーン: {style.get('tone', '論理的・実用重視')}
  - フォーマット: {style.get('format', 'Markdown')}
  - 言語: {style.get('language', '日本語')}
{rag_section}
## 現在のタスク

{task_instructions}

---
**重要**: あなたは {p.get('name', 'Admin')} として振る舞います。
「私は」と書く場合は {p.get('name', 'Admin')} の視点からの発言です。
外部への破壊的操作（force push、本番環境変更等）は行いません。"""

    return prompt


def get_persona_summary() -> str:
    """ペルソナの簡易サマリーを返す（ログ・通知用）"""
    p = load_persona()
    interests = p.get("interests", [])
    return f"{p.get('name', 'Admin')} | 興味: {', '.join(interests[:2])}..."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== Persona System Prompt (daily_research) ===\n")
    print(build_system_prompt("daily_research"))
    print("\n=== Persona Summary ===")
    print(get_persona_summary())
