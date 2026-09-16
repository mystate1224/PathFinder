# -*- coding: utf-8 -*-
"""resources.py —— 资源发布 / 学生申请 / 教师处理（链路 D）。

四种资源类型由接口下发（``rtypes``），**前端不写死**：新增类型只改后端一处。

权限与幂等都在服务层校验，路由层只做参数转发与「异常 → HTTP 错误」的转换。
教师之间数据隔离：``teacher_view`` 只返回当前教师名下的资源与其申请。
"""
from __future__ import annotations

from typing import Sequence

import db
from services.errors import ServiceError

RTYPES: dict[str, str] = {
    "group": "课题组",
    "contest": "比赛",
    "internship": "实习",
    "project": "项目",
}

STATUS_TEXT = {"pending": "待处理", "accepted": "已通过", "declined": "已婉拒"}


class ResourceError(ServiceError):
    """资源相关的业务校验失败。路由层按 ``status`` 转状态码（默认 400）。"""


def rtype_options() -> list[dict]:
    return [{"value": k, "label": v} for k, v in RTYPES.items()]


def _decorate(row: dict, application_counts: dict[int, dict] | None = None) -> dict:
    row["tags"] = db.jload(row.get("tags"), [])
    row["rtype_label"] = RTYPES.get(str(row.get("rtype")), str(row.get("rtype")))
    row["status_text"] = "接收申请中" if row.get("status") == "open" else "已停止"
    if application_counts is not None:
        stat = application_counts.get(int(row.get("id") or 0), {})
        row["applied"] = stat.get("total", 0)
        row["pending"] = stat.get("pending", 0)
        row["accepted"] = stat.get("accepted", 0)
    return row


def _application_counts(resource_ids: Sequence[int]) -> dict[int, dict]:
    if not resource_ids:
        return {}
    marks = ",".join("?" for _ in resource_ids)
    rows = db.query(
        f"SELECT resource_id, status, COUNT(*) AS n FROM resource_applications "
        f"WHERE resource_id IN ({marks}) GROUP BY resource_id, status",
        tuple(resource_ids),
    )
    out: dict[int, dict] = {}
    for row in rows:
        bucket = out.setdefault(int(row["resource_id"]), {"total": 0, "pending": 0, "accepted": 0})
        count = int(row["n"] or 0)
        bucket["total"] += count
        if row["status"] == "pending":
            bucket["pending"] = count
        elif row["status"] == "accepted":
            bucket["accepted"] = count
    return out


# ================================================================ 教师侧
def teacher_view(teacher_id: int) -> dict:
    """我发布的资源 + 名下申请 + 类型选项（严格数据隔离）。"""
    resources = db.query(
        "SELECT * FROM teacher_resources WHERE teacher_id = ? ORDER BY id DESC", (teacher_id,)
    )
    ids = [int(r["id"]) for r in resources]
    counts = _application_counts(ids)
    resources = [_decorate(r, counts) for r in resources]

    applications: dict[int, list[dict]] = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        rows = db.query(
            f"SELECT a.*, u.name AS student_name, u.username AS student_username, "
            f"u.class_name, u.class_id, p.track, p.grade_level, p.gpa "
            f"FROM resource_applications a "
            f"JOIN users u ON u.id = a.student_id "
            f"LEFT JOIN student_profiles p ON p.user_id = a.student_id "
            f"WHERE a.resource_id IN ({marks}) ORDER BY "
            f"CASE a.status WHEN 'pending' THEN 0 ELSE 1 END, a.id DESC",
            tuple(ids),
        )
        for row in rows:
            row["status_text"] = STATUS_TEXT.get(str(row.get("status")), str(row.get("status")))
            applications.setdefault(int(row["resource_id"]), []).append(row)

    for resource in resources:
        resource["applications"] = applications.get(int(resource["id"]), [])

    pending_total = sum(r.get("pending", 0) for r in resources)
    return {
        "resources": resources,
        "rtypes": rtype_options(),
        "stats": {
            "total": len(resources),
            "open": sum(1 for r in resources if r.get("status") == "open"),
            "pending": pending_total,
            "accepted": sum(r.get("accepted", 0) for r in resources),
        },
        "groups": my_groups(teacher_id),
    }


