# -*- coding: utf-8 -*-
"""画像 v2 的证据层：把原始行为数据量化成六维能力分。

设计文档见 `docs/学生画像量化指标方案-v2.md`。本模块只做**规则计算**，模型不参与判定。

六维（权威出处见方案第 2 节）：
    D1 知识掌握  CEEAA-1 工程知识
    D2 分析推理  CEEAA-2 问题分析 / NACE Critical Thinking
    D3 工具实践  CEEAA-5 使用现代工具 / NACE Technology
    D4 研究创新  CEEAA-4 研究 / 人社部 创新革新
    D5 协作沟通  CEEAA-9,10 个人和团队、沟通 / NACE Teamwork
    D6 自主发展  CEEAA-12 终身学习 / NACE Career & Self-Development

纪律：
  * 规则表即数据 —— 加词只 append，不重排；
  * 缺失证据**不惩罚分数**，只拉低置信度；
  * 命中型证据有 0.2 下限：没提问过 ≠ 能力为零。
"""
from __future__ import annotations

import math
from typing import Any

import db

DIMS = ["D1", "D2", "D3", "D4", "D5", "D6"]
DIM_NAME = {
    "D1": "知识掌握", "D2": "分析推理", "D3": "工具实践",
    "D4": "研究创新", "D5": "协作沟通", "D6": "自主发展",
}

# ---------------------------------------------------------------- 词典
# 强词 = 明确指向该维度的行为（系数 1.0）；弱词 = 高频口语，只能作旁证（系数 0.4）。
LEX: dict[str, dict[str, list[str]]] = {
    "D2": {"强": ["为什么", "为什么会", "为什么不是", "推导", "反例", "边界条件", "成立条件",
                "前提", "复杂度", "证明", "反证", "适用条件", "局限", "权衡", "取舍",
                "本质", "机制", "是不是一定", "能不能推广"],
           "弱": ["区别", "差异", "关系", "联系", "对比", "比较", "如果", "假设", "归纳", "原理"]},
    "D3": {"强": ["跑通", "部署", "报错", "显存", "并发", "压测", "吞吐", "docker", "git",
                "依赖", "缓存", "微调", "构建", "上线", "推理耗时", "装环境"],
           "弱": ["实现", "复现", "调参", "脚本", "接口", "日志", "数据集", "可视化", "封装",
                 "命令行", "版本", "调库", "断点", "单测"]},
    "D4": {"强": ["文献", "论文", "综述", "消融", "显著性", "对照组", "变量控制", "实验设计",
                "基线", "审稿", "投稿", "假设检验"],
           "弱": ["改进", "提出", "有没有更好", "新的思路", "如果不", "尝试", "优化一下",
                 "重新设计", "指标", "复现", "引用", "数据划分", "原创"]},
    "D5": {"强": ["我们组", "分工", "我负责", "汇报", "答辩", "队友", "协调", "意见不合",
                "对接", "评审"],
           "弱": ["沟通", "反馈", "说服", "写文档", "进度同步", "一起", "听众", "怎么表达",
                 "例会", "配合", "讲给"]},
    "D6": {"强": ["复盘", "周计划", "路线图", "时间管理", "拖延", "自律", "坚持", "习惯"],
           "弱": ["计划", "目标", "进展", "下一步", "总结", "自查", "长期", "规划", "每天",
                 "我该怎么学", "从哪里开始"]},
}

# Bloom 修订版认知层级系数：记忆/理解层的问题不该与分析层同权
BLOOM: dict[str, float] = {
    "记忆": 0.6, "理解": 0.6, "应用": 1.0, "分析": 1.3, "评价": 1.3, "创造": 1.5,
}

# 团队类型对 D3（工具实践）的贡献：科研课题组偏研究，不计入工程实践
GROUP_TOOL_VALUE = {"横向项目": 0.9, "实习实践": 0.85, "竞赛团队": 0.7, "科研课题组": 0.3}

# 六维权重（方案第 5、6 节）
W_ACAD = {"D1": 0.45, "D2": 0.35, "D4": 0.20}
W_CAREER = {"D3": 0.40, "D5": 0.35, "D6": 0.25}
W_LEVEL_ACAD = {"D1": 0.45, "D2": 0.30, "D4": 0.25}
W_LEVEL_CAREER = {"D3": 0.40, "D5": 0.35, "D6": 0.25}

