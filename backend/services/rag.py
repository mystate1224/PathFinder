# -*- coding: utf-8 -*-
"""rag.py —— 检索层：FTS5 入库与关键词召回。

## 为什么是 FTS5 + trigram

SQLite 默认的 ``unicode61`` 分词器对整段中文几乎无效（整句被当成一个 token），
只有 ``trigram`` 才能让中文**子串**可检索。建表失败时（老版本 SQLite）
整个模块自动降级为全表 ``LIKE`` 扫描，功能不丢、只是慢一些。

## search 的核心思路：自然问句 → 候选词

学生问的是"什么是注意力机制？"，而库里存的是"注意力机制的计算过程"。
直接把整句丢进检索会一句都命不中，所以要先把问句拆成**候选词**再逐个召回：

1. 标点切分后的片段；
2. 去掉疑问前缀（什么是 / 如何理解 / 怎么 / 为什么 …）后的片段；
3. 与已抽取**知识点名**有 3 字以上交集的概念名（课件里出现过的概念优先命中）。

长词优先（粒度更准），去重取前 6 个，每个候选词单独召回后合并去重。
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

import db

# 疑问前缀：剥掉之后剩下的才是"要找什么"
QUESTION_PREFIXES = [
    "请问一下", "请问", "我想知道", "我想问", "帮我看看", "帮我", "麻烦",
    "什么是", "是什么", "什么是叫", "何谓", "如何理解", "如何", "怎么理解",
    "怎么", "怎样", "为什么", "为何", "解释一下", "解释", "介绍一下", "介绍",
    "讲讲", "讲解", "说明一下", "说明", "能不能", "能否", "可以", "一下吧",
]

_SPLIT_RE = re.compile(r"[，。！？；：、,.!?;:\s（）()\[\]{}<>\"'“”‘’/\\|~`·—\-]+")


def _clean_term(term: str) -> str:
    term = (term or "").strip()
    for prefix in QUESTION_PREFIXES:
        if term.startswith(prefix):
            term = term[len(prefix):]
            break
    # 去掉尾部语气词与助词，避免"是什么"这类碎片进入召回
    term = re.sub(r"(呢|吗|啊|吧|的|了|呀|么)+$", "", term).strip()
    return term


def candidate_terms(query: str, limit: int = 6) -> list[str]:
    """自然问句 → 候选词（长词优先，去重）。"""
    query = (query or "").strip()
    if not query:
        return []

    pieces: list[str] = []
    for raw in _SPLIT_RE.split(query):
        raw = raw.strip()
        if not raw:
            continue
        pieces.append(raw)
        stripped = _clean_term(raw)
        if stripped and stripped != raw:
            pieces.append(stripped)

    # 与知识点名做 3 字以上交集的概念名，优先级最高
    kp_concepts: list[str] = []
    for row in db.query("SELECT DISTINCT name FROM knowledge_points WHERE name <> '' LIMIT 500"):
        name = str(row.get("name") or "").strip()
        if len(name) < 2:
            continue
        for gram in _ngrams(name, 3):
            if gram in query:
                kp_concepts.append(name)
                break

    ordered: list[str] = []
    for term in kp_concepts + pieces:
        term = term.strip()
        if len(term) < 2 or term in ordered:
            continue
        # 纯标点/纯数字的碎片丢掉
        if not re.search(r"[0-9A-Za-z\u4e00-\u9fa5]", term):
            continue
        ordered.append(term)

    ordered.sort(key=len, reverse=True)
    return ordered[: max(1, limit)]


def _ngrams(text: str, n: int) -> Iterable[str]:
    if len(text) < n:
        return []
    return [text[i: i + n] for i in range(len(text) - n + 1)]


def _fts_quote(term: str) -> str:
    """FTS5 字符串字面量：内部双引号需要转义成两个双引号。"""
    return '"' + term.replace('"', '""') + '"'


# ================================================================ 可见范围（用户数据隔离）
def search_scope(owner_id: int, teacher: bool = False, prefix: str = "",
                 id_col: str = "material_id") -> tuple[str, list]:
    """检索 / 知识点查询的**可见范围**子句（纯数据权限，与分层无关）。

    * 学生 → 自己上传的资料 + **已导入**的教师公用资料（``material_imports``）；
      同学之间互不可见：成绩单、简历是私人材料，绝不能出现在别人的检索结果里。
    * 教师 → 自己 + 全部教师上传的公用资料（公用池本就是教师共建的）。

    ``prefix`` 用于带表别名的列（如 ``kp.owner_id``）；``id_col`` 是"资料 id 列"的名字 ——
    分块表 / 知识点表叫 ``material_id``，而 ``materials`` 表主键就叫 ``id``，别写错。
    返回 ``(clause, args)``，clause 以 `` AND `` 开头，可直接拼在 WHERE 之后。
    """
    owner_id = int(owner_id or 0)
    if not owner_id:  # 0 = 不指定（自检 / 兼容旧调用）→ 不做过滤
        return "", []
    # 容错：调用方写 "kp" 还是 "kp." 都接受，别拼出 "kpowner_id" 这种列名。
    if prefix and not prefix.endswith("."):
        prefix += "."
    if teacher:
        clause = (
            f" AND ({prefix}owner_id = ? OR {prefix}owner_id IN "
            "(SELECT id FROM users WHERE role = 'teacher'))"
        )
        return clause, [owner_id]
    clause = (
        f" AND ({prefix}owner_id = ? OR {prefix}{id_col} IN "
        "(SELECT material_id FROM material_imports WHERE user_id = ?))"
    )
    return clause, [owner_id, owner_id]


def visible_material_ids(owner_id: int, teacher: bool = False) -> set[int]:
    """可见材料 id 集合（向量路内存过滤用）。``owner_id`` 为 0 时返回空集表示不过滤。"""
    if not owner_id:
        return set()
    # materials 表的主键是 id，不是 material_id —— 这里必须显式指定，否则会报 no such column。
    clause, args = search_scope(owner_id, teacher, id_col="id")
    rows = db.query("SELECT id FROM materials WHERE 1=1" + clause, tuple(args))
    return {int(r["id"]) for r in rows}


# ================================================================ 入库
def index_material(
    material_id: int,
    owner_id: int,
    course: str,
    filename: str,
    text: str,
) -> int:
    """建/重建一份材料的全文索引。先删旧片段再写新 = 增量替换。返回切片数。"""
    from services import extract  # 延迟导入，避免与 extract 形成模块级循环

    chunks = extract.split_chunks(text, size=None, overlap=None)
    filename = filename or "未命名"
    course = course or ""

    with db.connect() as conn:
        conn.execute("DELETE FROM kb_fts WHERE material_id = ?", (material_id,))
        if db.FTS_OK and chunks:
            conn.executemany(
                "INSERT INTO kb_fts (material_id, chunk_index, owner_id, course, filename, content) "
                "VALUES (?,?,?,?,?,?)",
                [
                    (material_id, idx, owner_id, course, filename, chunk)
                    for idx, chunk in enumerate(chunks)
                ],
            )
    return len(chunks)


def drop_material(material_id: int) -> None:
    """删除一份材料的全部索引（全文 + 向量 + 导入记录）。"""
    with db.connect() as conn:
        try:
            conn.execute("DELETE FROM kb_fts WHERE material_id = ?", (material_id,))
        except Exception:
            pass
        conn.execute("DELETE FROM kb_vec WHERE material_id = ?", (material_id,))
        try:
            conn.execute("DELETE FROM material_imports WHERE material_id = ?", (material_id,))
        except Exception:
            pass  # 老库还没升级出该表时忽略


# ================================================================ 召回
def _recall_one(term: str, top_k: int, course: str,
                owner_id: int = 0, teacher: bool = False) -> list[dict]:
    """单个候选词召回。``len>=3`` 走 FTS5，否则/无结果降级 LIKE。

    ``owner_id`` 非零时按用户隔离：只召回可见范围内的片段。
    """
    rows: list[dict] = []
    scope_clause, scope_args = search_scope(owner_id, teacher)

    if db.FTS_OK and len(term) >= 3:
        sql = (
            "SELECT material_id, chunk_index, owner_id, course, filename, content, "
            "bm25(kb_fts) AS rank_score FROM kb_fts "
            "WHERE kb_fts MATCH ?"
        )
        args: list = [f"content : {_fts_quote(term)}"]
        if course:
            sql += " AND course = ?"
            args.append(course)
        sql += scope_clause
        args.extend(scope_args)
        sql += " ORDER BY rank_score LIMIT ?"
        args.append(top_k)
        try:
            rows = db.query(sql, tuple(args))
        except Exception:
            rows = []

    if not rows:
        # 降级：LIKE 全表扫（trigram 不可用、或词太短、或 FTS 语法异常）
        sql = (
            "SELECT material_id, chunk_index, owner_id, course, filename, content, 0 AS rank_score "
            "FROM kb_fts WHERE content LIKE ?"
        )
        args = [f"%{term}%"]
        if course:
            sql += " AND course = ?"
            args.append(course)
        sql += scope_clause
        args.extend(scope_args)
        sql += " LIMIT ?"
        args.append(top_k)
        try:
            rows = db.query(sql, tuple(args))
        except Exception:
            rows = []

    for row in rows:
        row["term"] = term
        row["ref"] = f"{row.get('filename') or '未命名'}#{row.get('chunk_index')}"
    return rows


def search(query: str, top_k: int = 8, course: str = "",
           owner_id: int = 0, teacher: bool = False) -> list[dict]:
    """关键词路召回。返回带 ``ref``（``文件名#分片号``）的片段列表。

    ``owner_id`` 非零时按用户隔离（学生 = 自己 + 已导入的公用资料）。
    """
    seen: set[tuple] = set()
    merged: list[dict] = []
    for term in candidate_terms(query):
        for row in _recall_one(term, top_k, course, owner_id, teacher):
            key = (row.get("material_id"), row.get("chunk_index"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
            if len(merged) >= top_k * 2:
                break
        if len(merged) >= top_k * 2:
            break
    return merged


def stats(owner_id: int | None = None) -> dict:
    """知识库规模统计（资料库页顶部用）。"""
    if owner_id:
        materials = db.scalar("SELECT COUNT(*) FROM materials WHERE owner_id = ?", (owner_id,), 0)
        points = db.scalar("SELECT COUNT(*) FROM knowledge_points WHERE owner_id = ?", (owner_id,), 0)
    else:
        materials = db.scalar("SELECT COUNT(*) FROM materials", (), 0)
        points = db.scalar("SELECT COUNT(*) FROM knowledge_points", (), 0)
    chunks = 0
    try:
        chunks = db.scalar("SELECT COUNT(*) FROM kb_fts", (), 0)
    except Exception:
        chunks = 0
    return {
        "materials": materials,
        "knowledge_points": points,
        "chunks": chunks,
        "vectors": db.scalar("SELECT COUNT(*) FROM kb_vec", (), 0),
        "fts_ok": db.FTS_OK,
    }