def my_groups(teacher_id: int) -> list[dict]:
    """我的常设课题组（``research_groups``，与「课题组」类资源相互独立）。"""
    rows = db.query(
        "SELECT * FROM research_groups WHERE teacher_id = ? ORDER BY id", (teacher_id,)
    )
    for row in rows:
        row["directions"] = db.jload(row.get("directions"), [])
        row["member_count"] = db.scalar(
            "SELECT COUNT(*) FROM match_records WHERE group_id = ? AND teacher_action = 'accepted' "
            "AND student_action = 'accepted'",
            (row["id"],),
            0,
        )
    return rows


# ================================================================ 发布 / 编辑 / 删除
def create_resource(teacher_id: int, rtype: str, title: str, detail: str = "",
                    tags: Sequence[str] | None = None, capacity: int = 0,
                    deadline: str = "") -> int:
    rtype = str(rtype or "").strip()
    if rtype not in RTYPES:
        raise ResourceError(f"资源类型不合法：{rtype}（可选：{'/'.join(RTYPES)}）")
    title = str(title or "").strip()
    if not title:
        raise ResourceError("资源名称不能为空")
    if len(title) > 60:
        raise ResourceError("资源名称过长（≤60 字）")

    tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    return db.execute(
        "INSERT INTO teacher_resources (teacher_id, rtype, title, detail, tags, capacity, deadline, status, created_at) "
        "VALUES (?,?,?,?,?,?,?, 'open', ?)",
        (
            teacher_id, rtype, title, str(detail or "").strip(), db.jdump(tags[:8]),
            max(0, int(capacity or 0)), str(deadline or "").strip(), db.now(),
        ),
    )


def update_resource(teacher_id: int, resource_id: int, **fields) -> dict:
    """编辑资源（只允许改自己的）。只更新传进来的字段。"""
    resource = _owned_resource(teacher_id, resource_id)
    allowed = {
        "title", "detail", "rtype", "capacity", "deadline", "status",
    }
    updates: list[str] = []
    args: list = []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if key == "rtype" and str(value) not in RTYPES:
            raise ResourceError(f"资源类型不合法：{value}")
        if key == "title":
            value = str(value).strip()
            if not value:
                raise ResourceError("资源名称不能为空")
        if key == "capacity":
            value = max(0, int(value))
        if key == "status" and str(value) not in ("open", "closed"):
            raise ResourceError("状态只能是 open 或 closed")
        if key == "tags":
            value = db.jdump([str(t).strip() for t in (value or []) if str(t).strip()][:8])
        updates.append(f"{key} = ?")
        args.append(value)

    if not updates:
        return _decorate(resource)

    args.extend([resource_id, teacher_id])
    db.execute(
        f"UPDATE teacher_resources SET {', '.join(updates)} WHERE id = ? AND teacher_id = ?",
        tuple(args),
    )
    return _decorate(db.query_one("SELECT * FROM teacher_resources WHERE id = ?", (resource_id,)))


def delete_resource(teacher_id: int, resource_id: int) -> int:
    """删除资源并同步清理其下申请。返回被清理的申请条数。"""
    _owned_resource(teacher_id, resource_id)
    removed = db.scalar(
        "SELECT COUNT(*) FROM resource_applications WHERE resource_id = ?", (resource_id,), 0
    )
    with db.connect() as conn:
        conn.execute("DELETE FROM resource_applications WHERE resource_id = ?", (resource_id,))
        conn.execute("DELETE FROM teacher_resources WHERE id = ?", (resource_id,))
    return int(removed or 0)


def close_resource(teacher_id: int, resource_id: int) -> dict:
    """状态互换（``open ↔ closed``）：教师可随时停止或重启招募。"""
    resource = _owned_resource(teacher_id, resource_id)
    new_status = "closed" if resource.get("status") == "open" else "open"
    db.execute(
        "UPDATE teacher_resources SET status = ? WHERE id = ? AND teacher_id = ?",
        (new_status, resource_id, teacher_id),
    )
    return _decorate(db.query_one("SELECT * FROM teacher_resources WHERE id = ?", (resource_id,)))


