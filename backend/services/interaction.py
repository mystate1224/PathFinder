# -*- coding: utf-8 -*-
"""interaction.py —— 能力③「交互式答疑」的**交互协议**。

把「答疑」这件含糊的事拆成四个明确问题：

**答什么疑**：不是什么都能答。学生侧限定 8 类（概念辨析 / 作业卡点 / 方法步骤 /
路径规划 / 资源获取 / 资料解析 / 平台操作 / 其他），教师侧限定 6 类（学生情况 / 备课 /
讲解 / 批改标准 / 班级学情 / 操作）。分类结果随回答返回，答不上来的会明说，
不会硬凑。

**与谁交互**：:data:`COUNTERPART` 定义了两端。学生 ↔ 分层答疑智能体，
答不出来可升级给教师；教师 ↔ Copilot 智能体，产出可直接落回备课 / 作业 / 批改。

**怎么交互**：四段式协议 :data:`PROTOCOL_STAGES` ——
``clarify（信息不足先澄清）→ scaffold（按层次给不同强度的脚手架）→
answer（带引用作答）→ consolidate（给追问建议与可执行下一步）``。
每一步都对前端可见，不是一个黑盒的一次性问答。

**得到什么**：:data:`OUTPUT_CONTRACT` —— 答案之外还要有引用、追问、动作、
涉及的知识点，以及引擎标识（AI 生成 / 规则生成）。

纯函数模块：不碰数据库与网络，tutor / copilot 共用。
"""
from __future__ import annotations

import re
from typing import Any

# ================================================================ 答什么疑
QUESTION_TYPES: dict[str, list[dict[str, Any]]] = {
    "student": [
        {"id": "concept", "label": "概念辨析", "hint": "两个概念有什么区别？为什么要这样做？这个术语到底指什么？",
         "pattern": re.compile(r"区别|不同|差异|是什么|什么叫|指的是|为什么|为何|原因|辨析|意义")},
        {"id": "homework", "label": "作业卡点", "hint": "这道题卡在哪一步？我这样做对不对？",
         "pattern": re.compile(r"这道题|这题|作业|错题|哪里错|为什么错|怎么做|卡住|不会做")},
        {"id": "method", "label": "方法步骤", "hint": "先做什么再做什么？参数怎么调？",
         "pattern": re.compile(r"怎么(?:做|求|算|调|选|实现)|步骤|流程|如何|方法")},
        {"id": "path", "label": "路径规划", "hint": "我这个情况该走学业还是就业？接下来学什么？",
         "pattern": re.compile(r"方向|规划|出路|考研|就业|实习|接下来|该学|选哪")},
        {"id": "resource", "label": "资源获取", "hint": "有没有相关的资料或项目可以练？",
         "pattern": re.compile(r"资料|材料|资源|题|项目|练|推荐.*(?:书|课|视频)")},
        # v7.5 新增（加规则只 append）：学生三大高频需求里的「上传解析 / 总结」类。
        # 放在 resource 之后：问"有没有资料"仍归 resource，带"这份/我上传"的解析总结才归这里。
        {"id": "material", "label": "资料解析", "hint": "我上传的笔记 / 文档，帮我解析或总结要点",
         "pattern": re.compile(r"解析|总结|概括|归纳|我上传|上传了|我传了|"
                               r"这份(?:笔记|文档|资料|课件|论文|讲义)|我的(?:笔记|文档|资料)")},
        {"id": "ops", "label": "平台操作", "hint": "这个功能在哪、怎么用？",
         "pattern": re.compile(r"在哪|怎么用|如何上传|怎么提交|功能|入口")},
    ],
    "teacher": [
        {"id": "student", "label": "查学生", "hint": "某个学生/某批学生的画像与短板",
         "pattern": re.compile(r"学生|谁|哪些人|画像|成绩|表现|情况")},
        {"id": "lesson", "label": "备课", "hint": "出一节课的教案 / 大纲 / PPT 结构",
         "pattern": re.compile(r"备.{0,6}课|教案|教学设计|大纲|课件|ppt|讲义|出.{0,3}(?:卷|题)")},
        {"id": "explain", "label": "讲知识点", "hint": "把这个知识点讲成能直接上课用的版本",
         "pattern": re.compile(r"讲一下|讲讲|讲解|解释|原理|怎么理解")},
        {"id": "grading", "label": "批改与评分标准", "hint": "给一份评分标准或评语模板",
         "pattern": re.compile(r"批改|评分|打分|评语|标准|档| rubric|怎么给分")},
        {"id": "class", "label": "班级学情", "hint": "全班的整体分布与共性问题",
         "pattern": re.compile(r"班里|班级|全班|整体|分布|共性|学情")},
        {"id": "ops", "label": "平台操作", "hint": "这个功能在哪、怎么用",
         "pattern": re.compile(r"在哪|怎么用|如何|功能|入口")},
    ],
}

