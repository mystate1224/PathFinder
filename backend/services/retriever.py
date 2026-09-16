# -*- coding: utf-8 -*-
"""retriever.py —— 混合检索：BM25 + 向量 + RRF + 重排。

三层，**任何一层都能独立降级**（守住"断网可演示"底线）：

1. **召回**：关键词路 ``rag.search``（FTS5/BM25） + 语义路 ``vector_search``（向量余弦）；
2. **混排 RRF**：``score += 1/(k + rank + 1)``，``k=60``。按**排名**融合而不是按分数，
   天然规避了 BM25 分与余弦分量纲不一致的问题，非常稳健；
3. **重排**：模型可用时让模型对前 N 条按相关度排序；否则走启发式——
   查询词覆盖率优先，融合分次之。

对外唯一入口 ``hybrid_search(query, top_k=5, course="")``。
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

import config
import db
import llm
from services import embedding, rag

# 常见疑问词，用于启发式重排时计算"覆盖度"
_STOPWORDS = {"什么是", "是什么", "如何", "怎么", "为什么", "请问", "解释", "的", "了", "吗", "呢"}


def _material_map() -> dict[int, dict]:
    """材料元信息。``materials`` 表**没有** course 列 —— 课程由文件名推导，
    所以这里统一走 ``extract.course_from_filename``，保证与索引时写入的口径一致。
    """
    from services import extract  # 局部导入：避免模块级循环依赖

    rows = db.query("SELECT id, filename, kind, category, owner_id FROM materials")
    for row in rows:
        row["course"] = extract.course_from_filename(str(row.get("filename") or ""))
    return {int(r["id"]): r for r in rows}


def _course_of(material: dict | None, fallback: str = "") -> str:
    if not material:
        return fallback
    return str(material.get("course") or fallback or "")


# ================================================================ 语义路
def vector_search(query: str, top_k: int = 8, course: str = "") -> list[dict]:
    """向量召回。向量缺失或维度不匹配时静默返回空列表（交由关键词路兜底）。"""
    query_vec, _engine = embedding.embed_one(query)
    if not query_vec:
        return []

    rows = embedding.load_vectors()
    if not rows:
        return []

    materials = _material_map()
    scored: list[dict] = []
    for row in rows:
        vector = row.get("vector") or []
        if len(vector) != len(query_vec):
            continue  # 索引时的向量模型与现在不同，跳过而不是算错
        score = embedding.cosine(query_vec, vector)
        if score <= 0:
            continue
        material_id = int(row.get("material_id") or 0)
        material = materials.get(material_id)
        if course and _course_of(material) != course:
            continue
        scored.append(
            {
                "material_id": material_id,
                "chunk_index": int(row.get("chunk_index") or 0),
                "owner_id": 0,
                "course": _course_of(material),
                "filename": (material or {}).get("filename") or "未命名",
                "content": _chunk_text(material_id, int(row.get("chunk_index") or 0)),
                "vec_score": round(float(score), 6),
            }
        )

    scored.sort(key=lambda r: r["vec_score"], reverse=True)
    for row in scored:
        row["ref"] = f"{row['filename']}#{row['chunk_index']}"
    return scored[:top_k]


def _chunk_text(material_id: int, chunk_index: int) -> str:
    """按 (material_id, chunk_index) 取回切片正文（向量表不存正文，从 FTS 表取）。"""
    try:
        row = db.query_one(
            "SELECT content FROM kb_fts WHERE material_id = ? AND chunk_index = ? LIMIT 1",
            (material_id, chunk_index),
        )
    except Exception:
        row = None
    if row and row.get("content"):
        return str(row["content"])
    # FTS 不可用时退回材料正文（截取一段，保证有内容可展示）
    row = db.query_one("SELECT raw_text FROM materials WHERE id = ?", (material_id,))
    text = str((row or {}).get("raw_text") or "")
    start = chunk_index * config.CHUNK_SIZE
    return text[start: start + config.CHUNK_SIZE * 2]


# ================================================================ RRF 融合
def _rrf_merge(groups: Sequence[Sequence[dict]], k: int = None) -> list[dict]:
    k = config.RRF_K if k is None else k
    fused: dict[tuple, dict] = {}
    for group in groups:
        for rank, row in enumerate(group):
            key = (row.get("material_id"), row.get("chunk_index"))
            bucket = fused.setdefault(
                key,
                {
                    "material_id": row.get("material_id"),
                    "chunk_index": row.get("chunk_index"),
                    "course": row.get("course"),
                    "filename": row.get("filename"),
                    "content": row.get("content") or "",
                    "ref": row.get("ref"),
                    "fused_score": 0.0,
                    "via": [],
                },
            )
            bucket["fused_score"] += 1.0 / (k + rank + 1)
            bucket["via"].append("vec" if "vec_score" in row else "bm25")
            if not bucket.get("content") and row.get("content"):
                bucket["content"] = row["content"]
            if not bucket.get("ref") and row.get("ref"):
                bucket["ref"] = row["ref"]

    items = list(fused.values())
    for item in items:
        item["fused_score"] = round(item["fused_score"], 6)
        item["via"] = "+".join(sorted(set(item["via"])))
    items.sort(key=lambda r: r["fused_score"], reverse=True)
    return items


# ================================================================ 重排
def _query_terms(query: str) -> list[str]:
    """把问句拆成用于覆盖度统计的词。

    中文没有空格，整句当成一个词会让覆盖度恒为 0、重排失效。
    所以这里做三层拆解：候选词（复用 rag 的口径）→ 去疑问词后的片段 → 2-gram。
    """
    terms: list[str] = []
    for term in rag.candidate_terms(query, limit=6):
        if term not in _STOPWORDS and len(term) >= 2:
            terms.append(term)

    for seg in re.split(r"[^\w\u4e00-\u9fa5]+", query or ""):
        if not seg or seg in _STOPWORDS:
            continue
        clean = re.sub(r"(什么是|是什么|如何|怎么|为什么|请问|解释|的|了|吗|呢|请)", "", seg)
        if len(clean) >= 2:
            terms.append(clean)
        if len(clean) >= 4:  # 长片段补 2-gram，保证覆盖度有区分度
            terms.extend(clean[i:i + 2] for i in range(len(clean) - 1))

    return [t for t in dict.fromkeys(terms) if len(t) >= 2 and t not in _STOPWORDS][:12]


def _heuristic_rerank(query: str, items: list[dict], top_k: int) -> list[dict]:
    """启发式重排：查询词覆盖度优先（长词权重更高），融合分次之。"""
    terms = _query_terms(query)
    for item in items:
        content = str(item.get("content") or "")
        item["coverage"] = sum(len(t) for t in terms if t in content)
        item["_key"] = (item["coverage"], item.get("fused_score") or 0.0)
    items.sort(key=lambda r: r["_key"], reverse=True)
    for item in items:
        item.pop("_key", None)
    return items[:top_k]


def _llm_rerank(query: str, items: list[dict], top_k: int) -> list[dict] | None:
    if not llm.api_ready() or len(items) < 2:
        return None
    preview = "\n".join(
        f"[{i + 1}] {str(item.get('content') or '')[:180]}" for i, item in enumerate(items[:8])
    )
    prompt = (
        f"学生的问题：{query}\n\n以下是候选资料片段：\n{preview}\n\n"
        "请按与问题的相关度从高到低排序，只返回被选中的片段序号。"
    )
    result, engine = llm.chat_json(
        [{"role": "user", "content": prompt}],
        '{"order":[2,1,3]}',
        mock=None,
    )
    if engine != "llm":
        return None
    order = result.get("order") if isinstance(result, dict) else None
    if not isinstance(order, list) or not order:
        return None
    picked: list[dict] = []
    used: set[int] = set()
    for raw in order:
        try:
            idx = int(raw) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(items) and idx not in used:
            used.add(idx)
            picked.append(items[idx])
    if not picked:
        return None
    # 模型没排到的补在后面，保证结果数量不缩水
    for idx, item in enumerate(items):
        if idx not in used and len(picked) < top_k:
            picked.append(item)
    return picked[:top_k]


# ================================================================ 对外
def hybrid_search(query: str, top_k: int = 5, course: str = "") -> list[dict]:
    """混合检索唯一入口。返回带 ``fused_score`` 与 ``via``（``bm25``/``vec``/``bm25+vec``）。"""
    query = (query or "").strip()
    if not query:
        return []

    keyword_hits = rag.search(query, top_k=8, course=course)
    vector_hits = vector_search(query, top_k=8, course=course)

    if not keyword_hits and not vector_hits:
        return []

    fused = _rrf_merge([keyword_hits, vector_hits])
    if not fused:
        return []

    reranked = _llm_rerank(query, fused, top_k) or _heuristic_rerank(query, fused, top_k)
    for rank, item in enumerate(reranked):
        item["rank"] = rank
    return reranked


def context_block(items: Iterable[dict], max_chars: int = 2600) -> str:
    """把检索结果拼成给模型的参考资料块，并保留编号用于引用。"""
    lines: list[str] = []
    used = 0
    for i, item in enumerate(items, 1):
        text = str(item.get("content") or "").strip().replace("\n", " ")
        if not text:
            continue
        snippet = text[:600]
        piece = f"[{i}] 来源：{item.get('ref')}\n{snippet}"
        if used + len(piece) > max_chars:
            break
        lines.append(piece)
        used += len(piece)
    return "\n\n".join(lines)