# 判定阈值（合成数据标定，真实学期数据需重标定）
TRACK_THETA = 0.15
TRACK_HYSTERESIS = 0.15
MIN_CONF = 0.50
LEVEL_A = 3.64          # 临时线：合成常模 PR75
LEVEL_B = 3.17          # 临时线：合成常模 PR25
D1_FLOOR = 2.4          # 知识掌握过低一律不得评 A
LEX_REF = 6.0           # 命中型证据满分参照
LEX_FLOOR = 0.2         # 零命中下限
DECAY_HALF_LIFE = 90    # 时间衰减半衰期（天）


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def _lex_score(text: str, dim: str, kind: str) -> float:
    """强词 1.0 / 弱词 0.4。"""
    score = 0.0
    for w in LEX[dim][kind]:
        score += (1.0 if kind == "强" else 0.4) * str(text).count(w)
    return score


def lex_raw(chats: list[dict], dim: str, kind: str = "强", ref: float = LEX_REF) -> float | None:
    """命中型证据归一：按 Bloom 加权求和后**一次性** clamp，再套 0.2 下限。"""
    if not chats:
        return None
    total = 0.0
    for c in chats:
        bloom = BLOOM.get(str(c.get("layer") or ""), 1.0)
        total += _lex_score(str(c.get("content") or ""), dim, kind) * bloom
    return LEX_FLOOR + (1 - LEX_FLOOR) * _clamp(total / ref)


# ---------------------------------------------------------------- 证据采集
def collect(student_id: int) -> dict[str, Any]:
    """把库里的原始行为读成一份证据快照（不做任何判定）。"""
    prof = db.student_profile(student_id) or {}
    gpa = float(prof.get("gpa") or 0)

    grades = db.query("SELECT course, score FROM course_grades WHERE student_id = ?", (student_id,))
    mastery = db.query("SELECT kp_name, course, mastery FROM kp_mastery WHERE student_id = ?",
                       (student_id,))
    subs = db.query(
        "SELECT s.content, s.score, s.late, s.points_hit, s.points_total, h.full_score, h.title "
        "FROM homework_submissions s JOIN homework h ON h.id = s.homework_id "
        "WHERE s.student_id = ?", (student_id,))
    chats = db.query(
        "SELECT content, layer, session_id FROM chat_messages "
        "WHERE user_id = ? AND role = 'user'", (student_id,))
    groups = db.query(
        "SELECT g.kind, m.teacher_action FROM match_records m "
        "JOIN research_groups g ON g.id = m.group_id WHERE m.student_id = ?", (student_id,))
    tasks = db.query("SELECT status FROM tasks WHERE student_id = ?", (student_id,))
    mats = db.query("SELECT kind, category FROM materials WHERE owner_id = ?", (student_id,))
    apps = db.query(
        "SELECT r.rtype FROM resource_applications a JOIN teacher_resources r "
        "ON r.id = a.resource_id WHERE a.student_id = ?", (student_id,))

    return {"gpa": gpa, "profile": prof, "grades": grades, "mastery": mastery, "subs": subs,
            "chats": chats, "groups": groups, "tasks": tasks, "materials": mats, "apps": apps}


