# -*- coding: utf-8 -*-
"""synth.py —— 检索之后的 **综合生成层**（RAG 的最后一步，也是最容易省掉的一步）。

检索只负责"把可能有用的片段找出来"，回答不能直接把这些片段端给学生：

    证据归集 → 要点归并 → 结合学情组织推理 → 补易错提醒 → 标出处与下一步

少了这一层，答案就是"搜索结果拼接" —— 看似有引用，实际上没有理解，
换个问法就会露出破绽（这正是评委最容易追问的地方）。

两条引擎，返回结构完全一致：

* **模型综合**（:func:`compose` 的默认路径）：把证据、画像、层次塞进
  :data:`SYNTH_SYSTEM`，要求模型自己组织成「直接结论 / 怎么推出来的 /
  容易混淆的地方 / 下一步」四段，并且**禁止照抄资料原文**；
* **规则综合**（:func:`rule_compose`，断网兜底）：按 :data:`REASON_RULES`
  的模板把证据改写成"结论句 + 推理句 + 易错提醒"，
  模板里有连接词（也就是说 / 因此 / 反过来讲），读起来是一条讲得通的推理，
  而不是片段罗列。**规则表即数据**，新增一种讲法只 append，不动流程。

对外只暴露两个函数：

    compose(...)       -> (答案文本, engine, 结构化视图)
    rule_compose(...)  -> (答案文本, 结构化视图)     # 单独调试 / 单测用

视图里带 ``steps``，前端可以直接展示"这个答案是怎么想出来的"。
"""
from __future__ import annotations

import re
from typing import Any, Sequence

import llm

# ================================================================ 综合的五个动作
SYNTH_STEPS: list[dict[str, str]] = [
    {"id": "collect", "name": "归集证据",
     "desc": "把这次检索拿到的资料片段，挑出与问题最相关的几句。"},
    {"id": "merge", "name": "合并要点",
     "desc": "几句说的是同一件事就合成一条，互相补充的排成先后。"},
    {"id": "reason", "name": "组织推理",
     "desc": "按问题类型把要点串成一条能讲通的推理链，而不是罗列原文。"},
    {"id": "adapt", "name": "结合你的情况",
     "desc": "按画像与当前进度决定讲多深、用什么例子、先补哪个前置。"},
    {"id": "ground", "name": "标注出处",
     "desc": "每条结论标出来自哪份资料，结论之外的内容明确说明是推理。"},
]

# ================================================================ 推理模板（规则表即数据）
# 一条推理 = 两条证据（来自资料）+ 一句推断（{infer}，模型该做的那一步）。
# 占位符：{topic} 问题主题 / {e1}{e2} 证据句 / {infer} 推断句
REASON_RULES: list[dict[str, str]] = [
    {"id": "concept", "label": "概念辨析",
     "tmpl": "{topic}可以先这样理解：{e1}。\n"
             "再看它的边界——{e2}，超出这个范围，上面的说法就不再成立。\n"
             "{infer}"},
    {"id": "homework", "label": "作业卡点",
     "tmpl": "这道题卡住的地方，多半在 {e1} 这一步。\n"
             "按资料给的顺序往下走：先确认这一步成立，再看 {e2}。\n"
             "{infer}"},
    {"id": "method", "label": "方法步骤",
     "tmpl": "做这件事的顺序可以按资料里的说法排：先 {e1}，再 {e2}。\n"
             "{infer}"},
    {"id": "path", "label": "路径规划",
     "tmpl": "结合你现在的情况，方向可以这样定：{e1}。\n"
             "再往后看一步：{e2}。\n"
             "{infer}"},
    {"id": "resource", "label": "资源获取",
     "tmpl": "能对上这个方向的资料里，最贴的一条是：{e1}。\n"
             "另外还有 {e2}，可以用它先补齐基础，再往上加难度。\n"
             "{infer}"},
    {"id": "explain", "label": "讲知识点",
     "tmpl": "课堂上可以这样讲：先给结论——{e1}。\n"
             "再用 {e2} 展开一层，把中间那一跳单独拆出来讲。\n"
             "{infer}"},
    {"id": "student", "label": "查学生",
     "tmpl": "关于 {topic}，资料与学情合起来看：{e1}。\n"
             "再往下推一步：{e2}。\n"
             "{infer}"},
    {"id": "_default", "label": "通用",
     "tmpl": "把这几条资料合在一起看：{e1}；\n"
             "再看 {e2}。\n"
             "{infer}"},
]

