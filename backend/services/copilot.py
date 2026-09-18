# -*- coding: utf-8 -*-
"""copilot.py —— 教师 Copilot：把自然语言转成「查学生 / 备课 / 讲知识点」。

## 诚实说明当前形态

这**不是** Agent：它是「规则词典路由 + 单次 LLM」。
三个分支是硬编码的，不读多轮记忆（只带最近 2 轮），没有工具调用循环。
这样做的理由是：这三件事正好覆盖教师 90% 的日常动作，
用最少的复杂度拿到最稳的可用性；真要做 Agent 应单独设计（见 README 的"后续演进"）。

``engine`` 字段如实标注本次是"AI 生成"还是"规则生成"，不把模拟结果冒充模型输出。
"""
from __future__ import annotations

import re
import uuid
from typing import Sequence

import db
import llm
from services import (dashboard, interaction as ia, ragroute, retriever, synth,
                      teaching, tutor)

SKILLS: list[dict] = [
    {"value": "student", "label": "查学生", "hint": "例：看看张三的画像 / stu03 的成绩如何"},
    {"value": "lesson", "label": "备课", "hint": "例：帮我备一节注意力机制（拓展型）"},
    {"value": "explain", "label": "讲知识点", "hint": "例：讲一下反向传播，要能直接上课用"},
    {"value": "grading", "label": "批改标准", "hint": "例：这份作业怎么给分？给一份评分标准"},
]

# 意图词典：命中即路由。顺序有讲究——先判更具体的意图。
_INTENT_RULES: list[tuple[str, list[str]]] = [
    ("lesson", ["备课", "教案", "教学设计", "ppt", "大纲", "讲义", "课件", "幻灯片",
                "这节课怎么上", "上课怎么讲", "怎么讲这节课"]),
    ("grading", ["评分", "打分", "怎么给分", "批改", "评语", "评分标准", "扣分", "分档"]),
    ("explain", ["讲一下", "讲讲", "讲解", "解释", "什么是", "是什么", "原理", "知识点", "怎么理解"]),
    ("student", ["学生", "画像", "成绩", "分层", "学情", "情况", "怎么样", "表现"]),
]

# 正则模式：中文口语常把动词和宾语拆开（"帮我**备**一节注意力机制的**课**"），
# 纯子串匹配会漏。模式优先级高于词典。
_INTENT_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("lesson", re.compile(
        r"备[一二三四五六七八九十\d]{0,3}节|备.{0,6}课|做.{0,4}(课件|ppt|幻灯片)"
        r"|出.{0,3}(期末|期中|练习|试题|卷)|设计.{0,6}(教学|课堂|课程)"
        r"|(教案|讲义|大纲|课件|幻灯片)", re.I)),
    ("student", re.compile(r"(哪个|哪位|这些|我们班|班上).{0,4}学生|哪些学生|学情|整体情况")),
    ("grading", re.compile(r"(评分|打分|给分|批改).{0,8}(标准|细则|档|怎么|如何)|写.{0,4}评语|扣分")),
]


def detect_intent(question: str, skill: str = "") -> str:
    """规则词典路由。``skill`` 由前端显式指定时优先。"""
    if skill in ("student", "lesson", "explain", "grading"):
        return skill
    text = (question or "").strip()
    if not text:
        return "explain"
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(text):
            return intent
    lowered = text.lower()
    for intent, words in _INTENT_RULES:
        if any(word.lower() in lowered for word in words):
            return intent
    return "explain"  # 兜底：当知识点讲解处理


