# -*- coding: utf-8 -*-
"""admin.py —— 管理端（角色 admin）：用户 / 知识库 / 模型配置的增删改查。

## 定位

管理端只做**运维**：看得全、改得动、改完立刻生效。它不参与教学业务逻辑，
也不替教师/学生做决定 —— 所以这里没有"智能"，只有清晰的 CRUD 与校验。

## 三类对象

1. **用户**：学生 / 教师的增、查、改、删（含重置密码）。
   删人走**级联清理**，不留孤儿数据（画像、会话、资料、作业提交等）。
2. **知识库**：资料（materials）与知识点（knowledge_points）的查、改、删。
   知识点是答疑与图谱的证据源，管理端可直接订正错误的抽取结果。
3. **模型**：可选模型的增、查、改、删 + **激活切换**。
   激活的那条在运行时覆盖 ``.env``（``llm.py`` 读库优先），
   这样换模型不用改配置、不用重启改代码 —— 运维场景下的关键诉求。

## 纪律

* **密钥不回显**：列表只给 ``has_key`` 布尔位，编辑时不返回明文密钥。
* **不允许删自己**、**不允许降级最后一个管理员**，避免把自己锁在门外。
* 删除操作都返回"影响了多少条"，让前端能如实告诉用户代价。
"""
from __future__ import annotations

from typing import Any

import config
import db

# 删除用户时需要级联清理的表（外键是 user_id / student_id / owner_id / teacher_id）
_CASCADE: list[tuple[str, str]] = [
    ("sessions", "user_id"),
    ("student_profiles", "user_id"),
    ("teacher_profiles", "user_id"),
    ("chat_messages", "user_id"),
    ("tasks", "student_id"),
    ("materials", "owner_id"),
    ("material_imports", "user_id"),
    ("artifacts", "user_id"),
    ("knowledge_points", "owner_id"),
    ("kp_mastery", "student_id"),
    ("course_grades", "student_id"),
    ("homework_submissions", "student_id"),
    ("resource_applications", "student_id"),
    ("prep_folders", "user_id"),
]


def _now() -> str:
    return db.now()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _str(value: Any, default: str = "") -> str:
    return default if value is None else str(value).strip()


# ================================================================ 概览
def overview() -> dict:
    """管理端首页：能一眼看清系统里有什么、跑在哪个模型上。"""
    counts = {}
    for label, sql in (
        ("students", "SELECT COUNT(*) FROM users WHERE role='student'"),
        ("teachers", "SELECT COUNT(*) FROM users WHERE role='teacher'"),
        ("admins", "SELECT COUNT(*) FROM users WHERE role='admin'"),
        ("materials", "SELECT COUNT(*) FROM materials"),
        ("knowledge_points", "SELECT COUNT(*) FROM knowledge_points"),
        ("homework", "SELECT COUNT(*) FROM homework"),
        ("submissions", "SELECT COUNT(*) FROM homework_submissions"),
        ("chats", "SELECT COUNT(*) FROM chat_messages"),
        ("models", "SELECT COUNT(*) FROM model_profiles"),
        ("classes", "SELECT COUNT(*) FROM classes"),
        ("operations", "SELECT COUNT(*) FROM admin_logs"),
        # 孤儿数据：看不见但会拖垮体验的东西，概览上要有一席之地
        ("orphan_knowledge_points", (
            "SELECT COUNT(*) FROM knowledge_points kp WHERE kp.material_id <> 0 AND NOT EXISTS "
            "(SELECT 1 FROM materials m WHERE m.id = kp.material_id)")),
    ):
        counts[label] = _int(db.scalar(sql, (), 0))
    active = active_model()
    import llm
    return {
        "counts": counts,
        "active_model": active,
        "runtime": {
            "llm_mode": config.LLM_MODE,
            "effective_model": (active or {}).get("model_id") or config.LLM_MODEL,
            "source": "database" if active else "env",
            "api_ready": llm.api_ready(),
            "last_error": llm.status().get("last_error") or "",
            "data_dir": str(config.DATA_DIR) if hasattr(config, "DATA_DIR") else "",
        },
    }


