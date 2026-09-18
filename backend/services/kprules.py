# -*- coding: utf-8 -*-
"""kprules.py —— 能力②「知识点结构化抽取」的**场景化规则引擎**。

核心结论先说在前面：**不同场景的抽取规则不一样，而且必须不一样。**

课件要的是「这节课讲了哪几个概念」，论文要的是「用了什么方法、得出了什么结论」，
作业要的是「这道题考查哪个知识点」，岗位 JD 要的是「要求掌握什么技能」。
用同一套「抽标题」的规则去套全部场景，抽出来的东西没有使用价值。

所以这里把规则做成**一张可增删的规则表** :data:`KP_RULE_SETS`，
按 ``kind`` / ``category`` 选路，每条命中结果都带上 ``rule_set`` 标识，
界面上可以看到「本次用的是哪套规则、命中了哪条锚点」。

抽取产出的知识点对象::

    {name, kp_type, definition, evidence, block_id, bloom, difficulty,
     keywords, confidence, anchor, rule_set}

``bloom`` 是布鲁姆认知层级（记忆/理解/应用/分析/评价/创造），
``difficulty`` 只表示**内容深度**，不表示学生层次（沿用全项目的分层口径）。
"""
from __future__ import annotations

import re
from typing import Any

from services import taxonomy as tax

BLOOM_LEVELS = ["记忆", "理解", "应用", "分析", "评价", "创造"]

# 动词 → 布鲁姆层级。题干动词是判断「考查到哪一层」最便宜也最准的信号。
VERB_BLOOM: list[tuple[str, list[str]]] = [
    ("创造", ["设计", "实现", "构建", "提出", "改进", "优化方案", "搭建", "开发一个"]),
    ("评价", ["评价", "比较", "论证", "评述", "权衡", "优缺点", "是否可行"]),
    ("分析", ["分析", "推导", "证明", "解释为什么", "找出原因", "推导", "诊断"]),
    ("应用", ["求", "计算", "求解", "使用", "应用", "编程", "画出", "写出代码"]),
    ("理解", ["说明", "简述", "阐述", "概括", "理解", "举例", "区别"]),
    ("记忆", ["说出", "列举", "背诵", "定义", "是什么", "复述"]),
]

# 研究方法术语表（论文场景专用，项目里原本没有，这里补齐）
RESEARCH_METHOD_TERMS: list[str] = [
    "对比学习", "自监督", "注意力机制", "Transformer", "预训练", "微调", "蒸馏",
    "检索增强", "RAG", "向量检索", "稠密检索", "稀疏检索", "BM25", "RRF", "重排序",
    "知识图谱", "表示学习", "图神经网络", "多模态", "跨模态", "消融实验",
    "交叉验证", "基线模型", "评价指标", "F1", "召回率", "准确率", "负采样",
    "强化学习", "迁移学习", "联邦学习", "对比实验", "显著性检验",
]

# 定义句锚点（课件/教案场景最有效的一类信号）
_DEFINITION_ANCHORS = [
    r"是指", r"定义为", r"所谓", r"即(?:为|是)", r"也称", r"指的是",
    r"包括[:：]", r"分为[:：]", r"由.{0,8}组成", r"本质上(?:是|为)",
]
_SUMMARY_ANCHORS = [r"本节(?:小结|要点|总结)", r"小结", r"总结", r"要点[:：]", r"关键(?:点|结论)"]


def _rx(patterns: list[str]) -> "re.Pattern[str]":
    return re.compile("|".join(patterns))


