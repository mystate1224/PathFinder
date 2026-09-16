# -*- coding: utf-8 -*-
"""homework.py —— 作业闭环：布置 / 提交 / 逐个批改 / AI 建议分（链路 E）。

## 班级口径（容易踩坑，务必区分）

* ``users.class_id``   —— **行政班号**，用于班级总览（一个老师带一个班）；
* ``users.class_name`` —— **教学班**，用于分发作业（一个老师可带多个教学班）。

作业按「课程 + 教学班」布置，学生只看到本班的作业。
老库缺列时由 ``db.init_db()`` 的 ``_COLUMN_UPGRADES`` 补列并回填（单一迁移入口）。

## 图片作业与文字作业共用同一份数据结构

文字进 ``content``，图片记 ``{name, path, kind}``，读取时按
``submission_id + 索引`` 鉴权返回，路径必须落在上传目录内。
"""
from __future__ import annotations

import csv
import io
import os
import re
from typing import Sequence

import config
import db
from services import extract, teaching
from services.errors import ServiceError

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
DOC_EXTS = {".txt", ".md", ".pdf"}
ALLOWED_SUB_EXTS = IMAGE_EXTS | DOC_EXTS

MAX_SUB_FILES = 9


class HomeworkError(ServiceError):
    """作业相关的业务校验失败。路由层按 ``status`` 转状态码（默认 400）。"""


# ================================================================ 教学班
def classes() -> list[dict]:
    """候选教学班（按学生实际班级去重 + 人数）。"""
    rows = db.query(
        "SELECT COALESCE(NULLIF(class_name,''), class_id) AS name, COUNT(*) AS n "
        "FROM users WHERE role='student' "
        "GROUP BY COALESCE(NULLIF(class_name,''), class_id) "
        "ORDER BY name"
    )
    return [
        {"name": str(r["name"] or ""), "count": int(r["n"] or 0)}
        for r in rows if str(r["name"] or "").strip()
    ]


def courses(teacher_id: int) -> list[str]:
    """历史课程名（供前端 datalist 复用，避免「高数」与「2026高等数学」分裂）。"""
    rows = db.query(
        "SELECT DISTINCT course FROM homework WHERE teacher_id = ? AND course <> '' "
        "UNION SELECT DISTINCT course FROM knowledge_points WHERE owner_id = ? AND course <> ''",
        (teacher_id, teacher_id),
    )
    return sorted({str(r["course"]).strip() for r in rows if str(r["course"] or "").strip()})


# ================================================================ 布置 / 编辑 / 删除
def create(teacher_id: int, title: str, course: str, class_name: str, detail: str = "",
           full_score: float = 100, deadline: str = "") -> int:
    title = str(title or "").strip()
    if not title:
        raise HomeworkError("作业标题不能为空")
    if len(title) > 60:
        raise HomeworkError("作业标题过长（≤60 字）")

    course = str(course or "").strip()
    class_name = str(class_name or "").strip()
    if not class_name:
        raise HomeworkError("请选择教学班（作业按教学班分发）")
    if not any(c["name"] == class_name for c in classes()):
        raise HomeworkError(f"教学班不存在：{class_name}")

    try:
        full_score = float(full_score or 100)
    except (TypeError, ValueError):
        full_score = 100.0
    full_score = max(1.0, min(1000.0, full_score))

    return db.execute(
        "INSERT INTO homework (teacher_id, title, course, class_name, detail, full_score, deadline, status, created_at) "
        "VALUES (?,?,?,?,?,?,?, 'open', ?)",
        (teacher_id, title, course, class_name, str(detail or "").strip()[:1000],
         full_score, str(deadline or "").strip(), db.now()),
    )


