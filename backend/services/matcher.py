# -*- coding: utf-8 -*-
"""matcher.py —— 师生匹配（补齐 §10 缺口）。

## 匹配逻辑（可解释、可复核）

对「学生 × 团队」逐对打分：

```
score = 方向契合(0~60) + 层次适配(0~20) + 兴趣新鲜度(0~10) + 名额余量(0~10)
```

* **方向契合**：学生兴趣方向 ∩ 团队方向，按交集占比给分（权重最高）；
* **层次适配**：A 层可进要求「有科研基础」的组；C 层优先给「入门友好」的组；
* **兴趣新鲜度**：学生尚未实践过的方向加分，鼓励探索；
* **名额余量**：已满的组直接降到 0，避免推一个进不去的组。

## 团队类型（kind）

老师带的不只是科研课题组：横向项目、竞赛团队、实习组同样要在这里管。
``kind`` 只做分类展示（驾驶舱的徽章与筛选），**不参与上面的打分**——
给非科研团队额外加权会让推荐理由变得不可解释。

## 双向确认

``match_records`` 存 ``teacher_action`` / ``student_action``，
两边都 ``accepted`` 才算匹配成功。任一方可以 ``declined``，
不覆盖对方的动作（各自的意向独立留痕）。
"""
from __future__ import annotations

import re
from typing import Sequence

import db
from services import taxonomy as tax
from services.errors import ServiceError

RESEARCH_KEYWORDS = ["科研", "论文", "实验", "算法", "研究", "综述", "推导", "创新"]
ENTRY_KEYWORDS = ["入门", "基础", "零基础", "培养", "学习", "指导"]

# 团队类型字典：与前端 PF.GROUP_KINDS 保持一致，改这里记得同步改前端。
GROUP_KINDS = ["科研课题组", "横向项目", "竞赛团队", "实习实践", "其他"]
DEFAULT_KIND = "科研课题组"


class MatchError(ServiceError):
    """匹配相关的业务校验失败。路由层按 ``status`` 转状态码（默认 400）。"""


def _group_rows(teacher_id: int = 0, group_id: int = 0) -> list[dict]:
    if group_id:
        rows = db.query("SELECT * FROM research_groups WHERE id = ?", (group_id,))
    elif teacher_id:
        rows = db.query(
            "SELECT g.*, u.name AS teacher_name FROM research_groups g "
            "JOIN users u ON u.id = g.teacher_id WHERE g.teacher_id = ? ORDER BY g.id",
            (teacher_id,),
        )
    else:
        rows = db.query(
            "SELECT g.*, u.name AS teacher_name FROM research_groups g "
            "JOIN users u ON u.id = g.teacher_id ORDER BY g.teacher_id, g.id"
        )
    for row in rows:
        row["directions"] = db.jload(row.get("directions"), [])
        row["kind"] = str(row.get("kind") or "").strip() or DEFAULT_KIND
        row["accepted_count"] = db.scalar(
            "SELECT COUNT(*) FROM match_records WHERE group_id = ? "
            "AND teacher_action = 'accepted' AND student_action = 'accepted'",
            (row["id"],), 0,
        )
        capacity = int(row.get("capacity") or 0)
        row["seats_left"] = max(0, capacity - int(row["accepted_count"])) if capacity else 99
    return rows


def score_pair(student: dict, profile: dict, group: dict) -> tuple[float, str]:
    """给学生与团队打分，并给出可复核的中文理由。"""
    interests = [str(i) for i in (profile.get("interests") or [])]
    group_dirs = [str(d) for d in (group.get("directions") or [])]
    level = str(profile.get("grade_level") or "B")

    hit = [d for d in interests if d in group_dirs]
    if group_dirs:
        direction_score = 60.0 * (len(hit) / len(group_dirs))
    else:
        direction_score = 24.0                      # 组没写方向 → 给中间值

    level_score = {"A": 20.0, "B": 14.0, "C": 8.0}.get(level, 10.0)
    requirement = str(group.get("requirement") or "")
    wants_experience = any(w in requirement for w in RESEARCH_KEYWORDS)
    entry_friendly = any(w in requirement for w in ENTRY_KEYWORDS)
    if wants_experience and level == "C":
        level_score = max(0.0, level_score - 8.0)   # 组要求科研基础，C 层学生硬进会挫败
    if entry_friendly and level == "C":
        level_score = min(20.0, level_score + 6.0)  # 入门友好组对 C 层学生更合适

    # 兴趣新鲜度：组方向里有学生尚未涉猎的研究类方向
    fresh = [d for d in group_dirs if d not in interests and tax.is_research(d)]
    fresh_score = min(10.0, 5.0 * len(fresh))

    seats = int(group.get("seats_left", 0))
    seat_score = 10.0 if seats >= 2 else 5.0 if seats == 1 else 0.0

    score = round(direction_score + level_score + fresh_score + seat_score, 1)
    if seats <= 0:
        score = min(score, 20.0)                    # 满员组不推

    bits = []
    if hit:
        bits.append(f"兴趣方向与团队方向重合 {'、'.join(hit)}")
    elif group_dirs:
        bits.append(f"团队方向为 {'、'.join(group_dirs)}，与学生当前兴趣暂无交集（可作为拓展方向）")
    bits.append(f"学业层次 {level} 层{'，与该组要求匹配' if not (wants_experience and level == 'C') else '，该组偏重科研基础，建议先补基础再申请'}")
    if fresh:
        bits.append(f"可探索的新方向：{'、'.join(fresh[:2])}")
    bits.append(f"剩余名额 {seats if seats < 99 else '不限'}")
    reason = f"{student.get('name') or '该生'}：" + "；".join(bits) + "。"

    return score, reason


