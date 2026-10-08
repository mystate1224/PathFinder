# -*- coding: utf-8 -*-
"""org.py —— 组织维度（学院 → 专业 → 班级）唯一入口。

职责：
* 三级字典的幂等播种与存量资料回填（``ensure_bootstrap``，lifespan / seeds 各调一次）；
* 组织树、用户的组织链、学生端「按范围可见」的 SQL 子句；
* 字典 CRUD（含删除保护：下游还有数据就不许删）。

口径纪律：
* ``classes.code`` 与 ``users.class_id`` 是同一个班号的两端（CS2301 等）；
* ``materials.college_code / major_code / class_code`` 全空 = **不限范围**（全员可见）；
  非空则按「班级 > 专业 > 学院」的最具体一级匹配学生组织链。
"""
from __future__ import annotations

import db

BOOTSTRAP_FLAG = "org_dict_v1"       # 字典播种标记
BACKFILL_FLAG = "org_material_backfill_v1"  # 存量资料归属/媒体类型回填标记（只跑一次）

# 种子字典：2 学院 / 3 专业 / 6 班。班号沿用 seeds 的 users.class_id，完全兼容。
COLLEGES: list[dict] = [
    {"code": "CS", "name": "计算机与人工智能学院", "sort": 1},
    {"code": "SE", "name": "软件工程学院", "sort": 2},
]
MAJORS: list[dict] = [
    {"college": "CS", "code": "CS", "name": "计算机科学与技术", "sort": 1},
    {"college": "CS", "code": "AI", "name": "人工智能", "sort": 2},
    {"college": "SE", "code": "SE", "name": "软件工程", "sort": 3},
]
# (专业code, 班号, 中文名, 年级, sort)
CLASSES: list[tuple[str, str, str, str, int]] = [
    ("CS", "CS2301", "计算机科学与技术 2301", "2023", 1),
    ("CS", "CS2302", "计算机科学与技术 2302", "2023", 2),
    ("CS", "CS2303", "计算机科学与技术 2303", "2023", 3),
    ("AI", "AI2301", "人工智能 2301", "2023", 4),
    ("AI", "AI2302", "人工智能 2302", "2023", 5),
    ("SE", "SE2301", "软件工程 2301", "2023", 6),
]

LEVELS = ("college", "major", "class")


# ================================================================ 播种与回填
def _write(sql: str, args: tuple) -> int:
    """执行写语句并返回**真实影响行数**（db.execute 返回的是 lastrowid，不适合计数）。"""
    with db.connect() as conn:
        cur = conn.execute(sql, tuple(args))
        return int(cur.rowcount or 0)


def ensure_bootstrap() -> dict:
    """幂等：字典播种 + 存量资料回填（媒体类型 / 组织归属）。可反复调用。"""
    report: dict[str, Any] = {"dict_seeded": 0, "media_backfilled": 0, "scope_backfilled": 0}

    if db.meta_get(BOOTSTRAP_FLAG) != "1":
        for c in COLLEGES:
            report["dict_seeded"] += _write(
                "INSERT OR IGNORE INTO colleges (code, name, sort, created_at) VALUES (?,?,?,?)",
                (c["code"], c["name"], c["sort"], db.now()),
            )
        for m in MAJORS:
            college = db.query_one("SELECT id FROM colleges WHERE code = ?", (m["college"],)) or {}
            report["dict_seeded"] += _write(
                "INSERT OR IGNORE INTO majors (college_id, code, name, sort, created_at) VALUES (?,?,?,?,?)",
                (int(college.get("id") or 0), m["code"], m["name"], m["sort"], db.now()),
            )
        for major_code, code, name, grade, sort in CLASSES:
            major = db.query_one("SELECT id FROM majors WHERE code = ?", (major_code,)) or {}
            report["dict_seeded"] += _write(
                "INSERT OR IGNORE INTO classes (major_id, code, name, grade, sort, created_at) VALUES (?,?,?,?,?,?)",
                (int(major.get("id") or 0), code, name, grade, sort, db.now()),
            )
        db.meta_set(BOOTSTRAP_FLAG, "1")

    if db.meta_get(BACKFILL_FLAG) != "1":
        report["media_backfilled"] = _backfill_media_types()
        report["scope_backfilled"] = _backfill_material_scope()
        db.meta_set(BACKFILL_FLAG, "1")
    return report