def update_homework(teacher_id: int, homework_id: int, **fields) -> dict:
    """编辑作业（标题 / 说明 / 满分 / 截止 / 停止提交）。只更新传进来的字段。"""
    _owned_homework(teacher_id, homework_id)
    allowed = {"title", "course", "class_name", "detail", "full_score", "deadline", "status"}
    updates: list[str] = []
    args: list = []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if key == "title":
            value = str(value).strip()
            if not value:
                raise HomeworkError("作业标题不能为空")
        if key == "full_score":
            value = max(1.0, min(1000.0, float(value)))
        if key == "status":
            if str(value) not in ("open", "closed"):
                raise HomeworkError("状态只能是 open 或 closed")
        if key == "class_name":
            value = str(value).strip()
            if not any(c["name"] == value for c in classes()):
                raise HomeworkError(f"教学班不存在：{value}")
        updates.append(f"{key} = ?")
        args.append(value)

    if not updates:
        return homework_detail(teacher_id, homework_id)

    args.extend([homework_id, teacher_id])
    db.execute(f"UPDATE homework SET {', '.join(updates)} WHERE id = ? AND teacher_id = ?", tuple(args))
    return homework_detail(teacher_id, homework_id)


def delete_homework(teacher_id: int, homework_id: int) -> int:
    """删除作业并清理其提交（返回被清理的提交数）。"""
    _owned_homework(teacher_id, homework_id)
    removed = db.scalar(
        "SELECT COUNT(*) FROM homework_submissions WHERE homework_id = ?", (homework_id,), 0
    )
    with db.connect() as conn:
        conn.execute("DELETE FROM homework_submissions WHERE homework_id = ?", (homework_id,))
        conn.execute("DELETE FROM homework WHERE id = ?", (homework_id,))
    folder = config.HOMEWORK_UPLOAD_DIR / str(homework_id)
    if folder.is_dir():
        for item in folder.iterdir():
            try:
                if item.is_file():
                    item.unlink()
            except OSError:
                pass
    return int(removed or 0)


def _owned_homework(teacher_id: int, homework_id: int) -> dict:
    row = db.query_one("SELECT * FROM homework WHERE id = ?", (homework_id,))
    if not row:
        raise HomeworkError("作业不存在")
    if int(row.get("teacher_id") or 0) != int(teacher_id):
        raise HomeworkError("只能操作自己布置的作业")
    return row


def homework_detail(teacher_id: int, homework_id: int) -> dict:
    row = _owned_homework(teacher_id, homework_id)
    return _decorate_homework(row, teacher_id)


# ================================================================ 进度统计
def _decorate_homework(row: dict, teacher_id: int) -> dict:
    expected = db.scalar(
        "SELECT COUNT(*) FROM users WHERE role='student' AND "
        "COALESCE(NULLIF(class_name,''), class_id) = ?",
        (row.get("class_name"),),
        0,
    )
    stat = db.query_one(
        "SELECT COUNT(*) AS submitted, "
        "SUM(CASE WHEN score >= 0 THEN 1 ELSE 0 END) AS graded, "
        "AVG(CASE WHEN score >= 0 THEN score END) AS avg_score, "
        "SUM(CASE WHEN late = 1 THEN 1 ELSE 0 END) AS late_count "
        "FROM homework_submissions WHERE homework_id = ?",
        (row["id"],),
    ) or {}
    submitted = int(stat.get("submitted") or 0)
    expected = int(expected or 0)
    row = dict(row)
    row["expected"] = expected
    row["submitted"] = submitted
    row["graded"] = int(stat.get("graded") or 0)
    row["late_count"] = int(stat.get("late_count") or 0)
    row["avg_score"] = round(float(stat.get("avg_score") or 0), 1) if stat.get("graded") else None
    row["progress"] = round(submitted / expected * 100) if expected else 0
    row["graded_progress"] = round(int(stat.get("graded") or 0) / expected * 100) if expected else 0
    row["status_text"] = "接收提交中" if row.get("status") == "open" else "已停止提交"
    row["overdue"] = bool(row.get("deadline")) and str(row["deadline"]) < db.now()
    return row