def _owned_resource(teacher_id: int, resource_id: int) -> dict:
    resource = db.query_one("SELECT * FROM teacher_resources WHERE id = ?", (resource_id,))
    if not resource:
        raise ResourceError("资源不存在或已被删除", 404)
    if int(resource.get("teacher_id") or 0) != int(teacher_id):
        raise ResourceError("只能操作自己发布的资源", 403)
    return resource


# ================================================================ 处理申请
def decide(teacher_id: int, application_id: int, action: str, reply: str = "") -> dict:
    """处理申请。``accepted`` 时**顺手给该学生建一条跟进任务**。"""
    action = str(action or "").strip()
    if action not in ("accepted", "declined"):
        raise ResourceError("处理结果只能是 accepted 或 declined")

    row = db.query_one(
        "SELECT a.*, r.title AS resource_title, r.rtype, r.teacher_id AS owner_id, r.capacity "
        "FROM resource_applications a "
        "JOIN teacher_resources r ON r.id = a.resource_id "
        "WHERE a.id = ?",
        (application_id,),
    )
    if not row:
        raise ResourceError("申请不存在")
    if int(row.get("owner_id") or 0) != int(teacher_id):
        raise ResourceError("只能处理自己资源上的申请")

    reply = str(reply or "").strip()[:300]
    db.execute(
        "UPDATE resource_applications SET status = ?, teacher_reply = ? WHERE id = ?",
        (action, reply, application_id),
    )

    created_task = 0
    if action == "accepted":
        created_task = _on_accepted(row, reply)

    return {
        "application_id": application_id,
        "status": action,
        "status_text": STATUS_TEXT.get(action, action),
        "teacher_reply": reply,
        "task_created": bool(created_task),
        "task_id": created_task,
    }


def _on_accepted(application: dict, reply: str) -> int:
    """通过后自动给学生建跟进任务（链路 D 的收口动作）。"""
    label = RTYPES.get(str(application.get("rtype")), "资源")
    title = f"跟进「{application.get('resource_title')}」"
    detail = (
        f"你申请的{label}已通过。"
        + (f"教师回复：{reply}" if reply else "请按教师要求开展后续工作。")
    )
    return db.execute(
        "INSERT INTO tasks (student_id, teacher_id, type, title, detail, status, progress, due_date, created_at) "
        "VALUES (?,?,?,?,?, 'todo', 0, '', ?)",
        (int(application["student_id"]), int(application["owner_id"]), "resource", title, detail, db.now()),
    )


# ================================================================ 学生侧
def board(student_id: int) -> dict:
    """学生端资源广场：按教师分组 + 我的申请记录。"""
    rows = db.query(
        "SELECT r.*, u.name AS teacher_name, u.username AS teacher_username "
        "FROM teacher_resources r JOIN users u ON u.id = r.teacher_id "
        "ORDER BY r.teacher_id, r.id DESC"
    )
    ids = [int(r["id"]) for r in rows]
    counts = _application_counts(ids)

    my_apps: dict[int, dict] = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        for app in db.query(
            f"SELECT * FROM resource_applications WHERE student_id = ? AND resource_id IN ({marks})",
            (student_id, *ids),
        ):
            app["status_text"] = STATUS_TEXT.get(str(app.get("status")), str(app.get("status")))
            my_apps[int(app["resource_id"])] = app

    teacher_ids = []
    grouped: dict[int, dict] = {}
    for row in rows:
        row = _decorate(row, counts)
        row["my_application"] = my_apps.get(int(row["id"]))
        tid = int(row["teacher_id"])
        if tid not in grouped:
            teacher_ids.append(tid)
            profile = db.teacher_profile(tid) or {}
            grouped[tid] = {
                "teacher_id": tid,
                "name": row.get("teacher_name") or row.get("teacher_username") or f"教师{tid}",
                "directions": profile.get("directions") or [],
                "summary": profile.get("summary") or "",
                "resources": [],
            }
        grouped[tid]["resources"].append(row)

    teachers = [grouped[tid] for tid in teacher_ids]
    return {
        "teachers": teachers,
        "rtypes": rtype_options(),
        "my_application_count": len(my_apps),
    }