def recommend_for_student(student_id: int, limit: int = 5) -> dict:
    """给学生推荐团队（写入 / 更新 match_records 的展示分，不改动双方意向）。"""
    student = db.user_by_id(student_id)
    if not student:
        raise MatchError("学生不存在")
    profile = db.student_profile(student_id) or {}

    scored = []
    for group in _group_rows():
        score, reason = score_pair(student, profile, group)
        scored.append({"group": group, "score": score, "reason": reason})
    scored.sort(key=lambda item: item["score"], reverse=True)

    existing = {
        int(r["group_id"]): r
        for r in db.query("SELECT * FROM match_records WHERE student_id = ?", (student_id,))
    }
    out = []
    for item in scored[:limit]:
        group = item["group"]
        record = existing.get(int(group["id"]))
        out.append({
            "group_id": group["id"],
            "name": group.get("name"),
            "kind": group.get("kind"),
            "teacher_id": group.get("teacher_id"),
            "teacher_name": group.get("teacher_name") or "",
            "directions": group.get("directions"),
            "requirement": group.get("requirement"),
            "capacity": group.get("capacity"),
            "seats_left": group.get("seats_left"),
            "score": item["score"],
            "reason": item["reason"],
            "engine": "rule",
            "teacher_action": (record or {}).get("teacher_action", "pending"),
            "student_action": (record or {}).get("student_action", "pending"),
            "extra": group.get("teacher_name") or "",
        })
    return {
        "student": {"id": student["id"], "name": student.get("name"),
                    "username": student.get("username")},
        "profile": {
            "track": profile.get("track"), "grade_level": profile.get("grade_level"),
            "gpa": profile.get("gpa"), "interests": db.jload(profile.get("interests"), []),
        },
        "matches": out,
        "confirmed": sum(
            1 for r in existing.values()
            if r.get("teacher_action") == "accepted" and r.get("student_action") == "accepted"
        ),
    }


def recommend_for_teacher(teacher_id: int, group_id: int = 0, limit: int = 12) -> dict:
    """给教师的团队推荐学生。"""
    groups = _group_rows(teacher_id, group_id)
    if not groups:
        raise MatchError("你还没有常设团队，请先创建")

    class_id = str((db.user_by_id(teacher_id) or {}).get("class_id") or "")
    sql = (
        "SELECT u.*, p.track, p.grade_level, p.gpa, p.interests FROM users u "
        "LEFT JOIN student_profiles p ON p.user_id = u.id WHERE u.role='student'"
    )
    args: list = []
    if class_id:
        sql += " AND u.class_id = ?"
        args.append(class_id)
    students = db.query(sql, tuple(args))

    out_groups = []
    for group in groups:
        scored = []
        for student in students:
            profile = {
                "interests": db.jload(student.get("interests"), []),
                "grade_level": student.get("grade_level") or "B",
                "track": student.get("track") or "",
            }
            score, reason = score_pair(student, profile, group)
            scored.append({
                "student_id": student["id"],
                "name": student.get("name"),
                "username": student.get("username"),
                "track": profile["track"],
                "grade_level": profile["grade_level"],
                "gpa": student.get("gpa"),
                "interests": profile["interests"],
                "score": score,
                "reason": reason,
                "engine": "rule",
            })
        scored.sort(key=lambda item: item["score"], reverse=True)

        records = {
            int(r["student_id"]): r
            for r in db.query("SELECT * FROM match_records WHERE group_id = ?", (group["id"],))
        }
        for item in scored:
            record = records.get(int(item["student_id"]))
            item["teacher_action"] = (record or {}).get("teacher_action", "pending")
            item["student_action"] = (record or {}).get("student_action", "pending")

        out_groups.append({
            "group_id": group["id"],
            "name": group.get("name"),
            "kind": group.get("kind"),
            "directions": group.get("directions"),
            "requirement": group.get("requirement"),
            "capacity": group.get("capacity"),
            "seats_left": group.get("seats_left"),
            "candidates": scored[:limit],
        })

    return {"groups": out_groups, "class_id": class_id}


