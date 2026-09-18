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

    统一走 ``rag.search_scope``，与检索层同一条规则：

    * 教师 → 自己 + 全部教师上传的公用课件（课程知识点是备课与命题的依据）；
    * 学生 → 自己的材料 + **已导入**的教师公用资料。

    学生之间互不可见：成绩单、简历是私人材料，而教师上传的课件是课程共享资产，
    两者性质不同，必须区别对待 —— 一刀切"全库"会泄露他人隐私，
    一刀切"只看自己"则学生看不到课程知识点（这是演示时的空库陷阱，见 seeds 的预导入）。
    """
    return rag.search_scope(owner_id, teacher_scope, prefix)


# ================================================================ 教师公用资料与导入
def shared_materials(viewer_id: int) -> list[dict]:
    """教师上传的公用资料列表（学生视角的「教师共享」区）。

    只给元信息与摘要，不给正文；带 ``imported`` 标记供前端渲染「导入 / 移除」。
    教师自己调用时返回空 —— 公用池本来就是他们建的，不重复展示。
    """
    rows = db.query(
        "SELECT m.id, m.filename, m.kind, m.category, m.engine, m.created_at, "
        "       m.parsed, u.name AS owner_name, "
        "       (SELECT COUNT(*) FROM knowledge_points kp WHERE kp.material_id = m.id) AS knowledge_count, "
        "       EXISTS(SELECT 1 FROM material_imports mi "
        "              WHERE mi.material_id = m.id AND mi.user_id = ?) AS imported "
        "FROM materials m JOIN users u ON u.id = m.owner_id "
        "WHERE u.role = 'teacher' ORDER BY m.id DESC",
        (int(viewer_id),),
    )
    for row in rows:
        parsed = db.jload(row.get("parsed"), {}) or {}
        row["summary"] = str(parsed.get("summary") or "")[:80]
        row.pop("parsed", None)
        row["imported"] = bool(row.get("imported"))
    return rows


def import_material(user_id: int, material_id: int) -> tuple[bool, str]:
    """把教师公用资料导入自己的检索库。返回 (ok, message)。"""
    row = db.query_one(
        "SELECT m.id, u.role AS owner_role FROM materials m "
        "JOIN users u ON u.id = m.owner_id WHERE m.id = ?",
        (material_id,),
    )
    if not row:
        return False, "资料不存在"
    if str(row.get("owner_role")) != "teacher":
        return False, "只能导入教师上传的公用资料"
    db.execute(
        "INSERT OR IGNORE INTO material_imports (user_id, material_id, created_at) VALUES (?,?,?)",
        (int(user_id), int(material_id), db.now()),
    )
    return True, "已导入：之后的提问可以引用这份资料"


def remove_import(user_id: int, material_id: int) -> bool:
    """移除导入：只删引用记录，公用资料本体不受影响。"""
    with db.connect() as conn:
        cur = conn.execute(
            "DELETE FROM material_imports WHERE user_id = ? AND material_id = ?",
            (int(user_id), int(material_id)),
        )
        return int(cur.rowcount or 0) > 0


def imported_ids(user_id: int) -> list[int]:
    rows = db.query(
        "SELECT material_id FROM material_imports WHERE user_id = ?", (int(user_id),)
    )
    return [int(r["material_id"]) for r in rows]


def overview(owner_id: int, teacher_scope: bool = False) -> dict:
    stats = rag.stats(owner_id)
    # 资料数是"我的资料"；知识点数按可见范围统计，否则两个数字会互相打架
    clause, args = _scope_clause(owner_id, teacher_scope)
    stats["knowledge_points"] = db.scalar(
        "SELECT COUNT(*) FROM knowledge_points kp WHERE 1=1" + clause, tuple(args), 0
    )
    stats["knowledge_scope"] = "教师公用资料（全量）" if teacher_scope else "我的资料 + 已导入的公用资料"
    return {
        "categories": categories(owner_id),
        "kinds": [{"value": k, "label": v} for k, v in extract.KINDS.items()],
        "stats": stats,
        "recent": extract.list_materials(owner_id)[:5],
    }


def materials(owner_id: int, category: str = "", course: str = "",
              keyword: str = "", teacher_scope: bool = False) -> dict:
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
        # 教师上传的公用资料：学生在列表里可见，可选择「导入数据库」进入自己的检索范围。
        # 教师视角不重复展示（公用池是教师自己建的）。
        "shared": [] if teacher_scope else shared_materials(owner_id),
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