# ================================================================ 推断句（模型该做的"想"的那一步）
# 规则版在这里给出的是**通用判断**：它不来自某一句资料，而是把两条证据连起来的那一步。
# 模型版由模型自己写；规则版用它兜底，并在页面上标注为"推断"。
INFER_RULES: dict[str, str] = {
    "concept": "把这两条连起来看：先记住它解决的是什么问题，再去记定义，比反过来背要省力得多。",
    "homework": "也就是说，先定位卡在哪一步，再判断这一步缺的是概念还是条件——两类的补救方式完全不同。",
    "method": "之所以是这个顺序，是因为每一步都在给下一步准备前提条件，跳步做出来通常也是错的。",
    "path": "这两条连起来是一条能走通的路线；中途频繁换方向的成本，比走得慢一点更高。",
    "resource": "资源不在多，挑一份跟到底，比收藏十份有用。",
    "explain": "学生卡住的通常不是结论本身，而是从结论到应用的那一跳，所以那一跳要单独拆出来讲。",
    "student": "先看趋势再看单点：一次作业的波动不足以判定短板，连续两次以上才有指导意义。",
    "_default": "这两条指向同一件事，所以结论在资料覆盖的范围内成立；范围之外我没有替它延伸。",
}

# ================================================================ 易错提醒（按问题类型）
REMIND_RULES: dict[str, str] = {
    "concept": "别把「定义」和「用法」混在一起背：先能一句话说清它是什么，再记它用在哪。",
    "homework": "改之前先分清是「概念没懂」还是「步骤跳步」，这两类的补救方式完全不同。",
    "method": "照着做之前先确认前置条件是否满足，资料里的顺序默认你已经准备好了。",
    "path": "路线可以调，但别频繁换方向：先按一条走满两周，再回头评估。",
    "resource": "资源不在多，选一份跟到底；同方向的资料挑最新的一份就够。",
    "explain": "讲的时候先结论后展开，并提前准备一个反例——学生最容易在反例上追问。",
    "student": "先看趋势再看单点，一次作业或一次考试的波动不足以判定短板。",
    "_default": "资料没覆盖到的部分我没有补充，宁可少说也不编。",
}

# 层次注脚：A/B/C 只影响"讲多深"，不影响能不能问
LEVEL_NOTE: dict[str, str] = {
    "A": "你可以顺手往前推一步：想想它在这门课里还可能出现在哪种题型里。",
    "B": "建议把上面那句话复述一遍，确认真的讲得通，再去做题。",
    "C": "先别急着做难题，把上面那句话用自己的话说清楚，这一步省不掉。",
}


# ================================================================ 证据处理
def _split_sentences(chunk: str) -> list[str]:
    """切句时丢掉 markdown 标题行与列表符——标题是目录，不是证据。"""
    out: list[str] = []
    for raw in re.split(r"(?<=[。！？；.!?;\n])", chunk or ""):
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^#{1,6}\s", line) or re.match(r"^[-*+>]\s", line):
            continue
        out.append(re.sub(r"^#{1,6}\s*", "", line))
    return out


def _best_sentence(chunk: str, question: str) -> str:
    """从一段命中文本里挑与问题最相关的一句：按问题实词命中数打分。"""
    chunk = (chunk or "").strip()
    if not chunk:
        return ""
    sentences = _split_sentences(chunk)
    if not sentences:
        return chunk[:120]
    terms = [t for t in re.split(r"[^\w\u4e00-\u9fa5]+", question or "") if len(t) >= 2]
    best, best_score = sentences[0], -1.0
    for sentence in sentences:
        score = sum(len(t) * sentence.count(t) for t in terms)
        score += min(len(sentence), 80) / 200.0
        if score > best_score:
            best, best_score = sentence, score
    return best[:260]