# ================================================================ 用户
def users(role: str = "", keyword: str = "", college: str = "",
          major: str = "", klass: str = "") -> list[dict]:
    """用户列表。``role`` 为空表示全部；``keyword`` 匹配用户名/姓名/班级。

    组织筛选（v7.29）：college / major / klass 分别按学院、专业、行政班过滤。
    教师与管理员没有行政班，组织筛选只会命中学生 —— 这是口径本身，不是漏人。
    """
    clause, args = "", []
    if role in ("student", "teacher", "admin"):
        clause += " AND u.role = ?"
        args.append(role)
    kw = _str(keyword)
    if kw:
        clause += " AND (u.username LIKE ? OR u.name LIKE ? OR u.class_id LIKE ? OR u.class_name LIKE ?)"
        args.extend([f"%{kw}%"] * 4)
    if klass:
        clause += " AND u.class_id = ?"
        args.append(klass)
    elif major:
        clause += (" AND u.class_id IN (SELECT c.code FROM classes c "
                   "JOIN majors m ON m.id = c.major_id WHERE m.code = ?)")
        args.append(major)
    elif college:
        clause += (" AND u.class_id IN (SELECT c.code FROM classes c "
                   "JOIN majors m ON m.id = c.major_id "
                   "JOIN colleges co ON co.id = m.college_id WHERE co.code = ?)")
        args.append(college)
    rows = db.query(
        "SELECT u.id, u.username, u.name, u.role, u.class_id, u.class_name, "
        "p.track, p.grade_level, p.gpa "
        "FROM users u LEFT JOIN student_profiles p ON p.user_id = u.id "
        "WHERE 1=1" + clause + " ORDER BY u.role, u.username",
        tuple(args),
    )
    out = []
    for r in rows:
        item = dict(r)
        item["track"] = item.get("track") or ""
        item["grade_level"] = item.get("grade_level") or ""
        out.append(item)
    return out


def create_user(payload: dict) -> dict:
    """新增用户。用户名唯一；学生可选填行政班/教学班。"""
    username = _str(payload.get("username"))
    role = _str(payload.get("role"), "student")
    name = _str(payload.get("name"), username)
    if not username:
        raise ValueError("用户名不能为空")
    if role not in ("student", "teacher", "admin"):
        raise ValueError("角色只能是 student / teacher / admin")
    if db.user_by_username(username):
        raise ValueError(f"用户名「{username}」已存在")
    password = _str(payload.get("password"), "123456")
    db.execute(
        "INSERT INTO users (username, pwd_hash, role, name, class_id, class_name) "
        "VALUES (?,?,?,?,?,?)",
        (username, db.hash_password(password), role, name,
         _str(payload.get("class_id")), _str(payload.get("class_name"))),
    )
    row = db.user_by_username(username) or {}
    if role == "student":
        # 学生必须有画像行，否则画像页与驾驶舱都会缺这个人
        db.execute(
            "INSERT OR IGNORE INTO student_profiles "
            "(user_id, track, grade_level, interests, ability, gpa, "
            " research_intent, job_intent, reason, engine) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (int(row.get("id") or 0), "学业型", "B", "[]", "{}",
             _int(payload.get("gpa"), 0) or 0.0, 3.0, 3.0, "管理员新建，尚未采集证据", "rule"),
        )
    return {"id": row.get("id"), "username": username, "role": role, "name": name}