def _backfill_media_types() -> int:
    """按扩展名给存量资料补 media_type。只在本机标记缺失时跑一次，避免覆盖人工修改。"""
    from services.extract import media_type_by_ext  # 延迟导入避免环

    total = 0
    for row in db.query("SELECT id, filename FROM materials"):
        want = media_type_by_ext(row.get("filename") or "")
        total += _write(
            "UPDATE materials SET media_type = ? WHERE id = ?", (want, int(row["id"]))
        )
    return total


def _backfill_material_scope() -> int:
    """给存量资料补组织归属：

    * owner 是学生 → 归到该生行政班（连带专业/学院）；
    * owner 是教师/管理员 → 保持全空（全员可见），教师常带多个班，
      硬归到一个班反而会让学生端「教师共享」莫名变少。
    """
    touched = 0
    rows = db.query(
        "SELECT m.id, u.class_id AS class_id, u.role AS role FROM materials m "
        "LEFT JOIN users u ON u.id = m.owner_id"
    )
    for row in rows:
        code = str(row.get("class_id") or "")
        if str(row.get("role")) == "student" and code:
            college, major, _ = chain_of_class(code)
            touched += _write(
                "UPDATE materials SET class_code = ?, major_code = ?, college_code = ? WHERE id = ?",
                (code, major, college, int(row["id"])),
            )
    return touched


# ================================================================ 查询
def tree() -> dict:
    """三级组织树，班级带学生数/资料数，专业与学院带资料数。"""
    colleges = db.query("SELECT id, code, name, sort FROM colleges ORDER BY sort, id")
    majors = db.query(
        "SELECT id, college_id, code, name, sort, "
        "(SELECT COUNT(*) FROM materials WHERE major_code = majors.code) AS materials "
        "FROM majors ORDER BY sort, id"
    )
    classes = db.query(
        "SELECT id, major_id, code, name, grade, sort, "
        "(SELECT COUNT(*) FROM users WHERE role = 'student' AND users.class_id = classes.code) AS students, "
        "(SELECT COUNT(*) FROM materials WHERE class_code = classes.code) AS materials "
        "FROM classes ORDER BY sort, id"
    )
    by_college: dict[int, list] = {}
    for m in majors:
        m["classes"] = []
        by_college[int(m["college_id"] or 0)] = by_college.get(int(m["college_id"] or 0), []) + [m]
    by_major: dict[int, list] = {}
    for c in classes:
        by_major.setdefault(int(c["major_id"] or 0), []).append(c)
    for m in majors:
        m["classes"] = by_major.get(int(m["id"] or 0), [])
    for c in colleges:
        c["majors"] = by_college.get(int(c["id"] or 0), [])
        c["materials"] = sum(int(mm.get("materials") or 0) for mm in c["majors"])
        c["students"] = sum(int(cc.get("students") or 0) for mm in c["majors"] for cc in mm["classes"])
    return {"colleges": colleges}


def class_row(code: str) -> dict | None:
    code = str(code or "").strip()
    return db.query_one("SELECT * FROM classes WHERE code = ?", (code,)) if code else None


def chain_of_class(class_code: str) -> tuple[str, str, str]:
    """班号 → (学院code, 专业code, 班号)。查不到返回空串元组。"""
    row = db.query_one(
        "SELECT c.code AS class_code, c.major_id, mj.code AS major_code, mj.college_id, co.code AS college_code "
        "FROM classes c LEFT JOIN majors mj ON mj.id = c.major_id "
        "LEFT JOIN colleges co ON co.id = mj.college_id WHERE c.code = ?",
        (str(class_code or "").strip(),),
    )
    if not row:
        return "", "", ""
    return (str(row.get("college_code") or ""), str(row.get("major_code") or ""),
            str(row.get("class_code") or ""))


def chain_of_user(user_id: int) -> tuple[str, str, str]:
    """用户 → 组织链。学生按行政班；教师/管理员返回空串元组（不受范围限制）。"""
    user = db.user_by_id(int(user_id or 0)) or {}
    if str(user.get("role")) != "student":
        return "", "", ""
    return chain_of_class(str(user.get("class_id") or ""))


