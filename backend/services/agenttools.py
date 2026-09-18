# -*- coding: utf-8 -*-
"""agenttools.py —— 对话智能体的 **Agent 工具层**。

对话智能体不应该只会聊天。学生侧要能"把我的资料喂给它、让它替我整理"，
教师侧要能"让它基于我上传的课件出备课草稿"。所以这里把对话之外的动作
收敛成**工具注册表**，统一走一个入口：

    GET  /api/agent/tools            工具清单（给前端渲染按钮）
    POST /api/agent/tools/{id}/run   执行工具

设计口径与全项目一致：
  * 每个工具都有**真实实现**（写库、检索、生成 markdown），不是占位按钮；
  * 涉及模型的部分走双引擎（``llm.chat`` + 规则兜底），engine 如实上报；
  * 生成的资料**可溯源**：正文里标注引用了哪些资料（refs），保存后入检索索引。

当前注册两个工具（后续加工具只需往 TOOLS 里 append，路由不用动）：

==== ================ ====================================================
 id  名称             说明
==== ================ ====================================================
upload_material    上传资料：把一段文本作为正式材料入库（解析 → 抽知识点 → 建索引）
generate_material  生成资料：基于检索证据 + 画像生成复习提纲 / 错题卡 / 学习小结等
==== ================ ====================================================
"""
from __future__ import annotations

import re
from typing import Any

import db
import llm
from services import extract, kprules, parsekit, rag, retriever

GEN_KINDS: list[dict[str, str]] = [
    {"id": "review", "label": "复习提纲", "desc": "按知识点列提纲，标注难度与出处"},
    {"id": "mistakes", "label": "错题卡", "desc": "把薄弱知识点整理成可自测的卡片"},
    {"id": "digest", "label": "学习小结", "desc": "把一段资料压缩成一页小结"},
    {"id": "lesson", "label": "教案要点", "desc": "面向教师的课堂环节与提问设计"},
    {"id": "exercise", "label": "练习题", "desc": "围绕知识点出 3 道由浅入深的题"},
]

CATEGORY_TO_KIND = [("课件", "courseware"), ("论文", "paper"), ("作业", "homework"),
                    ("教案", "lesson"), ("岗位", "jd"), ("笔记", "other")]

TOOLS: list[dict[str, Any]] = [
    {
        "id": "upload_material", "name": "上传资料", "side": "both",
        "desc": "把一段文本作为正式材料入库：自动解析、抽知识点、建检索索引，之后答疑可以引用它。",
        "args": [
            {"key": "title", "label": "标题", "type": "text", "required": True, "placeholder": "例如：我的深度学习笔记"},
            {"key": "category", "label": "分类", "type": "select",
             "options": ["笔记", "课件", "论文", "作业", "教案", "岗位"]},
            {"key": "text", "label": "正文", "type": "textarea", "required": True,
             "placeholder": "粘贴资料全文（至少 20 字）"},
        ],
    },
    {
        "id": "generate_material", "name": "生成资料", "side": "both",
        "desc": "基于教师上传的资料与你的画像生成草稿，可一键保存到资料库并进入检索索引。",
        "args": [
            {"key": "topic", "label": "主题", "type": "text", "required": True,
             "placeholder": "例如：注意力机制"},
            {"key": "kind", "label": "类型", "type": "select",
             "options": [k["label"] for k in GEN_KINDS]},
            {"key": "save", "label": "生成后保存到我的资料库", "type": "switch"},
        ],
    },
]


def tools_view(side: str = "student") -> list[dict[str, Any]]:
    return TOOLS


def _kind_of(category: str) -> str:
    for hint, kind in CATEGORY_TO_KIND:
        if hint in (category or ""):
            return kind
    return "other"


# ================================================================ 工具一：上传资料
def _run_upload(user: dict, args: dict) -> dict[str, Any]:
    title = str(args.get("title") or "").strip() or "未命名资料"
    text = str(args.get("text") or "").strip()
    category = str(args.get("category") or "笔记")
    if len(text) < 20:
        return {"ok": False, "error": "正文太短（至少 20 字），太短解析不出结构。"}

    kind = _kind_of(category)
    filename = title if title.endswith(".md") else title + ".md"
    parsed, engine = extract.parse_material(kind, filename, text)

    material_id = extract.save_material(
        int(user["id"]), kind, category, filename, "", text, parsed, engine
    )
    touched = extract.apply_parse_result(user, material_id, kind, filename, text, parsed)
    doc = parsekit.parse_document(filename, kind, text)
    kp = kprules.extract(text, kind=kind, category=category, blocks=doc["blocks"], limit=8)

    return {
        "ok": True, "tool": "upload_material", "engine": engine,
        "material_id": material_id,
        "indexed_chunks": int(touched.get("indexed") or 0),
        "knowledge_saved": int(touched.get("knowledge_points") or 0),
        "parse": parsekit.preview_report(doc),
        "kp_rule": {"rule_set": kp["rule_set"],
                    "items": [{k: i[k] for k in ("name", "kp_type", "bloom")}
                              for i in kp["items"][:6]]},
        "message": f"已入库：命中 {touched.get('indexed', 0)} 个索引片段、"
                   f"抽出 {touched.get('knowledge_points', 0)} 个知识点。之后的提问可以引用它。",
    }


# ================================================================ 工具二：生成资料
_GEN_TEMPLATES: dict[str, dict[str, str]] = {
    "review": {"title": "复习提纲", "verb": "列出复习要点"},
    "mistakes": {"title": "错题卡", "verb": "整理成自测问答"},
    "digest": {"title": "学习小结", "verb": "压缩成一页小结"},
    "lesson": {"title": "教案要点", "verb": "设计课堂环节与提问"},
    "exercise": {"title": "练习题", "verb": "出 3 道由浅入深的题"},
}