def update_user(user_id: int, payload: dict) -> dict:
    """改用户：姓名、班级、（学生的）主标签与层次。用户名与角色不可改（避免孤儿引用）。"""
    row = db.query("SELECT * FROM users WHERE id = ?", (user_id,))
    if not row:
        raise ValueError("用户不存在")
    sets, args = [], []
    for key in ("name", "class_id", "class_name"):
        if key in payload:
            sets.append(f"{key} = ?")
            args.append(_str(payload.get(key)))
    if sets:
        args.append(user_id)
        db.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", tuple(args))
    if row[0].get("role") == "student":
        psets, pargs = [], []
        if payload.get("track") in ("学业型", "事业型"):
            psets.append("track = ?")
            pargs.append(payload["track"])
        if payload.get("grade_level") in ("A", "B", "C"):
            psets.append("grade_level = ?")
            pargs.append(payload["grade_level"])
        if "gpa" in payload:
            psets.append("gpa = ?")
            pargs.append(_int(payload.get("gpa"), 0))
        if psets:
            pargs.append(user_id)
            db.execute(
                "UPDATE student_profiles SET " + ", ".join(psets) + " WHERE user_id = ?",
                tuple(pargs),
            )
    return {"id": user_id, "updated": True}


def reset_password(user_id: int, password: str = "123456") -> dict:
    pwd = _str(password, "123456")
    if len(pwd) < 6:
        raise ValueError("密码至少 6 位")
    db.execute("UPDATE users SET pwd_hash = ? WHERE id = ?", (db.hash_password(pwd), user_id))
    # 强制重新登录：清掉该用户的会话，避免旧 token 继续可用
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return {"id": user_id, "reset": True}


def delete_user(user_id: int, operator_id: int = 0) -> dict:
    """删除用户并级联清理关联数据。不允许删自己。"""
    if operator_id and int(operator_id) == int(user_id):
        raise ValueError("不能删除当前登录的账号")
    row = db.query("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
    if not row:
        raise ValueError("用户不存在")
    username = row[0].get("username") or ""
    if str(row[0].get("role")) == "admin":
        left = _int(db.scalar("SELECT COUNT(*) FROM users WHERE role='admin'", (), 0))
        if left <= 1:
            raise ValueError("至少保留一个管理员账号")
    cleaned = 0
    for table, col in _CASCADE:
        try:
            cur = db.execute(f"DELETE FROM {table} WHERE {col} = ?", (user_id,))
            cleaned += int(getattr(cur, "rowcount", 0) or 0)
        except Exception:
            # 表可能不存在（老库），跳过即可，不让删人失败
            continue
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"id": user_id, "username": username, "cleaned_rows": cleaned}


# ================================================================ 知识库
def materials(keyword: str = "", owner: str = "", college: str = "",
              major: str = "", klass: str = "", media: str = "") -> list[dict]:
    """管理台资料列表。v7.29 修复：materials 表没有 title 列，标题就是 filename。"""
    clause, args = "", []
    kw = _str(keyword)
    if kw:
        clause += " AND (m.filename LIKE ? OR m.category LIKE ?)"
        args.extend([f"%{kw}%"] * 2)
    if owner:
        clause += " AND u.username = ?"
        args.append(owner)
    if college:
        clause += " AND m.college_code = ?"
        args.append(college)
    if major:
        clause += " AND m.major_code = ?"
        args.append(major)
    if klass:
        clause += " AND m.class_code = ?"
        args.append(klass)
    if media:
        clause += " AND m.media_type = ?"
        args.append(media)
    rows = db.query(
        "SELECT m.id, m.filename, m.kind, m.category, m.owner_id, m.shared, "
        "m.created_at, m.media_type, m.college_code, m.major_code, m.class_code, "
        "u.username AS owner, u.name AS owner_name "
        "FROM materials m LEFT JOIN users u ON u.id = m.owner_id "
        "WHERE 1=1" + clause + " ORDER BY m.id DESC LIMIT 300",
        tuple(args),
    )
    out = [dict(r) for r in rows]
    for r in out:  # 前端按 r.title || r.filename 渲染，历史字段名保持兼容
        r["title"] = r.get("filename") or ""
    return out