# ================================================================ 规则表
KP_RULE_SETS: dict[str, dict[str, Any]] = {
    "courseware": {
        "id": "courseware", "name": "课件规则集", "applies_to": "课件 / 讲义 / 教材章节",
        "desc": "以标题层级为主骨架，定义句与小结句为补充；产出概念型、原理型知识点。",
        "types": {"heading": "概念型", "definition": "概念型", "summary": "原理型"},
        "anchors": [
            {"id": "definition", "name": "定义句", "pattern": _rx(_DEFINITION_ANCHORS)},
            {"id": "summary", "name": "小结/要点句", "pattern": _rx(_SUMMARY_ANCHORS)},
        ],
        "difficulty": "depth_words",
        "bloom_default": "理解",
    },
    "paper": {
        "id": "paper", "name": "论文规则集", "applies_to": "论文 / 研究报告",
        "desc": "按摘要—方法—实验—结论的段落职能拆分，优先抽研究方法术语；产出方法型、术语型、结论型。",
        "types": {"section:method": "方法型", "term": "术语型", "section:conclusion": "结论型",
                  "heading": "方法型"},
        "anchors": [
            {"id": "section:method", "name": "方法段",
             "pattern": re.compile(r"^(?:3|三|方法|方法论|模型|我们提出|本文提出|approach|method)")},
            {"id": "section:conclusion", "name": "结论段",
             "pattern": re.compile(r"^(?:5|五|结论|总结|实验表明|结果表明|本文贡献)")},
            {"id": "term", "name": "研究方法术语",
             "pattern": re.compile("|".join(re.escape(t) for t in RESEARCH_METHOD_TERMS))},
        ],
        "difficulty": "high",
        "bloom_default": "分析",
    },
    "homework": {
        "id": "homework", "name": "作业规则集", "applies_to": "作业 / 试题 / 练习题",
        "desc": "以题号为单位切分，用题干动词判定布鲁姆层级；产出考点型知识点并回指课程知识点。",
        "types": {"question": "考点型"},
        "anchors": [
            {"id": "question", "name": "题号",
             "pattern": re.compile(r"^\s*(?:第\s*[一二三四五六七八九十\d]+\s*题|[（(]?\d{1,2}[）).、])")},
            {"id": "verb", "name": "题干动词",
             "pattern": re.compile("|".join(v for _, vs in VERB_BLOOM for v in vs))},
        ],
        "difficulty": "by_verb",
        "bloom_default": "应用",
    },
    "lesson": {
        "id": "lesson", "name": "教案规则集", "applies_to": "教案 / 教学设计",
        "desc": "围绕教学目标与重难点抽取，产出目标型知识点，直接服务于备课。",
        "types": {"goal": "目标型", "heading": "目标型"},
        "anchors": [
            {"id": "goal", "name": "教学目标/重难点",
             "pattern": re.compile(r"教学目标|学习目标|重点|难点|核心素养|学生(?:将|能够|学会)")},
        ],
        "difficulty": "depth_words",
        "bloom_default": "理解",
    },
    "jd": {
        "id": "jd", "name": "岗位规则集", "applies_to": "岗位 JD / 招聘要求 / 实习要求",
        "desc": "从任职要求的条目里抽技能词，产出技能型知识点，用于学业—就业匹配。",
        "types": {"requirement": "技能型", "heading": "技能型"},
        "anchors": [
            {"id": "requirement", "name": "任职要求",
             "pattern": re.compile(r"任职要求|岗位要求|技能要求|熟悉|掌握|精通|具备|优先")},
        ],
        "difficulty": "depth_words",
        "bloom_default": "应用",
    },
    "default": {
        "id": "default", "name": "通用规则集", "applies_to": "未归类材料",
        "desc": "标题优先、段落首句兜底（旧版行为，作为保底）。",
        "types": {"heading": "概念型", "paragraph": "概念型"},
        "anchors": [],
        "difficulty": "depth_words",
        "bloom_default": "理解",
    },
}

_CATEGORY_HINTS: list[tuple[str, str]] = [
    ("课件", "courseware"), ("讲义", "courseware"), ("教材", "courseware"),
    ("论文", "paper"), ("报告", "paper"),
    ("作业", "homework"), ("试题", "homework"), ("练习", "homework"),
    ("教案", "lesson"), ("教学设计", "lesson"),
    ("岗位", "jd"), ("招聘", "jd"), ("实习", "jd"), ("JD", "jd"),
]


def set_for(kind: str = "", category: str = "") -> dict[str, Any]:
    """选规则集。``category``（用户手选的课件/论文/作业）优先于 ``kind``（按扩展名猜的）。"""
    text = f"{category or ''}".strip()
    for hint, key in _CATEGORY_HINTS:
        if hint.lower() in text.lower():
            return KP_RULE_SETS[key]
    if kind in KP_RULE_SETS:
        return KP_RULE_SETS[kind]
    return KP_RULE_SETS["default"]


# ================================================================ 判定工具
def bloom_of(text: str, default: str = "理解") -> str:
    """按动词判定布鲁姆层级（取最高命中级，题干常同时出现多个动词）。"""
    for level, verbs in VERB_BLOOM:
        for verb in verbs:
            if verb in text:
                return level
    return default


_DEPTH_HARD = ["推导", "证明", "收敛", "最优", "复杂度", "前沿", "理论", "正则化", "泛化"]
_DEPTH_EASY = ["简介", "概述", "入门", "是什么", "基本概念", "定义"]


def difficulty_of(text: str, mode: str = "depth_words", bloom: str = "理解") -> str:
    """A/B/C 只表示**内容深度**，不给学生贴标签、不参与分班。"""
    if mode == "high":
        return "A"
    if mode == "by_verb":
        return {"创造": "A", "评价": "A", "分析": "A", "应用": "B", "理解": "B", "记忆": "C"}.get(bloom, "B")
    if any(w in text for w in _DEPTH_HARD):
        return "A"
    if any(w in text for w in _DEPTH_EASY):
        return "C"
    return "B"


