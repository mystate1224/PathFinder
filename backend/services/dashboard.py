# -*- coding: utf-8 -*-
"""dashboard.py —— 教师班级驾驶舱的数据聚合。

把一个班的所有学生画像汇总成：分布 + 建议 + 课题组 + 名单（可按层筛选）。
**口径合规**：分布只用于"推荐内容深度与任务难度"，返回文案里不含分班表述。
"""
from __future__ import annotations

from typing import Sequence

import db
from services import planner, resources, tutor


def class_of(teacher: dict) -> str:
    """教师对应的行政班号（一个老师带一个班）。"""
    return str(teacher.get("class_id") or "").strip()


def overview(teacher: dict, level: str = "", track: str = "", keyword: str = "") -> dict:
    teacher_id = int(teacher.get("id") or 0)
    class_id = class_of(teacher)

    rows = db.query(
        "SELECT u.id, u.username, u.name, u.class_id, u.class_name, "
        "p.track, p.grade_level, p.gpa, p.interests, p.ability, p.reason, p.engine "
        "FROM users u LEFT JOIN student_profiles p ON p.user_id = u.id "
        "WHERE u.role = 'student' AND (? = '' OR u.class_id = ?) "
        "ORDER BY p.gpa DESC, u.username",
        (class_id, class_id),
    ) if class_id else db.query(
        "SELECT u.id, u.username, u.name, u.class_id, u.class_name, "
        "p.track, p.grade_level, p.gpa, p.interests, p.ability, p.reason, p.engine "
        "FROM users u LEFT JOIN student_profiles p ON p.user_id = u.id "
        "WHERE u.role = 'student' ORDER BY p.gpa DESC, u.username"
    )

    students: list[dict] = []
    track_dist = {"学业型": 0, "事业型": 0}
    level_dist = {"A": 0, "B": 0, "C": 0}
    interest_counter: dict[str, int] = {}

    for row in rows:
        row["interests"] = db.jload(row.get("interests"), [])
        row["ability"] = db.jload(row.get("ability"), {})
        row["track"] = str(row.get("track") or "未定")
        row["grade_level"] = str(row.get("grade_level") or "B")
        row["gpa"] = float(row.get("gpa") or 0)
        row["layer"] = tutor.layer_label(
            row["track"] if row["track"] in ("学业型", "事业型") else "学业型",
            row["grade_level"],
        )
        row["style"] = tutor.cell_of(
            row["track"] if row["track"] in ("学业型", "事业型") else "学业型",
            row["grade_level"],
        )["style"]
        row["ability_pairs"] = [
            {"name": name, "value": float(row["ability"].get(key, 0) or 0)}
            for key, name in (("foundation", "专业基础"), ("practice", "实践能力"),
                              ("research", "科研素养"), ("communication", "沟通协作"),
                              ("driveself", "自驱力"))
        ]
        row["task_count"] = db.scalar(
            "SELECT COUNT(*) FROM tasks WHERE student_id = ? AND status <> 'done'",
            (row["id"],), 0,
        )

        if row["track"] in track_dist:
            track_dist[row["track"]] += 1
        if row["grade_level"] in level_dist:
            level_dist[row["grade_level"]] += 1
        for direction in row["interests"]:
            interest_counter[direction] = interest_counter.get(direction, 0) + 1

        students.append(row)

    top_interests = [k for k, _ in sorted(interest_counter.items(), key=lambda kv: -kv[1])][:6]

    # 侧栏筛选（前端本地过滤的数据量很小，但服务端也支持，便于导出/分页扩展）
    filtered = students
    if level:
        filtered = [s for s in filtered if s["grade_level"] == level.upper()[:1]]
    if track:
        filtered = [s for s in filtered if s["track"] == track]
    if keyword:
        filtered = [
            s for s in filtered
            if keyword in str(s.get("name") or "") or keyword in str(s.get("username") or "")
        ]

    advice, advice_engine = planner.class_advice(
        track_dist, level_dist, top_interests, len(students)
    )

    pending = db.scalar(
        "SELECT COUNT(*) FROM resource_applications a "
        "JOIN teacher_resources r ON r.id = a.resource_id "
        "WHERE r.teacher_id = ? AND a.status = 'pending'",
        (teacher_id,), 0,
    )
    ungraded = db.scalar(
        "SELECT COUNT(*) FROM homework_submissions s "
        "JOIN homework h ON h.id = s.homework_id "
        "WHERE h.teacher_id = ? AND s.score < 0",
        (teacher_id,), 0,
    )

    return {
        "class_id": class_id or "全部班级",
        "stats": {
            "students": len(students),
            "avg_gpa": round(
                sum(s["gpa"] for s in students) / len(students), 1
            ) if students else 0,
            "track_dist": track_dist,
            "level_dist": level_dist,
            "pending_applications": int(pending or 0),
            "ungraded_submissions": int(ungraded or 0),
        },
        "top_interests": top_interests,
        "advice": advice,
        "advice_engine": advice_engine,
        "students": filtered,
        "groups": resources.my_groups(teacher_id),
        "teacher_profile": db.teacher_profile(teacher_id) or {},
    }