def update_material(material_id: int, payload: dict) -> dict:
    sets, args = [], []
    if "title" in payload:
        # 表里没有 title 列；「改名」落 filename（展示标题与文件名同源）
        sets.append("filename = ?")
        args.append(_str(payload.get("title")))
    if "category" in payload:
        sets.append("category = ?")
        args.append(_str(payload.get("category"), "未分类"))
    if payload.get("shared") is not None:
        sets.append("shared = ?")
        args.append(1 if payload.get("shared") else 0)
    if payload.get("media_type") is not None:
        media = _str(payload.get("media_type"))
        if media and media not in ("image", "doc", "slide"):
            raise ValueError("media_type 只能是 image / doc / slide")
        sets.append("media_type = ?")
        args.append(media)
    # 归属：给 class_code 就连带推导专业/学院（保持三级一致）；
    # 显式清空（空串）= 回到「不限范围，全员可见」；只给 college_code = 院级可见。
    if payload.get("class_code") is not None:
        klass = _str(payload.get("class_code"))
        if klass:
            from services import org  # 延迟导入避免环
            college, major, _ = org.chain_of_class(klass)
            if not major:
                raise ValueError(f"班级 {klass} 不在组织字典里，请先在「组织字典」中登记")
            sets.extend(["class_code = ?", "major_code = ?", "college_code = ?"])
            args.extend([klass, major, college])
        else:
            sets.extend(["class_code = ''", "major_code = ''", "college_code = ''"])
    elif payload.get("major_code") is not None:
        major = _str(payload.get("major_code"))
        sets.append("major_code = ?")
        args.append(major)
        if not major:
            sets.append("class_code = ''")
    elif payload.get("college_code") is not None:
        college = _str(payload.get("college_code"))
        sets.append("college_code = ?")
        args.append(college)
        if not college:
            sets.extend(["major_code = ''", "class_code = ''"])
    if not sets:
        raise ValueError("没有可更新的字段")
    args.append(material_id)
    db.execute(f"UPDATE materials SET {', '.join(sets)} WHERE id = ?", tuple(args))
    return {"id": material_id, "updated": True}


def delete_material(material_id: int) -> dict:
    row = db.query("SELECT id, filename, stored FROM materials WHERE id = ?", (material_id,))
    if not row:
        raise ValueError("资料不存在")
    db.execute("DELETE FROM material_imports WHERE material_id = ?", (material_id,))
    # 知识点若挂在这份资料下，一并清掉，避免留下无源证据
    kp = db.execute("DELETE FROM knowledge_points WHERE material_id = ?", (material_id,))
    db.execute("DELETE FROM materials WHERE id = ?", (material_id,))
    # 文件本体不在这里删 —— 磁盘文件由 material_file() 管，误删不可恢复
    return {"id": material_id, "title": row[0].get("filename") or "",
            "cleaned_kp": int(getattr(kp, "rowcount", 0) or 0)}


def knowledge_points(keyword: str = "", course: str = "", difficulty: str = "") -> dict:
    clause, args = "", []
    kw = _str(keyword)
    if kw:
        # 这张表没有 summary 列（说明写在 source_ref 里），别再查 summary
        clause += " AND (name LIKE ? OR source_ref LIKE ?)"
        args.extend([f"%{kw}%"] * 2)
    if course:
        clause += " AND course = ?"
        args.append(course)
    if difficulty:
        clause += " AND difficulty = ?"
        args.append(difficulty.upper()[:1])
    rows = db.query(
        "SELECT id, name, course, difficulty, keywords, source_ref, owner_id, material_id "
        "FROM knowledge_points WHERE 1=1" + clause +
        " ORDER BY id DESC LIMIT 300",
        tuple(args),
    )
    items = [dict(r) for r in rows]
    for item in items:
        item["keywords"] = db.jload(item.get("keywords"), [])
    # 统计（管理台可视化）：按课程 / 难度
    by_course: dict[str, int] = {}
    by_difficulty = {"A": 0, "B": 0, "C": 0}
    for r in db.query("SELECT course, difficulty FROM knowledge_points"):
        c = str(r.get("course") or "未分课程")
        by_course[c] = by_course.get(c, 0) + 1
        d = str(r.get("difficulty") or "B")
        by_difficulty[d if d in by_difficulty else "B"] += 1
    stats = {
        "total": int(db.scalar("SELECT COUNT(*) FROM knowledge_points", (), 0)),
        "by_course": sorted(
            [{"course": k, "count": v} for k, v in by_course.items()],
            key=lambda kv: -kv["count"]),
        "by_difficulty": by_difficulty,
    }
    return {"knowledge_points": items, "stats": stats}


