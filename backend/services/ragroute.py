# -*- coding: utf-8 -*-
"""ragroute.py —— 五种 RAG 架构的**路由与执行**。

为什么要路由，而不是只用混合检索：
混合检索（BM25 + 向量 + RRF）只擅长一类问题——"知识点的文字解释"。
但真实对话里的问题五花八门：问「A 和 B 什么关系」该走图结构；
问「结合我的情况给我个计划」需要先拆任务再调多个数据源；
问「那个为什么不行」这种口语指代，首查大概率落空，得先改写再查；
问「课件里那张图」则必须把图片素材一起召回。
**一种架构解决不了所有问题，所以先路由、再执行。**

五种策略（与业界 2026 五大 RAG 架构对应，全部有真实实现，不依赖网络）：

==== ============ ===========================================
 id  名称          什么时候用
==== ============ ===========================================
hybrid   混合式     知识点的文字解释（默认兜底）
graph    图谱式     问关系 / 关联 / 前置 / 知识链路
agentic  智能体式   复合任务：结合我的情况、要计划、要对比
corrective 纠错式   口语 / 指代 / 含糊，首查易落空
multimodal 多模态  问图表 / 图片 / 扫描件 / 版面内容
==== ============ ===========================================

路由本身也有两条引擎：
  * 规则路由（默认，断网可用）：关键词模式 + 意图词典
  * 模型路由（``route_llm``，接口已留好）：让模型从五选一并给出理由，规则版作 mock 兜底

每个策略的 ``execute`` 返回统一结构::

    {strategy, hits:[...], extra:{strategy-specific}}

``hits`` 保证与 ``retriever.hybrid_search`` 同构（ref / content / via / fused_score），
下游 ``tutor.rule_answer`` 与引用卡不用改。
"""
from __future__ import annotations

import re
from typing import Any

import db
from services import retriever
from services.rag import search_scope as db_scope  # 用户数据隔离的可见范围子句

STRATEGIES: list[dict[str, str]] = [
    {"id": "hybrid", "name": "混合式 RAG",
     "desc": "BM25 关键词 + 向量语义双路召回，RRF 融合，再交模型作答。",
     "when": "知识点的文字解释、概念问答（默认兜底）"},
    {"id": "graph", "name": "图谱 RAG",
     "desc": "以知识点为节点、课程与方向为边建图，先查子图再看证据。",
     "when": "问关系：A 和 B 什么关系、先学哪个、知识链路"},
    {"id": "agentic", "name": "智能体式 RAG",
     "desc": "先规划，再调用多个工具（资料检索 / 知识点库 / 学情画像），最后聚合推理。",
     "when": "复合任务：结合我的情况、要计划、要对比分析"},
    {"id": "corrective", "name": "纠错型 RAG",
     "desc": "先给检索质量打分，不合格就改写问题再查一次，而不是硬答。",
     "when": "口语、指代（那个 / 它）、首查容易落空的问题"},
    {"id": "multimodal", "name": "多模态 RAG",
     "desc": "文本块与图片素材统一召回，回答同时引用文字与图片资料。",
     "when": "问图表、图片、扫描件、课件版面"},
]

_STRATEGY_INDEX = {s["id"]: s for s in STRATEGIES}

# 路由规则：顺序有讲究，先判更具体的意图。
_ROUTE_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("graph", re.compile(
        r"关系|关联|联系|依赖|前置|基础.{0,4}是|先学|链路|脉络|知识图谱|"
        r"和.{1,10}(?:有什么|有什么样的)(?:关系|联系|区别)")),
    ("multimodal", re.compile(
        r"图\s*[里表中片]|图表|图上|板书|扫描|截图|课件里|第\s*[一二三四五六七八九十\d]+\s*页|"
        r"那张|这页|照片")),
    ("agentic", re.compile(
        r"帮我|给我|为我|规划|计划|方案|建议|该怎么安排|结合我|根据我|针对我|"
        r"对比|分析一下|总结一下我|生成|制定")),
    ("corrective", re.compile(
        r"^(?:那个|这个|它|他们|上面|刚才)|也就是说|简单说|通俗|"
        r"啥|为撒|咋|为什么不|到底")),
]

# 概念题：短问题（"什么是 X"）不能因为字数少就被当成口语指代，
# 这类问题对象明确，混合检索最稳。放在纠错式之后、长度兜底之前。
_CONCEPT = re.compile(
    r"什么是|是什么|什么叫|什么叫|定义|解释|原理|介绍一下|介绍下|讲一下|讲讲|"
    r"如何理解|怎么理解|如何计算|怎么算|区别|优缺点|优势|作用"
)

