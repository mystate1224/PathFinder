# -*- coding: utf-8 -*-
"""planner.py —— 规划引擎（教师侧班级建议 + 学生侧成长路线）。

设计原则：**先说依据（数据），再说动作**，让老师能复核、能拒绝。
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import llm
from services import stratify

# ---------------------------------------------------------------- 固定收口文案
LAYER_CAVEAT = (
    "建议每月复核一次分层结果：分层不是标签，而是随成绩与兴趣动态变化的培养依据。"
)

TRACK_ADVICE = {
    "学业型": {
        "A": "增设科研训练环节（文献精读 + 复现小实验），把课堂内容向原理与前沿延伸。",
        "B": "在讲清推导的基础上配可自查练习，帮助学生把「会做」升级为「讲得清」。",
        "C": "先补前置概念与数学工具，多用类比降低抽象门槛，暂缓大段公式推导。",
    },
    "事业型": {
        "A": "引入工程化深度内容（框架源码、性能调优、常见坑），配可复现的小项目。",
        "B": "以业务场景驱动教学，强调操作步骤与调试方法，让学生「能上手、能排错」。",
        "C": "用生活化用途引出概念，给最小可运行示例，先建立成就感再谈体系。",
    },
}


def _pct(part: int, total: int) -> str:
    return f"{round(part / total * 100)}%" if total else "0%"


# ================================================================ 班级建议
def rule_class_advice(
    track_dist: dict[str, int],
    level_dist: dict[str, int],
    top_interests: Sequence[str],
    total: int,
    course: str = "",
) -> list[str]:
    """规则版：每条都"数据 + 动作"，可在无模型时独立成立。"""
    total = int(total or 0) or 1
    advice: list[str] = []

    academic = int(track_dist.get("学业型", 0))
    career = int(track_dist.get("事业型", 0))
    if academic >= career:
        advice.append(
            f"班级以学业型为主（{academic}/{total}，{_pct(academic, total)}），"
            "建议在本课程中增设科研训练环节：文献精读、小实验复现、结果汇报。"
        )
    else:
        advice.append(
            f"班级以事业型为主（{career}/{total}，{_pct(career, total)}），"
            "建议增加工程实操与项目驱动内容：真实场景案例、可交付小项目、代码评审。"
        )

    level_a = int(level_dist.get("A", 0))
    level_c = int(level_dist.get("C", 0))
    if level_a > 0:
        advice.append(
            f"{level_a} 名学生处于 A 层（学有余力，{_pct(level_a, total)}），"
            "可提供拓展型作业（选做探究题）满足其挑战需求，同时避免全班统一加量。"
        )
    if level_c > 0:
        advice.append(
            f"{level_c} 名学生处于 C 层（{_pct(level_c, total)}），"
            "建议为其准备前置知识清单与例题精讲，先保障关键步骤能复现，再谈综合应用。"
        )

    if top_interests:
        names = "、".join(list(top_interests)[:3])
        advice.append(
            f"班级兴趣集中在 {names}，"
            f"建议把课程案例与作业选题向这些方向靠拢，提高内容与学生的相关性。"
        )

    advice.append(
        "建议采用「同班异任务」的作业策略：同一知识点，拓展型做探究题、标准型做基础题、"
        "巩固型重做例题并标注依据，既保证公平又回应差异。"
    )
    return advice[:5]


def class_advice(
    track_dist: dict[str, int],
    level_dist: dict[str, int],
    top_interests: Sequence[str],
    total: int,
    course: str = "",
) -> tuple[list[str], str]:
    """班级教学建议（双引擎）。返回 ``(建议列表, engine)``。"""
    rule = rule_class_advice(track_dist, level_dist, top_interests, total, course)

    def mock() -> dict:
        return {"advice": rule}

    prompt = (
        "你是高校教学发展中心的教学顾问。根据以下班级学情数据，给出 3~5 条教学建议。\n"
        f"课程：{course or '未指定'}\n"
        f"学生总数：{total}\n"
        f"主标签分布：{track_dist}\n"
        f"学业层次分布：{level_dist}\n"
        f"兴趣方向 Top：{'、'.join(list(top_interests)[:5]) or '无'}\n\n"
        "要求：每条建议必须「先说数据依据、再说具体教学动作」，可直接执行；"
        "绝对不能出现分班、贴标签式表述（如拔尖班/普通班/基础班）；"
        "每条 40~80 字，中文。"
    )
    result, engine = llm.chat_json(
        [{"role": "user", "content": prompt}],
        '{"advice":["建议1","建议2","建议3"]}',
        mock=mock,
    )
    advice = result.get("advice") if isinstance(result, dict) else None
    if not isinstance(advice, list) or not advice:
        advice, engine = rule, "rule"
    advice = [str(a).strip() for a in advice if str(a).strip()][:5]
    return advice, engine


# ================================================================ 个人成长路线
_STAGE_TEMPLATES = {
    ("学业型", "A"): [
        ("近期（2-4 周）", "把课程内容推到原理层",
         ["精读 1 篇本方向综述并做 1 页笔记", "复现课件里的一个核心公式或实验", "在答疑中追问「为什么」而非「怎么做」"]),
        ("中期（1-2 个月）", "进入科研训练",
         ["读 3 篇近两年论文，产出对比笔记", "把课程知识与方向前沿连成一张图", "向教师申请进组做文献综述类工作"]),
        ("远期（一学期）", "产出可展示的成果",
         ["完成一个可复现的小实验并写成 300 字结论", "争取一次组会或课堂汇报", "把成果沉淀进个人材料，用于保研/申研"]),
    ],
    ("学业型", "B"): [
        ("近期（2-4 周）", "把基础打透",
         ["按章节整理一页公式/概念清单", "重做课堂例题并标注每一步依据", "每周自查 3 道基础题，错题当天回炉"]),
        ("中期（1-2 个月）", "从会做走向讲得清",
         ["用 5 分钟给同学讲清一个知识点", "完成一次综合性作业，写清思路", "开始接触方向相关的入门资料"]),
        ("远期（一学期）", "明确方向并积累",
         ["在 2 个方向里做出取舍", "参与一次课程项目或小型竞赛", "把成绩稳定在 A/B 区间上沿"]),
    ],
    ("学业型", "C"): [
        ("近期（2-4 周）", "补齐前置概念",
         ["列出课本中读不懂的 5 个概念并逐个弄懂", "对照例题复现关键步骤", "每次答疑只问一个具体卡点"]),
        ("中期（1-2 个月）", "建立可复用的解题流程",
         ["整理同类题的三步固定做法", "把老师给的类比记成自己的话", "每两周做一次小复盘"]),
        ("远期（一学期）", "稳住基础、逐步提速",
         ["把专业课及格线推到 75 分以上", "尝试一个最小可运行的小练习", "观察自己的兴趣是否收窄"]),
    ],
    ("事业型", "A"): [
        ("近期（2-4 周）", "把课程知识接到工程实践上",
         ["用课程内容做一个最小可运行 demo", "读一个主流框架的官方快速上手文档", "记录 3 个自己踩过的坑与解法"]),
        ("中期（1-2 个月）", "工程化深化",
         ["给 demo 补上异常处理与基本测试", "了解性能瓶颈的定位方法", "完成一次代码评审或被评审"]),
        ("远期（一学期）", "产出可写进简历的项目",
         ["项目上线/开源并附 README", "沉淀一份技术笔记", "用项目匹配一份实习或竞赛"]),
    ],
    ("事业型", "B"): [
        ("近期（2-4 周）", "以场景驱动学习",
         ["为每章找一个真实业务场景", "跟着文档跑通一个官方示例", "把操作步骤写成可复制的清单"]),
        ("中期（1-2 个月）", "能上手、能排错",
         ["独立完成一次接口联调", "学会看日志定位问题", "参与一次小组项目并负责一个模块"]),
        ("远期（一学期）", "明确岗位方向",
         ["在后端/前端/数据/测试中选定主攻方向", "按该方向补 1 个专项技能", "投递一次实习或比赛练手"]),
    ],
    ("事业型", "C"): [
        ("近期（2-4 周）", "先建立成就感",
         ["找一个生活化的小工具复刻出来", "只学最少够用的语法/API", "每天保证一次成功的运行结果"]),
        ("中期（1-2 个月）", "把零散知识串起来",
         ["完整跟做一个入门教程项目", "把不会的地方列成问题清单逐条解决", "找一位同学互相讲一遍"]),
        ("远期（一学期）", "选定方向、稳定输出",
         ["确定一个主攻方向并坚持 8 周", "完成 1 个完整的小项目", "把课程成绩稳定在 70 分以上"]),
    ],
}


def rule_roadmap(profile: dict, kp_mastery: Iterable[dict] | None = None) -> dict:
    """规则版成长路线：按主标签 × 层次取三阶段模板，再按知识掌握度做局部替换。"""
    track = str(profile.get("track") or "学业型")
    level = str(profile.get("grade_level") or "B")
    interests = [str(i) for i in (profile.get("interests") or [])]
    stages = _STAGE_TEMPLATES.get((track, level)) or _STAGE_TEMPLATES[("学业型", "B")]

    weak: list[str] = []
    for row in (kp_mastery or []):
        try:
            mastery = float(row.get("mastery") or 0)
        except (TypeError, ValueError):
            mastery = 0.0
        if mastery < 0.6:
            name = str(row.get("kp_name") or "").strip()
            if name:
                weak.append(name)
    weak = weak[:4]

    out_stages = []
    for idx, (period, focus, actions) in enumerate(stages):
        acts = list(actions)
        if idx == 0 and weak:
            acts.insert(0, f"优先补强掌握度偏低的 {('、'.join(weak))}（来自作业与答疑记录）")
        out_stages.append({"period": period, "focus": focus, "actions": acts})

    direction = interests[0] if interests else "本专业核心方向"
    return {
        "title": f"{track} · {level} 层 · 个人成长路线",
        "direction": direction,
        "summary": (
            f"基于当前画像（{stratify.layer_badge(track, level)}，兴趣方向 "
            f"{'、'.join(interests[:3]) or '待识别'}）生成的三阶段路线。"
            "路线会随成绩、作业与答疑记录动态调整。"
        ),
        "stages": out_stages,
        "caveat": LAYER_CAVEAT,
    }


def roadmap(profile: dict, kp_mastery: Iterable[dict] | None = None) -> tuple[dict, str]:
    """个人成长路线（双引擎）。返回 ``(路线, engine)``。"""
    rule = rule_roadmap(profile, kp_mastery)

    def mock() -> dict:
        return rule

    prompt = (
        "你是高校学业导师。请为下面这名学生生成一份三阶段成长路线。\n"
        f"画像：主标签 {profile.get('track')}，学业层次 {profile.get('grade_level')}，"
        f"兴趣方向 {'、'.join(profile.get('interests') or []) or '待识别'}，"
        f"成绩 {profile.get('gpa')}\n"
        f"掌握度偏弱的知识点：{'、'.join(x['kp_name'] for x in (kp_mastery or [])[:4]) or '暂无数据'}\n\n"
        "要求：三个阶段分别为「近期（2-4 周）」「中期（1-2 个月）」「远期（一学期）」；"
        "每阶段给 2~3 条**具体可执行**的动作（动词开头、能被检查）；"
        "不得出现分班、贴标签式表述；全中文。"
    )
    result, engine = llm.chat_json(
        [{"role": "user", "content": prompt}],
        '{"title":"","direction":"","summary":"","stages":[{"period":"","focus":"","actions":[""]}],"caveat":""}',
        mock=mock,
    )
    stages = result.get("stages") if isinstance(result, dict) else None
    if not isinstance(stages, list) or not stages:
        result, engine = rule, "rule"
    else:
        result.setdefault("caveat", LAYER_CAVEAT)
        result.setdefault("title", rule["title"])
        result.setdefault("summary", rule["summary"])
    return result, engine


def _unused(*_: Any) -> None:  # pragma: no cover
    _ = TRACK_ADVICE
