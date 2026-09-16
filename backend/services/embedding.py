# -*- coding: utf-8 -*-
"""embedding.py —— 向量化（真实 embeddings / 本地哈希降级）。

## 为什么要有降级

语义检索是"锦上添花"，不能变成"没它就演示不了"。所以：

* 配了 Key → 走真实 ``/embeddings``；
* 没配 / 报错 → **字符 3-gram 加权哈希向量**（1024 维）。

哈希向量的语义泛化能力弱于真模型，但能捕获字面重合与相近写法，
保证整条检索链路在任何环境都能跑通、可演示。两种向量的 ``dim`` 一起存库，
检索时按维度匹配，混用也不会算错。
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Iterable, Sequence

import db
import llm

DIM = 1024
N_GRAM = 3


# ================================================================ 本地哈希向量
def hash_vector(text: str, dim: int = DIM) -> list[float]:
    """字符 3-gram → md5 取前 8 位 → 分桶累加 → L2 归一化。纯标准库。"""
    raw = (text or "").strip().lower()
    vec = [0.0] * dim
    if not raw:
        return vec

    if len(raw) >= N_GRAM:
        grams = [raw[i: i + N_GRAM] for i in range(len(raw) - N_GRAM + 1)]
    else:
        grams = [raw]

    for gram in grams:
        digest = hashlib.md5(gram.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % dim
        vec[bucket] += 1.0

    return l2_normalize(vec)


def l2_normalize(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(v) * float(v) for v in vec))
    if norm <= 0:
        return [0.0] * len(vec)
    return [round(float(v) / norm, 6) for v in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """纯 Python 余弦相似度（语料是课件级别，百条量级，无需 numpy）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    na = math.sqrt(sum(float(x) * float(x) for x in a))
    nb = math.sqrt(sum(float(y) * float(y) for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


# ================================================================ 对外
def embed_texts(texts: Iterable[str]) -> tuple[list[list[float]], str]:
    """批量向量化。返回 ``(向量列表, engine)``，engine ∈ {llm, hash}。"""
    items = [str(t or "") for t in texts]
    if not items:
        return [], "hash"

    real, engine = llm.embed(items)
    if real:
        return [l2_normalize(v) for v in real], "llm"
    return [hash_vector(t) for t in items], "hash"


def embed_one(text: str) -> tuple[list[float], str]:
    vectors, engine = embed_texts([text])
    return (vectors[0] if vectors else hash_vector(text)), engine


def vector_engine_label(engine: str) -> str:
    return {"llm": "语义向量（模型）", "hash": "语义向量（本地哈希降级）"}.get(engine, engine)


# ================================================================ 索引读写
def index_vectors(material_id: int, chunks: Sequence[str]) -> str:
    """把切片向量写入 ``kb_vec``（先删后写，增量 = 替换）。"""
    if not chunks:
        return "hash"
    vectors, engine = embed_texts(chunks)
    with db.connect() as conn:
        conn.execute("DELETE FROM kb_vec WHERE material_id = ?", (material_id,))
        conn.executemany(
            "INSERT INTO kb_vec (material_id, chunk_index, dim, vector) VALUES (?,?,?,?)",
            [
                (material_id, idx, len(vec), json.dumps(vec, separators=(",", ":")))
                for idx, vec in enumerate(vectors)
            ],
        )
    return engine


def load_vectors(material_ids: Sequence[int] | None = None) -> list[dict]:
    """载入向量。返回 ``[{material_id, chunk_index, dim, vector}]``。"""
    if material_ids:
        marks = ",".join("?" for _ in material_ids)
        rows = db.query(
            f"SELECT material_id, chunk_index, dim, vector FROM kb_vec "
            f"WHERE material_id IN ({marks})",
            tuple(material_ids),
        )
    else:
        rows = db.query("SELECT material_id, chunk_index, dim, vector FROM kb_vec")
    for row in rows:
        row["vector"] = db.jload(row.get("vector"), [])
    return rows


def drop_vectors(material_id: int) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM kb_vec WHERE material_id = ?", (material_id,))
