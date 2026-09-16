# -*- coding: utf-8 -*-
"""dashboard.py —— 教师班级驾驶舱的数据聚合。

把一个班的所有学生画像汇总成：分布 + 建议 + 课题组 + 名单（可按层筛选）。
**口径合规**：分布只用于"推荐内容深度与任务难度"，返回文案里不含分班表述。
"""
from __future__ import annotations

from typing import Sequence

import db
from services import planner, resources, tutor

# 行政班的中文全名（班级切换器与驾驶舱标题用；不在表里也能正常显示班号）
CLASS_LABELS: dict[str, str] = {
    "CS2301": "计算机科学与技术 2301",
    "CS2302": "计算机科学与技术 2302",
    "CS2303": "计算机科学与技术 2303",
    "AI2301": "人工智能 2301",
    "AI2302": "人工智能 2302",
    "SE2301": "软件工程 2301",
}


def class_label(class_id: str) -> str:
    cid = str(class_id or "").strip()
    return CLASS_LABELS.get(cid, cid)


def class_of(teacher: dict) -> str:
    """教师对应的行政班号（主班，一个老师默认带一个班）。"""
    return str(teacher.get("class_id") or "").strip()


def classes_of(teacher: dict) -> list[dict]:
    """该教师**可查看**的行政班列表（含人数）。

    来源 ``teacher_classes``；没有配置时退回主班。驾驶舱右上角的
    班级切换器直接吃这个列表。
    """
    teacher_id = int(teacher.get("id") or 0)
    rows = db.query(
        "SELECT class_id FROM teacher_classes WHERE teacher_id = ? ORDER BY class_id",
        (teacher_id,),
    )
    ids = [str(r.get("class_id") or "").strip() for r in rows]
    ids = [c for c in ids if c]
    if not ids:
        own = class_of(teacher)
        ids = [own] if own else []

    out: list[dict] = []
    for cid in ids:
        count = db.scalar(
            "SELECT COUNT(*) FROM users WHERE role = 'student' AND class_id = ?",
            (cid,), 0,
        )
        out.append({
            "id": cid,
            "label": class_label(cid),
            "students": int(count or 0),
        })
    return out


def _student_rows(class_id: str) -> list[dict]:
    sql = (
        "SELECT u.id, u.username, u.name, u.class_id, u.class_name, "
        "p.track, p.grade_level, p.gpa, p.interests, p.ability, p.reason, p.engine "
        "FROM users u LEFT JOIN student_profiles p ON p.user_id = u.id "
        "WHERE u.role = 'student' "
    )
    args: tuple = ()
    if class_id:
        sql += "AND u.class_id = ? "
        args = (class_id,)
    sql += "ORDER BY p.gpa DESC, u.username"
    return db.query(sql, args)


def resolve_class(teacher: dict, wanted: str = "") -> tuple[str, bool]:
    """决定这次要看哪个班。

    @return ``(class_id, is_all)``：``is_all`` 为真表示跨全部任教班级汇总；
    ``class_id`` 为空串也表示「不限班级」。越权的班号一律退回主班。
    """
    allowed = {c["id"] for c in classes_of(teacher)}
    wanted = str(wanted or "").strip()
    if wanted and wanted.lower() == "all":
        return "", True
    if wanted and wanted in allowed:
        return wanted, False
    return class_of(teacher), False