def _clean_name(raw: str, max_len: int = 30) -> str:
    name = re.sub(r"^[#\s\d.、,，:：（）()]+", "", (raw or "").strip())
    name = re.split(r"[。！？；;：:\n]", name)[0].strip()
    return name[:max_len].strip()


def _first_clause(text: str, max_len: int = 30) -> str:
    head = re.split(r"[。！？；;\n]", (text or "").strip())[0]
    return _clean_name(head, max_len)


# ================================================================ 抽取
def extract(
    text: str,
    kind: str = "",
    category: str = "",
    blocks: list[dict] | None = None,
    limit: int = 8,
) -> dict:
    """按场景规则抽知识点。

    返回 ``KPResult``::

        {rule_set:{id,name,applies_to,desc}, items:[...], stats:{...}, engine:"rule"}

    ``blocks`` 由 :func:`services.parsekit.to_blocks` 产出；不传则内部自行分块。
    """
    from services import parsekit  # 局部导入：避免与 parsekit 形成循环依赖

    rule_set = set_for(kind, category)
    blocks = blocks if blocks is not None else parsekit.to_blocks(text or "")
    anchors = rule_set.get("anchors") or []
    types = rule_set.get("types") or {}

    items: list[dict] = []
    seen: set[str] = set()
    anchor_hits: dict[str, int] = {}

    for block in blocks:
        if len(items) >= limit:
            break
        btype = str(block.get("type") or "")
        btext = str(block.get("text") or "").strip()
        if not btext or len(btext) < 4:
            continue

        matched: str = ""
        name = ""
        definition = ""

        # 1) 标题块：任何规则集都以标题为骨架
        if btype == "heading":
            matched = "heading"
            name = _clean_name(btext)
            definition = ""

        # 2) 锚点块：按场景规则判定这一段是否"值得抽"
        if not name:
            for anchor in anchors:
                if anchor["id"] == "verb":
                    continue  # 动词只用来定 bloom，不单独产生知识点
                if anchor["pattern"].search(btext):
                    matched = anchor["id"]
                    if rule_set["id"] == "homework":
                        name = _first_clause(re.sub(r"^\s*(?:第\s*[一二三四五六七八九十\d]+\s*题|[（(]?\d{1,2}[）).、])\s*", "", btext))
                    elif rule_set["id"] == "paper" and anchor["id"] == "term":
                        hit = anchor["pattern"].search(btext)
                        name = hit.group(0) if hit else _first_clause(btext)
                    else:
                        name = _first_clause(btext)
                    definition = btext[:160]
                    break

        # 3) 兜底：通用规则集用段落首句
        if not name and rule_set["id"] == "default" and btype in ("paragraph", "list", "quote"):
            matched = "paragraph"
            name = _first_clause(btext)
            definition = btext[:120]

        if not name or len(name) < 2:
            continue
        key = re.sub(r"\s+", "", name)
        if key in seen:
            continue
        seen.add(key)

        bloom = bloom_of(btext, rule_set.get("bloom_default", "理解"))
        anchor_hits[matched or "fallback"] = anchor_hits.get(matched or "fallback", 0) + 1
        context = f"{name} {definition} {btext}"[:400]
        directions = tax.directions_from_text(context, top=2)
        items.append({
            "name": name,
            "kp_type": types.get(matched or "heading", types.get("heading", "概念型")),
            "definition": definition or btext[:120],
            "evidence": btext[:200],
            "block_id": block.get("id") or "",
            "bloom": bloom,
            "difficulty": difficulty_of(context, rule_set.get("difficulty", "depth_words"), bloom),
            "keywords": directions or [w for w in tax.DIRECTION_KEYWORDS if w in context][:2],
            "confidence": round(min(1.0, 0.55 + 0.15 * len(directions) + (0.2 if definition else 0.0)), 2),
            "anchor": matched or "fallback",
            "rule_set": rule_set["id"],
        })

    return {
        "rule_set": {
            "id": rule_set["id"], "name": rule_set["name"],
            "applies_to": rule_set["applies_to"], "desc": rule_set["desc"],
        },
        "items": items,
        "stats": {
            "blocks_scanned": len(blocks),
            "items": len(items),
            "anchor_hits": anchor_hits,
            "bloom_distribution": {lv: sum(1 for i in items if i["bloom"] == lv) for lv in BLOOM_LEVELS},
        },
        "engine": "rule",
    }