def create_kp(payload: dict) -> dict:
    name = _str(payload.get("name"))
    if not name:
        raise ValueError("知识点名称不能为空")
    # v7.29 修复：原先 keywords / source_ref 两列的值写反了
    keywords = payload.get("keywords")
    if isinstance(keywords, str):
        keywords = [keywords] if keywords.strip() else []
    db.execute(
        "INSERT INTO knowledge_points "
        "(name, course, difficulty, keywords, source_ref, owner_id, material_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (name, _str(payload.get("course")), _str(payload.get("difficulty"), "B") or "B",
         db.jdump([str(k) for k in (keywords or [])][:6]),
         _str(payload.get("source_ref")) or f"{_str(payload.get('course'))}·{name}",
         _int(payload.get("owner_id"), 0), _int(payload.get("material_id"), 0)),
    )
    row = db.query("SELECT id FROM knowledge_points ORDER BY id DESC LIMIT 1")
    return {"id": (row[0]["id"] if row else 0), "name": name}


def update_kp(kp_id: int, payload: dict) -> dict:
    sets, args = [], []
    for key in ("name", "course", "difficulty", "source_ref"):
        if key in payload:
            sets.append(f"{key} = ?")
            args.append(_str(payload.get(key)))
    if not sets:
        raise ValueError("没有可更新的字段")
    args.append(kp_id)
    db.execute(f"UPDATE knowledge_points SET {', '.join(sets)} WHERE id = ?", tuple(args))
    return {"id": kp_id, "updated": True}


def delete_kp(kp_id: int) -> dict:
    row = db.query("SELECT id, name FROM knowledge_points WHERE id = ?", (kp_id,))
    if not row:
        raise ValueError("知识点不存在")
    db.execute("DELETE FROM kp_mastery WHERE kp_name = ?", (row[0].get("name") or "",))
    db.execute("DELETE FROM knowledge_points WHERE id = ?", (kp_id,))
    return {"id": kp_id, "name": row[0].get("name") or ""}


# ================================================================ 模型
def _model_view(row: dict) -> dict:
    """列表视图：**不返回密钥明文**，只给有没有配。"""
    return {
        "id": row.get("id"),
        "name": row.get("name") or "",
        "vendor": row.get("vendor") or "",
        "base_url": row.get("base_url") or "",
        "model_id": row.get("model_id") or "",
        "vision_model": row.get("vision_model") or "",
        "embed_model": row.get("embed_model") or "",
        "supports_images": bool(row.get("supports_images")),
        "is_active": bool(row.get("is_active")),
        "has_key": bool(row.get("api_key")),
        "note": row.get("note") or "",
        "updated_at": row.get("updated_at") or "",
    }


def models() -> list[dict]:
    rows = db.query(
        "SELECT * FROM model_profiles ORDER BY is_active DESC, id DESC")
    return [_model_view(dict(r)) for r in rows]


def active_model() -> dict | None:
    """当前激活的模型（供运行时覆盖 .env 用）。"""
    rows = db.query("SELECT * FROM model_profiles WHERE is_active=1 ORDER BY id DESC LIMIT 1")
    if not rows:
        return None
    row = dict(rows[0])
    row["has_key"] = bool(row.get("api_key"))
    return row