def overview(teacher: dict, level: str = "", track: str = "", keyword: str = "",
             class_id: str = "", include_all: bool = False) -> dict:
    teacher_id = int(teacher.get("id") or 0)
    classes = classes_of(teacher)
    target, is_all = resolve_class(teacher, class_id)
    if include_all and not target:
        is_all = True

    # 「跨班汇总」= 任教班级全部学生；单班 = 该班
    if is_all and classes:
        ids = [c["id"] for c in classes]
        ph = ",".join("?" * len(ids))
        rows = db.query(
            "SELECT u.id, u.username, u.name, u.class_id, u.class_name, "
            "p.track, p.grade_level, p.gpa, p.interests, p.ability, p.reason, p.engine "
            "FROM users u LEFT JOIN student_profiles p ON p.user_id = u.id "
            f"WHERE u.role = 'student' AND u.class_id IN ({ph}) "
            "ORDER BY p.gpa DESC, u.username",
            tuple(ids),
        )
    else:
        rows = _student_rows(target)

    students: list[dict] = []
    track_dist = {"学业型": 0, "事业型": 0}
    level_dist = {"A": 0, "B": 0, "C": 0}
    # 交叉分布：给驾驶舱的「方框」提供「其中 A 级 x 人、事业型 y 人」这类说明
    track_level = {
        "学业型": {"A": 0, "B": 0, "C": 0},
        "事业型": {"A": 0, "B": 0, "C": 0},
    }
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
            if row["grade_level"] in track_level[row["track"]]:
                track_level[row["track"]][row["grade_level"]] += 1
        if row["grade_level"] in level_dist:
            level_dist[row["grade_level"]] += 1
        for direction in row["interests"]:
            interest_counter[direction] = interest_counter.get(direction, 0) + 1

        students.append(row)

    top_interests = [k for k, _ in sorted(interest_counter.items(), key=lambda kv: -kv[1])][:6]
    # 兴趣方向带人数：给驾驶舱方框的「本班同学对 X 兴趣较浓」句子用
    interest_dist = [
        {"name": k, "count": v}
        for k, v in sorted(interest_counter.items(), key=lambda kv: -kv[1])[:6]
    ]

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
        "class_id": target or ("全部任教班级" if is_all else "全部班级"),
        "class_label": class_label(target) if target else ("全部任教班级" if is_all else "全部班级"),
        "classes": classes,
        "is_all": is_all,
        "stats": {
            "students": len(students),
            "avg_gpa": round(
                sum(s["gpa"] for s in students) / len(students), 1
            ) if students else 0,
            "track_dist": track_dist,
            "level_dist": level_dist,
            "track_level": track_level,
            "pending_applications": int(pending or 0),
            "ungraded_submissions": int(ungraded or 0),
        },
        "top_interests": top_interests,
        "interest_dist": interest_dist,
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


def account_profile(user: dict) -> dict:
    """个人中心：账号 + 画像 + 统计，一份直接可渲染的结构。"""
    uid = int(user.get("id") or 0)
    role = str(user.get("role") or "")
    is_teacher = role == "teacher"
    cid = str(user.get("class_id") or "")
    data: dict = {
        "id": uid,
        "username": user.get("username") or "",
        "name": user.get("name") or "",
        "role": role,
        "role_text": "教师" if is_teacher else "学生",
        "class_id": cid,
        "class_name": str(user.get("class_name") or ""),
        "class_label": class_label(cid) if cid else "",
    }

    if is_teacher:
        prof = db.teacher_profile(uid) or {}
        data.update({
            "directions": db.jload(prof.get("directions"), []),
            "expertise": db.jload(prof.get("expertise"), []),
            "summary": str(prof.get("summary") or ""),
            "classes": classes_of(user),
            "stats": [
                {"label": "主班学生", "value": db.scalar(
                    "SELECT COUNT(*) FROM users WHERE role='student' AND class_id=?", (cid,), 0)},
                {"label": "常设课题组", "value": db.scalar(
                    "SELECT COUNT(*) FROM research_groups WHERE teacher_id=?", (uid,), 0)},
                {"label": "发布资源", "value": db.scalar(
                    "SELECT COUNT(*) FROM teacher_resources WHERE teacher_id=?", (uid,), 0)},
                {"label": "布置作业", "value": db.scalar(
                    "SELECT COUNT(*) FROM homework WHERE teacher_id=?", (uid,), 0)},
            ],
        })
        return data

    prof = db.student_profile(uid) or {}
    track = str(prof.get("track") or "学业型")
    level = str(prof.get("grade_level") or "B")
    ability = db.jload(prof.get("ability"), {})
    data.update({
        "track": track,
        "grade_level": level,
        "layer": tutor.layer_label(track, level),
        "style": tutor.cell_of(track, level)["style"],
        "gpa": float(prof.get("gpa") or 0),
        "interests": db.jload(prof.get("interests"), []),
        "ability_pairs": [
            {"name": name, "value": float(ability.get(key, 0) or 0)}
            for key, name in (("foundation", "专业基础"), ("practice", "实践能力"),
                              ("research", "科研素养"), ("communication", "沟通协作"),
                              ("driveself", "自驱力"))
        ],
        "stats": [
            {"label": "在办任务", "value": db.scalar(
                "SELECT COUNT(*) FROM tasks WHERE student_id=? AND status<>'done'", (uid,), 0)},
            {"label": "已上传材料", "value": db.scalar(
                "SELECT COUNT(*) FROM materials WHERE owner_id=?", (uid,), 0)},
            {"label": "课题组申请", "value": db.scalar(
                "SELECT COUNT(*) FROM resource_applications WHERE student_id=?", (uid,), 0)},
        ],
    })
    return data


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