def decide(actor: str, student_id: int, group_id: int, action: str) -> dict:
    """双向确认：``actor`` ∈ {teacher, student}，``action`` ∈ {accepted, declined}。"""
    if actor not in ("teacher", "student"):
        raise MatchError("actor 只能是 teacher 或 student")
    if action not in ("accepted", "declined"):
        raise MatchError("action 只能是 accepted 或 declined")

    group = db.query_one("SELECT * FROM research_groups WHERE id = ?", (group_id,))
    if not group:
        raise MatchError("团队不存在")

    student = db.user_by_id(student_id)
    if not student or student.get("role") != "student":
        raise MatchError("学生不存在")

    profile = db.student_profile(student_id) or {}
    score, reason = score_pair(student, profile, group)

    record = db.query_one(
        "SELECT * FROM match_records WHERE student_id = ? AND group_id = ?", (student_id, group_id)
    )
    field = "teacher_action" if actor == "teacher" else "student_action"

    if action == "accepted" and group.get("capacity"):
        accepted = db.scalar(
            "SELECT COUNT(*) FROM match_records WHERE group_id = ? "
            "AND teacher_action = 'accepted' AND student_action = 'accepted' "
            "AND student_id <> ?",
            (group_id, student_id), 0,
        )
        if int(accepted or 0) >= int(group["capacity"]):
            raise MatchError("该团队名额已满")

    if record:
        db.execute(f"UPDATE match_records SET {field} = ?, score = ?, reason = ? WHERE id = ?",
                   (action, score, reason, record["id"]))
        record_id = int(record["id"])
    else:
        record_id = db.execute(
            "INSERT INTO match_records (student_id, group_id, teacher_id, score, reason, "
            "teacher_action, student_action, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                student_id, group_id, int(group.get("teacher_id") or 0), score, reason,
                "accepted" if actor == "teacher" and action == "accepted" else "pending",
                "accepted" if actor == "student" and action == "accepted" else "pending",
                db.now(),
            ),
        )
        if action == "declined":
            db.execute(f"UPDATE match_records SET {field} = 'declined' WHERE id = ?", (record_id,))

    current = db.query_one("SELECT * FROM match_records WHERE id = ?", (record_id,))
    matched = (current.get("teacher_action") == "accepted"
               and current.get("student_action") == "accepted")

    task_id = 0
    if matched and not db.query_one(
        "SELECT id FROM tasks WHERE student_id = ? AND title LIKE ?",
        (student_id, f"%{group.get('name')}%"),
    ):
        task_id = db.execute(
            "INSERT INTO tasks (student_id, teacher_id, type, title, detail, status, progress, due_date, created_at) "
            "VALUES (?,?,?,?,?, 'todo', 0, '', ?)",
            (
                student_id, int(group.get("teacher_id") or 0), "match",
                f"进入团队「{group.get('name')}」",
                "双方已确认匹配。请联系指导教师确认第一次组会（或项目启动会）时间与入门任务。",
                db.now(),
            ),
        )

    return {
        "record_id": record_id,
        "student_id": student_id,
        "group_id": group_id,
        "score": score,
        "reason": reason,
        "engine": "rule",
        "teacher_action": current.get("teacher_action"),
        "student_action": current.get("student_action"),
        "matched": matched,
        "task_created": bool(task_id),
        "message": ("双方已确认，匹配成功。" if matched
                    else ("已确认，等待对方确认。" if action == "accepted" else "已婉拒。")),
    }


def my_matches(student_id: int) -> list[dict]:
    rows = db.query(
        "SELECT m.*, g.name AS group_name, g.kind, g.directions, g.requirement, u.name AS teacher_name "
        "FROM match_records m "
        "JOIN research_groups g ON g.id = m.group_id "
        "JOIN users u ON u.id = g.teacher_id "
        "WHERE m.student_id = ? ORDER BY m.id DESC",
        (student_id,),
    )
    for row in rows:
        row["directions"] = db.jload(row.get("directions"), [])
        row["kind"] = str(row.get("kind") or "").strip() or DEFAULT_KIND
        row["matched"] = (row.get("teacher_action") == "accepted"
                          and row.get("student_action") == "accepted")
        row["engine"] = "rule"
    return rows


# ================================================================ 团队维护
# 团队原先只由 seeds.py 播种，任何新教师都建不了组，推荐链路对他就是死的。
# 这里补上教师自己的增删改，让「建组 → 推荐 → 双向确认 → 跟进任务」闭环。