def create_model(payload: dict) -> dict:
    name = _str(payload.get("name"))
    if not name:
        raise ValueError("模型名称不能为空")
    is_active = 1 if payload.get("is_active") else 0
    if is_active:
        db.execute("UPDATE model_profiles SET is_active = 0")
    db.execute(
        "INSERT INTO model_profiles "
        "(name, vendor, base_url, api_key, model_id, vision_model, embed_model, "
        " supports_images, is_active, note, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (name, _str(payload.get("vendor")), _str(payload.get("base_url")),
         _str(payload.get("api_key")), _str(payload.get("model_id")),
         _str(payload.get("vision_model")), _str(payload.get("embed_model")),
         1 if payload.get("supports_images") else 0, is_active,
         _str(payload.get("note")), _now()),
    )
    row = db.query("SELECT id FROM model_profiles ORDER BY id DESC LIMIT 1")
    return {"id": (row[0]["id"] if row else 0), "name": name, "is_active": bool(is_active)}


def update_model(model_id: int, payload: dict) -> dict:
    row = db.query("SELECT * FROM model_profiles WHERE id = ?", (model_id,))
    if not row:
        raise ValueError("模型不存在")
    sets, args = [], []
    for key in ("name", "vendor", "base_url", "model_id", "vision_model",
                "embed_model", "note"):
        if key in payload:
            sets.append(f"{key} = ?")
            args.append(_str(payload.get(key)))
    # 密钥：传空字符串表示"不改动"，传非空才覆盖
    if payload.get("api_key"):
        sets.append("api_key = ?")
        args.append(_str(payload.get("api_key")))
    if payload.get("supports_images") is not None:
        sets.append("supports_images = ?")
        args.append(1 if payload.get("supports_images") else 0)
    if payload.get("is_active"):
        db.execute("UPDATE model_profiles SET is_active = 0")
        sets.append("is_active = ?")
        args.append(1)
    elif payload.get("is_active") is False:
        sets.append("is_active = ?")
        args.append(0)
    if not sets:
        raise ValueError("没有可更新的字段")
    sets.append("updated_at = ?")
    args.append(_now())
    args.append(model_id)
    db.execute(f"UPDATE model_profiles SET {', '.join(sets)} WHERE id = ?", tuple(args))
    return {"id": model_id, "updated": True}


def delete_model(model_id: int) -> dict:
    row = db.query("SELECT id, name, is_active FROM model_profiles WHERE id = ?", (model_id,))
    if not row:
        raise ValueError("模型不存在")
    db.execute("DELETE FROM model_profiles WHERE id = ?", (model_id,))
    return {"id": model_id, "name": row[0].get("name") or "",
            "was_active": bool(row[0].get("is_active"))}


def activate_model(model_id: int) -> dict:
    """激活某个模型（同时把其它模型置为未激活）。"""
    row = db.query("SELECT id, name FROM model_profiles WHERE id = ?", (model_id,))
    if not row:
        raise ValueError("模型不存在")
    db.execute("UPDATE model_profiles SET is_active = 0")
    db.execute("UPDATE model_profiles SET is_active = 1, updated_at = ? WHERE id = ?",
               (_now(), model_id))
    return {"id": model_id, "name": row[0].get("name") or "", "is_active": True}


def probe_model(model_id: int) -> dict:
    """连通性自检：用这个模型真的发一次最小请求，能回话才算通。"""
    row = db.query("SELECT * FROM model_profiles WHERE id = ?", (model_id,))
    if not row:
        raise ValueError("模型不存在")
    m = dict(row[0])
    if not (m.get("base_url") and m.get("api_key") and m.get("model_id")):
        return {"ok": False, "message": "地址 / 密钥 / 模型 id 不完整，无法连通测试"}
    try:
        import httpx
    except Exception:
        return {"ok": False, "message": "httpx 未安装"}
    try:
        with httpx.Client(timeout=30) as c:
            resp = c.post(
                f"{m['base_url'].rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {m['api_key']}",
                         "Content-Type": "application/json"},
                json={"model": m["model_id"],
                      "messages": [{"role": "user", "content": "请只回复两个字：正常"}],
                      "max_tokens": 16, "temperature": 0},
            )
        if resp.status_code >= 400:
            return {"ok": False, "message": f"HTTP {resp.status_code}: {resp.text[:160]}"}
        text = (((resp.json().get("choices") or [{}])[0]
                 .get("message") or {}).get("content") or "").strip()
        return {"ok": bool(text), "message": text[:60] or "模型返回空内容"}
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:160]}"}