def student_detail(teacher: dict, student_id: int) -> dict:
    """学生画像 + 任务 + 掌握度 + 成长路线（教师侧查看）。"""
    user = db.user_by_id(student_id)
    if not user:
        raise ValueError("学生不存在")
    profile = db.student_profile(student_id) or {}

    profile.setdefault("track", "学业型")
    profile.setdefault("grade_level", "B")
    profile["layer"] = tutor.layer_label(profile["track"], profile["grade_level"])
    profile["style"] = tutor.cell_of(profile["track"], profile["grade_level"])["style"]
    ability = db.jload(profile.get("ability"), {})
    profile["ability_pairs"] = [
        {"name": name, "value": float(ability.get(key, 0) or 0)}
        for key, name in (("foundation", "专业基础"), ("practice", "实践能力"),
                          ("research", "科研素养"), ("communication", "沟通协作"),
                          ("driveself", "自驱力"))
    ]
    profile["interests"] = db.jload(profile.get("interests"), [])

    tasks = db.query(
        "SELECT * FROM tasks WHERE student_id = ? ORDER BY status, id DESC", (student_id,)
    )
    mastery = db.query(
        "SELECT * FROM kp_mastery WHERE student_id = ? ORDER BY mastery", (student_id,)
    )
    route, engine = planner.roadmap(profile, mastery)

    return {
        "student": {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "class_id": user.get("class_id"),
            "class_name": user.get("class_name"),
        },
        "profile": profile,
        "tasks": tasks,
        "mastery": mastery,
        "roadmap": route,
        "roadmap_engine": engine,
        "applications": resources.student_applications(student_id),
    }


def student_self(student_id: int) -> dict:
    """学生看自己的画像页：画像 + 任务 + 材料 + 路线 + 建议。"""
    user = db.user_by_id(student_id) or {}
    profile = db.student_profile(student_id) or {}
    profile["track"] = str(profile.get("track") or "学业型")
    profile["grade_level"] = str(profile.get("grade_level") or "B")
    profile["layer"] = tutor.layer_label(profile["track"], profile["grade_level"])
    profile["style"] = tutor.cell_of(profile["track"], profile["grade_level"])["style"]
    profile["next_step"] = tutor.cell_of(profile["track"], profile["grade_level"])["next"]
    profile["interests"] = db.jload(profile.get("interests"), [])
    ability = db.jload(profile.get("ability"), {})
    profile["ability_pairs"] = [
        {"name": name, "value": float(ability.get(key, 0) or 0)}
        for key, name in (("foundation", "专业基础"), ("practice", "实践能力"),
                          ("research", "科研素养"), ("communication", "沟通协作"),
                          ("driveself", "自驱力"))
    ]

    tasks = db.query(
        "SELECT * FROM tasks WHERE student_id = ? ORDER BY status, id DESC", (student_id,)
    )
    materials = db.query(
        "SELECT id, kind, category, filename, created_at, engine FROM materials "
        "WHERE owner_id = ? ORDER BY id DESC",
        (student_id,),
    )
    mastery = db.query(
        "SELECT * FROM kp_mastery WHERE student_id = ? ORDER BY mastery", (student_id,)
    )
    route, engine = planner.roadmap(profile, mastery)

    return {
        "user": {
            "id": user.get("id"), "username": user.get("username"), "name": user.get("name"),
            "class_id": user.get("class_id"), "class_name": user.get("class_name"),
        },
        "profile": profile,
        "tasks": tasks,
        "materials": materials,
        "mastery": mastery,
        "roadmap": route,
        "roadmap_engine": engine,
        "stats": {
            "tasks_todo": sum(1 for t in tasks if t.get("status") != "done"),
            "materials": len(materials),
            "applications": len(resources.student_applications(student_id)),
        },
    }


def recompute_mastery(student_id: int, course: str = "") -> int:
    """由「作业成绩 + 答疑命中」推导知识掌握度（供成长路线使用）。

    规则：某知识点在作业评语/正文中被命中 → 按该次作业得分率记一次观测；
    取该知识点所有观测的加权平均。没有观测的知识点不写记录（宁缺毋滥）。
    """
    rows = db.query(
        "SELECT kp.name AS kp_name, kp.course AS course, s.score, h.full_score, s.content, s.comment "
        "FROM knowledge_points kp "
        "JOIN homework h ON h.course = kp.course "
        "JOIN homework_submissions s ON s.homework_id = h.id AND s.student_id = ? "
        "WHERE s.score >= 0 AND (? = '' OR kp.course = ?)",
        (student_id, course, course),
    )
    buckets: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        name = str(row.get("kp_name") or "").strip()
        if len(name) < 2:
            continue
        blob = f"{row.get('content') or ''} {row.get('comment') or ''}"
        if name not in blob:
            continue
        full = float(row.get("full_score") or 100) or 100
        ratio = max(0.0, min(1.0, float(row.get("score") or 0) / full))
        buckets.setdefault((name, str(row.get("course") or "")), []).append(ratio)

    if not buckets:
        return 0

    written = 0
    for (name, course_name), ratios in buckets.items():
        mastery = round(sum(ratios) / len(ratios), 3)
        db.execute(
            "INSERT INTO kp_mastery (student_id, kp_name, course, mastery, evidence, updated_at) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(student_id, kp_name) DO UPDATE SET "
            "mastery=excluded.mastery, course=excluded.course, evidence=excluded.evidence, "
            "updated_at=excluded.updated_at",
            (
                student_id, name, course_name, mastery,
                f"由 {len(ratios)} 次作业观测推导（平均得分率 {round(mastery * 100)}%）",
                db.now(),
            ),
        )
        written += 1
    return written


def _unused(*_: Sequence) -> None:  # pragma: no cover
    pass