def _norm_kind(value) -> str:
    """类型入参容错：空值按默认类型，字典外的值一律落到「其他」。"""
    kind = str(value or "").strip()
    if not kind:
        return DEFAULT_KIND
    return kind if kind in GROUP_KINDS else "其他"

def _norm_dirs(value) -> list[str]:
    """方向入参容错：既接受数组，也接受「多模态、CV / LLM」这类分隔串。"""
    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = re.split(r"[,，、;；/|]+", str(value or ""))
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out[:12]


def _norm_capacity(value) -> int:
    try:
        cap = int(float(value))
    except (TypeError, ValueError):
        cap = 0
    return max(0, min(cap, 50))


def my_groups(teacher_id: int) -> list[dict]:
    """教师自己的团队（无组时返回空列表，不抛异常，便于页面渲染空态）。"""
    return _group_rows(teacher_id)


def _own_group(teacher_id: int, group_id: int) -> dict:
    group = db.query_one("SELECT * FROM research_groups WHERE id = ?", (int(group_id or 0),))
    if not group:
        raise MatchError("团队不存在", 404)
    if int(group.get("teacher_id") or 0) != int(teacher_id):
        raise MatchError("只能管理自己的团队", 403)
    return group


def _group_detail(group_id: int) -> dict:
    group = db.query_one("SELECT * FROM research_groups WHERE id = ?", (group_id,)) or {}
    if group:
        group["directions"] = db.jload(group.get("directions"), [])
        group["kind"] = str(group.get("kind") or "").strip() or DEFAULT_KIND
    return group


def create_group(teacher_id: int, name: str, directions=None,
                 requirement: str = "", capacity=0, kind: str = "") -> int:
    teacher = db.user_by_id(teacher_id)
    if not teacher or teacher.get("role") != "teacher":
        raise MatchError("教师账号不存在", 404)

    name = str(name or "").strip()
    if not name:
        raise MatchError("请填写团队名称")
    if len(name) > 60:
        raise MatchError("团队名称最多 60 个字")
    if db.query_one("SELECT id FROM research_groups WHERE teacher_id = ? AND name = ?",
                    (teacher_id, name)):
        raise MatchError("你已经有一个同名团队了")

    dirs = _norm_dirs(directions)
    if not dirs:
        raise MatchError("请至少填写一个方向（多个用顿号或逗号分隔）")

    return int(db.execute(
        "INSERT INTO research_groups (teacher_id, name, kind, directions, requirement, capacity) "
        "VALUES (?,?,?,?,?,?)",
        (teacher_id, name, _norm_kind(kind), db.jdump(dirs),
         str(requirement or "").strip(), _norm_capacity(capacity)),
    ))


def update_group(teacher_id: int, group_id: int, name=None, directions=None,
                 requirement=None, capacity=None, kind=None) -> dict:
    """局部更新：只改显式传入的字段，``None`` 表示保持原值。"""
    _own_group(teacher_id, group_id)

    if name is not None:
        name = str(name).strip()
        if not name:
            raise MatchError("团队名称不能为空")
        if db.query_one(
            "SELECT id FROM research_groups WHERE teacher_id = ? AND name = ? AND id <> ?",
            (teacher_id, name, group_id),
        ):
            raise MatchError("你已经有一个同名团队了")

    dirs = None if directions is None else _norm_dirs(directions)
    if dirs is not None and not dirs:
        raise MatchError("请至少填写一个方向（多个用顿号或逗号分隔）")

    fields: list[str] = []
    args: list = []
    if name is not None:
        fields.append("name = ?"); args.append(name)
    if dirs is not None:
        fields.append("directions = ?"); args.append(db.jdump(dirs))
    if requirement is not None:
        fields.append("requirement = ?"); args.append(str(requirement).strip())
    if capacity is not None:
        fields.append("capacity = ?"); args.append(_norm_capacity(capacity))
    if kind is not None:
        fields.append("kind = ?"); args.append(_norm_kind(kind))

    if fields:
        args.append(group_id)
        db.execute(f"UPDATE research_groups SET {', '.join(fields)} WHERE id = ?", tuple(args))
    return _group_detail(group_id)


def delete_group(teacher_id: int, group_id: int) -> int:
    """删除团队，连带清掉它的匹配记录，返回被清掉的记录数。"""
    group = _own_group(teacher_id, group_id)
    removed = db.scalar("SELECT COUNT(*) FROM match_records WHERE group_id = ?",
                        (group["id"],), 0)
    db.execute("DELETE FROM match_records WHERE group_id = ?", (group["id"],))
    db.execute("DELETE FROM research_groups WHERE id = ?", (group["id"],))
    return int(removed or 0)


def _unused(*_: Sequence) -> None:  # pragma: no cover
    pass