def scope_clause(chain: tuple[str, str, str], prefix: str = "m") -> tuple[str, list]:
    """学生端「按范围可见」子句，clause 以 `` AND `` 开头。

    资料三列全空 = 全员可见；否则按最具体的一级匹配：
    挂到班级 → 只有该班学生可见；只挂专业/学院 → 该专业/学院学生可见。
    组织链解析不出的学生只能看到全空资料（安全默认，不放大可见面）。
    """
    if prefix and not prefix.endswith("."):
        prefix += "."
    college, major, klass = chain
    if not (college or major or klass):
        # 解析不出组织链：只放行「不限范围」的资料，另外放行无资料源的知识点（m.id IS NULL 由调用方拼）
        clause = (f" AND ({prefix}college_code = '' AND {prefix}major_code = '' "
                  f"AND {prefix}class_code = '')")
        return clause, []
    clause = (
        f" AND (({prefix}college_code = '' AND {prefix}major_code = '' AND {prefix}class_code = '')"
        f" OR ({prefix}class_code <> '' AND {prefix}class_code = ?)"
        f" OR ({prefix}class_code = '' AND {prefix}major_code <> '' AND {prefix}major_code = ?)"
        f" OR ({prefix}class_code = '' AND {prefix}major_code = '' AND {prefix}college_code = ?))"
    )
    return clause, [klass, major, college]


def stats() -> dict:
    """知识库总览统计（管理台可视化用）。"""
    by_media = {"image": 0, "doc": 0, "slide": 0}
    for row in db.query("SELECT media_type AS t, COUNT(*) AS n FROM materials GROUP BY media_type"):
        key = str(row.get("t") or "doc")
        by_media[key if key in by_media else "doc"] = by_media.get(key if key in by_media else "doc", 0) + int(row["n"])
    by_college = [
        {"college": r["college_code"] or "未归属", "name": r["name"] or "", "count": int(r["n"])}
        for r in db.query(
            "SELECT m.college_code AS college_code, co.name AS name, COUNT(*) AS n "
            "FROM materials m LEFT JOIN colleges co ON co.code = m.college_code "
            "GROUP BY m.college_code ORDER BY n DESC"
        )
    ]
    return {
        "materials": db.scalar("SELECT COUNT(*) FROM materials", (), 0),
        "knowledge_points": db.scalar("SELECT COUNT(*) FROM knowledge_points", (), 0),
        "images": by_media.get("image", 0),
        "classes_covered": db.scalar(
            "SELECT COUNT(DISTINCT class_code) FROM materials WHERE class_code <> ''", (), 0),
        "by_media": by_media,
        "by_college": by_college,
        "colleges": db.scalar("SELECT COUNT(*) FROM colleges", (), 0),
        "majors": db.scalar("SELECT COUNT(*) FROM majors", (), 0),
        "classes": db.scalar("SELECT COUNT(*) FROM classes", (), 0),
    }


# ================================================================ 字典 CRUD
def create(level: str, payload: dict) -> dict:
    level = _check_level(level)
    code = str(payload.get("code") or "").strip()
    name = str(payload.get("name") or "").strip() or code
    if not code:
        raise ValueError("编码不能为空")
    if level == "college":
        if db.query_one("SELECT id FROM colleges WHERE code = ?", (code,)):
            raise ValueError(f"学院编码 {code} 已存在")
        item_id = db.execute(
            "INSERT INTO colleges (code, name, sort, created_at) VALUES (?,?,?,?)",
            (code, name, _sort(payload), db.now()),
        )
    elif level == "major":
        college_id = int(payload.get("college_id") or 0)
        if not college_id or not db.query_one("SELECT id FROM colleges WHERE id = ?", (college_id,)):
            raise ValueError("请选择上级学院")
        if db.query_one("SELECT id FROM majors WHERE code = ?", (code,)):
            raise ValueError(f"专业编码 {code} 已存在")
        item_id = db.execute(
            "INSERT INTO majors (college_id, code, name, sort, created_at) VALUES (?,?,?,?,?)",
            (college_id, code, name, _sort(payload), db.now()),
        )
    else:
        major_id = int(payload.get("major_id") or 0)
        if not major_id or not db.query_one("SELECT id FROM majors WHERE id = ?", (major_id,)):
            raise ValueError("请选择上级专业")
        if db.query_one("SELECT id FROM classes WHERE code = ?", (code,)):
            raise ValueError(f"班级编码 {code} 已存在（users.class_id 同口径，需唯一）")
        item_id = db.execute(
            "INSERT INTO classes (major_id, code, name, grade, sort, created_at) VALUES (?,?,?,?,?,?)",
            (major_id, code, name, str(payload.get("grade") or ""), _sort(payload), db.now()),
        )
    return {"id": item_id, "level": level, "code": code}


