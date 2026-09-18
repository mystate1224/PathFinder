# -*- coding: utf-8 -*-
"""parsekit.py —— 能力①「图文智能解析」的可执行契约。

把一句口号拆成四个**可实现、可验证**的问题：

1. **解析什么（INPUT）**
   载体：md / txt / csv / pdf / docx / pptx 的文本层；png / jpg 的图像层（走视觉模型）。
   元素：标题层级、正文段落、列表项、表格、代码块、公式、图片与其说明文字、页眉页脚。

2. **输出什么（OUTPUT）**：``ParseResult``，见 :func:`parse_document` 的返回说明。
   一句话：**原文可回溯**（每个切片都带 block_id），**去杂可审计**（每条规则命中数）。

3. **如何去杂（DENOISE）**：:data:`NOISE_RULES` 是一张**可增删的规则表**，
   每条规则独立开关、独立计数，命中情况随结果一起返回，界面上能直接看到
   「这条规则去掉了多少字符」。

4. **整理成什么信息（STRUCTURE）**：
   噪声清洗 → 版面分块 ``blocks`` → 素材登记 ``assets`` → 语义切片 ``chunks``
   （按标题边界优先、句边界兜底）→ 大纲 ``outline``。
   下游三件事吃同一份结构：知识点抽取吃 blocks + outline，
   检索入库吃 chunks，答疑引用吃 chunks（带 block_id 可回溯到原文位置）。

本模块是**纯函数**：不碰数据库、不碰网络，规则版与 LLM 版共用同一套契约。
"""
from __future__ import annotations

import re
from typing import Any

# ================================================================ ① 解析什么
PARSE_INPUTS: dict[str, Any] = {
    "carriers": [
        {"ext": "md/txt/csv", "layer": "文本层", "reader": "read_text 多编码探测"},
        {"ext": "pdf", "layer": "文本层（pypdf，前 40 页）", "reader": "read_text"},
        {"ext": "docx/pptx", "layer": "OOXML 文本层", "reader": "_read_ooxml"},
        {"ext": "png/jpg", "layer": "图像层", "reader": "llm.vision（未配视觉模型则显式降级）"},
    ],
    "elements": [
        {"type": "heading", "desc": "标题层级（markdown # / 第N章 / 数字编号）"},
        {"type": "paragraph", "desc": "正文段落"},
        {"type": "list", "desc": "列表项（- * · 1. 1)）"},
        {"type": "table", "desc": "表格（管道表 / 制表符表）"},
        {"type": "code", "desc": "代码块与示例输入"},
        {"type": "formula", "desc": "公式与推导行"},
        {"type": "image", "desc": "图片及其说明文字（图注）"},
        {"type": "quote", "desc": "引用块（> ）"},
    ],
}

# ================================================================ ③ 如何去杂
# 每条规则：id / name / why（为什么要去掉）/ test（判定函数）。
# 规则表是**数据**，加一条去杂规则只需往这里 append，不用改流程代码。
_RE_PAGE = re.compile(
    r"^\s*(?:第\s*\d{1,4}\s*页|第?\s*\d{1,4}\s*/\s*共?\s*\d{1,4}\s*页?|"
    r"page\s*\d+(?:\s*/\s*\d+)?|[-—–.\s]{0,3}\d{1,4}[-—–.\s]{0,3})\s*$", re.I
)
_RE_WATERMARK = re.compile(r"内部资料|仅供|机密|保密|样章|试读|试用版|请勿外传|水印|草稿")
_RE_TOC = re.compile(r"^.{2,40}?[.．·•]{3,}\s*\d{1,4}\s*$")
_RE_NAV = re.compile(r"^\s*(上一页|下一页|返回目录|回到顶部|目录\s*\|?\s*|\.{3,})\s*$")
_RE_URL = re.compile(r"^\s*(?:https?://|www\.)\S+\s*$", re.I)
_RE_QR = re.compile(r"扫码|二维码|长按识别|关注公众号")
_RE_CTRL = re.compile('[\\u0000-\\u0008\\u000b\\u000c\\u000e-\\u001f]')
_RE_GARBLE = re.compile(r"([^\s.·…\-—_])\1{8,}|[▓▒░█□■]{3,}")
_RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_RE_HEADING_CN = re.compile(r"^第\s*[一二三四五六七八九十\d]+\s*[章节讲篇部分]\s*(.*)$")
_RE_HEADING_NUM = re.compile(r"^\d{1,2}(?:[.\-]\d{1,2}){0,3}[.\-、]?\s+\S{1,40}$")
_RE_LIST = re.compile(r"^\s*(?:[-*·•]|\d{1,2}[.、)]|[（(]\d{1,2}[）)]|[一二三四五六七八九十]+[、.])\s+\S")
_RE_QUOTE = re.compile(r"^\s*>\s?")
_RE_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)|<img\b[^>]*>", re.I)
_RE_FORMULA = re.compile(r"\$\$?[^$]+\$\$?|\\\[.*?\\]|∑|∏|∫|≈|≤|≥|→|⇒|∈|⊂|√(.*?)|θ|α|β|λ|∇")
_RE_TABLE = re.compile(r"\|.*\||\t")