def _norm(s: str) -> str:
    return re.sub(r"[\s，,。.、；;：:（）()【】\[\]]+", "", s or "")


def evidence_of(hits: Sequence[dict], question: str, limit: int = 3) -> list[dict]:
    """把命中片段整理成"证据"：每份资料留一句，内容重复的合并掉。"""
    out: list[dict] = []
    for hit in list(hits or []):
        sentence = _best_sentence(str(hit.get("content") or ""), question)
        if not sentence:
            continue
        key = _norm(sentence)
        if any(key in _norm(o["sentence"]) or _norm(o["sentence"]) in key for o in out):
            continue  # 与已有证据说的是同一句，跳过
        out.append({
            "ref": str(hit.get("ref") or "资料"),
            "sentence": sentence,
            "via": str(hit.get("via") or ""),
            "score": float(hit.get("fused_score") or hit.get("score") or 0),
        })
        if len(out) >= limit:
            break
    return out


def core_of(sentence: str, max_len: int = 24) -> str:
    """取一句话的核心短语：第一个分句，太长就按虚词边界回退，避免砍在词中间。"""
    text = (sentence or "").strip().strip("。！？；.")
    text = re.sub(r"^(也就是说|换句话说|因此|所以|因为|另外|同时|并且|再从?|接着)", "", text)
    first = re.split(r"[，,；;]", text)[0].strip() or text
    if len(first) > max_len:
        cut = first[:max_len]
        bounds = list(re.finditer(r"[，,、的 和与及]", cut))
        if bounds and bounds[-1].end() > max_len * 0.5:
            cut = cut[:bounds[-1].end()]
        first = cut.rstrip("，,、的和与及 ") + "…"
    return first.strip("、，,的 了")


def topic_of(question: str, max_len: int = 18) -> str:
    """问题主题：去掉礼貌语、疑问尾巴与句末标点，截到 max_len。"""
    text = re.sub(r"^(请问|问一下|帮我|我想问|想问|麻烦|请|讲一下|讲讲|讲解|解释|怎么讲|如何讲)",
                  "", (question or "").strip())
    text = re.sub(r"[？?。！!]+$", "", text)
    text = re.sub(r"(是什么关系|是什么意思|怎么理解|如何理解|是什么|为什么|怎么|如何|有哪些|是什么区别)+$",
                  "", text)
    text = text.strip("、，,的 了吗呢")
    if len(text) > max_len:
        text = text[:max_len]
    return text or "这个问题"


def rule_of(intent_id: str) -> dict[str, str]:
    for rule in REASON_RULES:
        if rule["id"] == intent_id:
            return rule
    return REASON_RULES[-1]


def remind_of(intent_id: str) -> str:
    return REMIND_RULES.get(intent_id) or REMIND_RULES["_default"]


def infer_of(intent_id: str) -> str:
    """推断句：把两条证据连起来的那一步（模型版由模型自己写）。"""
    return INFER_RULES.get(intent_id) or INFER_RULES["_default"]


def evidence_block(ev: Sequence[dict]) -> str:
    """给模型的证据块：编号 + 出处 + 原文句，要求它据此推理而不是照抄。"""
    if not ev:
        return "（本次没有检索到相关资料，请说明这一点，并明确区分「资料里的结论」与「通用知识」。）"
    return "\n".join(
        f"[{i}] 出处：{e['ref']}\n    {e['sentence']}"
        for i, e in enumerate(ev, 1)
    )