def _rule_generate(kind_id: str, topic: str, hits: list[dict], kps: list[dict],
                   profile: dict) -> str:
    meta = _GEN_TEMPLATES.get(kind_id, _GEN_TEMPLATES["review"])
    lines = [f"# {meta['title']} · {topic}", ""]
    ref_text = "、".join("[" + str(h.get("ref")) + "]" for h in hits[:3])
    lines.append("> 依据：" + (ref_text or "（暂无命中的教师资料，以下为通用框架）"))

    if kps:
        lines += ["", "## 涉及知识点", *[f"- {k['name']}（{k.get('course') or '—'}，难度 {k.get('difficulty') or 'B'}）"
                                      for k in kps]]
    if kind_id == "exercise":
        lines += ["", "## 练习题", "",
                  "1.（基础）用自己的话说明" + topic + "是什么，并给一个例子。",
                  "2.（进阶）" + topic + "在什么条件下会失效？说明原因。",
                  "3.（挑战）把 " + topic + " 用到你最近的项目/作业里，写清步骤与结果。"]
    elif kind_id == "lesson":
        lines += ["", "## 课堂环节（45 分钟）", "",
                  "1. 导入（5min）：从一个会卡住大多数学生的例子开始；",
                  "2. 讲授（15min）：按上面知识点的顺序推进，每讲完一个就提问一次；",
                  "3. 推演（12min）：师生共同推导关键步骤；",
                  "4. 练习（8min）：现场做一道基础题并互评；",
                  "5. 小结（5min）：让学生用自己的话复述。"]
    else:
        lines += ["", "## 要点", *[f"- {h.get('ref')}：{str(h.get('content') or '')[:60]}……"
                                 for h in hits[:4]]]
        lines += ["", "## 建议下一步", "- 先复述一遍要点，再做一道同类题自测。"]

    track = profile.get("track") or ""
    level = profile.get("grade_level") or ""
    if track:
        lines += ["", f"---", f"*按你的画像（{track} · {level} 层）调整了内容的深度与任务难度；"
                            f"这只影响讲解深度，不代表分班。*"]
    return "\n".join(lines)


def _run_generate(user: dict, args: dict) -> dict[str, Any]:
    topic = str(args.get("topic") or "").strip()
    if not topic:
        return {"ok": False, "error": "请先填写主题。"}
    kind_label = str(args.get("kind") or "复习提纲")
    kind_id = next((k["id"] for k in GEN_KINDS if k["label"] == kind_label), "review")
    save = bool(args.get("save"))

    hits = retriever.hybrid_search(topic, top_k=4, owner_id=int(user.get("id") or 0),
                                   teacher=str(user.get("role")) == "teacher")
    tokens = [t for t in re.split(r"[\s，,。？?、]+", topic) if len(t) >= 2]
    kp_clause, kp_args = rag.search_scope(int(user.get("id") or 0),
                                          str(user.get("role")) == "teacher")
    kp_rows = db.query(
        "SELECT name, course, difficulty FROM knowledge_points WHERE 1=1" +
        kp_clause + " LIMIT 200", tuple(kp_args),
    )
    kps = [dict(r) for r in kp_rows
           if any(t in str(r["name"]) or str(r["name"]) in topic for t in tokens)][:5]
    profile = db.student_profile(int(user.get("id") or 0)) or {}

    rule = lambda: _rule_generate(kind_id, topic, hits, kps, profile)  # noqa: E731
    prompt = (
        f"你是教学资料助手。请基于给定资料，为「{topic}」生成一份{kind_label}（markdown）。\n"
        "要求：1. 只依据资料，不编造；2. 每个要点后用 [资料名] 标注出处；"
        "3. 结构清晰，中文，500 字以内。\n\n"
        f"【资料】\n" + "\n".join(f"[{h.get('ref')}] {str(h.get('content') or '')[:160]}"
                               for h in hits) or "（无）"
    )
    markdown, engine = llm.chat([{"role": "user", "content": prompt}], mock=rule, temperature=0.3)
    if not markdown.strip():
        markdown, engine = rule(), "rule"

    refs = [h.get("ref") for h in hits if h.get("ref")]
    result: dict[str, Any] = {
        "ok": True, "tool": "generate_material", "engine": engine,
        "title": f"{_GEN_TEMPLATES[kind_id]['title']} · {topic}",
        "markdown": markdown, "refs": refs,
        "message": f"已生成（依据 {len(refs)} 份资料，全部可溯源）。"
    }

    if save:
        text = markdown + "\n\n## 依据资料\n" + "\n".join(f"- [{r}]" for r in refs)
        parsed, pengine = extract.parse_material("other", result["title"] + ".md", text)
        material_id = extract.save_material(
            int(user["id"]), "other", "AI 生成", result["title"] + ".md", "", text, parsed, pengine
        )
        extract.apply_parse_result(user, material_id, "other", result["title"] + ".md", text, parsed)
        result["material_id"] = material_id
        result["message"] += " 已保存到资料库并进入检索索引。"
    return result


# ================================================================ 对外
def run_tool(tool_id: str, args: dict, user: dict) -> dict[str, Any]:
    """统一入口。新增工具只需在 TOOLS 注册并在这里加一个分支。"""
    if tool_id == "upload_material":
        return _run_upload(user, args or {})
    if tool_id == "generate_material":
        return _run_generate(user, args or {})
    return {"ok": False, "error": f"未知工具：{tool_id}"}