def _looks_like_page_number(line: str) -> bool:
    """纯页码 / 页脚计数。"""
    stripped = line.strip()
    if not stripped or len(stripped) > 12:
        return False
    if not _RE_PAGE.match(stripped):
        return False
    # 形如 "3.2 梯度下降" 的编号标题不是页码：必须整行只有数字与分隔符
    return bool(re.fullmatch(r"[第页page/\s\-—–.0-9]{1,12}", stripped, re.I))


NOISE_RULES: list[dict[str, Any]] = [
    {
        "id": "ctrl", "name": "控制字符与扫描乱码", "enabled": True,
        "why": "PDF 文本层与 OCR 常见产物，会污染切分与向量",
        "test": lambda line: bool(_RE_CTRL.search(line)) or bool(_RE_GARBLE.search(line)),
    },
    {
        "id": "page_number", "name": "纯页码行", "enabled": True,
        "why": "页码没有语义，进入切片会稀释检索密度",
        "test": _looks_like_page_number,
    },
    {
        "id": "watermark", "name": "水印与密级字样", "enabled": True,
        "why": "「内部资料 / 样章」会被误当成正文本体，影响摘要与知识点抽取",
        "test": lambda line: bool(_RE_WATERMARK.search(line)) and len(line.strip()) <= 40,
    },
    {
        "id": "toc", "name": "目录点线行", "enabled": True,
        "why": "目录是重复的标题列表，抽知识点时会产生大量同名噪声",
        "test": lambda line: bool(_RE_TOC.match(line.strip())),
    },
    {
        "id": "nav", "name": "导航残留", "enabled": True,
        "why": "「上一页 / 返回目录」是网页导出 PDF 的残留",
        "test": lambda line: bool(_RE_NAV.match(line)),
    },
    {
        "id": "url", "name": "纯链接与二维码提示", "enabled": True,
        "why": "链接会被切成碎片进入向量库，检索价值接近 0",
        "test": lambda line: bool(_RE_URL.match(line)) or bool(_RE_QR.search(line)) and len(line.strip()) <= 30,
    },
    {
        "id": "dup_line", "name": "重复行（≥3 次）", "enabled": True,
        "why": "页眉页脚不一定有固定格式，用「高频重复」兜底识别，保留首次出现",
        "test": None,  # 需要全文频次，由 denoise 单独处理
    },
    {
        "id": "blank", "name": "连续空行", "enabled": True,
        "why": "压缩为单空行，避免切分时被当成段落边界",
        "test": lambda line: not line.strip(),
    },
    {
        "id": "short_frag", "name": "过短碎片", "enabled": True,
        "why": "≤2 字且不是标题/列表的行，多为换行断裂残渣",
        "test": lambda line: 0 < len(line.strip()) <= 2,
    },
]