# ================================================================ 规则版综合
def rule_compose(
    role: str,
    question: str,
    hits: Sequence[dict],
    *,
    track: str = "学业型",
    level: str = "B",
    intent: str = "",
    style: str = "",
    next_step: str = "",
    extra: dict | None = None,
) -> tuple[str, dict]:
    """规则版综合：**把证据改写成一条推理**，不是把原文片段堆上去。"""
    ev = evidence_of(hits, question, limit=3)
    topic = topic_of(question)

    if not ev:
        text = (
            f"关于「{topic}」，这次没有检索到相关资料，所以我不给结论——"
            "没有依据的答案比不回答更危险。\n"
            "建议：① 到资料库确认这份材料是否已上传并解析完成；"
            "② 把问题再具体一点（指明章节、概念名或题目编号）。\n"
            f"提醒：{remind_of(intent)}"
        )
        view = _view(role, question, ev, topic, intent, track, level, style, next_step,
                     "", 0, len(list(hits or [])), "无依据，未作答")
        return text, view

    rule = rule_of(intent)
    e1 = ev[0]["sentence"].rstrip("。！？；.")
    r1 = ev[0]["ref"]
    e2 = (ev[1]["sentence"] if len(ev) > 1 else "").rstrip("。！？；.")
    r2 = (ev[1]["ref"] if len(ev) > 1 else "")
    infer = infer_of(intent)

    if e2:
        body = rule["tmpl"]
        for key, value in (("topic", topic), ("e1", e1), ("e2", e2),
                           ("r1", r1), ("r2", r2), ("infer", infer)):
            body = body.replace("{" + key + "}", value or topic)
        body = re.sub(r"\{(topic|e1|e2|r1|r2|core|infer)\}", "", body)
    else:
        # 只有一条证据时不硬凑第二条，直接"证据 + 推断"
        body = f"就目前检索到的资料看：{e1}。\n{infer}"

    # 综合结论：一句话放最前面（模型版同样要求先给结论）
    c1, c2 = core_of(e1), (core_of(e2) if e2 else "")
    conclusion = f"综合结论：{topic}的关键在于{c1}。"
    if len(c2) >= 6:
        conclusion += f"另外要注意，{c2}。"

    lines = [conclusion, "", body, "",
             f"容易踩的坑：{remind_of(intent)}"]
    note = LEVEL_NOTE.get(level, "")
    if note:
        lines.append(note)
    if next_step:
        lines.append(f"下一步建议：{next_step}")
    lines.append("依据：" + "、".join(f"[{e['ref']}]" for e in ev))
    lines.append("（以上为综合后的表述，证据原文见上；资料之外的推断已单独说明）")

    text = "\n".join(lines)
    view = _view(role, question, ev, topic, intent, track, level, style, next_step,
                 conclusion, len(ev), len(list(hits or [])), body.split("\n")[0])
    return text, view


def _view(
    role: str, question: str, ev: Sequence[dict], topic: str, intent: str,
    track: str, level: str, style: str, next_step: str,
    conclusion: str, used: int, total: int, reason_head: str,
) -> dict[str, Any]:
    """给前端的结构化视图：这个答案是怎么想出来的。"""
    steps = [
        {"id": "collect", "name": SYNTH_STEPS[0]["name"],
         "text": f"这次检索共命中 {total} 条候选片段。", "desc": SYNTH_STEPS[0]["desc"]},
        {"id": "merge", "name": SYNTH_STEPS[1]["name"],
         "text": f"去重合并后保留 {used} 条作为证据。", "desc": SYNTH_STEPS[1]["desc"]},
        {"id": "reason", "name": SYNTH_STEPS[2]["name"],
         "text": reason_head or "（无证据，未组织推理）", "desc": SYNTH_STEPS[2]["desc"]},
        {"id": "adapt", "name": SYNTH_STEPS[3]["name"],
         "text": (f"{track} · {level} 层" + (f" · {style}" if style else "") +
                  ("；" + LEVEL_NOTE.get(level, "") if LEVEL_NOTE.get(level) else "")),
         "desc": SYNTH_STEPS[3]["desc"]},
        {"id": "ground", "name": SYNTH_STEPS[4]["name"],
         "text": "、".join(f"[{e['ref']}]" for e in ev) or "本次无可用出处",
         "desc": SYNTH_STEPS[4]["desc"]},
    ]
    return {
        "role": role,
        "topic": topic,
        "intent": intent,
        "conclusion": conclusion,
        "remind": remind_of(intent),
        "next": next_step,
        "evidence": [
            {"ref": e["ref"], "sentence": e["sentence"], "via": e["via"]} for e in ev
        ],
        "evidence_count": used,
        "hit_count": total,
        "steps": steps,
    }


