# -*- coding: utf-8 -*-
"""tasks.py —— 学生的「成长任务」读写。

任务由两条链路**自动产生**，学生只负责推进：
* 资源闭环：教师通过申请 → 建一条跟进任务（``resources._on_accepted``）；
* 师生匹配：双方确认 → 建一条入组任务（``matcher.decide``）。

因此这里不提供"教师给学生派任务"的入口，也不允许学生删除任务 ——
删掉任务等于把成长记录抹掉，这对复盘没有好处。学生只能改状态与进度。
"""
from __future__ import annotations

from typing import Sequence

import db
from services.errors import ServiceError

STATUS_TEXT = {"todo": "待开始", "doing": "进行中", "done": "已完成"}
STATUS_ORDER = ("todo", "doing", "done")


class TaskError(ServiceError):
    """任务相关的业务校验失败。路由层按 ``status`` 转状态码（默认 400）。"""


TASK_TYPES = {
    "resource": "资源跟进",
    "match": "课题组",
    "roadmap": "成长路线",
    "todo": "待办",
}


def _decorate(row: dict) -> dict:
    status = str(row.get("status") or "todo")
    row["status_text"] = STATUS_TEXT.get(status, status)
    row["type_label"] = TASK_TYPES.get(str(row.get("type")), str(row.get("type")))
    row["progress"] = max(0, min(100, int(row.get("progress") or 0)))
    row["overdue"] = (
        status != "done"
        and bool(row.get("due_date"))
        and str(row["due_date"]) < db.now()
    )
    return row


def list_for_student(student_id: int, status: str = "") -> dict:
    sql = "SELECT * FROM tasks WHERE student_id = ?"
    args: list = [student_id]
    if status in STATUS_ORDER:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY (status = 'done'), due_date = '', due_date, id DESC"
    rows = [_decorate(r) for r in db.query(sql, tuple(args))]

    by_status = {key: 0 for key in STATUS_ORDER}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    return {
        "tasks": rows,
        "count": len(rows),
        "by_status": by_status,
        "status_options": [{"value": k, "label": STATUS_TEXT[k]} for k in STATUS_ORDER],
        "avg_progress": (
            round(sum(r["progress"] for r in rows) / len(rows)) if rows else 0
        ),
    }


def update(student_id: int, task_id: int, status: str = "",
           progress: int | None = None) -> dict:
    """推进任务。状态与进度双向联动：done 强制 100%，doing 至少 10%。"""
    task = db.query_one(
        "SELECT * FROM tasks WHERE id = ? AND student_id = ?", (task_id, student_id)
    )
    if not task:
        raise TaskError("任务不存在，或不属于你")

    new_status = str(status or "").strip() or str(task.get("status") or "todo")
    if new_status not in STATUS_ORDER:
        raise TaskError(f"状态不合法：{new_status}（可选：{'/'.join(STATUS_ORDER)}）")

    if progress is None:
        value = int(task.get("progress") or 0)
    else:
        try:
            value = int(progress)
        except (TypeError, ValueError):
            raise TaskError("进度必须是 0~100 的整数")
    value = max(0, min(100, value))

    if new_status == "done":
        value = 100
    elif new_status == "doing" and value == 0:
        value = 10
    elif new_status == "todo" and value >= 100:
        value = 0

    db.execute(
        "UPDATE tasks SET status = ?, progress = ? WHERE id = ?", (new_status, value, task_id)
    )
    return _decorate(db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,)) or {})


def create(student_id: int, title: str, detail: str = "", ttype: str = "roadmap",
           teacher_id: int = 0, due_date: str = "", progress: int = 0) -> int:
    """建任务。主要给成长路线的「加入计划」按钮与种子数据使用。"""
    title = str(title or "").strip()
    if not title:
        raise TaskError("任务标题不能为空")
    if len(title) > 60:
        raise TaskError("任务标题过长（≤60 字）")
    if ttype not in TASK_TYPES:
        ttype = "todo"

    # 同名学生同一学生只建一次，避免反复点「加入计划」堆出一串重复任务
    if db.query_one(
        "SELECT id FROM tasks WHERE student_id = ? AND title = ?", (student_id, title)
    ):
        raise TaskError("同名任务已存在")

    return db.execute(
        "INSERT INTO tasks (student_id, teacher_id, type, title, detail, status, progress, due_date, created_at) "
        "VALUES (?,?,?,?,?, 'todo', ?, ?, ?)",
        (student_id, int(teacher_id or 0), ttype, title,
         str(detail or "").strip()[:500], max(0, min(100, int(progress or 0))),
         str(due_date or "").strip(), db.now()),
    )


def stats(student_ids: Sequence[int]) -> dict[int, dict]:
    """批量取「每人未完成任务数」，给教师驾驶舱列表用（避免 N+1 查询）。"""
    ids = [int(i) for i in student_ids if i]
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = db.query(
        f"SELECT student_id, "
        f"SUM(CASE WHEN status <> 'done' THEN 1 ELSE 0 END) AS open_count, "
        f"SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_count "
        f"FROM tasks WHERE student_id IN ({marks}) GROUP BY student_id",
        tuple(ids),
    )
    return {
        int(r["student_id"]): {
            "open": int(r["open_count"] or 0),
            "done": int(r["done_count"] or 0),
        }
        for r in rows
    }