_FILLERS = re.compile(r"请问|帮忙|帮我|一下|那个|这个|它|到底|究竟|我想知道|告诉我")


def _grams(text: str, n: int = 2) -> set[str]:
    """把中文串切成 n-gram —— 知识点名往往比问句里的说法长
    （问「反向传播」，库里叫「反向传播的基本形式」），整串相等几乎必不中。"""
    out: set[str] = set()
    for chunk in re.findall(r"[一-龥A-Za-z0-9]{2,}", text or ""):
        for i in range(len(chunk) - n + 1):
            out.add(chunk[i:i + n])
    return out


def _seed_nodes(nodes: list[dict], question: str, limit: int = 4) -> list[str]:
    q = _grams(question)
    scored = []
    for n in nodes:
        hit = len(q & _grams(n["id"]))
        if hit:
            scored.append((hit, n["id"]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [name for _, name in scored[:limit]]


# ================================================================ 路由
def route(question: str, side: str = "student") -> dict[str, Any]:
    """规则路由：返回 ``{strategy, strategy_name, reason, confidence}``。"""
    text = (question or "").strip()
    if not text:
        return _route_view("hybrid", "空问题按默认策略处理", 0.4)
    for sid, pattern in _ROUTE_PATTERNS:
        m = pattern.search(text)
        if m:
            return _route_view(sid, f"命中信号：「{m.group(0)}」", 0.78)
    if _CONCEPT.search(text):
        return _route_view("hybrid", "概念题：对象明确，双路检索最稳", 0.74)
    # 文本较长且无特殊信号 → 混合检索最稳
    if len(text) >= 10:
        return _route_view("hybrid", "知识性提问，双路检索最稳", 0.72)
    return _route_view("corrective", "问题较短且无明确对象，先走纠错改写", 0.6)


def resolve(question: str, side: str = "student", strategy: str = "") -> dict[str, Any]:
    """路由统一入口：``strategy`` 为空或 ``auto`` 时自动路由，否则按演示指定走。

    自动路由目前是规则版（断网可用）；想让模型自己挑，把这里换成 ``route_llm`` 即可，
    下游调用方与前端都不用改。
    """
    sid = (strategy or "").strip()
    manual = bool(sid) and sid != "auto"
    view = route(question, side)
    if manual:
        if sid not in _STRATEGY_INDEX:
            sid = "hybrid"
        view = _route_view(sid, "演示指定：手动切换策略", 1.0)
    view["auto"] = not manual
    view["side"] = side
    return view


def _route_view(sid: str, reason: str, confidence: float) -> dict[str, Any]:
    meta = _STRATEGY_INDEX.get(sid, _STRATEGY_INDEX["hybrid"])
    return {"strategy": meta["id"], "strategy_name": meta["name"],
            "reason": reason, "confidence": confidence}


def route_llm(question: str, side: str = "student") -> dict[str, Any]:
    """模型路由（接口已留好）：让模型从五种策略里选一个并给理由。

    规则版作 mock 兜底，所以断网时这个函数同样可用 —— 与全项目双引擎口径一致。
    """
    from services import interaction as ia  # 局部导入避免循环

    rule = lambda: route(question, side)  # noqa: E731
    prompt = (
        "你是检索策略路由器。根据问题选择最合适的一种检索策略，只输出 JSON。\n"
        "可选策略：" + "；".join(f"{s['id']}（{s['when']}）" for s in STRATEGIES) + "\n"
        f"问题：{question}\n"
        '输出：{"strategy": "id", "reason": "一句话理由"}'
    )
    data, engine = llm_chat_json_safe(prompt, mock=rule)
    sid = str(data.get("strategy") or "")
    view = _route_view(sid if sid in _STRATEGY_INDEX else "hybrid",
                       str(data.get("reason") or "模型选择"), 0.85)
    view["engine"] = engine
    return view


def llm_chat_json_safe(prompt: str, mock):
    """延迟导入，避免 ragroute 在 import 期就拉起 llm 的配置依赖。"""
    import llm
    return llm.chat_json([{"role": "user", "content": prompt}], "", mock=mock)


# ================================================================ 执行
def _scope(user: dict) -> tuple[int, bool]:
    """从 user dict 取检索可见范围： ``(owner_id, teacher)``。

    用户隔离在这里统一下沉 —— 五种策略共享同一条规则：
    学生 = 自己 + 已导入的教师公用资料；教师 = 自己 + 全部教师公用资料。
    """
    u = user or {}
    return int(u.get("id") or 0), str(u.get("role")) == "teacher"


def execute(strategy: str, question: str, user: dict | None = None,
            top_k: int = 4, course: str = "") -> dict[str, Any]:
    """执行某个策略。所有策略都返回同构 hits + 各自的 extra。"""
    sid = strategy if strategy in _STRATEGY_INDEX else "hybrid"
    fn = {
        "hybrid": _ex_hybrid,
        "graph": _ex_graph,
        "agentic": _ex_agentic,
        "corrective": _ex_corrective,
        "multimodal": _ex_multimodal,
    }[sid]
    return fn(question, user or {}, top_k, course)


def _hit(ref: str, content: str, via: str, score: float, course: str = "") -> dict:
    return {"ref": ref, "content": content[:300], "via": via,
            "fused_score": round(float(score), 5), "course": course}


def _ex_hybrid(question: str, user: dict, top_k: int, course: str) -> dict:
    oid, teacher = _scope(user)
    hits = retriever.hybrid_search(question, top_k=top_k, course=course,
                                   owner_id=oid, teacher=teacher)
    return {"strategy": "hybrid", "hits": hits,
            "extra": {"note": f"双路召回 {len(hits)} 条，RRF 融合"}}


def _ex_graph(question: str, user: dict, top_k: int, course: str) -> dict:
    """图谱式：知识点为节点，同学课程 / 共享方向词为边；先取子图，再取文本证据。"""
    oid, teacher = _scope(user)
    clause, args = db_scope(oid, teacher)
    rows = db.query(
        "SELECT name, course, difficulty, keywords FROM knowledge_points WHERE 1=1" +
        clause + " LIMIT 300",
        tuple(args),
    )
    nodes, edges = [], []
    for r in rows:
        name = str(r["name"] or "").strip()
        if name:
            nodes.append({"id": name, "course": r["course"] or "",
                          "difficulty": r["difficulty"] or "B",
                          "keywords": db.jload(r.get("keywords"), [])})
    index = {n["id"]: i for i, n in enumerate(nodes)}
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            weight = 0
            if a["course"] and a["course"] == b["course"]:
                weight += 1
            shared = set(a["keywords"]) & set(b["keywords"])
            weight += len(shared)
            if weight >= 2:
                edges.append({"source": a["id"], "target": b["id"], "weight": weight,
                              "reason": "同课程" if a["course"] == b["course"] else "共享方向词"})

    # 子图：问题命中的知识点为种子，扩一跳邻居
    seeds = _seed_nodes(nodes, question)
    sub_nodes = list(seeds)
    for e in edges:
        if e["source"] in seeds and e["target"] not in sub_nodes:
            sub_nodes.append(e["target"])
        if e["target"] in seeds and e["source"] not in sub_nodes:
            sub_nodes.append(e["source"])
    sub_nodes = sub_nodes[:12]
    sub_edges = [e for e in edges if e["source"] in sub_nodes and e["target"] in sub_nodes][:20]

    hits = retriever.hybrid_search(question, top_k=top_k, course=course,
                                   owner_id=oid, teacher=teacher)
    if seeds and not hits:
        # 图上有结构但文本库没证据时，用知识点本身做可引用的"证据"
        course_of = {n["id"]: n["course"] for n in nodes}
        hits = [_hit(f"知识点 · {s}", f"{s}（{course_of.get(s) or '—'}）", "graph", 0.42)
                for s in seeds]
    return {"strategy": "graph", "hits": hits,
            "extra": {"graph": {"nodes": sub_nodes, "edges": sub_edges,
                                "total_nodes": len(nodes), "total_edges": len(edges)},
                      "note": f"子图 {len(sub_nodes)} 节点 / {len(sub_edges)} 边，证据 {len(hits)} 条"}}


def _ex_agentic(question: str, user: dict, top_k: int, course: str) -> dict:
    """智能体式：规划 → 逐工具执行 → 聚合。每个工具都有真实数据来源。"""
    oid, teacher = _scope(user)
    plan: list[dict[str, Any]] = []
    hits: list[dict] = []

    # 工具一：资料检索
    found = retriever.hybrid_search(question, top_k=top_k, course=course,
                                    owner_id=oid, teacher=teacher)
    plan.append({"tool": "资料检索（混合式）", "found": len(found),
                 "note": "BM25 + 向量双路"})
    hits.extend(found)

    # 工具二：知识点库
    tokens = [t for t in re.split(r"[\s，,。？?、：:；;（）()]+", question) if len(t) >= 2]
    kp_clause, kp_args = db_scope(oid, teacher)
    kp_rows = db.query(
        "SELECT name, course, difficulty FROM knowledge_points WHERE 1=1" +
        kp_clause + " LIMIT 200", tuple(kp_args),
    )
    kps = [r for r in kp_rows
           if any(t in str(r["name"]) or str(r["name"]) in question for t in tokens)][:3]
    plan.append({"tool": "知识点库", "found": len(kps), "note": "按问题实词匹配"})
    for r in kps:
        hits.append(_hit(f"知识点 · {r['name']}",
                         f"{r['name']}（{r['course']}，难度 {r['difficulty']}）", "agentic", 0.40,
                         r["course"] or ""))

    # 工具三：学情画像（学生）或课程知识点分布（教师）
    uid = int(user.get("id") or 0)
    if str(user.get("role")) == "student":
        prof = db.student_profile(uid) or {}
        plan.append({"tool": "学情画像", "found": 1 if prof else 0,
                     "note": f"主标签 {prof.get('track') or '—'} · 层次 {prof.get('grade_level') or '—'}"})
    else:
        cnt = db.scalar("SELECT COUNT(*) FROM knowledge_points", (), 0)
        plan.append({"tool": "课程知识点分布", "found": int(cnt or 0),
                     "note": f"知识点库共 {cnt} 条，供备课引用"})

    return {"strategy": "agentic", "hits": hits[:top_k + 3],
            "extra": {"plan": plan,
                      "note": f"规划 {len(plan)} 步，聚合 {len(hits)} 条证据"}}


def _ex_corrective(question: str, user: dict, top_k: int, course: str) -> dict:
    """纠错式：先查一次并评分，不合格就改写再查。改写逻辑可见、可解释。"""
    oid, teacher = _scope(user)
    round1 = retriever.hybrid_search(question, top_k=top_k, course=course,
                                     owner_id=oid, teacher=teacher)
    best = max([float(h.get("fused_score") or 0) for h in round1] or [0])
    quality = "合格" if (round1 and best >= 0.35) else "偏弱"

    if quality == "合格":
        return {"strategy": "corrective", "hits": round1,
                "extra": {"rounds": 1, "quality": quality,
                          "note": f"首查 {len(round1)} 条即达标（最高分 {best:.2f}），无需改写"}}

    rewritten = _rewrite(question, course)
    round2 = retriever.hybrid_search(rewritten, top_k=top_k, course=course,
                                     owner_id=oid, teacher=teacher) \
        if rewritten != question else []
    hits = round2 or round1
    return {"strategy": "corrective", "hits": hits,
            "extra": {"rounds": 2, "quality": quality,
                      "rewrite": {"from": question, "to": rewritten},
                      "note": f"首查偏弱（最高分 {best:.2f}），改写后召回 {len(round2)} 条"}}


def _rewrite(question: str, course: str) -> str:
    """保守改写：去掉口语填充词；改完没变化就补检索词。不假装做了语义改写。"""
    cleaned = _FILLERS.sub("", question).strip(" ，。？?")
    if cleaned and cleaned != question:
        return cleaned
    suffix = " 概念 解释 例题" if course else " 概念 定义 用法"
    return (question + suffix).strip()


def _ex_multimodal(question: str, user: dict, top_k: int, course: str) -> dict:
    """多模态：文本块 + 图片素材一起召回。图片素材来自 materials 表里的图片文件。"""
    oid, teacher = _scope(user)
    hits = retriever.hybrid_search(question, top_k=top_k, course=course,
                                   owner_id=oid, teacher=teacher)
    images: list[dict[str, Any]] = []
    # materials 表主键是 id（不是 material_id），范围子句必须换成 id_col="id"。
    img_clause, img_args = db_scope(oid, teacher, id_col="id")
    rows = db.query(
        "SELECT id, filename, kind, category, parsed FROM materials "
        "WHERE (stored LIKE '%.png' OR stored LIKE '%.jpg' OR stored LIKE '%.jpeg')" +
        img_clause + " ORDER BY id DESC LIMIT 20",
        tuple(img_args),
    )
    for r in rows:
        parsed = db.jload(r.get("parsed"), {}) or {}
        images.append({"material_id": r["id"], "filename": r["filename"],
                       "kind": r["kind"], "category": r["category"],
                       "summary": str(parsed.get("summary") or "")[:120],
                       "title": str(parsed.get("title") or r["filename"])})
    # 问题或文本证据命中图片标题时，把图片排进证据
    for img in images:
        blob = img["title"] + img["summary"] + img["filename"]
        if any(t in blob for t in re.split(r"[\s，,。？?]+", question) if len(t) >= 2):
            hits.append(_hit(f"图片 · {img['title']}", img["summary"] or "（图片素材）",
                             "multimodal", 0.45))
            break
    return {"strategy": "multimodal", "hits": hits,
            "extra": {"images": images[:6],
                      "note": f"文本证据 {len(hits)} 条，图片素材库 {len(images)} 项"}}


def strategies_view() -> list[dict[str, str]]:
    return STRATEGIES