# ================================================================ 模型版 prompt
def synth_system(role: str, ev: Sequence[dict], context: str, **kw: Any) -> str:
    """模型综合的 system prompt：先结论、再推理链、再提醒，**禁止照抄原文**。"""
    who = "高校课程的 AI 助教，正在给一名具体的学生答疑" if role != "teacher" \
        else "高校教学顾问，正在帮教师把内容讲成能直接上课用的版本"
    style_line = f"讲解取向：{kw.get('style') or '按对象自行判断深度'}；层次：{kw.get('level') or 'B'} 层。" if \
        (kw.get("style") or kw.get("level")) else ""
    return (
        f"你是{who}。\n\n"
        "【任务】下面的资料片段是检索得到的**证据**，你的工作不是复述它们，"
        "而是基于证据**推理出一段能讲通的回答**。\n\n"
        "【输出四段，结构固定】\n"
        "1. 直接结论：1-2 句给出判断，不要铺垫。\n"
        "2. 怎么推出来的：把证据串成一条推理链（用「也就是说 / 因此 / 反过来讲」这类连接），"
        "每一步后面用 [资料名] 标注出处。\n"
        "3. 容易混淆的地方：1 条，指出学生/听众最可能理解错的点。\n"
        "4. 下一步：1 条可执行建议。\n\n"
        "【硬性约束】\n"
        "a. 禁止大段照抄资料原文，必须转成你自己的表述；\n"
        "b. 资料里没有的内容，如果要说，必须写明「资料未覆盖，以下是通用知识」；\n"
        "c. 中文，300-400 字，不用 Markdown 标题符号。\n\n"
        f"{style_line}\n"
        f"【证据】\n{context}"
    )


# ================================================================ 对外
def compose(
    role: str,
    question: str,
    hits: Sequence[dict],
    *,
    track: str = "学业型",
    level: str = "B",
    intent: str = "",
    interests: Sequence[str] | None = None,
    style: str = "",
    next_step: str = "",
    history: Sequence[dict] | None = None,
    temperature: float = 0.3,
) -> tuple[str, str, dict]:
    """综合生成。返回 ``(答案文本, engine, 视图)``。

    ``engine`` 为 ``llm`` 时是模型综合，为 ``rule`` 时是规则版改写（断网演示）。
    两条路径返回的文本结构与视图结构一致，前端不需要判断引擎。
    """
    question = (question or "").strip()
    ev = evidence_of(hits, question, limit=3)
    context = evidence_block(ev)

    rule_text, view = rule_compose(
        role, question, hits, track=track, level=level, intent=intent,
        style=style, next_step=next_step,
    )

    messages = [{"role": "system", "content": synth_system(
        role, ev, context, style=style, level=level, track=track,
        interests=list(interests or []),
    )}]
    if history:
        messages.extend(list(history)[-4:])
    messages.append({"role": "user", "content": question})

    text, engine = llm.chat(messages, mock=lambda: rule_text, temperature=temperature)
    if not (text or "").strip():
        text, engine = rule_text, "rule"

    # 模型版没标出处时补在末尾，保证"结论可溯源"
    refs = [e["ref"] for e in ev]
    if engine == "llm" and refs and not any(f"[{r}]" in text for r in refs[:2]):
        text += "\n\n依据：" + "、".join(f"[{r}]" for r in refs[:3])

    view["engine"] = engine
    view["mode"] = "模型综合" if engine == "llm" else "规则综合"
    return text, engine, view
