# -*- coding: utf-8 -*-
"""db.py —— 数据层。

职责边界（很重要）：
* 只做三件事：**建表 / 通用读写 / 鉴权基础设施（密码、会话）**。
* 任何业务规则都不许写在这里，一律放 ``services/``。
* 每次调用新建 SQLite 连接（建连极廉价），天然适配多线程与 uvicorn 工作进程。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

import config

# FTS5 是否可用：建表失败（老版本 SQLite）时由 rag.py 降级为全表 LIKE 扫描
FTS_OK = False


# ================================================================ 连接
def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def query(sql: str, args: Sequence[Any] = ()) -> list[dict]:
    """查多行，返回 list[dict]。"""
    with connect() as conn:  # with 只负责 commit/rollback，不关闭连接
        rows = conn.execute(sql, tuple(args)).fetchall()
    return [dict(r) for r in rows]


def query_one(sql: str, args: Sequence[Any] = ()) -> dict | None:
    with connect() as conn:
        row = conn.execute(sql, tuple(args)).fetchone()
    return dict(row) if row else None


def scalar(sql: str, args: Sequence[Any] = (), default: Any = None) -> Any:
    with connect() as conn:
        row = conn.execute(sql, tuple(args)).fetchone()
    if row is None or row[0] is None:
        return default
    return row[0]


def execute(sql: str, args: Sequence[Any] = ()) -> int:
    """写一行，返回 lastrowid。"""
    with connect() as conn:
        cur = conn.execute(sql, tuple(args))
        return int(cur.lastrowid or 0)


def execute_many(sql: str, rows: Iterable[Sequence[Any]]) -> int:
    rows = [tuple(r) for r in rows]
    if not rows:
        return 0
    with connect() as conn:
        cur = conn.executemany(sql, rows)
        return int(cur.rowcount or 0)


def run_script(sql: str) -> None:
    with connect() as conn:
        conn.executescript(sql)


def jload(value: Any, default: Any = None) -> Any:
    """安全解析 JSON 文本列；已经是 list/dict 就原样返回。"""
    if default is None:
        default = []
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return default
    return default if parsed is None else parsed


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ================================================================ 建表
_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL UNIQUE,
    pwd_hash   TEXT NOT NULL,
    role       TEXT NOT NULL,            -- teacher | student
    name       TEXT NOT NULL DEFAULT '',
    class_id   TEXT NOT NULL DEFAULT '', -- 行政班（班级总览用）
    class_name TEXT NOT NULL DEFAULT ''  -- 教学班（作业分发用）
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS student_profiles (
    user_id     INTEGER PRIMARY KEY,
    track       TEXT NOT NULL DEFAULT '',   -- 学业型 | 事业型
    grade_level TEXT NOT NULL DEFAULT 'B',  -- A | B | C
    interests   TEXT NOT NULL DEFAULT '[]',
    ability     TEXT NOT NULL DEFAULT '{}',
    gpa         REAL NOT NULL DEFAULT 0,
    research_intent REAL NOT NULL DEFAULT 3, -- 1~5，学生自评的科研倾向
    job_intent      REAL NOT NULL DEFAULT 3, -- 1~5，学生自评的就业倾向
    reason      TEXT NOT NULL DEFAULT '',
    engine      TEXT NOT NULL DEFAULT 'rule'
);

CREATE TABLE IF NOT EXISTS teacher_profiles (
    user_id    INTEGER PRIMARY KEY,
    directions TEXT NOT NULL DEFAULT '[]',
    expertise  TEXT NOT NULL DEFAULT '[]',
    projects   TEXT NOT NULL DEFAULT '[]',
    summary    TEXT NOT NULL DEFAULT ''
);

-- 任教班级：一位教师可以带多个行政班（驾驶舱据此切换）。
-- users.class_id 仍是「主班」，这里只是可查看范围。
CREATE TABLE IF NOT EXISTS teacher_classes (
    teacher_id INTEGER NOT NULL,
    class_id   TEXT NOT NULL,
    PRIMARY KEY (teacher_id, class_id)
);

CREATE TABLE IF NOT EXISTS materials (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id  INTEGER NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'courseware',
    category  TEXT NOT NULL DEFAULT '未分类',
    filename  TEXT NOT NULL DEFAULT '',
    stored    TEXT NOT NULL DEFAULT '',   -- 落盘后的相对路径
    raw_text  TEXT NOT NULL DEFAULT '',
    parsed    TEXT NOT NULL DEFAULT '{}',
    engine    TEXT NOT NULL DEFAULT 'rule',
    created_at TEXT NOT NULL DEFAULT '',
    shared    INTEGER NOT NULL DEFAULT 1     -- 教师资料默认进「教师共享」池；0 = 仅自己可见
);

CREATE TABLE IF NOT EXISTS knowledge_points (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL DEFAULT 0,
    owner_id    INTEGER NOT NULL DEFAULT 0,
    course      TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL DEFAULT '',
    difficulty  TEXT NOT NULL DEFAULT 'B',  -- A | B | C（内容深度建议，不用于分班）
    keywords    TEXT NOT NULL DEFAULT '[]',
    source_ref  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kb_vec (
    material_id INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL,
    dim         INTEGER NOT NULL DEFAULT 0,
    vector      TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (material_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS research_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id  INTEGER NOT NULL,
    name        TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT '科研课题组',
    directions  TEXT NOT NULL DEFAULT '[]',
    requirement TEXT NOT NULL DEFAULT '',
    capacity    INTEGER NOT NULL DEFAULT 3
);

CREATE TABLE IF NOT EXISTS match_records (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     INTEGER NOT NULL,
    group_id       INTEGER NOT NULL,
    teacher_id     INTEGER NOT NULL DEFAULT 0,
    score          REAL NOT NULL DEFAULT 0,
    reason         TEXT NOT NULL DEFAULT '',
    teacher_action TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | declined
    student_action TEXT NOT NULL DEFAULT 'pending',
    created_at     TEXT NOT NULL DEFAULT '',
    UNIQUE (student_id, group_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    teacher_id INTEGER NOT NULL DEFAULT 0,
    type       TEXT NOT NULL DEFAULT 'todo',
    title      TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'todo',   -- todo | doing | done
    progress   INTEGER NOT NULL DEFAULT 0,
    due_date   TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    scene      TEXT NOT NULL DEFAULT 'tutor',  -- tutor | copilot | agent
    role       TEXT NOT NULL DEFAULT 'user',   -- user | assistant
    content    TEXT NOT NULL DEFAULT '',
    refs       TEXT NOT NULL DEFAULT '[]',
    layer      TEXT NOT NULL DEFAULT '',
    engine     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS teacher_resources (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    rtype      TEXT NOT NULL DEFAULT 'group', -- group | contest | internship | project
    title      TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '[]',
    capacity   INTEGER NOT NULL DEFAULT 0,    -- 0 = 不限
    deadline   TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'open',  -- open | closed
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS resource_applications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id   INTEGER NOT NULL,
    student_id    INTEGER NOT NULL,
    message       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending', -- pending | accepted | declined
    teacher_reply TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT '',
    UNIQUE (resource_id, student_id)
);

CREATE TABLE IF NOT EXISTS homework (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    course     TEXT NOT NULL DEFAULT '',
    class_name TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '',
    full_score REAL NOT NULL DEFAULT 100,
    deadline   TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'open',  -- open | closed（停止提交）
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS homework_submissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    homework_id INTEGER NOT NULL,
    student_id  INTEGER NOT NULL,
    content     TEXT NOT NULL DEFAULT '',
    files       TEXT NOT NULL DEFAULT '[]',
    score       REAL NOT NULL DEFAULT -1,     -- -1 = 未批改
    level       TEXT NOT NULL DEFAULT '',
    comment     TEXT NOT NULL DEFAULT '',
    attempt     INTEGER NOT NULL DEFAULT 1,   -- 第几次提交（留痕）
    late        INTEGER NOT NULL DEFAULT 0,   -- 是否逾期提交
    submitted_at TEXT NOT NULL DEFAULT '',
    graded_at   TEXT NOT NULL DEFAULT '',
    UNIQUE (homework_id, student_id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'md',    -- pptx | docx | md | lesson | slides
    title      TEXT NOT NULL DEFAULT '',
    course     TEXT NOT NULL DEFAULT '',
    file_path  TEXT NOT NULL DEFAULT '',
    content    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    folder     TEXT NOT NULL DEFAULT '',      -- 备课文件夹名，'' = 未归档
    material_id INTEGER NOT NULL DEFAULT 0    -- 同步存进资料库的那条记录，0 = 没存
);

CREATE TABLE IF NOT EXISTS kp_mastery (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  INTEGER NOT NULL,
    kp_name     TEXT NOT NULL DEFAULT '',
    course      TEXT NOT NULL DEFAULT '',
    mastery     REAL NOT NULL DEFAULT 0,      -- 0~1
    evidence    TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT '',
    UNIQUE (student_id, kp_name)
);

-- 备课文件夹：教师可以**先建好空文件夹**再把产物移进去，所以文件夹不能只靠
-- artifacts.folder 分组推导（空的就推导不出来），必须单独登记一条。
CREATE TABLE IF NOT EXISTS prep_folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    UNIQUE (user_id, name)
);

-- 资料导入记录：学生把「教师上传的公用资料」导入自己的检索库。
-- 数据隔离的关键 —— 学生默认只检索自己的资料，公用资料必须显式导入才进入范围；
-- 不复制正文，只记引用，删除资料时级联清理。
CREATE TABLE IF NOT EXISTS material_imports (
    user_id     INTEGER NOT NULL,
    material_id INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, material_id)
);
"""