# ================================================================ 分支一：查学生
def _find_students(keyword: str, class_id: str = "") -> list[dict]:
    """按姓名或学号模糊匹配本班学生。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    tokens = [t for t in re.split(r"[\s,，、和与]+", keyword) if len(t) >= 2]
    found: list[dict] = []
    for token in tokens[:3]:
        sql = (
            "SELECT u.id, u.username, u.name, u.class_id, u.class_name, "
            "p.track, p.grade_level, p.gpa, p.interests, p.ability "
            "FROM users u LEFT JOIN student_profiles p ON p.user_id = u.id "
            "WHERE u.role='student' AND (u.name LIKE ? OR u.username LIKE ?)"
        )
        args: list = [f"%{token}%", f"%{token}%"]
        if class_id:
            sql += " AND u.class_id = ?"
            args.append(class_id)
        sql += " LIMIT 5"
        for row in db.query(sql, tuple(args)):
            if row["id"] not in {r["id"] for r in found}:
                found.append(row)
    return found


def _render_student_card(teacher: dict, student: dict) -> str:
    detail = dashboard.student_detail(teacher, int(student["id"]))
    profile = detail["profile"]
    lines = [
        f"{student.get('name')}（{student.get('username')}）",
        f"分层：{profile.get('layer')}",
        f"成绩：{profile.get('gpa')} 分 · 层次 {profile.get('grade_level')}",
        f"兴趣方向：{'、'.join(profile.get('interests') or []) or '待识别'}",
        f"能力短板：{_weakest(profile.get('ability_pairs'))}",
        f"待办任务：{sum(1 for t in detail['tasks'] if t.get('status') != 'done')} 项",
        "",
        "判定依据：" + str(profile.get("reason") or "暂无"),
        "",
        "建议动作：" + profile.get("next_step", ""),
    ]
    if detail["mastery"]:
        weak = [m["kp_name"] for m in detail["mastery"] if float(m.get("mastery") or 0) < 0.6]
        if weak:
            lines.append("掌握度偏低的知识点：" + "、".join(weak[:4]))
    return "\n".join(lines)


def _weakest(pairs: Sequence[dict] | None) -> str:
    items = [p for p in (pairs or []) if p.get("value")]
    if not items:
        return "暂无数据"
    lowest = min(items, key=lambda p: p["value"])
    return f"{lowest['name']}（{lowest['value']}）"


def _branch_student(teacher: dict, question: str) -> dict:
    class_id = dashboard.class_of(teacher)
    students = _find_students(question, class_id)
    if not students:
        return {
            "answer": "没有在本班找到匹配的学生。可以试试直接写姓名或学号（例如 stu03）。\n"
                      "如果你问的是班级整体情况，可以说「班里成绩分布怎么样」。",
            "data": {"students": []},
        }
    cards = [_render_student_card(teacher, s) for s in students[:2]]
    return {
        "answer": "\n\n---\n\n".join(cards),
        "data": {"students": students[:2]},
    }


# ================================================================ 分支二：备课
def _parse_lesson_params(question: str) -> tuple[str, str, int, str]:
    """从自然语言里抽 topic / periods / 取向。"""
    text = question or ""
    level = "B"
    if any(w in text for w in ("拓展", "拔高", "前沿", "探究")):
        level = "A"
    elif any(w in text for w in ("巩固", "基础", "例题", "补")):
        level = "C"

    periods = 1
    match = re.search(r"(\d+)\s*(课时|节)", text)
    if match:
        periods = max(1, min(6, int(match.group(1))))

    topic = re.sub(r"(帮我|请|麻烦|生成|设计|写|一份|一节课的|的)?(备课|教案|教学设计|大纲|ppt|讲义)", "", text)
    topic = re.sub(r"[（(].*?[)）]", "", topic)
    topic = re.sub(r"\d+\s*(课时|节)", "", topic)
    topic = re.sub(r"(拓展型|标准型|巩固型|拓展|标准|巩固)", "", topic)
    topic = topic.strip(" ：:，,。.、？?") or "本次课主题"
    return topic[:40], "", periods, level


def _branch_lesson(teacher: dict, question: str) -> dict:
    topic, _course, periods, level = _parse_lesson_params(question)
    courses = db.query(
        "SELECT DISTINCT course FROM knowledge_points WHERE owner_id = ? AND course <> '' LIMIT 1",
        (int(teacher.get("id") or 0),),
    )
    course = str(courses[0]["course"]) if courses else ""
    result = teaching.lesson_plan(topic, course=course, periods=periods, level=level,
                                  owner_id=int(teacher.get("id") or 0))
    plan = result["plan"]

    lines = [
        f"教案已生成：{plan.get('title')}",
        f"取向：{plan.get('orientation')} · 课时：{plan.get('periods')} × 45 分钟 = {plan.get('total_minutes')} 分钟",
        "",
        "教学目标：",
    ]
    lines += [f"  {i}. {o}" for i, o in enumerate(plan.get("objectives") or [], 1)]
    lines.append("")
    lines.append("教学环节：")
    for seg in plan.get("outline") or []:
        lines.append(f"  · {seg.get('step')}（{seg.get('minutes')} 分钟）：{seg.get('content')}")
    lines += [
        "",
        "重点：" + "；".join(plan.get("key_points") or []),
        "难点：" + "；".join(plan.get("difficulties") or []),
        "",
        "作业：" + str(plan.get("homework") or ""),
        "资料来源：" + ("、".join(f"[{r}]" for r in (plan.get("refs") or [])) or "（本次未命中教师上传的资料）"),
    ]
    return {
        "answer": "\n".join(lines),
        "data": {"plan": plan, "engine": result["engine"]},
        "engine": result["engine"],
    }


# ================================================================ 分支三：讲知识点
def _branch_explain(teacher: dict, question: str) -> dict:
    hits = retriever.hybrid_search(question, top_k=4, owner_id=int(teacher.get("id") or 0),
                                   teacher=True)
    refs = [h.get("ref") for h in hits if h.get("ref")]

    # 综合生成层：检索只给证据，讲解要"过一遍脑子"再出来
    #   模型版：结论 / 推理链 / 易混点 / 下一步；规则版：按 REASON_RULES 组织推理
    answer, engine, synth_view = synth.compose(
        "teacher", question, hits,
        track="学业型", level="A",          # 教师视角：按最高信息密度组织
        intent="explain", style="讲知识点",
        next_step="课堂上先给结论，再让学生复述一遍中间那一跳。",
    )
    if engine == "llm" and refs and not any(f"[{r}]" in answer for r in refs[:2]):
        answer += "\n\n资料来源：" + "；".join(f"[{r}]" for r in refs[:3])
    return {"answer": answer,
            "data": {"refs": refs, "hits": len(hits), "synth": synth_view},
            "engine": engine}


# ================================================================ 分支四：批改标准
def _branch_grading(teacher: dict, question: str) -> dict:
    """给一份可改的评分标准草案 + 常见扣分点。

    规则版也必须有真实内容：三档描述 + 三条扣分点是教师真正会用的东西。
    """
    hits = retriever.hybrid_search(question, top_k=3, owner_id=int(teacher.get("id") or 0),
                                   teacher=True)
    context = retriever.context_block(hits)
    refs = [h.get("ref") for h in hits if h.get("ref")]
    rubric = {
        "A": "结构完整、推导清晰、结论正确，能说明关键步骤的依据。",
        "B": "主要步骤正确，推导或表述有小瑕疵，结论基本正确。",
        "C": "缺少关键推导或结论错误，需要按反馈补做。",
    }
    rule = "\n".join([
        "评分标准（草案，可直接改）：",
        "A 档：" + rubric["A"],
        "B 档：" + rubric["B"],
        "C 档：" + rubric["C"],
        "常见扣分点：① 未说明假设条件；② 跳步且未给依据；③ 结论与过程不一致。",
        "资料来源：" + ("、".join(f"[{r}]" for r in refs) or "（本次未命中教师上传的资料）"),
    ])
    messages = [
        {"role": "system", "content": (
            "你是高校教学顾问，正在帮教师制定作业评分标准。\n"
            "要求：1. 给出 A/B/C 三档的可操作描述；2. 列出 3 条常见扣分点；"
            "3. 给一条评语模板；4. 只依据给定资料，不要编造；5. 中文，350 字以内。\n\n"
            f"【参考资料】\n{context or '（本次未检索到相关教师资料）'}"
        )},
        {"role": "user", "content": question},
    ]
    answer, engine = llm.chat(messages, mock=lambda: rule, temperature=0.3)
    return {"answer": answer,
            "data": {"refs": refs, "rubric": rubric,
                     "deductions": ["未说明假设条件", "跳步且未给依据", "结论与过程不一致"]},
            "engine": engine}


# ================================================================ 对外
def ask(teacher: dict, question: str, skill: str = "",
        session_id: str = "", strategy: str = "auto") -> dict:
    """教师 Copilot 入口。返回 ``{intent, answer, data, engine, skills, rag, session_id}``。

    ``session_id``：不传就新开一次对话，传了就续上（支持「回到某一次对话」）。
    ``strategy``：``auto`` 走 RAG 路由，也可显式指定五种架构之一做演示对比。
    """
    question = (question or "").strip()
    if not question:
        return {"intent": "explain", "answer": "请先描述你想做什么。",
                "data": {}, "engine": "rule", "skills": SKILLS,
                "session_id": session_id or "", "rag": {}}
    session_id = (session_id or "").strip() or ("s" + uuid.uuid4().hex[:10])

    intent = detect_intent(question, skill)
    engine = "rule"
    if intent == "student":
        result = _branch_student(teacher, question)
    elif intent == "lesson":
        result = _branch_lesson(teacher, question)
    elif intent == "grading":
        result = _branch_grading(teacher, question)
    else:
        result = _branch_explain(teacher, question)

    engine = str(result.get("engine") or engine)
    typed = ia.classify(question, "teacher")
    user_id = int(teacher.get("id") or 0)

    # ---- RAG 路由：与学生侧共用同一套五种架构；需要查证的分支才真正执行检索
    rag = ragroute.resolve(question, "teacher", strategy)
    if intent in ("explain", "student"):
        executed = ragroute.execute(rag["strategy"], question, teacher, 4, "")
        rag = {**rag, "extra": executed.get("extra") or {}}
        data = result.setdefault("data", {})
        if not data.get("refs") and executed.get("hits"):
            data["refs"] = [h.get("ref") for h in executed["hits"] if h.get("ref")]

    db.log_chat(user_id, "user", question, scene="copilot", session_id=session_id)
    db.log_chat(user_id, "assistant", result.get("answer") or "", scene="copilot",
                engine=engine, session_id=session_id)

    return {
        "intent": intent,
        "intent_label": next((s["label"] for s in SKILLS if s["value"] == intent), intent),
        "answer": result.get("answer") or "",
        "data": result.get("data") or {},
        "engine": engine,
        "skills": SKILLS,
        # ---- 交互协议（能力③）：与教师 Copilot 共用同一套四段式协议
        "typed": typed,
        "protocol": ia.protocol_view(
            "consolidate", False, "", "A",   # 教师视角默认给满信息，不设脚手架降级
        ),
        "followups": ia.followups_of(typed["type"]),
        "actions": ia.actions_of("teacher", intent,
                                 (result.get("data") or {}).get("refs")),
        "session_id": session_id,
        "rag": rag,
        # ---- 综合生成视图：教师侧同样展示"答案是怎么想出来的"
        "synth": (result.get("data") or {}).get("synth") or {},
    }


def history(teacher_id: int, limit: int = 20, session_id: str = "") -> list[dict]:
    """读某一次对话；``session_id`` 为空时读全部（兼容老数据的「早期对话」）。"""
    sql = "SELECT * FROM chat_messages WHERE user_id = ? AND scene = 'copilot'"
    args: list = [teacher_id]
    if session_id:
        sql += " AND session_id = ?"
        args.append(session_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    rows = db.query(sql, tuple(args))
    rows.reverse()
    for row in rows:
        row["session_id"] = row.get("session_id") or ""
    return rows


def sessions(teacher_id: int, limit: int = 30) -> list[dict]:
    """会话列表：新开对话 / 回到某一次对话。"""
    out = []
    for r in db.chat_sessions(teacher_id, "copilot", limit):
        sid = r.get("session_id") or ""
        out.append({
            "session_id": sid,
            "title": (db.first_question(teacher_id, "copilot", sid) or "（空会话）") if sid else "早期对话",
            "turns": int(r.get("turns") or 0),
            "last_at": r.get("last_at") or "",
        })
    return out


def new_session() -> str:
    return "s" + uuid.uuid4().hex[:10]


def clear_history(teacher_id: int, session_id: str = "") -> None:
    """只清 Copilot 场景的记录；传 ``session_id`` 时只清那一次对话。"""
    with db.connect() as conn:
        if session_id:
            conn.execute(
                "DELETE FROM chat_messages WHERE user_id = ? AND scene = 'copilot' AND session_id = ?",
                (teacher_id, session_id))
        else:
            conn.execute(
                "DELETE FROM chat_messages WHERE user_id = ? AND scene = 'copilot'", (teacher_id,)
            )
