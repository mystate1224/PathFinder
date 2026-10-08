# -*- coding: utf-8 -*-
"""ragroute.py —— 五种 RAG 架构的**路由与执行**。

为什么要路由，而不是只用混合检索：
混合检索（BM25 + 向量 + RRF）只擅长一类问题——"知识点的文字解释"。
但真实对话里的问题五花八门：问「A 和 B 什么关系」该走图结构；
问「结合我的情况给我个计划」需要先拆任务再调多个数据源；
问「那个为什么不行」这种口语指代，首查大概率落空，得先改写再查；
问「课件里那张图」则必须把图片素材一起召回。
**一种架构解决不了所有问题，所以先路由、再执行。**

五种策略（与业界 2026 五大 RAG 架构对应）：

==== ============ ===========================================
 id  名称          什么时候用
==== ============ ===========================================
hybrid   混合式     知识点的文字解释（★ 当前唯一启用）
graph    图谱式     问关系 / 关联 / 前置 / 知识链路
agentic  智能体式   复合任务：结合我的情况、要计划、要对比
corrective 纠错式   口语 / 指代 / 含糊，首查易落空
multimodal 多模态  问图表 / 图片 / 扫描件 / 版面内容
==== ============ ===========================================

## 当前落地口径（2026-10-08 调整）

**只保留一种真实实现：``hybrid`` 混合式** —— BM25 关键词 + 向量语义双路召回，
RRF 融合。理由：多策略路由的落地与维护成本高于收益，而混合式在绝大多数
教学问答场景下已足够稳，且行为可预测、便于排查。

其余四种**保留接口、移除实现**：

  * ``STRATEGIES`` 仍登记五种（带 ``enabled`` 标记），前端据此展示与置灰；
  * ``execute()`` 的分派表仍保留五个入口，未启用的策略统一回落到混合式执行，
    并在 ``extra.note`` 里如实标注"该策略未启用，已按混合式执行"——不假装跑过；
  * 各自的 ``_ex_*`` 函数保留同名占位（docstring 写明"接口保留，实现待接回"），
    将来要接回时只需在函数体内补实现，调用方与前端一行都不用改。

路由接口同样保留：``route()`` 现在恒定返回 hybrid；``route_llm()`` 是模型路由
预留口，将来想让模型挑策略时接入即可。

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
    {"id": "hybrid", "name": "混合式 RAG", "enabled": True,
     "desc": "BM25 关键词 + 向量语义双路召回，RRF 融合，再交模型作答。",
     "when": "知识点的文字解释、概念问答（当前唯一启用）"},
    {"id": "graph", "name": "图谱 RAG", "enabled": False,
     "desc": "以知识点为节点、课程与方向为边建图，先查子图再看证据。",
     "when": "问关系：A 和 B 什么关系、先学哪个、知识链路"},
    {"id": "agentic", "name": "智能体式 RAG", "enabled": False,
     "desc": "先规划，再调用多个工具（资料检索 / 知识点库 / 学情画像），最后聚合推理。",
     "when": "复合任务：结合我的情况、要计划、要对比分析"},
    {"id": "corrective", "name": "纠错型 RAG", "enabled": False,
     "desc": "先给检索质量打分，不合格就改写问题再查一次，而不是硬答。",
     "when": "口语、指代（那个 / 它）、首查容易落空的问题"},
    {"id": "multimodal", "name": "多模态 RAG", "enabled": False,
     "desc": "文本块与图片素材统一召回，回答同时引用文字与图片资料。",
     "when": "问图表、图片、扫描件、课件版面"},
]

# 当前唯一启用的策略。改这一行即可整体切换（其余策略实现接回后置 True）。
DEFAULT_STRATEGY = "hybrid"

_STRATEGY_INDEX = {s["id"]: s for s in STRATEGIES}

# ================================================================ 路由
def route(question: str, side: str = "student") -> dict[str, Any]:
    """路由：当前**恒定**返回混合式。

    接口保留（调用方与前端不变），将来要恢复多策略路由时，在函数体内补判定
    逻辑即可；模型路由见 ``route_llm``。
    """
    text = (question or "").strip()
    if not text:
        return _route_view(DEFAULT_STRATEGY, "空问题按默认策略处理", 0.4)
    return _route_view(DEFAULT_STRATEGY, "统一走混合式：BM25 + 向量双路召回，RRF 融合", 0.9)


def resolve(question: str, side: str = "student", strategy: str = "") -> dict[str, Any]:
    """路由统一入口：``strategy`` 为空或 ``auto`` 时走默认策略，否则按演示指定走。

    未启用的策略也能被"手动指定"，但 ``execute`` 会如实回落到混合式并在
    ``extra.note`` 里标注 —— 不假装跑过未实现的架构。
    将来想让模型自己挑，把这里的 ``route`` 换成 ``route_llm`` 即可，
    下游调用方与前端都不用改。
    """
    sid = (strategy or "").strip()
    manual = bool(sid) and sid != "auto"
    view = route(question, side)
    if manual:
        if sid not in _STRATEGY_INDEX:
            sid = DEFAULT_STRATEGY
        view = _route_view(sid, "手动指定：按所选策略执行", 1.0)
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
    """执行某个策略。所有策略都返回同构 hits + 各自的 extra。

    未启用的策略（``enabled=False``）保留分派入口，但统一回落到混合式，
    并在 ``extra.note`` 里注明，避免界面上出现"选了 A 却按 B 算"的误解。
    """
    sid = strategy if strategy in _STRATEGY_INDEX else DEFAULT_STRATEGY
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
    """图谱式 —— **接口保留，实现待接回**。

    原实现：知识点建图（同课程 / 共享方向词为边）→ 种子扩一跳取子图 → 取文本证据。
    当前统一回落到混合式，回落事实写入 ``extra.note``。
    接回时在本函数体内补实现即可，调用方与前端无需改动。
    """
    out = _ex_hybrid(question, user, top_k, course)
    return {"strategy": "graph", "hits": out["hits"],
            "extra": {"note": "图谱式未启用，已按混合式执行（接口保留）"}}


def _ex_agentic(question: str, user: dict, top_k: int, course: str) -> dict:
    """智能体式 —— **接口保留，实现待接回**。

    原实现：规划 → 调资料检索 / 知识点库 / 学情画像三个工具 → 聚合证据。
    当前统一回落到混合式；个性化仍由 ``synth.compose`` 的画像参数保证。
    """
    out = _ex_hybrid(question, user, top_k, course)
    return {"strategy": "agentic", "hits": out["hits"],
            "extra": {"note": "智能体式未启用，已按混合式执行（接口保留）"}}


def _ex_corrective(question: str, user: dict, top_k: int, course: str) -> dict:
    """纠错型 —— **接口保留，实现待接回**。

    原实现：首查打分，最高分 < 0.35 判偏弱 → 去填充词 / 补检索词后二次检索。
    当前统一回落到混合式（只检索一轮）。
    """
    out = _ex_hybrid(question, user, top_k, course)
    return {"strategy": "corrective", "hits": out["hits"],
            "extra": {"note": "纠错型未启用，已按混合式执行（接口保留）"}}


def _ex_multimodal(question: str, user: dict, top_k: int, course: str) -> dict:
    """多模态 —— **接口保留，实现待接回**。

    原实现：文本块 + materials 表里的图片素材统一召回。
    当前统一回落到混合式，**图片素材不再进入证据链**（已知回退：问"课件里那张图"
    时不会有图片引用）。接回时在此补图片召回即可。
    """
    out = _ex_hybrid(question, user, top_k, course)
    return {"strategy": "multimodal", "hits": out["hits"],
            "extra": {"note": "多模态未启用，已按混合式执行（接口保留）"}}


def strategies_view() -> list[dict[str, Any]]:
    """五种策略的展示数据。``enabled=False`` 的由前端置灰标注「规划中」。"""
    return STRATEGIES


def enabled_ids() -> list[str]:
    """当前真正有实现的策略 id（前端据此禁用未启用的选项）。"""
    return [s["id"] for s in STRATEGIES if s.get("enabled")]
