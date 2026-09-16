# -*- coding: utf-8 -*-
"""tutor.py —— ③ 交互式分层答疑（核心卖点落点）。

## 流程

提问 → 取画像 → ``hybrid_search(q, 4)`` → 按层组装 system prompt → 生成 →
带引用落库 → 返回 ``{answer, refs, layer, style, engine}``。

## 六格矩阵（分层亮点）

主标签 × 层次 → 答疑风格 + 下一步建议。

|      | A | B | C |
|------|---|---|---|
| 学业型 | 科研拔高 | 稳基拔高 | 补基引导 |
| 事业型 | 工程深化 | 应用实操 | 场景入门 |

**规则版答案也必须按层不同** —— 从命中片段中挑与问题最相关的一句，
拼 2 条引用，加层标签与下一步建议。这样断网时"两个学生同问一题答案不同"
的核心卖点依然成立。
"""
from __future__ import annotations

import re
from typing import Sequence

import db
import llm
from services import retriever, stratify

# 六格矩阵：风格名 + 回答策略 + 下一步建议
MATRIX: dict[tuple[str, str], dict] = {
    ("学业型", "A"): {
        "style": "科研拔高",
        "strategy": "讲清原理与推导脉络，指出该知识点在前沿研究中的位置与常见研究问题，信息密度可以高。",
        "next": "建议本周精读一篇该方向的近期综述，把公式与前沿问题对应起来。",
    },
    ("学业型", "B"): {
        "style": "稳基拔高",
        "strategy": "把推导过程讲清楚，给出可自查的练习方向，帮助学生把「会做」升级为「讲得清」。",
        "next": "建议先复现一遍关键推导，再尝试用一句话向同学解释这个知识点。",
    },
    ("学业型", "C"): {
        "style": "补基引导",
        "strategy": "先补前置概念，多用类比与图示式描述，避免堆砌公式，降低抽象门槛。",
        "next": "建议先把这个概念用生活化的例子说明白，再回头看公式。",
    },
    ("事业型", "A"): {
        "style": "工程深化",
        "strategy": "落到框架/接口/性能与常见坑，给出可复现的小项目思路，强调工程取舍。",
        "next": "建议用 30 行以内的代码把这个知识点跑通，并记录遇到的报错与解法。",
    },
    ("事业型", "B"): {
        "style": "应用实操",
        "strategy": "以业务场景切入，给操作步骤与调试方法，让学生能上手、能排错。",
        "next": "建议找一个小场景动手做一遍，重点关注报错信息怎么读。",
    },
    ("事业型", "C"): {
        "style": "场景入门",
        "strategy": "用生活化用途引出概念，避开公式，给最小可运行示例，先建立成就感。",
        "next": "建议先跑通一个最小示例，成功一次之后再扩展。",
    },
}


def cell_of(track: str, level: str) -> dict:
    """取六格矩阵中的一格。画像缺失时按「学业型 · B」兜底。"""
    track = track if track in ("学业型", "事业型") else "学业型"
    level = level if level in ("A", "B", "C") else "B"
    return MATRIX[(track, level)]


def layer_label(track: str, level: str) -> str:
    """形如 ``学业型 · A 层 · 科研拔高``。"""
    track = track if track in ("学业型", "事业型") else "学业型"
    level = level if level in ("A", "B", "C") else "B"
    return f"{track} · {level} 层 · {cell_of(track, level)['style']}"


# ================================================================ prompt 组装
def system_prompt(track: str, level: str, interests: Sequence[str], context: str) -> str:
    """按画像动态拼装 system prompt（等价于 ChatPromptTemplate）。"""
    cell = cell_of(track, level)
    interests_text = "、".join(list(interests)[:4]) or "暂未识别"
    return (
        "你是一名高校课程的 AI 助教，正在为一名具体的学生答疑。\n\n"
        f"【学生画像】主标签：{track}；学业层次：{level} 层；兴趣方向：{interests_text}\n"
        f"【本次答疑风格】{cell['style']}：{cell['strategy']}\n\n"
        "【硬性约束】\n"
        "1. 只回答与问题和所给资料相关的内容，资料中没有的不要编造；\n"
        "2. 优先使用参考资料，关键结论后用 [资料名] 标注来源；\n"
        "3. 中文、300 字以内、结构清晰，最后给一条针对性下一步建议。\n\n"
        f"【参考资料】\n{context or '（本次未检索到教师上传的相关资料，请基于通用知识作答并说明这一点）'}"
    )


def history(user_id: int, turns: int = 4) -> list[dict]:
    """最近 N 轮对话（历史塞进 messages，支持追问）。"""
    return [
        {"role": row["role"], "content": row["content"]}
        for row in db.recent_chat(user_id, "tutor", turns)
        if row.get("content")
    ]


