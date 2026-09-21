# -*- coding: utf-8 -*-
"""extract.py —— ① 图文素材智能解析 + ② 知识点结构化抽取。

## 图文双通道

有文本层 → ``chat_json(prompt, schema)``；
无文本层但有图 → ``vision(image_b64, prompt, schema)``。
两条路**共用同一套 schema 与同一份规则兜底**，所以返回结构完全一致。

图片但未配视觉模型时，规则版会**如实提示**（``note`` 字段），绝不假装解析成功。

## 规则版不是假数据

``rule_parse()`` 的每个字段都从真实文本统计而来：
方向由关键词词典命中次数排序；成绩单用正则抽课程与分数；摘要取正文前若干字。
断网时"两个学生同问一题答案不同"这类核心卖点，全靠这套规则版撑住。
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import zipfile
from typing import Any, Sequence

import config
import db
import llm
from services import embedding, rag, stratify, taxonomy as tax

# ================================================================ 常量
KINDS: dict[str, str] = {
    "courseware": "教学课件",
    "paper": "论文",
    "fund": "基金项目",
    "award": "获奖证明",
    "transcript": "成绩单",
    "resume": "简历",
    # 对话里整理出来的笔记（Copilot「存成笔记」）—— 没有扩展名会映射到这里，
    # 只由保存笔记的代码显式指定，与上传材料的六类并列展示。
    "note": "学习笔记",
    "other": "其它材料",
}

# 「课件」= 系统生成的 PPT（一键备课 / 教案转 PPT / 资料转 PPT），单独成一类，
# 是为了让老师备完课不用带 U 盘 —— 直接在资料库里按「课件」找回来打开。
CATEGORIES: list[str] = ["未分类", "课程资料", "课件", "科研成果", "教学备课", "个人材料"]

TEXT_EXTS = {".txt", ".md", ".markdown", ".csv", ".json"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PDF_EXTS = {".pdf"}
OFFICE_EXTS = {".docx", ".pptx"}
ALLOWED_EXTS = TEXT_EXTS | IMAGE_EXTS | PDF_EXTS | OFFICE_EXTS

MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
    ".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8", ".docx":
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# 六类材料的 schema：真模型与规则版共用同一份字段定义
_SCHEMAS: dict[str, str] = {
    "paper": '{"title":"","directions":["方向"],"keywords":["关键词"],"summary":"不超过120字"}',
    "fund": '{"title":"","level":"国家级|省部级|校级","directions":["方向"],"summary":"不超过120字"}',
    "award": '{"title":"","level":"国家级|省部级|校级","year":"","directions":["方向"]}',
    "courseware": (
        '{"title":"","directions":["方向"],'
        '"knowledge_points":[{"name":"","difficulty":"A|B|C","keywords":[""]}]}'
    ),
    "transcript": '{"courses":[{"name":"","score":0}],"skills":[""],"summary":"不超过120字"}',
    "resume": '{"skills":[""],"experiences":[""],"directions":["方向"],"summary":"不超过120字"}',
    "other": '{"title":"","directions":["方向"],"summary":"不超过120字"}',
}

_DIFFICULTY_HARD = ["推导", "证明", "前沿", "综述", "优化", "定理", "复杂", "深入", "收敛", "复杂网络"]
_DIFFICULTY_EASY = ["基础", "入门", "概述", "简介", "概念", "是什么", "定义", "导论", "初识", "概览"]

# 标题识别：markdown 井号 / 第N章讲节 / 数字编号
_HEADING_RE = re.compile(r"^(#{1,4}\s|第[一二三四五六七八九十百\d]+[章节讲篇部分]|\d+(\.\d+)*[\s、.])")
_SCORE_RE = re.compile(r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9 ]{1,11})\s*[：:,\s]?\s*(\d{2,3}(?:\.\d+)?)")


# ================================================================ 文件名安全
def safe_name(filename: str) -> str:
    """只取 basename（防 ``../../`` 穿越），非法字符替换为 ``_``，截断 80 字符。"""
    name = os.path.basename(filename or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5._-]", "_", name)
    name = name.strip("._") or "unnamed"
    if len(name) > 80:
        stem, ext = os.path.splitext(name)
        keep = max(1, 80 - len(ext))
        name = stem[:keep] + ext
    return name


def ext_of(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def kind_by_ext(filename: str) -> str:
    ext = ext_of(filename)
    if ext in IMAGE_EXTS:
        return "award"
    if ext in PDF_EXTS:
        return "paper"
    if ext in OFFICE_EXTS:
        return "courseware"
    return "courseware"


def course_from_filename(filename: str) -> str:
    """从文件名推课程名：``2026高等数学-第3讲.md`` → ``2026高等数学``。"""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    stem = re.sub(r"[（(].*?[)）]", " ", stem)
    parts = re.split(r"[-_—\s]+", stem)
    parts = [p for p in parts if p and not re.fullmatch(r"第?\d+[讲章节次课]?", p)]
    return (parts[0] if parts else stem).strip()[:40] or "未命名课程"


# ================================================================ 文本抽取
def read_text(filename: str, data: bytes) -> str:
    """文本抽取。按扩展名分派，**任何失败都返回空串**（交给上层走图片或如实提示）。"""
    ext = ext_of(filename)

    if ext in TEXT_EXTS:
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return ""

    if ext in PDF_EXTS:
        try:  # 按需 import：没装 pypdf 也不影响服务启动
            from pypdf import PdfReader
        except Exception:
            return ""
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = []
            for page in reader.pages[:40]:      # 前 40 页足够覆盖课件
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            return "\n".join(pages)
        except Exception:
            return ""

    if ext in OFFICE_EXTS:
        return _read_ooxml(data, ext)

    return ""  # 图片没有文本层


def _read_ooxml(data: bytes, ext: str) -> str:
    """docx/pptx 纯标准库解析（zipfile 解包 + 正则抽标签文本），零新增依赖。"""
    member_re = (
        re.compile(r"^word/document\.xml$")
        if ext == ".docx"
        else re.compile(r"^ppt/(slides|notesSlides)/[^/]+\.xml$")
    )
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            chunks: list[str] = []
            for name in sorted(zf.namelist()):
                if not member_re.match(name):
                    continue
                try:
                    xml = zf.read(name).decode("utf-8", "ignore")
                except Exception:
                    continue
                # 段落级切分，保留可读的行结构
                for para in re.split(r"</a:p>|</w:p>", xml):
                    texts = re.findall(r"<(?:a|w):t[^>]*>(.*?)</(?:a|w):t>", para, re.S)
                    line = "".join(texts).strip()
                    if line:
                        chunks.append(line)
                if ext == ".pptx" and len(chunks) > 800:
                    break
            return "\n".join(chunks)
    except Exception:
        return ""


def to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# ================================================================ 文本切分
def split_chunks(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """按句子边界贪心切分。

    默认取**入库索引**粒度（``400 / 80``）：粒度更细，答疑才能定位到具体章节。
    解析时传 ``800 / 200``（``config.PARSE_CHUNK_SIZE``）。
    """
    size = config.CHUNK_SIZE if size is None else max(40, int(size))
    overlap = config.CHUNK_OVERLAP if overlap is None else max(0, min(int(overlap), size // 2))

    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    sentences = re.split(r"(?<=[。！？；.!?;\n])", text)
    chunks: list[str] = []
    buf = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(buf) + len(sentence) <= size:
            buf += sentence
            continue
        if buf:
            chunks.append(buf.strip())
            # 下一片带 overlap 长度的重叠尾巴，保证跨片语义不断裂
            tail = buf[-overlap:] if overlap else ""
            buf = tail + sentence
        else:
            # 单句就超长：硬切
            for i in range(0, len(sentence), size):
                chunks.append(sentence[i: i + size].strip())
            buf = ""
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c]


# ================================================================ ② 知识点抽取
def _clean_name(raw: str) -> str:
    return re.sub(r"^[#\s\d.、,，:：]+", "", (raw or "").strip())[:40].strip()


def difficulty_of(text: str) -> str:
    """A/B/C 只是**内容深度与任务难度**的建议，不用于分班、不给学生贴标签。"""
    if any(word in text for word in _DIFFICULTY_HARD):
        return "A"
    if any(word in text for word in _DIFFICULTY_EASY):
        return "C"
    return "B"


def rule_knowledge_points(
    text: str,
    limit: int = 6,
    course: str = "",
    material_id: int = 0,
    owner_id: int = 0,
) -> list[dict]:
    """规则版知识点抽取：**标题优先、段落兜底**。"""
    text = text or ""
    headings: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) > 60:
            continue
        if _HEADING_RE.match(line):
            name = _clean_name(line)
            if len(name) >= 2 and name not in headings:
                headings.append(name)
        if len(headings) >= limit:
            break

    if not headings:
        # 段落兜底：取前 N 段，每段用第一个分句做名字
        for chunk in split_chunks(text, size=config.PARSE_CHUNK_SIZE,
                                 overlap=config.PARSE_CHUNK_OVERLAP)[:limit]:
            first = re.split(r"[。！？；\n]", chunk.strip())[0]
            name = _clean_name(first)
            if len(name) >= 2:
                headings.append(name)

    points: list[dict] = []
    for name in headings[:limit]:
        scope = [name]
        # 用知识点名去正文里找上下文，供难度与关键词判定
        for line in text.splitlines():
            if name[:8] and name[:8] in line:
                scope.append(line.strip()[:200])
                break
        context = "\n".join(scope)
        directions = tax.directions_from_text(context, top=2)
        keywords = directions or [w for w in tax.DIRECTION_KEYWORDS if w in context][:2]
        points.append(
            {
                "name": name,
                "difficulty": difficulty_of(context),
                "keywords": keywords[:3],
                "course": course,
                "material_id": material_id,
                "owner_id": owner_id,
                "source_ref": f"{course}·{name}" if course else name,
            }
        )
    return points


# ================================================================ 规则版解析
def _first_sentences(text: str, limit: int = 160) -> str:
    body = re.sub(r"\s+", " ", (text or "").strip())
    return body[:limit]


def rule_parse(kind: str, filename: str, text: str) -> dict:
    """规则版结构化解析。所有字段都从真实文本统计，不是占位假数据。"""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    text = text or ""
    directions = tax.directions_from_text(text, top=4)
    summary = _first_sentences(text, 160)

    if kind == "award":
        year = ""
        match = re.search(r"(19|20)\d{2}", text or stem)
        if match:
            year = match.group(0)
        level = "校级"
        for candidate in ("国家级", "省部级", "市级", "校级"):
            if candidate in text or candidate in stem:
                level = candidate
                break
        return {
            "title": stem or "获奖证明",
            "level": level,
            "year": year,
            "directions": directions,
            "note": "图片无文本层，本条为按文件名与可见信息的规则推断结果。",
        }

    if kind == "fund":
        level = "校级"
        for candidate in ("国家级", "国家自然科学基金", "省部级", "校级"):
            if candidate in text or candidate in stem:
                level = candidate.replace("国家自然科学基金", "国家级")
                break
        return {"title": stem or "基金项目", "level": level,
                "directions": directions, "summary": summary}

    if kind == "courseware":
        return {
            "title": stem or "教学课件",
            "directions": directions,
            "knowledge_points": [
                {k: p[k] for k in ("name", "difficulty", "keywords")}
                for p in rule_knowledge_points(text, limit=6)
            ],
        }

    if kind == "transcript":
        courses: list[dict] = []
        seen: set[str] = set()
        for name, score in _SCORE_RE.findall(text):
            name = name.strip(" \t:：,，")
            if len(name) < 2 or name in seen:
                continue
            try:
                value = float(score)
            except ValueError:
                continue
            if not (0 <= value <= 150):
                continue
            seen.add(name)
            courses.append({"name": name[:20], "score": value})
        scores = [c["score"] for c in courses]
        gpa = round(sum(scores) / len(scores), 1) if scores else 0.0
        skills = []
        for direction in directions:
            skills.extend(tax.keywords_of(direction)[:2])
        return {
            "courses": courses[:20],
            "skills": list(dict.fromkeys(skills))[:6],
            "summary": summary or f"共识别 {len(courses)} 门课程，平均分 {gpa}。",
            "avg_score": gpa,
        }

    if kind == "resume":
        experiences: list[str] = []
        for line in (text or "").splitlines():
            line = line.strip()
            if len(line) >= 6 and re.search(r"(实习|项目|经历|竞赛|获奖|任职|工作)", line):
                experiences.append(line[:80])
            if len(experiences) >= 6:
                break
        return {
            "skills": list(dict.fromkeys(tax.DIRECTION_KEYWORDS and
                                         [w for d in directions for w in tax.keywords_of(d)]))[:8],
            "experiences": experiences,
            "directions": directions,
            "summary": summary,
        }

    if kind == "paper":
        return {"title": stem or "论文", "directions": directions,
                "keywords": [w for d in directions for w in tax.keywords_of(d)[:2]][:6] or directions,
                "summary": summary}

    return {"title": stem or "材料", "directions": directions, "summary": summary}


# ================================================================ 双引擎解析
def _prompt_for(kind: str, filename: str, text: str) -> str:
    label = KINDS.get(kind, "材料")
    return (
        f"你是高校教学资料结构化助手。请从下面这份「{label}」中抽取结构化字段。\n"
        f"文件名：{filename}\n"
        "要求：\n"
        "1. 只依据材料内容，不要编造；无法确定的字段留空字符串或空数组；\n"
        "2. directions 只能从这些方向里选："
        f"{'、'.join(tax.ALL_DIRECTIONS)}；\n"
        "3. 若为课件，knowledge_points 抽 4~8 条，difficulty 按内容深度给 A/B/C"
        "（A=需要推导/证明/前沿，C=基础概念入门，其余 B），"
        "difficulty 只表示内容深度，不代表学生层次；\n"
        "4. summary 用中文，不超过 120 字。\n\n"
        f"材料正文：\n{text[:4000]}"
    )


def parse_material(
    kind: str,
    filename: str,
    text: str = "",
    image_b64: str = "",
) -> tuple[dict, str]:
    """结构化解析（双引擎）。返回 ``(解析结果, engine)``。"""
    kind = kind if kind in _SCHEMAS else "other"
    schema = _SCHEMAS[kind]
    rule = lambda: rule_parse(kind, filename, text)  # noqa: E731

    if text.strip():
        return llm.chat_json(
            [{"role": "user", "content": _prompt_for(kind, filename, text)}],
            schema,
            mock=rule,
        )

    # 无文本层：交给视觉模型；未配视觉模型时规则版会带 note 如实提示
    vision_mock = lambda: {  # noqa: E731
        **rule_parse(kind, filename, filename),
        "note": "该文件没有文本层，且未配置视觉模型，本次未真正读图。"
                "配好 LLM_VISION_MODEL 后即可自动识别图片内容。",
    }
    prompt = (
        f"请阅读这张「{KINDS.get(kind, '材料')}」图片，抽取结构化字段。"
        "只依据图片内容，不要编造。"
    )
    return llm.vision(image_b64, prompt, schema, mock=vision_mock)


def rule_parse_public(kind: str, filename: str, text: str) -> dict:
    """给外部（如自检脚本）用的规则版入口。"""
    return rule_parse(kind, filename, text)


# ================================================================ 落库与副作用
def save_material(
    owner_id: int,
    kind: str,
    category: str,
    filename: str,
    stored: str,
    raw_text: str,
    parsed: dict,
    engine: str,
    shared: int = 1,
) -> int:
    """入一条资料。``shared=0`` = 只进自己的资料库，不进「教师共享」池。

    一键备课生成的 PPT 就是这一类：老师存它是为了自己随时打开放映，
    不等于要发给学生，所以默认不出现在学生的共享列表里。
    """
    return db.execute(
        "INSERT INTO materials (owner_id, kind, category, filename, stored, raw_text, parsed, engine, created_at, shared) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (owner_id, kind, category, filename, stored, raw_text,
         db.jdump(parsed), engine, db.now(), 1 if shared else 0),
    )


def knowledge_points_of(parsed: dict) -> list[dict]:
    points = (parsed or {}).get("knowledge_points")
    if isinstance(points, list) and points:
        return [p for p in points if isinstance(p, dict)]
    return []


def replace_knowledge_points(
    material_id: int,
    owner_id: int,
    course: str,
    parsed: dict,
    text: str,
    filename: str,
) -> int:
    """把解析出的知识点写入库。模型没给出时用规则版补齐，保证"解析必然有用"。"""
    points = knowledge_points_of(parsed)
    if not points and text:
        points = rule_knowledge_points(text, limit=6, course=course,
                                       material_id=material_id, owner_id=owner_id)
    if not points:
        return 0

    rows = []
    for index, point in enumerate(points[:12]):
        name = _clean_name(str(point.get("name") or ""))
        if len(name) < 2:
            continue
        difficulty = str(point.get("difficulty") or "B").upper()[:1]
        if difficulty not in ("A", "B", "C"):
            difficulty = "B"
        keywords = point.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        rows.append(
            (
                material_id,
                owner_id,
                str(point.get("course") or course or ""),
                name,
                difficulty,
                db.jdump([str(k) for k in keywords][:6]),
                str(point.get("source_ref") or f"{course or filename}·{name}"),
            )
        )
    if not rows:
        return 0

    with db.connect() as conn:
        conn.execute("DELETE FROM knowledge_points WHERE material_id = ?", (material_id,))
        conn.executemany(
            "INSERT INTO knowledge_points (material_id, owner_id, course, name, difficulty, keywords, source_ref) "
            "VALUES (?,?,?,?,?,?,?)",
            rows,
        )
    return len(rows)


def apply_parse_result(
    user: dict,
    material_id: int,
    kind: str,
    filename: str,
    text: str,
    parsed: dict,
) -> dict:
    """上传副作用 —— 这是"解析有用"的关键，把解析产物接到画像与索引上。"""
    user_id = int(user.get("id") or 0)
    role = str(user.get("role") or "")
    course = course_from_filename(filename)
    touched: dict[str, Any] = {"course": course, "knowledge_points": 0, "indexed": 0}

    # ---- 角色无关：只要材料有正文，就同步建索引 + 抽知识点
    # 三种检索资产必须一起更新，否则会出现"BM25 搜得到、向量搜不到"这类
    # 只在特定问法下才暴露的偏差。学生上传的课件同样要能被答疑引用。
    if text.strip():
        touched["indexed"] = rag.index_material(material_id, user_id, course, filename, text)
        embedding.index_vectors(
            material_id, split_chunks(text, size=None, overlap=None)
        )
        touched["knowledge_points"] = replace_knowledge_points(
            material_id, user_id, course, parsed, text, filename
        )

    # ---- 教师材料：合并研究方向
    if role == "teacher":
        if kind in ("paper", "fund", "award"):
            profile = db.teacher_profile(user_id) or {}
            directions = list(profile.get("directions") or [])
            for direction in (parsed or {}).get("directions") or []:
                direction = str(direction).strip()
                if direction and direction not in directions:
                    directions.append(direction)
            db.execute(
                "INSERT INTO teacher_profiles (user_id, directions, expertise, projects, summary) "
                "VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET directions=excluded.directions",
                (
                    user_id,
                    db.jdump(directions[:8]),
                    db.jdump(profile.get("expertise") or []),
                    db.jdump(profile.get("projects") or []),
                    profile.get("summary") or "",
                ),
            )
            touched["directions"] = directions[:8]

    # ---- 学生材料：合并兴趣、重算 GPA 与层次（索引与知识点已在上方统一处理）
    else:
        profile = db.student_profile(user_id) or {}
        interests = list(profile.get("interests") or [])
        for direction in (parsed or {}).get("directions") or []:
            direction = str(direction).strip()
            if direction and direction not in interests:
                interests.append(direction)

        gpa = float(profile.get("gpa") or 0)
        if kind == "transcript":
            courses = (parsed or {}).get("courses") or []
            scores: list[float] = []
            for row in courses:
                try:
                    scores.append(float(row.get("score")))
                except (TypeError, ValueError, AttributeError):
                    continue
            if scores:
                gpa = round(sum(scores) / len(scores), 1)

        # 科研/就业倾向暂按 1-5 中值起步，由后续行为（申请/答疑）微调
        research = float(profile.get("research_intent") or 3.0)
        job = float(profile.get("job_intent") or 3.0)
        new_profile, engine = stratify.stratify(
            gpa=gpa,
            research_intent=research,
            job_intent=job,
            interests=interests,
            extra_text=text[:800],
        )
        stratify.save_profile(user_id, new_profile, engine)
        touched["interests"] = new_profile.get("interests")
        touched["gpa"] = new_profile.get("gpa")
        touched["grade_level"] = new_profile.get("grade_level")
        touched["engine"] = engine

        # 学生自己的材料也建索引，便于答疑时引用自己的成绩单/简历
        if text.strip():
            touched["indexed"] = rag.index_material(material_id, user_id, course, filename, text)

    return touched


def list_materials(owner_id: int, category: str = "", course: str = "", keyword: str = "") -> list[dict]:
    sql = "SELECT * FROM materials WHERE owner_id = ?"
    args: list = [owner_id]
    if category:
        sql += " AND category = ?"
        args.append(category)
    if course:
        sql += " AND filename LIKE ?"
        args.append(f"%{course}%")
    if keyword:
        sql += " AND (filename LIKE ? OR raw_text LIKE ?)"
        args.extend([f"%{keyword}%", f"%{keyword}%"])
    sql += " ORDER BY id DESC"
    rows = db.query(sql, tuple(args))
    for row in rows:
        row["parsed"] = db.jload(row.get("parsed"), {})
        row["size_chars"] = len(str(row.get("raw_text") or ""))
        # 前端列表直接显示中文名，别把 courseware / note 这种键名亮给师生看
        row["kind_label"] = KINDS.get(str(row.get("kind") or ""), "其它材料")
        row.pop("raw_text", None)
        row["knowledge_count"] = db.scalar(
            "SELECT COUNT(*) FROM knowledge_points WHERE material_id = ?", (row["id"],), 0
        )
    return rows


def delete_material(owner_id: int, material_id: int) -> bool:
    """删除资料及其索引。只允许删自己的。"""
    row = db.query_one("SELECT * FROM materials WHERE id = ?", (material_id,))
    if not row or int(row.get("owner_id") or 0) != int(owner_id):
        return False
    rag.drop_material(material_id)
    with db.connect() as conn:
        conn.execute("DELETE FROM knowledge_points WHERE material_id = ?", (material_id,))
        conn.execute("DELETE FROM materials WHERE id = ?", (material_id,))
    # 顺手删掉落盘文件
    stored = str(row.get("stored") or "")
    if stored:
        path = config.UPLOAD_DIR / stored
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    return True


def set_category(owner_id: int, material_id: int, category: str) -> bool:
    row = db.query_one("SELECT owner_id FROM materials WHERE id = ?", (material_id,))
    if not row or int(row.get("owner_id") or 0) != int(owner_id):
        return False
    db.execute("UPDATE materials SET category = ? WHERE id = ?", (category or "未分类", material_id))
    return True


def ensure_upload_dir(owner_id: int) -> Any:
    target = config.UPLOAD_DIR / str(owner_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _self_check() -> None:  # pragma: no cover
    sample = "# 第一章 注意力机制\n注意力机制是 Transformer 的核心，需要推导。\n# 第二章 基础概念\n入门介绍。"
    points = rule_knowledge_points(sample, limit=4)
    assert points and all(p["name"] for p in points), points
    assert split_chunks("一。" * 500), "split_chunks 不应为空"
    _ = (json, Sequence)