def teacher_list(teacher_id: int) -> dict:
    """我布置的作业 + 提交进度（已提交 / 应交 / 已批改 / 平均分）。"""
    rows = db.query(
        "SELECT * FROM homework WHERE teacher_id = ? ORDER BY id DESC", (teacher_id,)
    )
    items = [_decorate_homework(r, teacher_id) for r in rows]
    return {
        "homework": items,
        "classes": classes(),
        "courses": courses(teacher_id),
        "stats": {
            "total": len(items),
            "open": sum(1 for h in items if h.get("status") == "open"),
            "ungraded": sum(max(0, h["submitted"] - h["graded"]) for h in items),
            "students": db.scalar(
                "SELECT COUNT(DISTINCT student_id) FROM homework_submissions", (), 0
            ),
        },
    }


def roster(teacher_id: int, homework_id: int) -> dict:
    """批改名单：本班学生（**含未提交的**）左连接提交记录，已提交的排前面。

    这里必须用 ``LEFT JOIN``：画像缺失的学生也要能被点到名，
    否则"没画像的学生直接从名单里消失"（这是踩过的坑）。
    """
    homework = _owned_homework(teacher_id, homework_id)
    rows = db.query(
        "SELECT u.id AS student_id, u.username, u.name, u.class_id, u.class_name, "
        "p.track, p.grade_level, p.gpa, p.interests, "
        "s.id AS submission_id, s.content, s.files, s.score, s.level, s.comment, "
        "s.attempt, s.late, s.submitted_at, s.graded_at "
        "FROM users u "
        "LEFT JOIN student_profiles p ON p.user_id = u.id "
        "LEFT JOIN homework_submissions s ON s.homework_id = ? AND s.student_id = u.id "
        "WHERE u.role = 'student' AND COALESCE(NULLIF(u.class_name,''), u.class_id) = ? "
        "ORDER BY (s.id IS NULL), u.username",
        (homework_id, homework.get("class_name")),
    )
    students: list[dict] = []
    for row in rows:
        row["files"] = db.jload(row.get("files"), [])
        row["interests"] = db.jload(row.get("interests"), [])
        row["submitted"] = row.get("submission_id") is not None
        row["graded"] = float(row.get("score") or -1) >= 0
        row["level_text"] = {"A": "优秀", "B": "良好", "C": "需改进"}.get(
            str(row.get("level") or ""), ""
        )
        students.append(row)

    graded = sum(1 for s in students if s["graded"])
    return {
        "homework": _decorate_homework(homework, teacher_id),
        "students": students,
        "stats": {
            "expected": len(students),
            "submitted": sum(1 for s in students if s["submitted"]),
            "graded": graded,
            "ungraded": sum(1 for s in students if s["submitted"] and not s["graded"]),
            "missing": sum(1 for s in students if not s["submitted"]),
            "first_ungraded": next(
                (i for i, s in enumerate(students) if s["submitted"] and not s["graded"]), None
            ),
        },
    }


def score_stats(teacher_id: int, homework_id: int) -> dict:
    """成绩统计视图：A/B/C 分布、最高分、最低分、中位数。"""
    homework = _owned_homework(teacher_id, homework_id)
    full = float(homework.get("full_score") or 100)
    rows = db.query(
        "SELECT score, level FROM homework_submissions WHERE homework_id = ? AND score >= 0 "
        "ORDER BY score",
        (homework_id,),
    )
    scores = [float(r["score"]) for r in rows]
    dist = {"A": 0, "B": 0, "C": 0}
    for row in rows:
        level = str(row.get("level") or "")
        if level in dist:
            dist[level] += 1
    median = 0.0
    if scores:
        mid = len(scores) // 2
        median = scores[mid] if len(scores) % 2 else round((scores[mid - 1] + scores[mid]) / 2, 1)
    return {
        "full_score": full,
        "graded": len(scores),
        "dist": dist,
        "max": max(scores) if scores else None,
        "min": min(scores) if scores else None,
        "median": median or None,
        "avg": round(sum(scores) / len(scores), 1) if scores else None,
        "buckets": _score_buckets(scores, full),
    }