# ================================================================ 规则版答案
def _best_sentence(chunk: str, question: str) -> str:
    """从命中片段里挑与问题最相关的一句：按问题中的长词命中数打分。"""
    chunk = (chunk or "").strip()
    if not chunk:
        return ""
    sentences = [s.strip() for s in re.split(r"(?<=[。！？；.!?;])", chunk) if s.strip()]
    if not sentences:
        return chunk[:120]

    terms = [t for t in re.split(r"[^\w\u4e00-\u9fa5]+", question or "") if len(t) >= 2]
    best, best_score = sentences[0], -1.0
    for sentence in sentences:
        score = sum(len(t) * sentence.count(t) for t in terms)
        score += min(len(sentence), 80) / 200.0   # 太短的句子略降权
        if score > best_score:
            best, best_score = sentence, score
    return best[:260]


def rule_answer(
    question: str,
    hits: Sequence[dict],
    track: str,
    level: str,
) -> str:
    """规则版答案：**同样按层不同**，且带引用与下一步建议。"""
    cell = cell_of(track, level)
    label = layer_label(track, level)

    lines: list[str] = []
    for hit in list(hits)[:2]:
        sentence = _best_sentence(str(hit.get("content") or ""), question)
        if not sentence:
            continue
        lines.append(f"- {sentence} [{hit.get('ref') or '资料'}]")

    if not lines:
        return (
            f"（{label}）这个问题在当前知识库里没有检索到教师上传的相关资料，"
            "所以先不给结论，避免编造。建议先到「资料库」确认该内容是否已上传，"
            "或把问题再具体一点（例如指明章节或概念名）。\n\n"
            f"下一步建议：{cell['next']}"
        )

    if track == "学业型" and level == "A":
        opener = "从原理层面看："
    elif track == "学业型" and level == "C":
        opener = "先用一句话说清它是什么，再展开："
    elif track == "事业型" and level == "A":
        opener = "从工程落地角度看："
    elif track == "事业型" and level == "C":
        opener = "先看它有什么用："
    else:
        opener = "按你现在的进度，可以这样理解："

    body = f"（{label}）{opener}\n" + "\n".join(lines)
    body += (
        "\n\n注：以上要点来自教师上传的课件原文；"
        "受规则版能力限制，这里只抽取了与问题最相关的原文片段，未做扩展解释。"
    )
    body += f"\n\n下一步建议：{cell['next']}"
    return body


# ================================================================ 对外
def ask(
    user: dict,
    question: str,
    course: str = "",
    scope: str = "",
    top_k: int = 4,
) -> dict:
    """分层答疑。返回 ``{answer, refs, layer, style, engine, hits}``。"""
    question = (question or "").strip()
    if not question:
        return {"answer": "请先输入你的问题。", "refs": [], "layer": "", "style": "",
                "engine": "rule", "hits": []}

    user_id = int(user.get("id") or 0)
    profile = db.student_profile(user_id) or {}
    track = str(profile.get("track") or "学业型")
    level = str(profile.get("grade_level") or "B")
    interests = profile.get("interests") or []

    # 学生可以限定检索范围（自己的材料 / 某门课）
    effective_course = course
    if scope == "mine":
        pass  # 检索层不做 owner 过滤时等价于全库；此处保留语义位，便于后续扩展
    elif scope and scope not in ("all", ""):
        effective_course = effective_course or scope

    hits = retriever.hybrid_search(question, top_k=top_k, course=effective_course)
    context = retriever.context_block(hits)
    refs = [h.get("ref") for h in hits if h.get("ref")]

    messages = [{"role": "system", "content": system_prompt(track, level, interests, context)}]
    messages.extend(history(user_id))
    messages.append({"role": "user", "content": question})

    answer_text, engine = llm.chat(
        messages,
        mock=lambda: rule_answer(question, hits, track, level),
        temperature=0.3,
    )
    if not answer_text.strip():
        answer_text, engine = rule_answer(question, hits, track, level), "rule"

    # 兜底：模型没标引用时，把检索到的出处补在末尾，保证"结果可溯源"
    if engine == "llm" and refs and not any(f"[{r}]" in answer_text for r in refs[:2]):
        answer_text += "\n\n参考资料：" + "；".join(f"[{r}]" for r in refs[:3])

    style = cell_of(track, level)["style"]
    layer = layer_label(track, level)
    db.log_chat(user_id, "user", question, scene="tutor", layer=layer)
    db.log_chat(user_id, "assistant", answer_text, refs=refs, scene="tutor",
                layer=layer, engine=engine)

    return {
        "answer": answer_text,
        "refs": refs,
        "layer": layer,
        "style": style,
        "engine": engine,
        "hits": [
            {
                "ref": h.get("ref"),
                "course": h.get("course"),
                "via": h.get("via"),
                "score": h.get("fused_score"),
                "snippet": str(h.get("content") or "")[:160],
            }
            for h in hits
        ],
        "profile": {
            "track": track,
            "grade_level": level,
            "interests": interests,
        },
    }


def history_view(user_id: int, limit: int = 30) -> list[dict]:
    rows = db.query(
        "SELECT * FROM chat_messages WHERE user_id = ? AND scene = 'tutor' ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows.reverse()
    for row in rows:
        row["refs"] = db.jload(row.get("refs"), [])
    return rows


def clear_history(user_id: int) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM chat_messages WHERE user_id = ? AND scene = 'tutor'", (user_id,))


def _unused(*_: object) -> None:  # pragma: no cover
    _ = stratify