def denoise(text: str, rules: list[dict[str, Any]] | None = None) -> tuple[str, dict]:
    """去杂。返回 ``(清洗后文本, 去杂报告)``。

    报告结构：``{removed_lines, removed_chars, ratio, rules:[{id,name,why,hits,chars}]}``。
    规则可整体关闭：传入自定义 ``rules`` 即可（演示时用来对比「开/关某条规则的差异」）。
    """
    active = [r for r in (rules or NOISE_RULES) if r.get("enabled", True)]
    raw_lines = (text or "").splitlines()
    freq: dict[str, int] = {}
    for line in raw_lines:
        key = line.strip()
        if len(key) >= 6:
            freq[key] = freq.get(key, 0) + 1

    seen: set[str] = set()
    hits = {r["id"]: {"hits": 0, "chars": 0} for r in active}
    kept: list[str] = []
    removed_chars = 0
    removed_lines = 0

    prev_blank = False
    for line in raw_lines:
        stripped = line.strip()
        # 空行单独处理：连续空行只保留一个，段落之间的"一次空行"是结构，必须留下
        if not stripped:
            if prev_blank:
                removed_chars += len(line)
                removed_lines += 1
                hits["blank"]["hits"] += 1
                hits["blank"]["chars"] += len(line)
            else:
                kept.append(line)
            prev_blank = True
            continue
        prev_blank = False
        dropped_by = ""
        for rule in active:
            if rule["id"] in ("blank", "dup_line"):
                if len(stripped) >= 6 and freq.get(stripped, 0) >= 3:
                    if stripped in seen:
                        dropped_by = "dup_line"
                        break
                continue
            test = rule.get("test")
            if test and test(line):
                dropped_by = rule["id"]
                break
        if dropped_by:
            removed_chars += len(line)
            removed_lines += 1
            hits[dropped_by]["hits"] += 1
            hits[dropped_by]["chars"] += len(line)
        else:
            if stripped:
                seen.add(stripped)
            kept.append(line)

    # 首尾空行去掉；中间的空行已在上面按"连续只留一个"处理
    after = "\n".join(kept).strip()
    before_chars = len(text or "")
    report = {
        "removed_lines": removed_lines,
        "removed_chars": removed_chars,
        "before_chars": before_chars,
        "after_chars": len(after),
        "ratio": round(removed_chars / before_chars, 4) if before_chars else 0.0,
        "rules": [
            {"id": r["id"], "name": r["name"], "why": r["why"],
             "hits": hits[r["id"]]["hits"], "chars": hits[r["id"]]["chars"]}
            for r in active
        ],
    }
    return after, report


# ================================================================ ④ 整理成什么信息
def heading_level(line: str) -> int:
    """判定标题层级，非标题返回 0。"""
    stripped = line.strip()
    if not stripped or len(stripped) > 60:
        return 0
    m = _RE_HEADING.match(stripped)
    if m:
        return len(m.group(1))
    if _RE_HEADING_CN.match(stripped):
        return 2
    if _RE_HEADING_NUM.match(stripped) and not _RE_LIST.match(stripped):
        return 3
    return 0


def to_blocks(text: str) -> list[dict]:
    """版面分块。每个块带 ``id / type / level / text / order``，是后续一切结构的原子。"""
    blocks: list[dict] = []
    lines = (text or "").splitlines()
    index = 0
    fence = False
    buffer: list[str] = []
    buf_type = "paragraph"

    def flush() -> None:
        nonlocal buffer, buf_type, index
        body = "\n".join(buffer).strip()
        if body:
            index += 1
            blocks.append({
                "id": f"b{index}",
                "type": buf_type,
                "level": heading_level(buffer[0]) if buf_type == "heading" else 0,
                "text": body,
                "order": index,
            })
        buffer = []

    for line in lines:
        if line.strip().startswith("```"):
            flush()
            fence = not fence
            buf_type = "code"
            continue
        if fence:
            buffer.append(line)
            continue
        stripped = line.strip()
        if not stripped:
            flush()
            buf_type = "paragraph"
            continue
        level = heading_level(stripped)
        if level:
            flush()
            buf_type = "heading"
            buffer = [stripped]
            flush()
            buf_type = "paragraph"
            continue
        kind = "paragraph"
        if _RE_QUOTE.match(line):
            kind = "quote"
        elif _RE_LIST.match(line):
            kind = "list"
        elif _RE_TABLE.search(line) and line.count("|") >= 2:
            kind = "table"
        elif _RE_FORMULA.search(line):
            kind = "formula"
        elif _RE_IMAGE.search(line):
            kind = "image"
        if kind != buf_type:
            flush()
            buf_type = kind
        buffer.append(line)
    flush()
    return blocks