# ================================================================ 与谁交互
COUNTERPART: dict[str, dict[str, Any]] = {
    "student": {
        "agent": "学生 Copilot 智能体",
        "who": "学生本人（一对一，不公开、不进班级排行）",
        "escalate_to": "授课教师（答不上来或需要人工判定时，给出「转问老师」动作）",
        "memory": "多轮上下文 + 学生画像（主标签 / 学业层次 / 兴趣方向）",
        "grounding": "只引用教师上传并入库的资料；没有依据时明确说明，不编造",
    },
    "teacher": {
        "agent": "教师 Copilot 智能体",
        "who": "任课教师（能看到本班数据，看不到其他班）",
        "escalate_to": "产出的草稿直接落回备课 / 作业 / 批改模块",
        "memory": "最近若干轮上下文 + 所任教班级的学情",
        "grounding": "查事实走数据库，讲内容走上传资料，两者分开展示",
    },
}

# ================================================================ 怎么交互
PROTOCOL_STAGES: list[dict[str, Any]] = [
    {"id": "clarify", "name": "澄清", "desc": "问题过于笼统（缺对象/缺条件）时，先回一个澄清问题，不硬答。"},
    {"id": "scaffold", "name": "脚手架", "desc": "按学业层次决定讲解深度与提示强度：A 层给方向与关键一步，C 层给分步拆解与示范。"},
    {"id": "answer", "name": "作答", "desc": "带引用作答，每条结论可回溯到具体资料片段与检索通道。"},
    {"id": "consolidate", "name": "巩固", "desc": "给出 3 个追问建议与可执行下一步，把一次问答变成一次推进。"},
]

# 脚手架强度：A/B/C 只影响"给多少提示"，不影响能不能问、问什么
SCAFFOLD: dict[str, dict[str, Any]] = {
    "A": {"steps": 2, "give_answer": False, "style": "先给方向与关键一步，留推导空间",
          "next": "再做一道需要推导或证明的变式"},
    "B": {"steps": 3, "give_answer": False, "style": "给思路框架 + 关键提示，答案留给你补齐",
          "next": "完成一道同类中等题并自评"},
    "C": {"steps": 4, "give_answer": True, "style": "拆成小步骤，配示范与模板，逐步跟做",
          "next": "先复现示范，再做一道基础题"},
}

# ================================================================ 得到什么
OUTPUT_CONTRACT: list[dict[str, str]] = [
    {"field": "answer", "desc": "答案正文（分层组织，带引用标记）"},
    {"field": "intent", "desc": "{type,label,confidence} —— 本次属于哪一类问题，置信度多少"},
    {"field": "protocol", "desc": "{stage,need_clarify,clarify_question,scaffold} —— 当前处在协议哪一段"},
    {"field": "hits", "desc": "命中的资料片段（含 ref / via / score / snippet），保证可溯源"},
    {"field": "followups", "desc": "3 个追问建议，一键接着问"},
    {"field": "actions", "desc": "可执行下一步（练习 / 资源 / 转问老师 / 落地到某模块）"},
    {"field": "kps", "desc": "本次涉及的知识点（名称 + 类型 + 难度）"},
    {"field": "engine", "desc": "AI 生成 / 规则生成，界面常显徽标"},
]


def classify(question: str, side: str = "student") -> dict[str, Any]:
    """问题分类。返回 ``{type, label, confidence}``。"""
    text = (question or "").strip()
    table = QUESTION_TYPES.get(side, QUESTION_TYPES["student"])
    if not text:
        return {"type": "other", "label": "未分类", "confidence": 0.0}
    for item in table:
        if item["pattern"].search(text):
            return {"type": item["id"], "label": item["label"], "confidence": 0.75}
    return {"type": "other", "label": "其他", "confidence": 0.4}


_VAGUE = re.compile(r"^(?:为什么|怎么|如何|讲讲|讲一下|说说)?\s*(?:它|这个|那个|这|那)\s*$")


def needs_clarify(question: str, hits: list[dict] | None = None) -> dict[str, Any]:
    """协议第一段：判断要不要先澄清。

    触发条件：问题过短（<6 字）、纯指代（"这个为什么"）、或检索完全无命中。
    """
    text = (question or "").strip()
    reason = ""
    if len(text) < 6:
        reason = "问题太短，缺少对象"
    elif _VAGUE.search(text):
        reason = "问题里只有代词，看不出指什么"
    elif not (hits or []) and len(text) < 12:
        reason = "问题很短，且知识库里暂时没检索到相关材料"
    if not reason:
        return {"need_clarify": False, "clarify_question": "", "reason": ""}
    return {
        "need_clarify": True,
        "reason": reason,
        "clarify_question": "方便把问题再具体一点吗？例如指明**哪门课 / 哪个概念 / 卡在哪一步**，"
                            "或者把题目原文贴进来。也可以先从右侧「试试这些问题」里选一个。",
    }