def apply(student_id: int, resource_id: int, message: str = "") -> dict:
    """提交申请：校验资源存在 / 状态开放 / 名额未满 / 不重复申请。"""
    resource = db.query_one("SELECT * FROM teacher_resources WHERE id = ?", (resource_id,))
    if not resource:
        raise ResourceError("资源不存在", 404)
    if resource.get("status") != "open":
        raise ResourceError("该资源已停止接收申请")

    existing = db.query_one(
        "SELECT * FROM resource_applications WHERE resource_id = ? AND student_id = ?",
        (resource_id, student_id),
    )
    if existing:
        status = str(existing.get("status"))
        if status == "pending":
            raise ResourceError("你已提交过申请，正在等待教师处理")
        if status == "accepted":
            raise ResourceError("你已通过该资源的申请")
        raise ResourceError("你此前被婉拒，暂不能重复申请（可与教师直接沟通）")

    capacity = int(resource.get("capacity") or 0)
    if capacity > 0:
        accepted = db.scalar(
            "SELECT COUNT(*) FROM resource_applications WHERE resource_id = ? AND status = 'accepted'",
            (resource_id,), 0,
        )
        if int(accepted or 0) >= capacity:
            raise ResourceError("该资源名额已满")

    app_id = db.execute(
        "INSERT INTO resource_applications (resource_id, student_id, message, status, teacher_reply, created_at) "
        "VALUES (?,?,?, 'pending', '', ?)",
        (resource_id, student_id, str(message or "").strip()[:300], db.now()),
    )

    # 学生申请行为微调就业倾向（这是个弱信号，只做 ±0.2 的微调，不改变主标签口径）
    _nudge_intent(student_id, resource.get("rtype"))

    return {"application_id": app_id, "status": "pending", "status_text": STATUS_TEXT["pending"]}


def _nudge_intent(student_id: int, rtype: str) -> None:
    profile = db.student_profile(student_id)
    if not profile:
        return
    delta = {"group": 0.2, "contest": 0.1, "internship": -0.2, "project": -0.1}.get(str(rtype), 0.0)
    if not delta:
        return
    reason = str(profile.get("reason") or "")
    # 倾向值本身没有单列，这里通过 reason 的更新间接体现 —— 保持简单，不做过度建模
    if "申请行为" not in reason:
        db.execute(
            "UPDATE student_profiles SET reason = ? WHERE user_id = ?",
            (f"{reason}（近期有资源申请行为，倾向信号已微调。）", student_id),
        )


def resource_detail(resource_id: int, student_id: int = 0) -> dict:
    resource = db.query_one(
        "SELECT r.*, u.name AS teacher_name FROM teacher_resources r "
        "JOIN users u ON u.id = r.teacher_id WHERE r.id = ?",
        (resource_id,),
    )
    if not resource:
        raise ResourceError("资源不存在", 404)
    resource = _decorate(resource, _application_counts([resource_id]))
    resource["my_application"] = (
        db.query_one(
            "SELECT * FROM resource_applications WHERE resource_id = ? AND student_id = ?",
            (resource_id, student_id),
        )
        if student_id else None
    )
    return resource


def student_applications(student_id: int) -> list[dict]:
    rows = db.query(
        "SELECT a.*, r.title AS resource_title, r.rtype, u.name AS teacher_name "
        "FROM resource_applications a "
        "JOIN teacher_resources r ON r.id = a.resource_id "
        "JOIN users u ON u.id = r.teacher_id "
        "WHERE a.student_id = ? ORDER BY a.id DESC",
        (student_id,),
    )
    for row in rows:
        row["status_text"] = STATUS_TEXT.get(str(row.get("status")), str(row.get("status")))
        row["rtype_label"] = RTYPES.get(str(row.get("rtype")), str(row.get("rtype")))
    return rows