def _score_buckets(scores: Sequence[float], full: float) -> list[dict]:
    edges = [(0, 0.6), (0.6, 0.7), (0.7, 0.85), (0.85, 1.01)]
    labels = ["<60%", "60~70%", "70~85%", "≥85%"]
    out = []
    for (low, high), label in zip(edges, labels):
        out.append({
            "label": label,
            "count": sum(1 for s in scores if low <= (s / full) < high),
        })
    return out


def export_csv(teacher_id: int, homework_id: int, only_missing: bool = False) -> tuple[str, str]:
    """导出成绩 CSV（学号、姓名、分数、等级、评语、提交时间）。返回 ``(文件名, 文本)``。"""
    homework = _owned_homework(teacher_id, homework_id)
    data = roster(teacher_id, homework_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["学号", "姓名", "分数", "等级", "评语", "提交时间", "逾期", "提交次数", "状态"])
    for stu in data["students"]:
        submitted = bool(stu["submitted"])
        if only_missing and submitted:
            continue
        score = stu.get("score")
        writer.writerow([
            stu.get("username") or "",
            stu.get("name") or "",
            "" if score is None or float(score) < 0 else score,
            stu.get("level") or "",
            str(stu.get("comment") or "").replace("\n", " "),
            stu.get("submitted_at") or "",
            "是" if stu.get("late") else "",
            stu.get("attempt") or "",
            ("已提交" if submitted else "未提交"),
        ])
    filename = f"{homework.get('course') or '作业'}-{homework.get('title')}-成绩.csv"
    filename = re.sub(r"[^\w\u4e00-\u9fa5.-]", "_", filename)[:80]
    return filename, buffer.getvalue()


def export_missing(teacher_id: int, homework_id: int) -> list[dict]:
    """未提交名单（一键催交用）。"""
    data = roster(teacher_id, homework_id)
    return [
        {"student_id": s["student_id"], "username": s.get("username"), "name": s.get("name")}
        for s in data["students"] if not s["submitted"]
    ]


# ================================================================ 学生侧
def student_list(student_id: int) -> dict:
    """我的作业：本班作业 + 我的提交与批改结果。"""
    user = db.user_by_id(student_id) or {}
    class_name = str(user.get("class_name") or user.get("class_id") or "")
    rows = db.query(
        "SELECT h.*, u.name AS teacher_name, "
        "s.id AS submission_id, s.content, s.files, s.score, s.level, s.comment, "
        "s.attempt, s.late, s.submitted_at, s.graded_at "
        "FROM homework h "
        "LEFT JOIN users u ON u.id = h.teacher_id "
        "LEFT JOIN homework_submissions s ON s.homework_id = h.id AND s.student_id = ? "
        "WHERE COALESCE(NULLIF(h.class_name,''), '') = ? "
        "ORDER BY (h.deadline = '') , h.deadline, h.id DESC",
        (student_id, class_name),
    )
    items: list[dict] = []
    for row in rows:
        row["files"] = db.jload(row.get("files"), [])
        row["submitted"] = row.get("submission_id") is not None
        score = float(row.get("score") or -1)
        row["graded"] = score >= 0
        row["level_text"] = {"A": "优秀", "B": "良好", "C": "需改进"}.get(
            str(row.get("level") or ""), ""
        )
        row["overdue"] = bool(row.get("deadline")) and str(row["deadline"]) < db.now()
        row["closed"] = row.get("status") == "closed"
        items.append(row)

    todo = [h for h in items if not h["submitted"] and not h["overdue"]]
    return {
        "homework": items,
        "class_name": class_name,
        "stats": {
            "total": len(items),
            "todo": len(todo),
            "submitted": sum(1 for h in items if h["submitted"]),
            "graded": sum(1 for h in items if h["graded"]),
        },
    }


