# -*- coding: utf-8 -*-
"""ops.py —— 管理端运维：数据体检 / 重建检索索引 / 重算画像 / 清理孤儿数据。

为什么要把这些放进管理端：演示与运维里最容易出问题的，恰恰是**看不见的东西** ——
索引没建起来（检索永远空）、知识点挂在没有正文的材料上（答疑证据失效）、
上传文件被误删而库里还有记录（点「打开」必然 404）。这些都不会报错，只会"看起来能用"。
所以体检要给出可判定的数字，修复动作要一键完成、并如实汇报影响了多少条。
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import config
import db

# 重建索引的重入锁：两个 reindex 并发跑会交错 DELETE/INSERT，把索引打花。
_REINDEX_LOCK = threading.Lock()

# 孤儿判定：知识点/导入记录/索引片段 指向了已经不存在的资料
_ORPHAN_KP = (
    "SELECT COUNT(*) FROM knowledge_points kp WHERE kp.material_id <> 0 "
    "AND NOT EXISTS (SELECT 1 FROM materials m WHERE m.id = kp.material_id)"
)


def _dir_size(path: Path) -> tuple[int, int]:
    """目录占用：返回 ``(字节数, 文件数)``。目录不存在返回 (0, 0)。"""
    total, count = 0, 0
    if not path.exists():
        return 0, 0
    for root, _dirs, files in os.walk(str(path)):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
                count += 1
            except OSError:
                continue
    return total, count


def _mb(size: float) -> float:
    return round(size / 1024 / 1024, 2)


def health() -> dict:
    """一份可判定的体检报告：索引、孤儿数据、磁盘、活跃度。"""
    materials = int(db.scalar("SELECT COUNT(*) FROM materials", (), 0))
    knowledge = int(db.scalar("SELECT COUNT(*) FROM knowledge_points", (), 0))

    # ---- 索引
    try:
        fts_chunks = int(db.scalar("SELECT COUNT(*) FROM kb_fts", (), 0)) if db.FTS_OK else -1
    except Exception:  # noqa: BLE001 - FTS 表不可用时如实标记
        fts_chunks = -1
    vec_chunks = int(db.scalar("SELECT COUNT(*) FROM kb_vec", (), 0))
    indexed_materials = int(db.scalar(
        "SELECT COUNT(DISTINCT material_id) FROM kb_fts", (), 0)) if db.FTS_OK else 0
    try:
        orphan_fts = int(db.scalar(
            "SELECT COUNT(*) FROM kb_fts f WHERE NOT EXISTS "
            "(SELECT 1 FROM materials m WHERE m.id = f.material_id)", (), 0)) if db.FTS_OK else 0
    except Exception:  # noqa: BLE001
        orphan_fts = 0
    orphan_vec = int(db.scalar(
        "SELECT COUNT(*) FROM kb_vec v WHERE NOT EXISTS "
        "(SELECT 1 FROM materials m WHERE m.id = v.material_id)", (), 0))
    # 有正文却没进索引 = 检索会漏；这是"看起来能用"的头号原因
    try:
        unindexed = int(db.scalar(
            "SELECT COUNT(*) FROM materials m WHERE TRIM(COALESCE(m.raw_text, '')) <> '' "
            "AND NOT EXISTS (SELECT 1 FROM kb_fts f WHERE f.material_id = m.id)", (), 0)) if db.FTS_OK else 0
    except Exception:  # noqa: BLE001
        unindexed = 0

    # ---- 孤儿数据
    orphan_kp = int(db.scalar(_ORPHAN_KP, (), 0))
    orphan_imports = int(db.scalar(
        "SELECT COUNT(*) FROM material_imports mi WHERE NOT EXISTS "
        "(SELECT 1 FROM materials m WHERE m.id = mi.material_id)", (), 0))

    # ---- 落盘文件缺失（逐个 stat，资料量不大，够用且不做任何删除动作）
    missing_files = 0
    for row in db.query("SELECT id, stored FROM materials WHERE stored <> ''"):
        path = config.DATA_DIR / str(row.get("stored") or "")
        if not path.exists():
            missing_files += 1

    # ---- 磁盘
    up_size, up_n = _dir_size(config.UPLOAD_DIR)
    ex_size, ex_n = _dir_size(config.EXPORT_DIR)
    try:
        db_size = os.path.getsize(str(config.DB_PATH))
    except OSError:
        db_size = 0

    # ---- 活跃度（近 7 天）
    def recent(table: str, col: str = "created_at") -> int:
        try:
            return int(db.scalar(
                f"SELECT COUNT(*) FROM {table} WHERE {col} >= date('now','-7 days')", (), 0))
        except Exception:  # noqa: BLE001 - 老表可能没有该列
            return 0

    engine_rows = db.query("SELECT engine, COUNT(*) AS n FROM chat_messages GROUP BY engine")
    engines = {str(r.get("engine") or "rule"): int(r["n"]) for r in engine_rows}

    return {
        "counts": {
            "materials": materials,
            "knowledge_points": knowledge,
            "students": int(db.scalar("SELECT COUNT(*) FROM users WHERE role='student'", (), 0)),
            "teachers": int(db.scalar("SELECT COUNT(*) FROM users WHERE role='teacher'", (), 0)),
        },
        "index": {
            "fts_ok": bool(db.FTS_OK),
            "fts_chunks": fts_chunks,
            "vec_chunks": vec_chunks,
            "indexed_materials": indexed_materials,
            "materials": materials,
            "unindexed": unindexed,
            "orphan_fts": orphan_fts,
            "orphan_vec": orphan_vec,
        },
        "orphans": {
            "knowledge_points": orphan_kp,
            "imports": orphan_imports,
            "missing_files": missing_files,
        },
        "disk": {
            "uploads_mb": _mb(up_size), "uploads_files": up_n,
            "exports_mb": _mb(ex_size), "exports_files": ex_n,
            "database_mb": _mb(db_size),
            "data_dir": str(config.DATA_DIR),
        },
        "activity": {
            "chats_7d": recent("chat_messages"),
            "submissions_7d": recent("homework_submissions", "submitted_at"),
            "materials_7d": recent("materials"),
            "engines": engines,
        },
    }


def reindex() -> dict:
    """重建全部资料的检索索引（全文 + 向量）。先删后写 = 幂等，可反复点。

    带重入锁：已在执行中时直接返回 ``busy``，绝不并发跑（并发会交错删插，
    把索引打花 —— 这是实测踩过的坑）。
    """
    from services import embedding, extract, rag  # 延迟导入避免与它们形成模块级循环

    if not _REINDEX_LOCK.acquire(blocking=False):
        return {"busy": True, "message": "已有一次重建正在进行，请等它结束"}

    try:
        rows = db.query("SELECT id, owner_id, filename, raw_text FROM materials ORDER BY id")
        chunks_total, vectors_total = 0, 0
        for row in rows:
            mid = int(row["id"])
            text = str(row.get("raw_text") or "")
            course = extract.course_from_filename(str(row.get("filename") or ""))
            chunks = extract.split_chunks(text)
            chunks_total += rag.index_material(mid, int(row.get("owner_id") or 0),
                                              course, str(row.get("filename") or ""), text)
            if chunks:
                embedding.index_vectors(mid, chunks)
                vectors_total += 1
        return {"materials": len(rows), "fts_chunks": chunks_total, "vectors": vectors_total}
    finally:
        _REINDEX_LOCK.release()


def recompute(limit: int = 500) -> dict:
    """重算全体学生画像（六维 v2 + 掌握度）。与线上同一条链路，不是另写一套。"""
    from services import dashboard, stratify  # 延迟导入避免循环

    students = db.query(
        "SELECT id FROM users WHERE role='student' ORDER BY id LIMIT ?", (max(int(limit), 1),))
    done, failed = 0, 0
    for row in students:
        uid = int(row["id"])
        try:
            prof = db.student_profile(uid) or {}
            v2, _engine = stratify.recompute_profile(uid, prev_track=str(prof.get("track_v2") or ""))
            db.execute(
                "UPDATE student_profiles SET ability_v2=?, ability_conf=?, track_v2=?, level_v2=? "
                "WHERE user_id=?",
                (db.jdump(v2.get("dims") or {}), db.jdump(v2.get("conf_dims") or {}),
                 v2.get("track", ""), v2.get("level", ""), uid),
            )
            dashboard.recompute_mastery(uid)
            done += 1
        except Exception:  # noqa: BLE001 - 单个学生算不出来不该中断整批
            failed += 1
    return {"students": len(students), "recomputed": done, "failed": failed}


def cleanup() -> dict:
    """清理孤儿数据：无源的知识点、失效的导入记录、没有资料可指的索引片段。

    **不动磁盘文件**，也**不动资料本身** —— 删除资料是有代价的操作，只由管理端显式发起。
    """
    with db.connect() as conn:
        kp = conn.execute(
            "DELETE FROM knowledge_points WHERE material_id <> 0 AND NOT EXISTS "
            "(SELECT 1 FROM materials m WHERE m.id = knowledge_points.material_id)").rowcount
        imp = conn.execute(
            "DELETE FROM material_imports WHERE NOT EXISTS "
            "(SELECT 1 FROM materials m WHERE m.id = material_imports.material_id)").rowcount
        vec = conn.execute(
            "DELETE FROM kb_vec WHERE NOT EXISTS "
            "(SELECT 1 FROM materials m WHERE m.id = kb_vec.material_id)").rowcount
        fts = 0
        if db.FTS_OK:
            try:
                fts = conn.execute(
                    "DELETE FROM kb_fts WHERE NOT EXISTS "
                    "(SELECT 1 FROM materials m WHERE m.id = kb_fts.material_id)").rowcount
            except Exception:  # noqa: BLE001 - FTS 表可能不可用
                fts = 0
    return {
        "knowledge_points": int(kp or 0), "imports": int(imp or 0),
        "kb_vec": int(vec or 0), "kb_fts": int(fts or 0),
    }