# ---------------------------------------------------------------- 六维计算
def ability_v2(student_id: int) -> dict[str, Any]:
    """算出六维分、置信度、主标签与层次（试算，不写库）。"""
    e = collect(student_id)
    ev: dict[str, list[tuple[str, str, float, float | None]]] = {d: [] for d in DIMS}

    # ---- D1 知识掌握
    ev["D1"].append(("E1.1", f"GPA {e['gpa']:.1f} 分（分段线性 55→0 / 100→1）",
                     0.45, _clamp((e["gpa"] - 55) / 45)))
    if e["grades"]:
        avg_course = sum(float(r["score"]) for r in e["grades"]) / len(e["grades"])
        ev["D1"].append(("E1.1b", f"单科成绩均值 {avg_course:.1f}（{len(e['grades'])} 门）",
                         0.15, _clamp((avg_course - 55) / 45)))
    if e["mastery"]:
        m_avg = sum(float(r["mastery"]) for r in e["mastery"]) / len(e["mastery"])
        ev["D1"].append(("E1.2", f"知识点掌握度均值 {m_avg:.3f}（{len(e['mastery'])} 个）",
                         0.35, _clamp(m_avg)))
    if e["subs"]:
        ratios = []
        for r in e["subs"]:
            full = float(r["full_score"] or 100) or 100
            score = float(r["score"] or 0)
            ratios.append(0.0 if score < 0 else _clamp(score / full))
        ev["D1"].append(("E1.3", f"作业得分率均值 {sum(ratios)/len(ratios):.3f}（{len(ratios)} 份）",
                         0.20, sum(ratios) / len(ratios)))

    # ---- D2 分析推理
    ev["D2"].append(("E2.1", "推理型强词命中（Bloom 加权）", 0.30, lex_raw(e["chats"], "D2")))
    hit = [r for r in e["subs"] if float(r["points_total"] or 0) > 0]
    if hit:
        h = sum(float(r["points_hit"] or 0) for r in hit)
        t = sum(float(r["points_total"] or 0) for r in hit)
        ev["D2"].append(("E2.2", f"作业要点覆盖率 {h/t:.3f}（{len(hit)} 份标注过要点）",
                         0.35, _clamp(h / t)))
    if e["chats"]:
        sess = {str(c.get("session_id") or f"#{c.get('session_id')}") for c in e["chats"]}
        avg_turn = len(e["chats"]) / max(len(sess), 1)
        ev["D2"].append(("E2.3", f"追问深度 {len(sess)} 个会话，平均 {avg_turn:.1f} 轮",
                         0.20, _clamp((avg_turn - 1) / 3)))
    # E2.4 订正提升需要"同一知识点的历史提交"表，当前 schema 只有一次提交记录，
    # 因此显式记为未观测：不拉低分数，但把 D2 的置信度压到 0.85，提醒这条证据尚未接入。
    ev["D2"].append(("E2.4", "订正提升（需提交历史表，暂未接入）", 0.15, None))

    # ---- D3 工具实践
    gkinds = [str(r["kind"]) for r in e["groups"] if str(r.get("teacher_action")) == "accepted"]
    if gkinds:
        ev["D3"].append(("E3.1", "团队类型：" + "、".join(gkinds), 0.35,
                         max(GROUP_TOOL_VALUE.get(k, 0.3) for k in gkinds)))
    work_apps = [r for r in e["apps"] if str(r["rtype"]) in ("project", "internship", "contest")]
    if work_apps:
        ev["D3"].append(("E3.2", f"资源申请 {len(work_apps)} 项（项目/实习/竞赛）", 0.20,
                         _clamp(len(work_apps) / 3)))
    if e["subs"]:
        runnable = any(any(k in str(r["content"]) for k in ("跑通", "压测", "Docker", "docker", "脚本"))
                       for r in e["subs"])
        ev["D3"].append(("E3.3", "作业含可运行产物与运行说明", 0.25, 0.9 if runnable else 0.2))
    ev["D3"].append(("E3.4", "答疑工具强词命中", 0.20, lex_raw(e["chats"], "D3")))

    # ---- D4 研究创新
    kg = [k for k in gkinds if k == "科研课题组"]
    if kg:
        ev["D4"].append(("E4.1", "科研课题组参与（成员）", 0.40, 0.7))
    papers = [m for m in e["materials"] if str(m.get("category")) == "论文"]
    if papers:
        ev["D4"].append(("E4.2", f"论文类材料 {len(papers)} 份", 0.25, _clamp(len(papers) / 4)))
    ev["D4"].append(("E4.3", "答疑学术强词命中", 0.20, lex_raw(e["chats"], "D4")))
    ev["D4"].append(("E4.4", "创新表述命中", 0.15, lex_raw(e["chats"], "D4", "弱", ref=3.0)))

    # ---- D5 协作沟通
    if gkinds:
        ev["D5"].append(("E5.1", f"团队匹配 accepted {len(gkinds)} 项", 0.30,
                         _clamp(len(gkinds) / 3)))
    if e["subs"]:
        role = any(k in str(r["content"]) for r in e["subs"] for k in ("我负责", "我们组", "分工"))
        if role:
            ev["D5"].append(("E5.2", "小组作业含分工表述", 0.25, 0.8))
    ev["D5"].append(("E5.3", "答疑协作强词命中", 0.25, lex_raw(e["chats"], "D5")))
    if e["chats"]:
        expr = sum(1 for c in e["chats"]
                   if any(k in str(c["content"]) for k in ("怎么讲", "汇报", "怎么写")))
        ev["D5"].append(("E5.4", f"表达型提问 {expr} 次", 0.20, _clamp(expr / 3)))

    # ---- D6 自主发展
    if e["tasks"]:
        done = len([t for t in e["tasks"] if str(t["status"]) == "done"])
        ev["D6"].append(("E6.1", f"任务完成率 {done}/{len(e['tasks'])}", 0.30,
                         done / len(e["tasks"])))
    if e["subs"]:
        late = len([r for r in e["subs"] if int(r["late"] or 0)])
        ev["D6"].append(("E6.2", f"准时率（逾期 {late} 次）", 0.20, 1 - late / len(e["subs"])))
    if e["materials"]:
        n = len(e["materials"])
        ev["D6"].append(("E6.3", f"主动上传资料 {n} 份", 0.15,
                         min(1.0, math.log(1 + n) / math.log(6))))
    ev["D6"].append(("E6.4", "复盘/规划强词命中", 0.20, lex_raw(e["chats"], "D6")))
    prof = e["profile"]
    try:
        intent = max(float(prof.get("research_intent") or 3), float(prof.get("job_intent") or 3))
    except (TypeError, ValueError):
        intent = 3.0
    ev["D6"].append(("E6.5", f"自评意图 {intent:.1f}（自评只在此处生效）", 0.15,
                     _clamp((intent - 1) / 4)))

    # ---- 合成
    D: dict[str, float] = {}
    conf: dict[str, float] = {}
    for d in DIMS:
        num = den = full = 0.0
        for _eid, _desc, w, raw in ev[d]:
            full += w
            if raw is None:
                continue
            num += w * (1 + 4 * raw)
            den += w
        D[d] = round(num / den, 2) if den else 3.0     # 无观测 → 先验 3.0
        conf[d] = round(den / full, 2) if full else 0.0
    return {"dims": D, "conf": conf, "evidence": ev,
            "conf_all": round(sum(conf.values()) / len(DIMS), 2)}