# ================================================================ 教师任教班级
def teacher_classes_view() -> list[dict]:
    """教师 ↔ 任教班级。驾驶舱右上角的班级切换器读的就是这张表。"""
    teachers = db.query(
        "SELECT id, username, name, class_id FROM users WHERE role='teacher' ORDER BY username")
    links = db.query("SELECT teacher_id, class_id FROM teacher_classes")
    by_teacher: dict[int, list[str]] = {}
    for row in links:
        by_teacher.setdefault(int(row["teacher_id"]), []).append(str(row["class_id"]))
    out = []
    for t in teachers:
        classes = sorted(set(by_teacher.get(int(t["id"]), [])))
        out.append({
            "id": int(t["id"]),
            "username": t.get("username") or "",
            "name": t.get("name") or "",
            "class_id": str(t.get("class_id") or ""),   # users.class_id 是「主班」
            "classes": classes,
        })
    return out


def set_teacher_classes(teacher_id: int, class_ids: list[str]) -> dict:
    """重设某位教师的任教班级（全量替换）。

    * 教师本人必须存在且是 teacher 角色；
    * 班号必须在组织字典里（否则班级切换器会切到一个没有名字的班）；
    * 主班（users.class_id）不在任教清单里时自动并入，避免"人在主班却看不到自己班"。
    """
    teacher = db.query_one("SELECT * FROM users WHERE id = ? AND role = 'teacher'", (teacher_id,))
    if not teacher:
        raise ValueError("教师不存在或不是教师角色")
    codes: list[str] = []
    for raw in class_ids or []:
        code = _str(raw).strip()
        if code and code not in codes:
            codes.append(code)
    known = {str(r["code"]) for r in db.query("SELECT code FROM classes")}
    unknown = [c for c in codes if c not in known]
    if unknown:
        raise ValueError(f"班号不在组织字典里：{'、'.join(unknown)}（请先在「组织字典」登记）")
    main = _str(teacher.get("class_id"))
    if main and main not in codes:
        codes.append(main)
    with db.connect() as conn:
        conn.execute("DELETE FROM teacher_classes WHERE teacher_id = ?", (teacher_id,))
        conn.executemany(
            "INSERT INTO teacher_classes (teacher_id, class_id) VALUES (?,?)",
            [(teacher_id, c) for c in codes],
        )
    return {"id": teacher_id, "classes": codes}


# ================================================================ 操作日志
def logs(action: str = "", keyword: str = "", limit: int = 200) -> list[dict]:
    """管理端操作日志（新 → 旧）。``action`` 精确匹配，``keyword`` 模糊匹配对象/详情/操作人。"""
    clause, args = "", []
    act = _str(action)
    if act:
        clause += " AND action = ?"
        args.append(act)
    kw = _str(keyword)
    if kw:
        clause += " AND (username LIKE ? OR action LIKE ? OR target LIKE ? OR detail LIKE ?)"
        args.extend([f"%{kw}%"] * 4)
    rows = db.query(
        "SELECT id, user_id, username, action, target, detail, created_at FROM admin_logs "
        "WHERE 1=1" + clause + " ORDER BY id DESC LIMIT ?",
        tuple(args) + (max(int(limit), 1),),
    )
    return [dict(r) for r in rows]


def log_actions() -> list[str]:
    """已有操作类型（供筛选下拉用）。"""
    rows = db.query("SELECT DISTINCT action FROM admin_logs ORDER BY action")
    return [str(r.get("action") or "") for r in rows if r.get("action")]