def scaffold_of(level: str) -> dict[str, Any]:
    """协议第二段：按层次取脚手架强度。层次只影响讲解深度与任务难度。"""
    key = str(level or "B").upper().strip()[:1]
    return SCAFFOLD.get(key, SCAFFOLD["B"])


_FOLLOWUP_TPL: dict[str, list[str]] = {
    "concept": ["能举一个具体的例子吗？", "它和相近概念的区别是什么？", "这个概念常在哪类题里考？"],
    "homework": ["这一步为什么这么变形？", "换个条件结论还成立吗？", "给我一道同类题练一下"],
    "method": ["每一步的依据是什么？", "参数/条件怎么选？", "有没有更简单的做法？"],
    "path": ["我现在最该补的是哪一块？", "有没有可以马上做的项目？", "这个方向需要哪些前置知识？"],
    "resource": ["有没有更基础的入门材料？", "这份材料该怎么用？", "做完之后怎么检验效果？"],
    "material": ["这份资料里哪些是必背的重点？", "帮我把薄弱点整理成错题卡", "基于这份资料出几道练习题"],
    "ops": ["还有哪些入口经常被忽略？", "失败了一般是什么原因？"],
    "student": ["他的短板该怎么补？", "给他布置什么任务合适？", "和他同类型的学生还有谁？"],
    "lesson": ["这节课的重难点该放在哪？", "有没有更合适的例子？", "怎么设计课堂提问？"],
    "explain": ["学生最容易卡在哪一步？", "有没有一个能记住的类比？", "板书该怎么组织？"],
    "grading": ["这份评分标准怎么分档？", "评语怎么写更有针对性？", "常见扣分点有哪些？"],
    "class": ["共性问题是哪些？", "哪些学生需要单独关注？", "下节课该调整什么？"],
    "other": ["能再具体一点吗？", "有没有相关的资料可以参考？"],
}


def followups_of(intent_type: str, kps: list[dict] | None = None, limit: int = 3) -> list[str]:
    """协议第四段：追问建议。优先用同类模板，再把知识点名拼进去。"""
    base = list(_FOLLOWUP_TPL.get(intent_type, _FOLLOWUP_TPL["other"]))
    for item in (kps or [])[:1]:
        name = str(item.get("name") or "").strip()
        if name:
            base.append(f"围绕「{name}」再讲深一点")
    return list(dict.fromkeys(base))[:limit]


def actions_of(side: str, intent_type: str, refs: list[str] | None = None) -> list[dict[str, str]]:
    """协议第四段：可执行下一步。demo 里给出动作定义，落地接口保留在各自模块。"""
    has_ref = bool(refs)
    if side == "student":
        acts = [
            {"type": "drill", "label": "出一道同类练习", "hint": "按本次层次生成变式题（接口：tasks.generate）"},
            {"type": "escalate", "label": "转问老师", "hint": "把问题与上下文打包发给授课教师（接口：tasks.escalate）"},
            {"type": "save", "label": "存入错题本", "hint": "沉淀到个人薄弱项（接口：mylibrary.mark_weak）"},
        ]
        if has_ref:
            acts.insert(0, {"type": "resource", "label": "看引用原文", "hint": "跳转到命中的资料片段（接口：mylibrary.open）"})
        return acts[:3]
    acts = [
        {"type": "draft", "label": "生成可编辑草稿", "hint": "落到备课助手继续编辑（接口：teaching.plan.save）"},
        {"type": "export", "label": "导出 docx / pptx", "hint": "备课助手已支持导出（接口：office.export）"},
        {"type": "assign", "label": "布置为任务", "hint": "下发给学生并跟踪完成（接口：tasks.assign）"},
    ]
    if intent_type in ("student", "class"):
        acts.insert(0, {"type": "review", "label": "去画像库看完整画像",
                        "hint": "打开教师驾驶舱学生页（跳转 /teacher#/tab=students）"})
    if intent_type == "grading":
        acts.insert(0, {"type": "grade", "label": "按此标准批改",
                        "hint": "打开「作业批改 → 按作业批改」（跳转 /homework#/tab=grade）"})
    return acts[:3]


def protocol_view(stage: str, need_clarify: bool, clarify_question: str, level: str) -> dict[str, Any]:
    """组装协议字段，供接口直接返回。"""
    return {
        "stage": stage,
        "stage_label": next((s["name"] for s in PROTOCOL_STAGES if s["id"] == stage), stage),
        "stages": PROTOCOL_STAGES,
        "need_clarify": need_clarify,
        "clarify_question": clarify_question,
        "scaffold": scaffold_of(level),
    }
