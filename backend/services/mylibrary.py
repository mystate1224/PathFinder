# -*- coding: utf-8 -*-
"""mylibrary.py —— 我的资料：分类维护、删除、知识点视图。

薄薄一层，把 ``extract`` 的读写能力包成"资料库"语义，
路由层只管参数转发，不碰 SQL。
"""
from __future__ import annotations

import db
from services import extract, rag

DEFAULT_CATEGORIES = extract.CATEGORIES


def categories(owner_id: int) -> list[str]:
    rows = db.query(
        "SELECT DISTINCT category FROM materials WHERE owner_id = ? AND category <> ''",
        (owner_id,),
    )
    found = [r["category"] for r in rows if r.get("category")]
    merged = list(dict.fromkeys(DEFAULT_CATEGORIES + found))
    return merged


def _scope_clause(owner_id: int, teacher_scope: bool, prefix: str = "kp") -> tuple[str, list]:
    """知识点的可见范围（纯数据权限，与"分层教学"无关）。

    * 教师 → 全库：课程知识点的整体覆盖情况是备课与命题的依据。
    * 学生 → 自己的材料 + **教师上传的共享课件**。

    学生之间互不可见：成绩单、简历是私人材料，而教师上传的课件是课程共享资产，
    两者性质不同，必须区别对待 —— 一刀切"全库"会泄露他人隐私，
    一刀切"只看自己"则学生永远看不到课程知识点（这是演示时的空库陷阱）。
    """
    if teacher_scope:
        return "", []
    clause = (
        f" AND ({prefix}.owner_id = ? OR {prefix}.owner_id IN "
        "(SELECT id FROM users WHERE role = 'teacher'))"
    )
    return clause, [owner_id]


def overview(owner_id: int, teacher_scope: bool = False) -> dict:
    stats = rag.stats(owner_id)
    # 资料数是"我的资料"；知识点数按可见范围统计，否则两个数字会互相打架
    clause, args = _scope_clause(owner_id, teacher_scope)
    stats["knowledge_points"] = db.scalar(
        "SELECT COUNT(*) FROM knowledge_points kp WHERE 1=1" + clause, tuple(args), 0
    )
    stats["knowledge_scope"] = "全库（课程知识点）" if teacher_scope else "我的材料 + 教师共享课件"
    return {
        "categories": categories(owner_id),
        "kinds": [{"value": k, "label": v} for k, v in extract.KINDS.items()],
        "stats": stats,
        "recent": extract.list_materials(owner_id)[:5],
    }


def materials(owner_id: int, category: str = "", course: str = "", keyword: str = "") -> dict:
    items = extract.list_materials(owner_id, category, course, keyword)
    # 按分类分组，前端可直接渲染分组卡片
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(str(item.get("category") or "未分类"), []).append(item)
    return {
        "materials": items,
        "grouped": [{"category": k, "items": v} for k, v in grouped.items()],
        "categories": categories(owner_id),
        "count": len(items),
    }


def set_category(owner_id: int, material_id: int, category: str) -> bool:
    return extract.set_category(owner_id, material_id, category)


def delete(owner_id: int, material_id: int) -> bool:
    return extract.delete_material(owner_id, material_id)


def knowledge(owner_id: int, course: str = "", difficulty: str = "",
              keyword: str = "", teacher_scope: bool = False) -> dict:
    """知识点列表。可见范围见 ``_scope_clause``（教师全库 / 学生自己+教师共享）。"""
    sql = "SELECT kp.*, m.filename, m.category FROM knowledge_points kp " \
          "LEFT JOIN materials m ON m.id = kp.material_id WHERE 1=1"
    clause, args = _scope_clause(owner_id, teacher_scope)
    sql += clause
    if course:
        sql += " AND kp.course = ?"
        args.append(course)
    if difficulty:
        sql += " AND kp.difficulty = ?"
        args.append(difficulty.upper()[:1])
    if keyword:
        sql += " AND (kp.name LIKE ? OR kp.keywords LIKE ?)"
        args.extend([f"%{keyword}%", f"%{keyword}%"])
    sql += " ORDER BY kp.id DESC LIMIT 300"

    rows = db.query(sql, tuple(args))
    dist = {"A": 0, "B": 0, "C": 0}
    courses: dict[str, int] = {}
    for row in rows:
        row["keywords"] = db.jload(row.get("keywords"), [])
        level = str(row.get("difficulty") or "B")
        dist[level] = dist.get(level, 0) + 1
        name = str(row.get("course") or "未分课程")
        courses[name] = courses.get(name, 0) + 1

    return {
        "knowledge": rows,
        "count": len(rows),
        "dist": dist,
        "courses": [{"course": k, "count": v} for k, v in
                    sorted(courses.items(), key=lambda kv: -kv[1])],
    }


def teacher_profile(owner_id: int) -> dict:
    profile = db.teacher_profile(owner_id) or {}
    profile["materials"] = db.scalar(
        "SELECT COUNT(*) FROM materials WHERE owner_id = ?", (owner_id,), 0
    )
    profile["groups"] = db.query(
        "SELECT * FROM research_groups WHERE teacher_id = ? ORDER BY id", (owner_id,)
    )
    for group in profile["groups"]:
        group["directions"] = db.jload(group.get("directions"), [])
    return profile
