# -*- coding: utf-8 -*-
"""stratify.py —— 分层引擎（学生画像）。

## 口径声明（三条底线之一，务必守住）

分层产物只有两个用途：
1. 决定**给学生推什么深度的内容**（答疑风格、练习难度）；
2. 决定**教师给这个学生什么建议**。

**不用于分班、不给学生贴固定标签。** 所有对外文案必须体现动态与建议性
（如"学业 A 层 · 学有余力"、"拓展型 · 增加探究内容"），
严禁出现「拔尖班 / 普通班 / 基础班」等表述。

## 输出结构

主标签（学业型 / 事业型） × 学业层次（A / B / C） × 兴趣方向 + 五维能力 + 可复核理由。
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import db
import llm
from services import evidence, taxonomy as tax

DIRECTION_KEYWORDS: dict[str, list[str]] = tax.DIRECTION_KEYWORDS
RESEARCH_DIRECTIONS: set[str] = tax.RESEARCH_DIRECTIONS
ENGINEERING_DIRECTIONS: set[str] = tax.ENGINEERING_DIRECTIONS

# 五维能力的展示顺序与中文名（旧口径，仅作兜底保留）
ABILITY_KEYS: list[tuple[str, str]] = [
    ("foundation", "专业基础"),
    ("practice", "实践能力"),
    ("research", "科研素养"),
    ("communication", "沟通协作"),
    ("driveself", "自驱力"),
]

# 画像 v2 六维（当前主口径）：D1~D6
ABILITY_KEYS_V2: list[tuple[str, str]] = [
    ("D1", "知识掌握"),
    ("D2", "分析推理"),
    ("D3", "工具实践"),
    ("D4", "研究创新"),
    ("D5", "协作沟通"),
    ("D6", "自主发展"),
]

# v2 生效的最低置信度：低于它说明证据不够，回落到旧口径（双引擎纪律）
V2_MIN_CONF = 0.50

# 分层引擎的 schema（双引擎共用，保证两条路返回结构一致）
SCHEMA = (
    '{"track":"学业型|事业型",'
    '"grade_level":"A|B|C",'
    '"interests":["方向1","方向2"],'
    '"ability":{"foundation":1.0-5.0,"practice":1.0-5.0,"research":1.0-5.0,'
    '"communication":1.0-5.0,"driveself":1.0-5.0},'
    '"reason":"60-160字中文，说明判定依据"}'
)


def _clamp(value: float, low: float = 1.0, high: float = 5.0) -> float:
    return round(max(low, min(high, float(value))), 1)


# ================================================================ 基础判定
def grade_level_of(gpa: float) -> str:
    """学业层次：规则明确、可解释，便于老师复核。

    ``gpa >= 85 -> A``（学有余力） / ``>= 70 -> B`` / 否则 C。
    """
    try:
        value = float(gpa)
    except (TypeError, ValueError):
        return "C"
    if value >= 85:
        return "A"
    if value >= 70:
        return "B"
    return "C"


def grade_level_text(level: str) -> str:
    return {"A": "学有余力", "B": "基础扎实", "C": "需巩固前置"}.get(level, "待评估")


def track_of(research_intent: float, job_intent: float, interests: Sequence[str]) -> str:
    """主标签：``diff >= 0.5`` 学业型 / ``<= -0.5`` 事业型 / 接近时看兴趣方向属性。"""
    try:
        diff = float(research_intent) - float(job_intent)
    except (TypeError, ValueError):
        diff = 0.0
    if diff >= 0.5:
        return "学业型"
    if diff <= -0.5:
        return "事业型"
    research_hits = sum(1 for d in interests if d in RESEARCH_DIRECTIONS)
    engineering_hits = sum(1 for d in interests if d in ENGINEERING_DIRECTIONS)
    return "学业型" if research_hits >= engineering_hits else "事业型"


def direction_flavour(interests: Sequence[str]) -> str:
    """兴趣方向的整体属性，用于理由文案。"""
    research_hits = sum(1 for d in interests if d in RESEARCH_DIRECTIONS)
    engineering_hits = sum(1 for d in interests if d in ENGINEERING_DIRECTIONS)
    if research_hits and not engineering_hits:
        return "偏科研"
    if engineering_hits and not research_hits:
        return "偏工程"
    if research_hits and engineering_hits:
        return "科研与工程兼有"
    return "尚无明确属性"


def ability_vector(track: str, gpa: float, research_intent: float, job_intent: float) -> dict:
    """五维能力。``base = gpa / 20``（80 分 → 4.0），再按主标签套不同权重。"""
    try:
        base = float(gpa) / 20.0
    except (TypeError, ValueError):
        base = 3.0
    res = float(research_intent or 3)
    job = float(job_intent or 3)

    if track == "事业型":
        values = {
            "foundation": base,
            "practice": base + 0.4 + (job - 3) * 0.4,
            "research": base - 1.2 + (res - 3) * 0.3,
            "communication": 3.6 + (job - 3) * 0.3,
            "driveself": base + 0.2,
        }
    else:  # 学业型（含未判定）
        values = {
            "foundation": base + 0.2,
            "practice": base - 0.6 + (job - 3) * 0.3,
            "research": base + 0.3 + (res - 3) * 0.4,
            "communication": 3.4 + (job - 3) * 0.2,
            "driveself": base + 0.1,
        }
    return {k: _clamp(v) for k, v in values.items()}


def interests_from_text(text: str, top: int = 5) -> list[str]:
    """从任意文本里按关键词命中次数排序取方向（extract 与 stratify 同源）。"""
    return tax.directions_from_text(text, top=top)


# ================================================================ 规则版
def rule_stratify(
    gpa: float,
    research_intent: float = 3.0,
    job_intent: float = 3.0,
    interests: Iterable[str] | None = None,
    extra_text: str = "",
) -> dict:
    """纯规则分层。**不是假数据**：所有结论都由传入的真实数值推导。"""
    interest_list = [str(i).strip() for i in (interests or []) if str(i).strip()]
    if extra_text:
        for d in interests_from_text(extra_text, top=6):
            if d not in interest_list:
                interest_list.append(d)
    interest_list = interest_list[:6]

    level = grade_level_of(gpa)
    track = track_of(research_intent, job_intent, interest_list)
    ability = ability_vector(track, gpa, research_intent, job_intent)

    flavour = direction_flavour(interest_list)
    interests_text = "、".join(interest_list[:3]) if interest_list else "暂未识别到明确方向"
    if level == "A":
        level_hint = "，可承接更高挑战"
    elif level == "B":
        level_hint = "，建议按当前节奏巩固"
    else:
        level_hint = "，建议先补前置概念"

    # 判定依据必须写进理由：否则会出现「科研倾向 3.6 / 就业倾向 3.4，却判为事业型」
    # 这种读起来自相矛盾的画像 —— 实际是两者接近时改由兴趣方向属性定夺。
    diff = float(research_intent or 0) - float(job_intent or 0)
    if abs(diff) >= 0.5:
        track_hint = "科研倾向明显高于就业倾向" if diff > 0 else "就业倾向明显高于科研倾向"
    else:
        track_hint = (
            f"两项倾向接近（相差 {abs(diff):.1f}），"
            f"因此按兴趣方向的属性（{flavour}）定夺"
        )
    reason = (
        f"学业成绩 {float(gpa or 0):.1f} 分，评为 {level} 层（{grade_level_text(level)}{level_hint}）；"
        f"科研倾向 {float(research_intent or 0):.1f} / 就业倾向 {float(job_intent or 0):.1f}，"
        f"{track_hint}；兴趣方向为 {interests_text}（{flavour}），综合判定为{track}。"
        "本结论用于推荐内容深度与任务难度，不用于分班，且会随成绩与兴趣动态更新。"
    )

    return {
        "track": track,
        "grade_level": level,
        "interests": interest_list,
        "ability": ability,
        "gpa": round(float(gpa or 0), 1),
        "research_intent": round(float(research_intent or 0), 2),
        "job_intent": round(float(job_intent or 0), 2),
        "reason": reason,
    }


# ================================================================ 双引擎
def stratify(
    gpa: float,
    research_intent: float = 3.0,
    job_intent: float = 3.0,
    interests: Iterable[str] | None = None,
    extra_text: str = "",
) -> tuple[dict, str]:
    """分层（双引擎）。返回 ``(画像, engine)``。

    ``grade_level`` / ``gpa`` 永远以规则为准（可解释、可复核），
    模型只负责润色 ``track`` / ``interests`` / ``ability`` / ``reason``。
    """
    rule = rule_stratify(gpa, research_intent, job_intent, interests, extra_text)
    prompt = (
        "你是高校学业发展中心的画像分析师。请根据以下数据给出学生画像。\n"
        f"学业成绩（百分制）：{rule['gpa']}\n"
        f"科研倾向（1-5）：{research_intent}\n"
        f"就业倾向（1-5）：{job_intent}\n"
        f"兴趣方向候选：{'、'.join(rule['interests']) or '无'}\n"
        f"补充材料摘要：{extra_text[:600] or '无'}\n\n"
        "要求：grade_level 必须按「>=85 为 A，>=70 为 B，其余 C」判定，不得改动；"
        "理由要引用具体数字；不得出现分班、贴标签式表述。"
    )
    result, engine = llm.chat_json([{"role": "user", "content": prompt}], SCHEMA, mock=rule)
    # 学业层次与 GPA 以规则为准，杜绝模型改口径
    result["grade_level"] = rule["grade_level"]
    result["gpa"] = rule["gpa"]
    # 自评倾向是**输入事实**，模型只允许解读，不允许改写
    result["research_intent"] = rule["research_intent"]
    result["job_intent"] = rule["job_intent"]
    if not result.get("interests"):
        result["interests"] = rule["interests"]
    if not result.get("reason"):
        result["reason"] = rule["reason"]
    result.setdefault("ability", rule["ability"])
    return result, engine


def save_profile(user_id: int, profile: dict, engine: str = "rule") -> None:
    """写入（或更新）学生画像 —— 唯一写入口。

    ``research_intent`` / ``job_intent`` 必须一起落库：
    否则下次上传材料时读不到自评值，会被默认值 3.0 覆盖，
    表现为"学生改了自评，一上传文件就被打回默认值"。
    """
    db.execute(
        "INSERT INTO student_profiles "
        "(user_id, track, grade_level, interests, ability, gpa, research_intent, job_intent, reason, engine) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "track=excluded.track, grade_level=excluded.grade_level, interests=excluded.interests, "
        "ability=excluded.ability, gpa=excluded.gpa, reason=excluded.reason, engine=excluded.engine, "
        "research_intent=excluded.research_intent, job_intent=excluded.job_intent",
        (
            user_id,
            profile.get("track", ""),
            profile.get("grade_level", "B"),
            db.jdump(profile.get("interests") or []),
            db.jdump(profile.get("ability") or {}),
            float(profile.get("gpa") or 0),
            _clamp(profile.get("research_intent") or 3.0),
            _clamp(profile.get("job_intent") or 3.0),
            profile.get("reason", ""),
            engine,
        ),
    )


def layer_badge(track: str, level: str) -> str:
    return f"{track or '未定'} · {level or 'B'} 层"


def ability_pairs_of(profile: dict) -> list[dict]:
    """画像能力对（前端雷达图直接用）。

    六维（v2）优先；库里还是旧五维时按旧键输出，保证老数据也能显示。
    """
    ability = profile.get("ability")
    if not isinstance(ability, dict):
        ability = db.jload(ability, {}) or {}
    if any(k in ability for k in ("D1", "D2", "D3", "D4", "D5", "D6")):
        return [{"name": name, "value": float(ability.get(key, 0) or 0)}
                for key, name in ABILITY_KEYS_V2]
    return [{"name": name, "value": float(ability.get(key, 0) or 0)}
            for key, name in ABILITY_KEYS]


def recompute_profile(student_id: int, prev_track: str = "") -> tuple[dict, str]:
    """画像主口径：**六维 v2 优先**，证据不足则回落旧规则版。

    结论写入 ``student_profiles.track / grade_level / ability`` —— 分层答疑、
    匹配打分、成长路线与驾驶舱分布都读这几列，所以切换后整条链路自动生效。

    两条降级纪律（与项目的双引擎一致）：
      * v2 计算异常 → 回落旧口径；
      * v2 置信度 < ``V2_MIN_CONF``（证据太少）→ 回落旧口径，避免给出没依据的结论。
    """
    prof = db.student_profile(student_id) or {}
    try:
        v2 = evidence.profile_v2(
            student_id,
            prev_track=prev_track or str(prof.get("track") or ""),
        )
    except Exception as exc:  # noqa: BLE001 - 画像不能因为试算异常而算不出来
        v2 = {"error": f"{type(exc).__name__}: {exc}"}

    conf = float(v2.get("conf") or 0)
    if not v2.get("error") and conf >= V2_MIN_CONF:
        ability = {d["key"]: d["value"] for d in v2["dims_named"]}
        # 业务字段只认二元主标签与 ABC：待定按差值方向落一侧，理由里写明"双轨并进"
        track = v2.get("track")
        if track not in ("学业型", "事业型"):
            track = "学业型" if float(v2.get("delta") or 0) >= 0 else "事业型"
        level = v2.get("level") if v2.get("level") in ("A", "B", "C") else "B"
        return {
            "track": track,
            "grade_level": level,
            "interests": prof.get("interests") or [],
            "ability": ability,
            "ability_conf": v2.get("conf_dims") or {},
            "gpa": prof.get("gpa") or 0,
            "research_intent": prof.get("research_intent") or 3.0,
            "job_intent": prof.get("job_intent") or 3.0,
            "reason": v2.get("reason", ""),
            "dims": v2.get("dims") or {},
            "dims_named": v2.get("dims_named") or [],
            "profile_source": "v2",
            "profile_conf": conf,
            "conf": conf,
            "s_academic": v2.get("s_academic"),
            "s_career": v2.get("s_career"),
            "delta": v2.get("delta"),
            "level_score": v2.get("level_score"),
            # 与 profile_v2() 的字段形状保持一致，前端不需要分支判断
            "conf": conf,
            "s_academic": v2.get("s_academic"),
            "s_career": v2.get("s_career"),
        }, "rule-v2"

    # ---- 兜底：旧规则口径
    old, engine = stratify(
        gpa=float(prof.get("gpa") or 0),
        research_intent=float(prof.get("research_intent") or 3.0),
        job_intent=float(prof.get("job_intent") or 3.0),
        interests=db.jload(prof.get("interests"), []) or [],
    )
    old["interests"] = db.jload(prof.get("interests"), []) or []
    old["profile_source"] = "v1-fallback"
    old["profile_conf"] = round(conf, 2)
    # 与 v2 分支保持同样的字段形状，前端不用分支判断
    old["dims"] = old.get("ability") or {}
    old["dims_named"] = ability_pairs_of(old)
    if v2.get("error"):
        old["reason"] = f"六维试算异常，已回落旧口径（{v2['error']}）。{old.get('reason', '')}"
    else:
        old["reason"] = (f"六维证据不足（置信度 {conf:.2f} < {V2_MIN_CONF}），"
                         f"暂用旧口径：{old.get('reason', '')}")
    return old, "rule-v1"


def update_intent(
    user_id: int,
    research_intent: float | None = None,
    job_intent: float | None = None,
    interests: Iterable[str] | None = None,
    extra_text: str = "",
) -> tuple[dict, str]:
    """学生自评（科研/就业倾向、兴趣方向）→ 重算画像。

    ``grade_level`` / ``gpa`` 保持原有数值不变：自评不该改成绩口径。
    倾向值落在 1~5，超出范围按边界截断，避免前端传错值把画像带偏。
    """
    profile = db.student_profile(user_id) or {}
    gpa = float(profile.get("gpa") or 0)
    research = _clamp(research_intent if research_intent is not None
                      else float(profile.get("research_intent") or 3.0))
    job = _clamp(job_intent if job_intent is not None
                 else float(profile.get("job_intent") or 3.0))
    merged = list(profile.get("interests") or [])
    for direction in (interests or []):
        direction = str(direction).strip()
        if direction and direction not in merged:
            merged.append(direction)

    # 先把自评与兴趣落库，再走主口径重算 —— 自评只影响 D6（自主发展）15% 的权重，
    # 主标签与层次由六维综合结果决定，不再由自评直接判定。
    db.execute(
        "INSERT INTO student_profiles "
        "(user_id, track, grade_level, interests, ability, gpa, research_intent, job_intent, reason, engine) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
        "interests=excluded.interests, research_intent=excluded.research_intent, "
        "job_intent=excluded.job_intent",
        (
            user_id,
            profile.get("track", ""),
            profile.get("grade_level", "B"),
            db.jdump(merged),
            db.jdump(profile.get("ability") or {}),
            gpa, research, job,
            profile.get("reason", ""),
            "rule",
        ),
    )
    result, engine = recompute_profile(user_id)
    save_profile(user_id, result, engine)
    return result, engine


def ability_pairs(ability: Any) -> list[tuple[str, float]]:
    """把 ability dict 转成前端雷达图要的 ``[(中文名, 分数)]``。"""
    data = db.jload(ability, {}) if not isinstance(ability, dict) else ability
    out: list[tuple[str, float]] = []
    for key, label in ABILITY_KEYS:
        try:
            out.append((label, float(data.get(key, 0) or 0)))
        except (TypeError, ValueError):
            out.append((label, 0.0))
    return out
