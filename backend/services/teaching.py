# -*- coding: utf-8 -*-
"""teaching.py —— 备课（教案 / PPT 大纲）+ 作业批改。

## 教案的三种「课堂内容取向」

``level`` 是**教师对本次课深度与例题量的选择**，不是给学生分班。
三种取向必须有可见差异（环节配比、额外目标、作业形态都不同），
否则老师的这个按钮就白点了。

| 取向 | 环节配比 | 额外目标 | 作业 |
|---|---|---|---|
| A 拓展型 | 导入10% 讲授40% **探究35%** 小结15% | 能提出并验证延伸问题 | 选做：查资料写 300 字对比笔记 |
| B 标准型 | 导入10% 讲授45% 演练30% 小结15% | 独立完成基础练习 | 课后对应章节习题 |
| C 巩固型 | 铺垫10% 讲授35% **例题精讲40%** 小结15% | 跟随例题复现关键步骤 | 重做课堂例题并标注依据 |
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

import db
import llm
from services import retriever, taxonomy as tax

MINUTES_PER_PERIOD = 45

# 三种课堂内容取向
ORIENTATIONS: dict[str, dict] = {
    "A": {
        "name": "拓展型",
        "goal": "能提出并验证延伸问题",
        "homework": "选做：查阅资料后写 300 字对比笔记，说明本文思路与另一种方案的差异。",
        "segments": [
            ("导入", 0.10, "用一个真实问题或反例引发认知冲突，明确本次课的探究问题。"),
            ("讲授", 0.40, "讲清核心原理与推导脉络，指出它在方向前沿中的位置。"),
            ("探究", 0.35, "给出一个开放性问题，分组设计验证方案并汇报结论。"),
            ("小结", 0.15, "回扣探究问题，梳理方法迁移到其它场景的可能性。"),
        ],
    },
    "B": {
        "name": "标准型",
        "goal": "独立完成基础练习",
        "homework": "课后对应章节习题：完成课后第 1~5 题，写出关键步骤依据。",
        "segments": [
            ("导入", 0.10, "回顾上节要点，用一道小题引出本节内容。"),
            ("讲授", 0.45, "按「概念 → 方法 → 例题」顺序完整讲授，强调适用条件。"),
            ("演练", 0.30, "学生独立完成 2 道课堂练习，教师巡视并当堂订正共性错误。"),
            ("小结", 0.15, "归纳本节知识结构，布置作业并提示易错点。"),
        ],
    },
    "C": {
        "name": "巩固型",
        "goal": "跟随例题复现关键步骤",
        "homework": "重做课堂例题并标注每一步依据；对读不懂的步骤写一句话说明卡在哪里。",
        "segments": [
            ("铺垫", 0.10, "先补前置概念与必要工具，用一个类比建立直觉。"),
            ("讲授", 0.35, "只讲最关键的概念与方法，控制信息量，避免一次抛太多。"),
            ("例题精讲", 0.40, "逐题演示计算或推理过程，每步停下来让学生跟做一遍。"),
            ("小结", 0.15, "用一张流程图复述解题步骤，明确课下要重做哪几题。"),
        ],
    },
}


def orientation_of(level: str) -> dict:
    """把前端传来的取向归一化。既接受 ``A/B/C`` 也接受 ``拓展型/标准型/巩固型``。"""
    raw = str(level or "B").strip()
    if raw in ORIENTATIONS:
        return ORIENTATIONS[raw]
    for key, value in ORIENTATIONS.items():
        if value["name"] == raw or value["name"] in raw or key in raw.upper():
            return value
    return ORIENTATIONS["B"]


def orientation_options() -> list[dict]:
    return [
        {"value": key, "label": f"{key} {value['name']}", "goal": value["goal"]}
        for key, value in ORIENTATIONS.items()
    ]


# ================================================================ 教案
def _segments_minutes(level: str, periods: int) -> list[dict]:
    """按 ``periods * 45`` 分配分钟数；最后一环节取余量，保证总和等于总时长。"""
    total = max(1, int(periods or 1)) * MINUTES_PER_PERIOD
    segments = orientation_of(level)["segments"]
    out: list[dict] = []
    allocated = 0
    for index, (step, ratio, content) in enumerate(segments):
        if index == len(segments) - 1:
            minutes = max(1, total - allocated)
        else:
            minutes = max(1, int(round(total * ratio)))
            allocated += minutes
        out.append({"step": step, "content": content, "minutes": minutes})
    return out


def rule_lesson_plan(topic: str, course: str, periods: int, level: str,
                     hits: Sequence[dict] | None = None) -> dict:
    """规则版教案。资料里有内容就引到目标与要点里，绝不凭空编造。"""
    orientation = orientation_of(level)
    topic = (topic or "本次课主题").strip()
    course = (course or "本课程").strip()

    refs = [h.get("ref") for h in (hits or []) if h.get("ref")]
    snippets = [str(h.get("content") or "").strip() for h in (hits or []) if h.get("content")]

    key_points: list[str] = []
    for snippet in snippets:
        first = re.split(r"[。！？；\n]", snippet)[0].strip()
        if 4 <= len(first) <= 40 and first not in key_points:
            key_points.append(first)
        if len(key_points) >= 4:
            break
    if not key_points:
        key_points = [f"{topic}的基本概念与适用条件", f"{topic}的典型方法步骤",
                      f"{topic}的常见错误与辨析"]

    difficulties = [
        f"{topic}中抽象概念与直观理解的衔接（建议用类比或图示）",
        f"{topic}方法的适用条件判断（学生常忽略前提）",
    ]
    if orientation is ORIENTATIONS["C"]:
        difficulties.append("前置工具不熟练导致跟不上例题节奏（需先补基础）")
    elif orientation is ORIENTATIONS["A"]:
        difficulties.append("开放式探究中方案设计的严谨性（需教师给评价维度）")

    objectives = [
        f"能用自己的话说明{topic}的核心思想",
        orientation["goal"],
    ]
    if snippets:
        objectives.append("能结合课堂资料中的具体例子解释该知识点的作用")

    plan = {
        "title": f"{topic}（{orientation['name']}）",
        "course": course,
        "periods": max(1, int(periods or 1)),
        "level": level if str(level).upper()[:1] in "ABC" else "B",
        "orientation": orientation["name"],
        "objectives": objectives,
        "key_points": key_points,
        "difficulties": difficulties,
        "outline": _segments_minutes(level, periods),
        "homework": orientation["homework"],
        "advice": (
            f"本次课按「{orientation['name']}」取向组织，环节配比已按此调整；"
            "若班级内基础差异较大，建议课堂练习采取同题分层要求（同一道题允许不同完成度），"
            "而不是分成不同班级或贴标签。"
        ),
        "refs": refs[:4],
    }
    if not snippets:
        plan["note"] = "本次未检索到教师上传的相关资料，教案为基于主题的通用结构，建议先上传对应课件。"
    return plan


def lesson_plan(topic: str, course: str = "", periods: int = 1, level: str = "B",
                top_k: int = 4) -> dict:
    """生成教案（双引擎）。先检索资料再生成，避免凭空编造。"""
    query = f"{course} {topic}".strip()
    hits = retriever.hybrid_search(query, top_k=top_k, course=course) if query else []
    if not hits and course:
        hits = retriever.hybrid_search(topic, top_k=top_k)

    rule = rule_lesson_plan(topic, course, periods, level, hits)
    context = retriever.context_block(hits, max_chars=2000)

    prompt = (
        f"你是高校教师备课助手。请为「{course}」的「{topic}」设计一份"
        f"{rule['periods']} 课时（每课时 {MINUTES_PER_PERIOD} 分钟）的教案。\n"
        f"课堂内容取向：{rule['orientation']}（{orientation_of(level)['goal']}）。\n"
        "要求：\n"
        "1. 教学目标 2~3 条、重点 3~4 条、难点 2~3 条，均用中文短句；\n"
        "2. outline 必须是 4 个环节，环节名沿用给定配比表，minutes 之和必须等于总时长；\n"
        "3. 只能依据下面提供的资料，资料没覆盖的不要编造；\n"
        "4. 不得出现分班、贴标签式表述。\n\n"
        f"【参考资料】\n{context or '（无）'}"
    )
    result, engine = llm.chat_json(
        [{"role": "user", "content": prompt}],
        '{"title":"","objectives":[""],"key_points":[""],"difficulties":[""],'
        '"outline":[{"step":"","content":"","minutes":0}],"homework":"","advice":""}',
        mock=rule,
    )

    # 分钟总和必须等于总时长：模型算错时用规则版覆盖，保证界面上的数字自洽
    total = rule["periods"] * MINUTES_PER_PERIOD
    outline = result.get("outline")
    if not isinstance(outline, list) or not outline:
        result["outline"] = rule["outline"]
    else:
        clean: list[dict] = []
        for index, seg in enumerate(outline[:4]):
            if not isinstance(seg, dict):
                continue
            try:
                minutes = int(float(seg.get("minutes") or 0))
            except (TypeError, ValueError):
                minutes = 0
            clean.append(
                {
                    "step": str(seg.get("step") or f"环节{index + 1}")[:12],
                    "content": str(seg.get("content") or "")[:200],
                    "minutes": minutes,
                }
            )
        if clean and sum(s["minutes"] for s in clean) != total:
            clean = rule["outline"]
        result["outline"] = clean

    result.setdefault("orientation", rule["orientation"])
    result.setdefault("periods", rule["periods"])
    result.setdefault("refs", rule["refs"])
    result.setdefault("course", course)
    result["total_minutes"] = total
    return {"plan": result, "engine": engine, "refs": rule["refs"]}


# ================================================================ PPT 大纲
def rule_slide_outline(topic: str, pages: int, hits: Sequence[dict] | None = None) -> dict:
    pages = max(3, min(20, int(pages or 8)))
    topic = (topic or "本次课主题").strip()

    titles = [f"{topic}：本节要解决的问题"]
    for snippet in (hits or []):
        first = re.split(r"[。！？；\n]", str(snippet.get("content") or "").strip())[0].strip()
        if 4 <= len(first) <= 30:
            titles.append(first)
    fallback = [
        f"{topic}的核心概念",
        f"{topic}的方法步骤",
        f"{topic}的典型例题",
        f"{topic}的常见错误",
        f"{topic}的实际应用",
        "课堂小结与作业",
    ]
    for name in fallback:
        if len(titles) >= pages:
            break
        titles.append(name)

    slides: list[dict] = []
    for index in range(pages):
        title = titles[index] if index < len(titles) else f"{topic} 补充{index + 1}"
        if index == pages - 1:
            bullets = ["本节要点回顾", "易错点提示", "课后作业与提交要求"]
            note = "最后一页留出提问时间；作业要求逐条念一遍，避免学生漏项。"
        else:
            bullets = [
                f"讲清「{title}」的定义与适用条件",
                "给出一个具体例子并演示完整过程",
                "指出学生最容易出错的一步",
            ][: 4]
            note = f"讲解提示：本页约 3~5 分钟，先问一个学生已知的问题再引入新内容。"
        slides.append({"title": title[:40], "bullets": bullets, "note": note})
    return {"title": topic, "pages": len(slides), "slides": slides}


def slide_outline(topic: str, pages: int = 8, course: str = "") -> dict:
    """生成 PPT 大纲（双引擎）。每页 title + bullets(≤4) + note。"""
    query = f"{course} {topic}".strip()
    hits = retriever.hybrid_search(query, top_k=4, course=course) if query else []
    rule = rule_slide_outline(topic, pages, hits)

    prompt = (
        f"你是高校教师备课助手。请为「{course or '本课程'}」的「{topic}」生成一份 PPT 大纲。\n"
        f"共 {rule['pages']} 页，每页 title 简短、bullets 不超过 4 条、note 是讲给教师看的讲解提示。\n"
        "最后一页固定为课堂小结与作业。只依据给定资料，不要编造。\n\n"
        f"【参考资料】\n{retriever.context_block(hits, max_chars=1600) or '（无）'}"
    )
    result, engine = llm.chat_json(
        [{"role": "user", "content": prompt}],
        '{"title":"","pages":0,"slides":[{"title":"","bullets":[""],"note":""}]}',
        mock=rule,
    )
    slides = result.get("slides")
    if not isinstance(slides, list) or not slides:
        result, engine = rule, "rule"
    else:
        clean = []
        for index, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            bullets = slide.get("bullets") or []
            if isinstance(bullets, str):
                bullets = [bullets]
            clean.append(
                {
                    "title": str(slide.get("title") or f"第 {index + 1} 页")[:40],
                    "bullets": [str(b)[:80] for b in bullets][:4],
                    "note": str(slide.get("note") or "")[:200],
                }
            )
        result["slides"] = clean or rule["slides"]
        result["pages"] = len(result["slides"])
    return {"outline": result, "engine": engine}


# ================================================================ 批改
def key_terms(course: str = "", limit: int = 8) -> list[str]:
    """评分参照要点。

    **只取结构化概念名**：知识点表里的概念名 + 资料中的 markdown 标题。
    直接对正文正则切片会抽出「何让计算机从数据」这类无意义碎片。
    """
    terms: list[str] = []

    if course:
        rows = db.query(
            "SELECT DISTINCT name FROM knowledge_points WHERE course = ? AND name <> '' LIMIT 40",
            (course,),
        )
    else:
        rows = db.query("SELECT DISTINCT name FROM knowledge_points WHERE name <> '' LIMIT 40")
    for row in rows:
        name = str(row.get("name") or "").strip()
        if 2 <= len(name) <= 30:
            terms.append(name)

    # 资料中的 markdown 标题
    mat_rows = (
        db.query("SELECT raw_text FROM materials WHERE raw_text LIKE ? LIMIT 20", (f"%{course}%",))
        if course else db.query("SELECT raw_text FROM materials LIMIT 20")
    )
    for row in mat_rows:
        for line in str(row.get("raw_text") or "").splitlines():
            line = line.strip()
            if line.startswith("#"):
                name = re.sub(r"^#+\s*", "", line).strip()
                if 2 <= len(name) <= 30:
                    terms.append(name)

    # 按连接词拆开，取更细的要点（"注意力机制与位置编码" → 两个要点）
    expanded: list[str] = []
    for term in terms:
        parts = [p.strip() for p in re.split(r"[与和及、，,/]", term) if len(p.strip()) >= 2]
        expanded.extend(parts or [term])

    ordered = list(dict.fromkeys(expanded))
    return ordered[:limit]


def rule_grade(text: str, topic: str = "", full_score: float = 100,
               terms: Sequence[str] | None = None) -> dict:
    """规则版评分：长度分 + 要点覆盖分 + 结构加分。"""
    text = (text or "").strip()
    length = len(text)

    if length >= 600:
        length_score = 40.0
    elif length >= 300:
        length_score = 28.0
    elif length >= 120:
        length_score = 16.0
    else:
        length_score = 6.0

    terms = [t for t in (terms or []) if t]
    hit_terms = [t for t in terms if t in text]
    if terms:
        cover_score = 40.0 * (len(hit_terms) / len(terms))
        cover_note = f"命中要点 {len(hit_terms)}/{len(terms)} 个。"
    else:
        cover_score = 24.0
        cover_note = "未配置参考答案要点，按 60% 中间值计分，建议教师人工复核。"

    structure = 0.0
    if re.search(r"(^\s*[\d一二三四五六七八九十]+[、.．)])", text, re.M) or text.count("\n- ") >= 2:
        structure += 10.0
    if re.search(r"(总结|结论|综上|因此|可见)", text):
        structure += 10.0

    raw = length_score + cover_score + structure          # 百分制原始分
    score = round(min(float(full_score or 100), raw / 100.0 * float(full_score or 100)), 1)

    pct = score / float(full_score or 100)
    level = "A" if pct >= 0.85 else "B" if pct >= 0.70 else "C"
    level_text = {"A": "优秀", "B": "良好", "C": "需改进"}[level]

    highlights: list[str] = []
    if hit_terms:
        highlights.append("覆盖了要点：" + "、".join(hit_terms[:4]))
    if structure >= 10:
        highlights.append("作答有分点或总结，结构清晰")
    if length >= 300:
        highlights.append("篇幅充实，展开较充分")
    if not highlights:
        highlights.append("已作答，具备基本回应")

    missing = [t for t in terms if t not in text][:4]
    parts = [f"本次作答 {length} 字，{cover_note}"]
    if missing:
        parts.append("建议补充：" + "、".join(missing))
    else:
        parts.append("要点覆盖较完整，注意把关键步骤的依据写清楚")
    parts.append(f"综合评定为{level_text}。")
    comment = "；".join(parts) + "（规则生成，可修改后再保存）"

    return {
        "score": score,
        "level": level,
        "level_text": level_text,
        "highlights": highlights,
        "missing": missing,
        "comment": comment,
        "engine": "rule",
        "full_score": float(full_score or 100),
    }


def grade_one(text: str, rubric: str = "", topic: str = "", full_score: float = 100,
              terms: Sequence[str] | None = None) -> tuple[dict, str]:
    """批改单份文字作业（双引擎）。返回 ``(结果, engine)``。"""
    rule = rule_grade(text, topic, full_score, terms)
    prompt = (
        f"你是高校课程助教，正在批改一份作业。主题：{topic or '未指定'}，满分 {full_score} 分。\n"
        f"评分要点参考：{rubric or '、'.join(terms or []) or '未提供'}\n\n"
        f"学生作答：\n{text[:3000]}\n\n"
        "要求：score 为 0~满分的数字；level 为 A/B/C；highlights 与 missing 各 1~3 条；"
        "comment 为 60~120 字中文评语，先肯定再给具体改进建议，语气平和不对人做评价。"
    )
    result, engine = llm.chat_json(
        [{"role": "user", "content": prompt}],
        '{"score":0,"level":"A|B|C","highlights":[""],"missing":[""],"comment":""}',
        mock=rule,
    )
    try:
        score = float(result.get("score") or 0)
    except (TypeError, ValueError):
        score = rule["score"]
    result["score"] = round(max(0.0, min(float(full_score or 100), score)), 1)
    result["level"] = str(result.get("level") or rule["level"]).upper()[:1]
    if result["level"] not in ("A", "B", "C"):
        result["level"] = rule["level"]
    result["level_text"] = {"A": "优秀", "B": "良好", "C": "需改进"}[result["level"]]
    result.setdefault("highlights", rule["highlights"])
    result.setdefault("missing", rule["missing"])
    result.setdefault("comment", rule["comment"])
    result["full_score"] = float(full_score or 100)
    return result, engine


def batch_grade(files: Sequence[tuple[str, str]], course: str = "", topic: str = "",
                full_score: float = 100) -> dict:
    """临时批量批改（**不入库**）。``files`` 为 ``[(filename, text), ...]``。"""
    terms = key_terms(course)
    results = []
    engines = set()
    for filename, text in files:
        if not (text or "").strip():
            results.append({
                "filename": filename,
                "score": 0,
                "level": "C",
                "level_text": "需改进",
                "highlights": [],
                "missing": list(terms[:3]),
                "comment": "该文件没有可读文本（可能是图片或扫描件），需要人工批改或配置视觉模型。",
                "engine": "rule",
                "note": "无文本层",
            })
            engines.add("rule")
            continue
        result, engine = grade_one(text, topic=topic, full_score=full_score, terms=terms)
        result["filename"] = filename
        results.append(result)
        engines.add(engine)

    scores = [r["score"] for r in results]
    return {
        "results": results,
        "summary": {
            "count": len(results),
            "avg": round(sum(scores) / len(scores), 1) if scores else 0,
            "max": max(scores) if scores else 0,
            "min": min(scores) if scores else 0,
            "terms": terms,
        },
        "engine": "llm" if engines == {"llm"} else "rule",
        "stored": False,
    }


def _unused(*_: Iterable) -> None:  # pragma: no cover
    _ = tax