def to_assets(blocks: list[dict]) -> list[dict]:
    """素材登记：把表格 / 代码 / 公式 / 图片从正文里单拎出来，避免被切碎。"""
    assets: list[dict] = []
    for block in blocks:
        if block["type"] in ("table", "code", "formula", "image"):
            caption = ""
            if block["type"] == "image":
                m = _RE_IMAGE.search(block["text"])
                caption = (m.group(1) if m and m.groups() else "") or block["text"][:40]
            assets.append({
                "id": f"a{len(assets) + 1}",
                "type": block["type"],
                "block_id": block["id"],
                "caption": caption[:80],
                "chars": len(block["text"]),
            })
    return assets


def outline_of(blocks: list[dict]) -> list[dict]:
    """大纲：只取标题块，保留层级，用于知识点抽取的「章节归属」。"""
    return [{"block_id": b["id"], "level": b["level"], "text": b["text"]}
            for b in blocks if b["type"] == "heading"]


def _split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[。！？；.!?;])\s*", text) if s]


def chunk_blocks(blocks: list[dict], size: int = 400, overlap: int = 80) -> list[dict]:
    """语义切片：标题单独成句、正文按句累积，超过 size 在句边界切断并回带 overlap。"""
    units: list[tuple[str, str]] = []
    for block in blocks:
        if block["type"] == "heading":
            units.append((block["id"], block["text"]))
        else:
            for sentence in _split_sentences(block["text"]):
                units.append((block["id"], sentence))

    chunks: list[dict] = []
    buf: list[str] = []
    ids: list[str] = []
    length = 0

    def flush() -> None:
        nonlocal buf, ids, length
        if not buf:
            return
        chunks.append({
            "id": f"c{len(chunks) + 1}",
            "text": "".join(buf),
            "block_ids": list(dict.fromkeys(ids)),
            "chars": len("".join(buf)),
        })

    for block_id, sentence in units:
        buf.append(sentence)
        ids.append(block_id)
        length += len(sentence)
        if length >= size:
            flush()
            tail: list[str] = []
            tail_ids: list[str] = []
            tail_len = 0
            for s, b in reversed(list(zip(buf, ids))):
                if tail and tail_len + len(s) > overlap:
                    break
                tail.insert(0, s)
                tail_ids.insert(0, b)
                tail_len += len(s)
            buf, ids, length = tail, tail_ids, tail_len
    flush()
    return chunks


# ================================================================ ② 输出什么
def parse_document(
    filename: str,
    kind: str,
    text: str,
    chunk_size: int = 400,
    chunk_overlap: int = 80,
) -> dict:
    """解析主入口。

    返回 ``ParseResult``::

        {
          "doc":   {filename, kind, title, chars_before, chars_after, blocks, chunks, assets},
          "outline": [{block_id, level, text}],
          "blocks": [{id, type, level, text, order}],
          "assets": [{id, type, block_id, caption, chars}],
          "chunks": [{id, text, block_ids, chars}],
          "noise": {removed_lines, removed_chars, before_chars, after_chars, ratio,
                    rules:[{id, name, why, hits, chars}]},
          "engine": "rule"
        }

    ``engine`` 恒为 ``"rule"``：本模块只做确定性清洗与结构化，
    语义层面的补全交给上层（``extract.parse_material``）的模型分支。
    """
    clean, noise = denoise(text)
    blocks = to_blocks(clean)
    assets = to_assets(blocks)
    chunks = chunk_blocks(blocks, size=chunk_size, overlap=chunk_overlap)
    outline = outline_of(blocks)
    raw_title = outline[0]["text"] if outline else filename.rsplit(".", 1)[0]
    title = re.sub(r"^[#\s]+", "", raw_title).strip() or raw_title
    return {
        "doc": {
            "filename": filename,
            "kind": kind,
            "title": title[:60],
            "chars_before": noise["before_chars"],
            "chars_after": noise["after_chars"],
            "blocks": len(blocks),
            "chunks": len(chunks),
            "assets": len(assets),
        },
        "outline": outline,
        "blocks": blocks,
        "assets": assets,
        "chunks": chunks,
        "noise": noise,
        "engine": "rule",
    }


def preview_report(result: dict) -> dict:
    """给界面用的精简版（不含 blocks/chunks 全文，避免响应过大）。"""
    doc = result.get("doc") or {}
    return {
        "doc": doc,
        "outline": (result.get("outline") or [])[:12],
        "assets": (result.get("assets") or [])[:8],
        "noise": result.get("noise") or {},
        "engine": result.get("engine", "rule"),
    }
