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
import uuid
from typing import Sequence

import db
import llm
from services import interaction as ia, rag, ragroute, retriever, stratify, synth

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
    """规则版答案：**同样按层不同**，且带引用与下一步建议。

    已改为走 :mod:`services.synth` 的综合生成层——先给结论，再组织推理，
    最后标出处与下一步，而不是把检索到的原文片段直接堆上去。
    这里保留原签名，老调用方（教师 Copilot 等）不用改。
    """
    cell = cell_of(track, level)
    text, _view = synth.rule_compose(
        "student", question, hits, track=track, level=level,
        style=cell["style"], next_step=cell["next"],
    )
    return f"（{layer_label(track, level)}）{text}"


def related_kps(question: str, course: str = "", limit: int = 3,
                owner_id: int = 0, teacher: bool = False) -> list[dict]:
    """本次问题涉及的知识点：用问题的实词去匹配已入库的知识点名。

    比「把问题当材料再抽一次」便宜得多，也不会凭空造知识点。
    可见范围与检索层一致（``rag.search_scope``），不引用他人私人材料里的知识点。
    """
    clause, args = rag.search_scope(owner_id, teacher)
    rows = db.query(
        "SELECT name, difficulty, course FROM knowledge_points WHERE 1=1" +
        clause + " ORDER BY id DESC LIMIT 200", tuple(args),
    )
    tokens = [t for t in re.split(r"[\s，,。？?、：:；;（）()【】\[\]]+", question or "")
              if len(t) >= 2]
    out: list[dict] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if course and str(row.get("course") or "") and str(row.get("course") or "") != course:
            continue
        hit = name in (question or "") or any(t in name or name in t for t in tokens)
        if hit:
            out.append({"name": name, "difficulty": row.get("difficulty") or "B",
                        "course": row.get("course") or ""})
        if len(out) >= limit:
            break
    return out


# ================================================================ 对外
def ask(
    user: dict,
    question: str,
    course: str = "",
    scope: str = "",
    top_k: int = 4,
    session_id: str = "",
    strategy: str = "auto",
) -> dict:
    """分层答疑。返回 ``{answer, refs, layer, style, engine, hits, rag, session_id}``。

    ``strategy``：``auto`` 走 RAG 路由（按问题选五种架构之一），也可显式指定
    ``hybrid / graph / agentic / corrective / multimodal`` 供演示对比。
    """
    question = (question or "").strip()
    if not question:
        return {"answer": "请先输入你的问题。", "refs": [], "layer": "", "style": "",
                "engine": "rule", "hits": [], "rag": {}, "session_id": session_id or ""}

    user_id = int(user.get("id") or 0)
    # 会话：不传就新开一次；传了就续上（支持「回到某一次对话」）
    session_id = (session_id or "").strip() or ("s" + uuid.uuid4().hex[:10])

    profile = db.student_profile(user_id) or {}
    track = str(profile.get("track") or "学业型")
    level = str(profile.get("grade_level") or "B")
    interests = profile.get("interests") or []

    # 学生可以限定课程范围；用户隔离（只检索自己的 + 已导入的公用资料）在
    # ragroute._scope 里统一生效，不再是可选项。
    effective_course = course
    if scope and scope not in ("all", "mine"):
        effective_course = effective_course or scope

    # ---- RAG 路由：auto 时按问题选策略，也可显式指定（演示时用来对比五种架构）
    rag = ragroute.resolve(question, "student", strategy)
    executed = ragroute.execute(rag["strategy"], question, user, top_k, effective_course)
    hits = executed["hits"]
    rag = {**rag, "extra": executed.get("extra") or {}}
    context = retriever.context_block(hits)
    refs = [h.get("ref") for h in hits if h.get("ref")]

    style = cell_of(track, level)["style"]
    layer = layer_label(track, level)

    # ---- 交互协议（能力③）：答什么疑 / 怎么交互 / 得到什么
    intent = ia.classify(question, "student")
    kps = related_kps(question, effective_course,
                      owner_id=user_id, teacher=str(user.get("role")) == "teacher")

    # ---- 综合生成：检索只给证据，答案要"过一遍脑子"再出来
    #     模型版：按 结论 / 推理链 / 易混点 / 下一步 四段组织，禁止照抄原文；
    #     规则版：按 REASON_RULES 模板把证据改写成一条讲得通的推理。
    answer_text, engine, synth_view = synth.compose(
        "student", question, hits,
        track=track, level=level, intent=str(intent.get("type") or ""),
        interests=interests, style=style,
        next_step=cell_of(track, level)["next"],
        history=history(user_id),
    )
    if not answer_text.strip():
        answer_text, engine = rule_answer(question, hits, track, level), "rule"
    clarify = ia.needs_clarify(question, hits)
    db.log_chat(user_id, "user", question, scene="tutor", layer=layer, session_id=session_id)
    db.log_chat(user_id, "assistant", answer_text, refs=refs, scene="tutor",
                layer=layer, engine=engine, session_id=session_id)

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
        "session_id": session_id,
        "rag": rag,
        "synth": synth_view,
        "intent": intent,
        "protocol": ia.protocol_view(
            "clarify" if clarify["need_clarify"] else "answer",
            bool(clarify["need_clarify"]), str(clarify.get("clarify_question") or ""), level,
        ),
        "followups": ia.followups_of(intent["type"], kps),
        "actions": ia.actions_of("student", intent["type"], refs),
        "kps": kps,
    }


def history_view(user_id: int, limit: int = 30, session_id: str = "") -> list[dict]:
    """读某一次会话的消息；``session_id`` 为空时读全部（兼容老数据的「早期对话」）。"""
    sql = ("SELECT * FROM chat_messages WHERE user_id = ? AND scene = 'tutor'")
    args: list = [user_id]
    if session_id:
        sql += " AND session_id = ?"
        args.append(session_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    rows = db.query(sql, tuple(args))
    rows.reverse()
    for row in rows:
        row["refs"] = db.jload(row.get("refs"), [])
        row["session_id"] = row.get("session_id") or ""
    return rows


def sessions(user_id: int, limit: int = 30) -> list[dict]:
    """会话列表：第一问做标题 + 轮次 + 最后时间，供左侧「历史对话」选择。"""
    rows = db.chat_sessions(user_id, "tutor", limit)
    out = []
    for r in rows:
        sid = r.get("session_id") or ""
        out.append({
            "session_id": sid,
            "title": db.first_question(user_id, "tutor", sid) or "（空会话）" if sid else "早期对话",
            "turns": int(r.get("turns") or 0),
            "last_at": r.get("last_at") or "",
        })
    return out


def new_session() -> str:
    """生成一次新对话的 id。前端「新开对话」时先拿这个再发问。"""
    return "s" + uuid.uuid4().hex[:10]


def clear_history(user_id: int, session_id: str = "") -> None:
    """清空全部，或只清某一次对话（传 session_id）。"""
    with db.connect() as conn:
        if session_id:
            conn.execute(
                "DELETE FROM chat_messages WHERE user_id = ? AND scene = 'tutor' AND session_id = ?",
                (user_id, session_id),
            )
        else:
            conn.execute("DELETE FROM chat_messages WHERE user_id = ? AND scene = 'tutor'", (user_id,))


def _unused(*_: object) -> None:  # pragma: no cover
    _ = stratify