def submit(student_id: int, homework_id: int, content: str = "",
           files: Sequence[dict] | None = None) -> dict:
    """提交 / 重新提交。**重新提交会清空原分数**，提醒教师重批。"""
    homework = db.query_one("SELECT * FROM homework WHERE id = ?", (homework_id,))
    if not homework:
        raise HomeworkError("作业不存在")

    user = db.user_by_id(student_id) or {}
    my_class = str(user.get("class_name") or user.get("class_id") or "")
    if str(homework.get("class_name") or "") != my_class:
        raise HomeworkError("这份作业不属于你所在的教学班")

    if homework.get("status") == "closed":
        raise HomeworkError("教师已停止该作业的提交")

    content = str(content or "").strip()
    files = [f for f in (files or []) if isinstance(f, dict) and f.get("path")]
    if not content and not files:
        raise HomeworkError("请至少提交文字内容或一张图片")

    late = 1 if (homework.get("deadline") and str(homework["deadline"]) < db.now()) else 0

    existing = db.query_one(
        "SELECT * FROM homework_submissions WHERE homework_id = ? AND student_id = ?",
        (homework_id, student_id),
    )
    if existing:
        attempt = int(existing.get("attempt") or 1) + 1
        with db.connect() as conn:
            conn.execute(
                "UPDATE homework_submissions SET content = ?, files = ?, score = -1, level = '', "
                "comment = '', attempt = ?, late = ?, submitted_at = ?, graded_at = '' "
                "WHERE id = ?",
                (content, db.jdump(files), attempt, late, db.now(), existing["id"]),
            )
        return {
            "submission_id": int(existing["id"]),
            "attempt": attempt,
            "late": bool(late),
            "resubmitted": True,
            "reset_score": float(existing.get("score") or -1) >= 0,
            "message": "已重新提交；原分数与评语已清空，等待教师重新批改。",
        }

    submission_id = db.execute(
        "INSERT INTO homework_submissions (homework_id, student_id, content, files, score, level, "
        "comment, attempt, late, submitted_at, graded_at) VALUES (?,?,?,?, -1, '', '', 1, ?, ?, '')",
        (homework_id, student_id, content, db.jdump(files), late, db.now()),
    )
    return {
        "submission_id": submission_id,
        "attempt": 1,
        "late": bool(late),
        "resubmitted": False,
        "reset_score": False,
        "message": "已提交，等待教师批改。" + ("（本次提交已逾期）" if late else ""),
    }


# ================================================================ 附件
def save_file(student_id: int, homework_id: int, filename: str, data: bytes) -> dict:
    """存作业图片/文档到 ``uploads/homework/{hid}/``，返回相对路径。"""
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HomeworkError(f"单个文件不能超过 {config.MAX_UPLOAD_MB}MB")

    name = extract.safe_name(filename)
    ext = extract.ext_of(name)
    if ext not in ALLOWED_SUB_EXTS:
        raise HomeworkError(
            "只允许提交图片（png/jpg/webp/gif/bmp）或 txt / md / pdf 文件"
        )

    folder = config.HOMEWORK_UPLOAD_DIR / str(homework_id)
    folder.mkdir(parents=True, exist_ok=True)
    stored = f"{student_id}_{db.now().replace('-', '').replace(':', '').replace(' ', '')[:14]}_{name}"
    target = folder / stored
    target.write_bytes(data)

    return {
        "name": name,
        "path": f"homework/{homework_id}/{stored}",
        "kind": "image" if ext in IMAGE_EXTS else "doc",
        "mime": extract.MIME_BY_EXT.get(ext, "application/octet-stream"),
        "size": len(data),
    }