# ---------------------------------------------------------------- 判定
def _sub(D: dict[str, float], w: dict[str, float]) -> float:
    return sum(D[d] * w[d] for d in w)


def decide(D: dict[str, float], conf_all: float, prev_track: str = "") -> dict[str, Any]:
    """六维 → 主标签 + 层次。与方案第 5、6 节一致（含滞回与置信度门槛）。"""
    s_acad, s_career = _sub(D, W_ACAD), _sub(D, W_CAREER)
    delta = round(s_acad - s_career, 2)

    if prev_track == "学业型":
        track = "学业型" if delta > -(TRACK_THETA + TRACK_HYSTERESIS) else "事业型"
    elif prev_track == "事业型":
        track = "事业型" if delta < (TRACK_THETA + TRACK_HYSTERESIS) else "学业型"
    elif delta >= TRACK_THETA:
        track = "学业型"
    elif delta <= -TRACK_THETA:
        track = "事业型"
    else:
        track = "待定"

    if track == "学业型":
        L, weights = _sub(D, W_LEVEL_ACAD), W_LEVEL_ACAD
    elif track == "事业型":
        L, weights = _sub(D, W_LEVEL_CAREER), W_LEVEL_CAREER
    else:
        L, weights = sum(D.values()) / len(DIMS), {}

    if conf_all < MIN_CONF:
        level = "待评估"
    elif D["D1"] < D1_FLOOR:
        level = "C" if L < LEVEL_B else "B"
    else:
        level = "A" if L >= LEVEL_A else ("B" if L >= LEVEL_B else "C")
    L = round(L, 2)

    if conf_all < MIN_CONF:
        reason = f"证据不足（置信度 {conf_all:.2f} < {MIN_CONF}），暂不给主标签与层次结论。"
    elif track == "待定":
        reason = (f"学业子指数 {s_acad:.2f} 与事业子指数 {s_career:.2f} 接近"
                  f"（相差 {abs(delta):.2f}，阈值 {TRACK_THETA}），判为双轨并进，两条路径的资源都会推荐。")
    else:
        reason = (f"学业子指数 {s_acad:.2f}、事业子指数 {s_career:.2f}，差值 {delta:+.2f}"
                  f"（阈值 ±{TRACK_THETA}），判为{track}；"
                  f"按该轨道三件套加权得分 {L:.2f}，评为 {level} 层。")

    return {"track": track, "level": level, "delta": delta,
            "s_academic": round(s_acad, 2), "s_career": round(s_career, 2),
            "level_score": L, "conf": conf_all, "weights": weights, "reason": reason}


def profile_v2(student_id: int, prev_track: str = "") -> dict[str, Any]:
    """完整试算：六维 + 置信度 + 主标签 + 层次 + 理由。"""
    a = ability_v2(student_id)
    d = decide(a["dims"], a["conf_all"], prev_track)
    d["dims"] = a["dims"]
    d["conf_dims"] = a["conf"]
    d["dims_named"] = [{"key": k, "name": DIM_NAME[k], "value": a["dims"][k],
                        "conf": a["conf"][k]} for k in DIMS]
    return d