# 索引：把最常用的过滤/连接列都建上
_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_kp_mat ON knowledge_points(material_id)",
    "CREATE INDEX IF NOT EXISTS idx_kp_owner ON knowledge_points(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_mat_owner ON materials(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_messages(user_id, scene, id)",
    "CREATE INDEX IF NOT EXISTS idx_task_stu ON tasks(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_res_teacher ON teacher_resources(teacher_id)",
    "CREATE INDEX IF NOT EXISTS idx_app_res ON resource_applications(resource_id)",
    "CREATE INDEX IF NOT EXISTS idx_app_stu ON resource_applications(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_hw_teacher ON homework(teacher_id)",
    "CREATE INDEX IF NOT EXISTS idx_hw_class ON homework(class_name)",
    "CREATE INDEX IF NOT EXISTS idx_sub_hw ON homework_submissions(homework_id)",
    "CREATE INDEX IF NOT EXISTS idx_sub_stu ON homework_submissions(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_imp_user ON material_imports(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_prep_folder ON prep_folders(user_id)",
]

# 表 -> 后补列（老库平滑升级用）
_COLUMN_UPGRADES: dict[str, list[tuple[str, str]]] = {
    "users": [("class_name", "TEXT NOT NULL DEFAULT ''")],
    "student_profiles": [
        ("research_intent", "REAL NOT NULL DEFAULT 3"),
        ("job_intent", "REAL NOT NULL DEFAULT 3"),
    ],
    "materials": [
        ("category", "TEXT NOT NULL DEFAULT '未分类'"),
        ("stored", "TEXT NOT NULL DEFAULT ''"),
        ("engine", "TEXT NOT NULL DEFAULT 'rule'"),
        # v7.18：一键备课生成的 PPT 存进课件库但**不进**教师共享池（那是教师的私人备课产物）
        ("shared", "INTEGER NOT NULL DEFAULT 1"),
    ],
    "knowledge_points": [("owner_id", "INTEGER NOT NULL DEFAULT 0")],
    "homework": [("status", "TEXT NOT NULL DEFAULT 'open'")],
    # 备课产物归档：教案与 PPT 可以归到同一个备课文件夹里，空串 = 未归档。
    # v7.18：PPT 会同步存一份进资料库「课件」，material_id 记住是哪一条，改大纲后好覆盖。
    "artifacts": [("folder", "TEXT NOT NULL DEFAULT ''"),
                  ("material_id", "INTEGER NOT NULL DEFAULT 0")],
    "homework_submissions": [
        ("attempt", "INTEGER NOT NULL DEFAULT 1"),
        ("late", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "chat_messages": [
        ("scene", "TEXT NOT NULL DEFAULT 'tutor'"),
        # 会话：支持「新开对话 / 回到某一次对话」。老数据 session_id 为空串，
        # 界面归到「早期对话」，不强行拆散。
        ("session_id", "TEXT NOT NULL DEFAULT ''"),
    ],
    # 团队类型：老师带的不只是科研课题组，还有横向项目、竞赛队、实习组。
    # 老库补列时靠 DEFAULT 回填为「科研课题组」（历史数据全是科研组）。
    "research_groups": [("kind", "TEXT NOT NULL DEFAULT '科研课题组'")],
}


def init_db() -> None:
    """建表 + 建索引 + 补列 + 建 FTS5 虚拟表。幂等，可反复调用。"""
    global FTS_OK
    with connect() as conn:
        conn.executescript(_SCHEMA)
        for stmt in _INDEXES:
            try:
                conn.execute(stmt)
            except sqlite3.Error:
                pass

        # 补列：ALTER TABLE ADD COLUMN 在老库上补齐新增字段
        for table, cols in _COLUMN_UPGRADES.items():
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols:
                if col not in existing:
                    try:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                    except sqlite3.Error:
                        pass

        # 教学班回填：老库只有 class_id 时，用行政班兜底，保证作业能分发
        try:
            conn.execute(
                "UPDATE users SET class_name = class_id "
                "WHERE role='student' AND (class_name IS NULL OR class_name='') AND class_id <> ''"
            )
        except sqlite3.Error:
            pass

        # 团队类型回填：更早的库没有 kind 列，补列后若是空串一律按「科研课题组」归位，
        # 否则前端会显示出一个没有类型的空徽章。字典与 matcher.GROUP_KINDS 保持一致。
        try:
            conn.execute(
                "UPDATE research_groups SET kind = '科研课题组' "
                "WHERE kind IS NULL OR TRIM(kind) = ''"
            )
        except sqlite3.Error:
            pass

    # FTS5 独立 try/except：不支持 trigram 分词器时整条检索链降级为 LIKE
    try:
        with connect() as conn:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5("
                "material_id UNINDEXED, chunk_index UNINDEXED, owner_id UNINDEXED, "
                "course, filename, content, tokenize='trigram')"
            )
        FTS_OK = True
    except sqlite3.Error as exc:  # pragma: no cover
        print(f"[db] FTS5 不可用，检索将降级为 LIKE 扫描：{exc}")
        FTS_OK = False


# ================================================================ 密码
PBKDF2_ROUNDS = 100_000


def hash_password(password: str) -> str:
    """pbkdf2_hmac('sha256', salt, 100_000)，返回 ``salt$hash``。绝不存明文。"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, digest = stored.split("$", 1)
    try:
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS
        )
    except (TypeError, ValueError):
        return False
    return secrets.compare_digest(dk.hex(), digest)


# ================================================================ 会话
# 两种 token 并存：
# * ``v2.<uid>.<过期时间戳>.<HMAC 签名>`` —— 自包含，服务端不存也能验，
#   专为无服务器平台（Vercel）设计：实例之间不共享 /tmp，存在库里的会话
#   会「换一个实例就掉线」。签名用的是 config.SECRET_KEY，所有实例共享。
# * 旧的纯随机 token —— 仅为了兼容本地已有的会话记录，仍走查库。
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    return hmac.new(
        config.SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]


def make_session_token(user_id: int, days: int) -> str:
    """生成自包含签名 token（不依赖数据库即可校验）。"""
    exp_ts = int(time.time()) + max(int(days), 1) * 24 * 3600
    payload = f"{int(user_id)}.{exp_ts}"
    return f"v2.{payload}.{_sign(payload)}"


def parse_session_token(token: str) -> tuple[int, int] | None:
    """校验签名并返回 ``(user_id, 过期时间戳)``；格式/签名不对返回 None。"""
    parts = (token or "").split(".")
    if len(parts) != 4 or parts[0] != "v2":
        return None
    payload = f"{parts[1]}.{parts[2]}"
    if not secrets.compare_digest(parts[3], _sign(payload)):
        return None
    try:
        return int(parts[1]), int(parts[2])
    except (TypeError, ValueError):
        return None


def create_session(user_id: int, days: int | None = None) -> str:
    days = config.SESSION_DAYS if days is None else days
    token = make_session_token(user_id, days)
    expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with connect() as conn:
            # 顺手清理过期会话，避免表无限膨胀
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
                (token, user_id, expires),
            )
    except sqlite3.Error:
        # 库不可写时不影响登录：签名 token 本身已经自足
        pass
    return token


def session_user(token: str | None) -> dict | None:
    """用 token 换用户；过期即返回 None。

    先按签名自校验（跨实例、冷启动都稳），失败再回退查库（兼容旧 token）。
    """
    if not token:
        return None

    parsed = parse_session_token(token)
    if parsed is not None:
        user_id, exp_ts = parsed
        if exp_ts < int(time.time()):
            return None
        try:
            row = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
        except sqlite3.Error:
            return None
        if not row:
            return None
        row.pop("pwd_hash", None)
        row["token"] = token
        row["expires_at"] = datetime.fromtimestamp(exp_ts).strftime("%Y-%m-%d %H:%M:%S")
        return row

    row = query_one(
        "SELECT s.token, s.expires_at, u.* FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token = ?",
        (token,),
    )
    if not row:
        return None
    if str(row.get("expires_at") or "") < now():
        delete_session(token)
        return None
    row.pop("pwd_hash", None)
    return row


def delete_session(token: str | None) -> None:
    if not token:
        return
    try:
        with connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    except sqlite3.Error:
        pass


# ================================================================ 便捷读取
def user_by_username(username: str) -> dict | None:
    return query_one("SELECT * FROM users WHERE username = ?", (username,))


def user_by_id(user_id: int) -> dict | None:
    return query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def student_profile(user_id: int) -> dict | None:
    row = query_one("SELECT * FROM student_profiles WHERE user_id = ?", (user_id,))
    if row:
        row["interests"] = jload(row.get("interests"), [])
        row["ability"] = jload(row.get("ability"), {})
    return row


def teacher_profile(user_id: int) -> dict | None:
    row = query_one("SELECT * FROM teacher_profiles WHERE user_id = ?", (user_id,))
    if row:
        row["directions"] = jload(row.get("directions"), [])
        row["expertise"] = jload(row.get("expertise"), [])
        row["projects"] = jload(row.get("projects"), [])
    return row


def students_of_class(class_name: str = "", class_id: str = "") -> list[dict]:
    """按教学班优先、其次行政班取学生名单。"""
    if class_name:
        return query(
            "SELECT * FROM users WHERE role='student' AND class_name = ? ORDER BY username",
            (class_name,),
        )
    if class_id:
        return query(
            "SELECT * FROM users WHERE role='student' AND class_id = ? ORDER BY username",
            (class_id,),
        )
    return query("SELECT * FROM users WHERE role='student' ORDER BY username")


def all_students() -> list[dict]:
    return query("SELECT * FROM users WHERE role='student' ORDER BY username")


def log_chat(user_id: int, role: str, content: str, refs: Any = None,
             scene: str = "tutor", layer: str = "", engine: str = "",
             session_id: str = "") -> int:
    return execute(
        "INSERT INTO chat_messages (user_id, scene, role, content, refs, layer, engine, session_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, scene, role, content, jdump(refs or []), layer, engine, session_id, now()),
    )


def chat_sessions(user_id: int, scene: str, limit: int = 30) -> list[dict]:
    """会话列表：按 session_id 聚合，取每会话的第一问做标题。空 session_id 归为「早期对话」。"""
    return query(
        "SELECT session_id, COUNT(*) AS turns, MAX(created_at) AS last_at, "
        "MIN(id) AS first_id "
        "FROM chat_messages WHERE user_id = ? AND scene = ? "
        "GROUP BY session_id ORDER BY last_at DESC LIMIT ?",
        (user_id, scene, limit),
    )


def first_question(user_id: int, scene: str, session_id: str) -> str:
    row = query(
        "SELECT content FROM chat_messages "
        "WHERE user_id = ? AND scene = ? AND session_id = ? AND role = 'user' "
        "ORDER BY id ASC LIMIT 1",
        (user_id, scene, session_id),
    )
    return str(row[0]["content"]) if row else ""


def recent_chat(user_id: int, scene: str = "tutor", turns: int = 4) -> list[dict]:
    """最近 N 轮对话（一问一答算一轮），按时间正序返回。"""
    limit = max(1, turns) * 2
    rows = query(
        "SELECT * FROM chat_messages WHERE user_id = ? AND scene = ? "
        "ORDER BY id DESC LIMIT ?",
        (user_id, scene, limit),
    )
    rows.reverse()
    for r in rows:
        r["refs"] = jload(r.get("refs"), [])
    return rows


def health_snapshot() -> dict:
    tables = [
        "users", "sessions", "student_profiles", "teacher_profiles", "teacher_classes",
        "materials",
        "knowledge_points", "kb_vec", "research_groups", "match_records", "tasks",
        "chat_messages", "teacher_resources", "resource_applications", "homework",
        "homework_submissions", "artifacts", "kp_mastery",
    ]
    counts = {}
    for t in tables:
        try:
            counts[t] = scalar(f"SELECT COUNT(*) FROM {t}", (), 0)
        except sqlite3.Error:
            counts[t] = -1
    try:
        counts["kb_fts"] = scalar("SELECT COUNT(*) FROM kb_fts", (), 0)
    except sqlite3.Error:
        counts["kb_fts"] = -1
    return {"fts_ok": FTS_OK, "counts": counts, "db": str(config.DB_PATH)}


_ = time  # 保留 time 供后续扩展（缓存/限流）