def submission_file(user: dict, submission_id: int, index: int) -> tuple[str, str, str]:
    """取附件。返回 ``(绝对路径, mime, 原始文件名)``。

    鉴权：**只有本人或该作业的任课教师可取**；且路径必须落在上传目录内（防穿越）。
    """
    row = db.query_one(
        "SELECT s.files, s.student_id, s.homework_id, h.teacher_id "
        "FROM homework_submissions s JOIN homework h ON h.id = s.homework_id "
        "WHERE s.id = ?",
        (submission_id,),
    )
    if not row:
        raise HomeworkError("提交记录不存在")

    user_id = int(user.get("id") or 0)
    is_owner = user_id == int(row.get("student_id") or 0)
    is_teacher = user_id == int(row.get("teacher_id") or 0) and user.get("role") == "teacher"
    if not (is_owner or is_teacher):
        raise HomeworkError("无权访问该附件")

    files = db.jload(row.get("files"), [])
    if index < 0 or index >= len(files):
        raise HomeworkError("附件不存在")
    item = files[index] if isinstance(files[index], dict) else {}

    relative = str(item.get("path") or "").lstrip("/\\")
    target = (config.UPLOAD_DIR / relative).resolve()
    root = config.UPLOAD_DIR.resolve()
    if root not in target.parents and target != root:
        raise HomeworkError("附件路径非法")

    if not target.is_file():
        raise HomeworkError("附件已丢失")

    mime = str(item.get("mime") or "") or extract.MIME_BY_EXT.get(target.suffix.lower(), "application/octet-stream")
    return str(target), mime, str(item.get("name") or target.name)


# ================================================================ 批改
def grade(teacher_id: int, homework_id: int, student_id: int, score: float,
          comment: str = "", level: str = "") -> dict:
    """打分写评语。分数按满分封顶，等级 A ≥ 85% / B ≥ 70% / C 自动换算。"""
    homework = _owned_homework(teacher_id, homework_id)
    full = float(homework.get("full_score") or 100)

    submission = db.query_one(
        "SELECT * FROM homework_submissions WHERE homework_id = ? AND student_id = ?",
        (homework_id, student_id),
    )
    if not submission:
        raise HomeworkError("该学生尚未提交，无法批改")

    try:
        value = float(score)
    except (TypeError, ValueError):
        raise HomeworkError("分数必须是数字")
    value = round(max(0.0, min(full, value)), 1)

    if level and str(level).upper()[:1] in "ABC":
        final_level = str(level).upper()[:1]
    else:
        pct = value / full if full else 0
        final_level = "A" if pct >= 0.85 else "B" if pct >= 0.70 else "C"

    db.execute(
        "UPDATE homework_submissions SET score = ?, level = ?, comment = ?, graded_at = ? WHERE id = ?",
        (value, final_level, str(comment or "").strip()[:500], db.now(), submission["id"]),
    )
    return {
        "student_id": student_id,
        "submission_id": int(submission["id"]),
        "score": value,
        "level": final_level,
        "level_text": {"A": "优秀", "B": "良好", "C": "需改进"}[final_level],
        "comment": str(comment or "").strip()[:500],
        "full_score": full,
    }


def grade_missing_zero(teacher_id: int, homework_id: int) -> int:
    """一键给未交者记 0 分。返回处理人数。"""
    data = roster(teacher_id, homework_id)
    count = 0
    for stu in data["students"]:
        if stu["submitted"]:
            continue
        db.execute(
            "INSERT INTO homework_submissions (homework_id, student_id, content, files, score, level, "
            "comment, attempt, late, submitted_at, graded_at) "
            "VALUES (?,?, '', '[]', 0, 'C', '未提交，按 0 分记录。', 0, 0, '', ?)",
            (homework_id, stu["student_id"], db.now()),
        )
        count += 1
    return count