def update(level: str, item_id: int, payload: dict) -> dict:
    level = _check_level(level)
    item_id = int(item_id)
    table = {"college": "colleges", "major": "majors", "class": "classes"}[level]
    row = db.query_one(f"SELECT * FROM {table} WHERE id = ?", (item_id,))
    if not row:
        raise ValueError("条目不存在")
    sets, args = [], []
    if payload.get("name") is not None:
        sets.append("name = ?")
        args.append(str(payload.get("name") or "").strip() or str(row["code"]))
    if payload.get("sort") is not None:
        try:
            sets.append("sort = ?")
            args.append(int(payload.get("sort") or 0))
        except (TypeError, ValueError):
            pass
    if level == "major" and payload.get("college_id") is not None:
        college_id = int(payload.get("college_id") or 0)
        if not db.query_one("SELECT id FROM colleges WHERE id = ?", (college_id,)):
            raise ValueError("上级学院不存在")
        sets.append("college_id = ?")
        args.append(college_id)
    if level == "class" and payload.get("major_id") is not None:
        major_id = int(payload.get("major_id") or 0)
        if not db.query_one("SELECT id FROM majors WHERE id = ?", (major_id,)):
            raise ValueError("上级专业不存在")
        sets.append("major_id = ?")
        args.append(major_id)
    if not sets:
        return {"id": item_id, "updated": False}
    args.append(item_id)
    db.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?", tuple(args))
    return {"id": item_id, "updated": True}


def delete(level: str, item_id: int, move_to: str = "") -> dict:
    """删除字典条目。下游还有数据就拒绝（blocked），班级资料可选迁移到 move_to 班级。"""
    level = _check_level(level)
    item_id = int(item_id)

    if level == "college":
        n = int(db.scalar("SELECT COUNT(*) FROM majors WHERE college_id = ?", (item_id,), 0))
        if n:
            return {"blocked": True, "reason": f"该学院下还有 {n} 个专业，先移走或删除专业"}
        db.execute("DELETE FROM colleges WHERE id = ?", (item_id,))
        return {"id": item_id, "deleted": True}

    if level == "major":
        n = int(db.scalar("SELECT COUNT(*) FROM classes WHERE major_id = ?", (item_id,), 0))
        if n:
            return {"blocked": True, "reason": f"该专业下还有 {n} 个班级，先移走或删除班级"}
        db.execute("DELETE FROM majors WHERE id = ?", (item_id,))
        return {"id": item_id, "deleted": True}

    row = db.query_one("SELECT * FROM classes WHERE id = ?", (item_id,))
    if not row:
        raise ValueError("班级不存在")
    code = str(row["code"])
    students = int(db.scalar(
        "SELECT COUNT(*) FROM users WHERE role = 'student' AND class_id = ?", (code,), 0))
    materials = int(db.scalar("SELECT COUNT(*) FROM materials WHERE class_code = ?", (code,), 0))
    if students:
        return {"blocked": True, "reason": f"该班级还有 {students} 名学生，不能删除",
                "students": students, "materials": materials}
    if materials:
        target = class_row(move_to)
        if not target:
            return {"blocked": True, "reason": f"该班级还有 {materials} 份资料，请先选择迁入的班级",
                    "students": 0, "materials": materials}
        college, major, _ = chain_of_class(str(target["code"]))
        db.execute(
            "UPDATE materials SET class_code = ?, major_code = ?, college_code = ? WHERE class_code = ?",
            (str(target["code"]), major, college, code),
        )
    db.execute("DELETE FROM classes WHERE id = ?", (item_id,))
    return {"id": item_id, "deleted": True, "moved_materials": materials}


def _check_level(level: str) -> str:
    level = str(level or "").strip().lower()
    if level not in LEVELS:
        raise ValueError("level 必须是 college / major / class")
    return level


def _sort(payload: dict) -> int:
    try:
        return int(payload.get("sort") or 0)
    except (TypeError, ValueError):
        return 0