def suggest(teacher_id: int, homework_id: int, student_id: int) -> dict:
    """AI 建议分。

    * 文字作业 → ``teaching.grade_one``（要点覆盖 + 结构 + 篇幅）；
    * 纯图片作业 → 配好视觉模型时用 ``llm.vision`` 读图打分，否则**如实提示需人工批改**。
    """
    homework = _owned_homework(teacher_id, homework_id)
    full = float(homework.get("full_score") or 100)
    submission = db.query_one(
        "SELECT * FROM homework_submissions WHERE homework_id = ? AND student_id = ?",
        (homework_id, student_id),
    )
    if not submission:
        raise HomeworkError("该学生尚未提交，无法给出建议分")

    content = str(submission.get("content") or "").strip()
    files = db.jload(submission.get("files"), [])
    terms = teaching.key_terms(str(homework.get("course") or ""))

    if content:
        result, engine = teaching.grade_one(
            content,
            topic=f"{homework.get('course')} {homework.get('title')}",
            full_score=full,
            terms=terms,
        )
        result["basis"] = "文字作答"
        result["engine"] = engine          # 前端据此显示「模型生成 / 规则兜底」徽标
        return result

    images = [f for f in files if isinstance(f, dict) and f.get("kind") == "image"]
    if not images:
        return {
            "score": -1, "level": "", "level_text": "",
            "comment": "这份提交没有可批改的文字，也没有图片，请人工确认。",
            "engine": "rule", "basis": "无可批改内容", "manual": True,
        }

    _path, mime, _name = submission_file({"id": teacher_id, "role": "teacher"},
                                         int(submission["id"]), 0)
    return suggest_image(images[0], mime, homework, full, terms)


def suggest_text(text: str, course: str = "", topic: str = "",
                 full_score: float = 100.0, terms: Sequence[str] | None = None) -> dict:
    """试批：不依赖已布置的作业，直接对一段作答给建议分。

    批改中心的「试批」入口用它 —— 演示时老师可以随手粘一段学生答案，
    看双引擎各自给出的分数与评语，不必先走一遍发布作业的流程。
    """
    if not str(text or "").strip():
        raise HomeworkError("请先粘贴一段学生作答")
    result, engine = teaching.grade_one(
        text,
        topic=topic or course or "未指定主题",
        full_score=float(full_score or 100),
        terms=list(terms or []) or teaching.key_terms(course),
    )
    result["engine"] = engine
    result["basis"] = "试批（自由文本）"
    return result


def suggest_image(file_info: dict, mime: str, homework: dict, full: float,
                  terms: Sequence[str]) -> dict:
    """图片作业的建议分（需要视觉模型）。"""
    import llm  # 局部导入，避免与 teaching 形成顶部循环

    try:
        raw = (config.UPLOAD_DIR / str(file_info.get("path") or "").lstrip("/\\")).read_bytes()
    except OSError:
        raw = b""
    if not raw:
        return {
            "score": -1, "level": "", "level_text": "",
            "comment": "图片读取失败，请人工批改。", "engine": "rule",
            "basis": "图片作业", "manual": True,
        }

    prompt = (
        f"这是一份手写作业的照片。作业题目：{homework.get('course')} {homework.get('title')}。"
        f"满分 {full} 分。参考要点：{'、'.join(list(terms)[:6]) or '无'}。"
        "请根据可见的作答内容给出分数、等级与评语。"
    )
    mock = {
        "score": -1, "level": "", "highlights": [], "missing": [],
        "comment": "该提交为图片作业，当前未配置视觉模型，无法自动读图评分，请人工批改。",
    }
    result, engine = llm.vision(extract.to_base64(raw), prompt,
                                '{"score":0,"level":"A|B|C","comment":"","highlights":[],"missing":[]}',
                                mock=mock)
    if engine != "llm" or float(result.get("score") or -1) < 0:
        return {
            "score": -1, "level": "", "level_text": "",
            "comment": result.get("comment") or "图片作业需配置视觉模型后才能自动评分，请人工批改。",
            "engine": "rule", "basis": "图片作业（需视觉模型）", "manual": True,
        }
    try:
        value = round(max(0.0, min(full, float(result.get("score")))), 1)
    except (TypeError, ValueError):
        value = -1
    level = str(result.get("level") or "").upper()[:1]
    if level not in ("A", "B", "C"):
        pct = value / full if full else 0
        level = "A" if pct >= 0.85 else "B" if pct >= 0.70 else "C"
    result["score"] = value
    result["level"] = level
    result["level_text"] = {"A": "优秀", "B": "良好", "C": "需改进"}[level]
    result["engine"] = engine
    result["basis"] = "图片作业（视觉模型读图）"
    result["manual"] = value < 0
    return result


def _unused(*_: object) -> None:  # pragma: no cover
    _ = os
