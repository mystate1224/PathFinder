# -*- coding: utf-8 -*-
"""demo.py —— 三项能力的**演示例子 + 测试用例**。

只为一个目标服务：演示的时候不冷场，验收的时候不靠嘴。

两层结构，职责分清：

**SAMPLES（示例材料）** —— "给观众看的"。
点一下就能跑完整链路：文本直接进解析与抽取，图片走视觉模型
（未配视觉模型时会**如实提示**"本次未真正读图"，这是设计内的降级，不是故障）。

**CASES（测试用例）** —— "给验收的人看的"。
期望结果**写死**在代码里，不依赖网络与模型；但每个用例都带着 ``runner``
（真实实现的入口），传 ``live=True`` 就会真的跑一遍并和写死的期望比对，
返回 PASS / FAIL 和差异明细。这就是"写死，但保留真实实现的可扩展接口"。

接口：
  GET  /api/demo/samples            列出示例材料
  POST /api/demo/samples/{id}/run   运行某个示例（文本/图片各自走对应链路）
  GET  /api/demo/cases              列出测试用例
  POST /api/demo/cases/{id}/run     运行用例；body 里 ``live=true`` 走真实链路
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import llm
from services import extract, interaction as ia, kprules, parsekit

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"

# ================================================================ 示例材料
SAMPLES: list[dict[str, Any]] = [
    {
        "id": "img-courseware",
        "title": "课件扫描页（含页眉 / 页码 / 水印 / 目录点线）",
        "ability": "parse",
        "type": "image",
        "file": "课件扫描页.png",
        "kind": "courseware",
        "category": "课件",
        "points": "看点：视觉模型读图，正文、表格、定义句被认出来；页码水印这类噪声被点名列出。",
        # 预置解析结果：图片是仓库自带的合成素材，内容确定，所以解析结果可以直接写死。
        # 作用是**让评委看到完整链路**——即使没配视觉模型，也能演示"读图 → 去杂 → 抽取"长什么样。
        # 一旦配置了 LLM_VISION_MODEL，走真实视觉模型，这份预置结果自动让位（见 _run_sample）。
        "fixture": {
            "title": "机器学习导论 · 第 3 章 逻辑回归与分类",
            "directions": ["机器学习", "深度学习"],
            "summary": "扫描页正文为 3.1 Sigmoid 函数与 3.2 决策边界，含函数定义句、取值判定表与本节要点。",
            "knowledge_points": [
                {"name": "Sigmoid 函数", "difficulty": "B", "keywords": ["机器学习"]},
                {"name": "决策边界", "difficulty": "B", "keywords": ["机器学习"]},
                {"name": "极大似然估计", "difficulty": "A", "keywords": ["机器学习"]},
            ],
            "detected_noise": ["页眉：机器学习导论 · 课件 / CS2301", "页码：第 42 页",
                               "水印：内部资料 请勿外传", "目录点线：3.1 / 3.2 两条"],
            "expected_rule_set": "课件规则集（概念型 / 原理型）",
        },
    },
    {
        "id": "img-homework",
        "title": "手写作业（含红笔批注）",
        "ability": "parse",
        "type": "image",
        "file": "手写作业.png",
        "kind": "homework",
        "category": "作业",
        "points": "看点：手写答案与教师批注分开认；题干动词决定布鲁姆层级。",
        "fixture": {
            "title": "作业三 · 梯度下降（林思远 stu02）",
            "directions": ["机器学习"],
            "summary": "第 2 题：推导批量梯度下降更新公式并说明学习率过大的后果。手写推导步骤完整，"
                       "红笔批注「推导正确，但未说明凸性假设 -3」，得分 17 / 20。",
            "knowledge_points": [
                {"name": "批量梯度下降更新公式", "difficulty": "B", "keywords": ["机器学习"]},
                {"name": "学习率与收敛性", "difficulty": "A", "keywords": ["机器学习"]},
                {"name": "损失函数的凸性假设", "difficulty": "A", "keywords": ["机器学习"]},
            ],
            "detected_noise": ["扫描倾斜（约 -1.1°）", "纸张噪点", "红笔批注（应分离为教师反馈，不算正文）"],
            "expected_rule_set": "作业规则集（考点型，按题号切分）",
        },
    },
    {
        "id": "img-paper",
        "title": "论文截图（摘要 / 关键词 / 方法段）",
        "ability": "parse",
        "type": "image",
        "file": "论文截图.png",
        "kind": "paper",
        "category": "论文",
        "points": "看点：论文结构被认出来后，交给论文规则集抽方法术语。",
        "fixture": {
            "title": "面向课程知识点的多模态检索增强问答方法",
            "directions": ["多模态", "知识图谱", "机器学习"],
            "summary": "摘要提出融合关键词检索与稠密向量检索的方法，并用 RRF 重排序；"
                       "实验显示相较 BM25 基线召回率提升 12.4 个百分点。",
            "knowledge_points": [
                {"name": "双路检索融合", "difficulty": "A", "keywords": ["多模态"]},
                {"name": "RRF 倒数排序融合", "difficulty": "A", "keywords": ["多模态"]},
                {"name": "稠密检索与句向量", "difficulty": "A", "keywords": ["多模态"]},
            ],
            "detected_noise": ["页面编号与页边距留白"],
            "expected_rule_set": "论文规则集（方法型 / 术语型 / 结论型）",
        },
    },
    {
        "id": "md-courseware",
        "title": "机器学习导论课件（文本）",
        "ability": "parse",
        "type": "text",
        "file": "机器学习导论课件.md",
        "kind": "courseware",
        "category": "课件",
        "points": "看点：解析 → 分块 → 切片 → 课件规则集抽知识点，一条龙。",
    },
    {
        "id": "md-paper",
        "title": "教师论文 · 多模态检索增强（文本）",
        "ability": "kp",
        "type": "text",
        "file": "教师论文-多模态检索增强.md",
        "kind": "paper",
        "category": "论文",
        "points": "看点：论文规则集会优先抓研究方法术语，而不是把参考文献当知识点。",
    },
    {
        "id": "md-lesson",
        "title": "教学设计 · 注意力机制（文本）",
        "ability": "kp",
        "type": "text",
        "file": "教学设计-注意力机制.md",
        "kind": "lesson",
        "category": "教案",
        "points": "看点：教案规则集围绕教学目标与重难点抽目标型知识点。",
    },
    {
        "id": "md-jd",
        "title": "实习岗位 · 检索方向（文本）",
        "ability": "kp",
        "type": "text",
        "file": "实习岗位-检索方向.md",
        "kind": "jd",
        "category": "岗位",
        "points": "看点：岗位规则集从任职要求里抽技能型知识点，用于学业—就业匹配。",
    },
    {
        "id": "md-homework",
        "title": "作业样本 · 优（文本）",
        "ability": "kp",
        "type": "text",
        "file": "作业样本-优.md",
        "kind": "homework",
        "category": "作业",
        "points": "看点：作业规则集按题号切分，用题干动词定布鲁姆层级。",
    },
]

# ================================================================ 测试用例
# expected 全部写死；runner 指向真实实现入口 —— live=True 时才会真的执行。
CASES: list[dict[str, Any]] = [
    {
        "id": "parse-denoise",
        "ability": "parse",
        "title": "去杂：页码 / 水印 / 目录点线应被清掉",
        "input": {
            "text": "机器学习导论 · 课件\n"
                    "\n"
                    "3.1 Sigmoid 函数 .......... 42\n"
                    "3.2 决策边界 .......... 45\n"
                    "\n"
                    "Sigmoid 函数是指把任意实数映射到 (0,1) 的单调可微函数。\n"
                    "\n"
                    "内部资料 请勿外传\n"
                    "第 42 页\n"
                    "第 43 页\n"
                    "\n"
                    "它把线性输出压缩成概率，可直接用极大似然估计求解。\n",
        },
        "expected": {
            "noise_hits": {"page_number": 2, "watermark": 1, "toc": 2},
            "min_blocks": 2,
            "min_chunks": 1,
        },
        "runner": "parsekit.parse_document",
        "note": "输入是一段手工拼出来的脏文本，三条去杂规则必须各自命中。",
    },
    {
        "id": "kp-courseware",
        "ability": "kp",
        "title": "课件规则集：应抽出定义句与标题",
        "input": {"sample": "md-courseware"},
        "expected": {"rule_set": "courseware", "min_items": 2},
        "runner": "kprules.extract",
        "note": "规则集必须是 courseware —— 如果跑成了 default，说明场景选路失效。",
    },
    {
        "id": "kp-paper",
        "ability": "kp",
        "title": "论文规则集：应优先抓研究方法术语",
        "input": {"sample": "md-paper"},
        "expected": {"rule_set": "paper", "min_items": 2},
        "runner": "kprules.extract",
        "note": "论文规则集带研究方法术语表，抽出「检索增强 / 重排序」这类才算对。",
    },
    {
        "id": "kp-lesson",
        "ability": "kp",
        "title": "教案规则集：围绕教学目标抽目标型知识点",
        "input": {"sample": "md-lesson"},
        "expected": {"rule_set": "lesson", "min_items": 2},
        "runner": "kprules.extract",
        "note": "",
    },
    {
        "id": "kp-jd",
        "ability": "kp",
        "title": "岗位规则集：从任职要求抽技能型知识点",
        "input": {"sample": "md-jd"},
        "expected": {"rule_set": "jd", "min_items": 2},
        "runner": "kprules.extract",
        "note": "",
    },
    {
        "id": "qa-student-concept",
        "ability": "qa",
        "title": "学生 · 概念辨析应被正确分类",
        "input": {"question": "注意力机制为什么要除以根号 d_k？", "side": "student"},
        "expected": {"intent_type": "concept"},
        "runner": "interaction.classify",
        "note": "分类错了，后面整套分层讲解的口径都会跟着错。",
    },
    {
        "id": "qa-student-homework",
        "ability": "qa",
        "title": "学生 · 作业卡点应被正确分类",
        "input": {"question": "这道题卡在第三步，梯度一直不收敛怎么办？", "side": "student"},
        "expected": {"intent_type": "homework"},
        "runner": "interaction.classify",
        "note": "",
    },
    {
        "id": "qa-teacher-grading",
        "ability": "qa",
        "title": "教师 · 评分标准应路由到 grading 技能",
        "input": {"question": "这份作业怎么给分？给我一份评分标准", "side": "teacher"},
        "expected": {"intent_type": "grading"},
        "runner": "copilot.detect_intent",
        "note": "",
    },
    {
        "id": "qa-clarify",
        "ability": "qa",
        "title": "答疑协议：问题太短时应先澄清而不是硬答",
        "input": {"question": "这个为什么", "side": "student"},
        "expected": {"need_clarify": True},
        "runner": "interaction.needs_clarify",
        "note": "宁可多问一句，也不编一个看起来像答案的东西。",
    },
]


# ================================================================ 内部工具
def _read_sample(sample: dict[str, Any]) -> tuple[Path | None, str]:
    path = SAMPLES_DIR / str(sample.get("file") or "")
    if not path.exists():
        return None, ""
    if sample.get("type") == "image":
        return path, ""
    try:
        return path, path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return path, ""


def _sample_by_id(sid: str) -> dict[str, Any] | None:
    return next((s for s in SAMPLES if s["id"] == sid), None)


def _case_by_id(cid: str) -> dict[str, Any] | None:
    return next((c for c in CASES if c["id"] == cid), None)


def _run_sample(sample: dict[str, Any]) -> dict[str, Any]:
    sid = sample["id"]
    path, text = _read_sample(sample)
    if path is None:
        return {"sample_id": sid, "error": f"示例文件缺失：samples/{sample.get('file')}"}

    if sample.get("type") == "image":
        # 两条路，必须分清楚，不能混为一谈：
        #   1) 配了视觉模型 → 真正读图（engine=llm）
        #   2) 没配 → **内置素材直接给预置解析结果**，因为图片是仓库自带的、
        #      内容确定，写死是诚实的（engine=fixture）。这样评委能看到完整链路。
        #   3) 用户自己新上传的图片不属于这里 —— 那条路走 /api/materials/upload，
        #      没配视觉模型时会如实提示"本次未真正读图"，绝不拿预置结果冒充。
        if llm.api_ready():
            data = path.read_bytes()
            parsed, engine = extract.parse_material(
                sample.get("kind", "other"), path.name, "", image_b64=base64.b64encode(data).decode()
            )
            return {"sample_id": sid, "type": "image", "engine": engine,
                    "source": "vision", "parsed": parsed,
                    "vision_note": str(parsed.get("note") or "")}

        fixture = dict(sample.get("fixture") or {})
        return {
            "sample_id": sid, "type": "image", "engine": "fixture", "source": "builtin",
            "parsed": {k: v for k, v in fixture.items()
                       if k in ("title", "directions", "summary", "knowledge_points")},
            "detected_noise": fixture.get("detected_noise") or [],
            "expected_rule_set": fixture.get("expected_rule_set") or "",
            "vision_note": "内置示例：图片是仓库自带素材、内容确定，这里给出**预置解析结果**，"
                           "用于完整演示「读图 → 去杂 → 抽取」链路。配置 LLM_VISION_MODEL 后"
                           "会自动切换为真实视觉模型读图，预置结果让位。",
        }

    # 文本：完整走一遍 解析 → 去杂 → 分块 → 抽取
    doc = parsekit.parse_document(path.name, sample.get("kind", "other"), text)
    kp = kprules.extract(text, kind=sample.get("kind", ""), category=sample.get("category", ""),
                         blocks=doc["blocks"], limit=8)
    return {
        "sample_id": sid, "type": "text", "engine": "rule",
        "parse": parsekit.preview_report(doc),
        "kp": {"rule_set": kp["rule_set"], "stats": kp["stats"],
               "items": [{k: i[k] for k in ("name", "kp_type", "bloom", "difficulty", "anchor")}
                         for i in kp["items"]]},
    }


# ================================================================ 对外
def list_samples() -> list[dict[str, Any]]:
    out = []
    for s in SAMPLES:
        path = SAMPLES_DIR / str(s.get("file") or "")
        out.append({**s, "file": f"samples/{s.get('file')}",
                    "available": path.exists(),
                    "size_kb": round(path.stat().st_size / 1024) if path.exists() else 0})
    return out


def run_sample(sid: str) -> dict[str, Any]:
    sample = _sample_by_id(sid)
    if not sample:
        return {"error": f"示例不存在：{sid}"}
    return _run_sample(sample)


def list_cases() -> list[dict[str, Any]]:
    return [{k: c[k] for k in ("id", "ability", "title", "input", "expected", "runner", "note")}
            for c in CASES]


def run_case(cid: str, live: bool = False) -> dict[str, Any]:
    """``live=False`` 返回写死的期望（fixture 模式，稳定可复现、断网可用）；
    ``live=True`` 真的执行一遍并和期望比对（接口已留好，接真实实现只改 runner 指向）。"""
    case = _case_by_id(cid)
    if not case:
        return {"error": f"用例不存在：{cid}"}
    expected = case["expected"]
    if not live:
        return {"mode": "fixture", "status": "约定", "case_id": cid,
                "expected": expected, "runner": case["runner"],
                "note": "写死期望，未执行真实链路。传 live=true 可真实跑一遍。"}

    actual, checks, ok = _execute(case), [], True
    ability = case["ability"]
    if ability == "parse":
        noise = {r["id"]: r["hits"] for r in (actual.get("noise") or {}).get("rules", []) if r["hits"]}
        for rid, want in (expected.get("noise_hits") or {}).items():
            good = noise.get(rid, 0) >= want
            checks.append({"name": f"去杂规则 {rid} ≥ {want}", "pass": good,
                           "actual": noise.get(rid, 0)})
            ok = ok and good
        for key in ("min_blocks", "min_chunks"):
            if key in expected:
                field = "blocks" if key == "min_blocks" else "chunks"
                value = int((actual.get("doc") or {}).get(field) or 0)
                good = value >= expected[key]
                checks.append({"name": f"{field} ≥ {expected[key]}", "pass": good, "actual": value})
                ok = ok and good
    elif ability == "kp":
        rs = (actual.get("rule_set") or {}).get("id")
        good = rs == expected.get("rule_set")
        checks.append({"name": f"规则集 = {expected.get('rule_set')}", "pass": good, "actual": rs})
        ok = ok and good
        count = len(actual.get("items") or [])
        good = count >= expected.get("min_items", 1)
        checks.append({"name": f"知识点数 ≥ {expected.get('min_items')}", "pass": good, "actual": count})
        ok = ok and good
    else:
        for key, want in expected.items():
            value = actual.get(key)
            good = value == want
            checks.append({"name": f"{key} = {want}", "pass": good, "actual": value})
            ok = ok and good

    return {"mode": "live", "status": "PASS" if ok else "FAIL", "case_id": cid,
            "expected": expected, "checks": checks, "actual": actual,
            "runner": case["runner"]}


def _execute(case: dict[str, Any]) -> dict[str, Any]:
    """真实链路。接真实模型后只需在对应分支补模型调用，用例与比对逻辑不用动。"""
    ability, inp = case["ability"], case.get("input") or {}
    if ability == "parse":
        doc = parsekit.parse_document("case-input.txt", "other", str(inp.get("text") or ""))
        return {"doc": doc["doc"], "noise": doc["noise"]}
    if ability == "kp":
        sample = _sample_by_id(str(inp.get("sample") or "")) or {}
        _, text = _read_sample(sample)
        kp = kprules.extract(text, kind=sample.get("kind", ""), category=sample.get("category", ""),
                             limit=8)
        return {"rule_set": kp["rule_set"], "items": kp["items"], "stats": kp["stats"]}
    if str(inp.get("side")) == "teacher":
        from services import copilot
        return {"intent_type": copilot.detect_intent(str(inp.get("question") or ""), "")}
    if case["runner"] == "interaction.needs_clarify":
        return {"need_clarify": bool(ia.needs_clarify(str(inp.get("question") or ""))["need_clarify"])}
    return {"intent_type": ia.classify(str(inp.get("question") or ""), "student")["type"]}


def overview() -> dict[str, Any]:
    """给页面一览用的汇总：几个示例、几条用例、live 模式是否可用。"""
    return {
        "samples": len(SAMPLES),
        "cases": len(CASES),
        "by_ability": {
            "parse": sum(1 for c in CASES if c["ability"] == "parse"),
            "kp": sum(1 for c in CASES if c["ability"] == "kp"),
            "qa": sum(1 for c in CASES if c["ability"] == "qa"),
        },
        "llm_mode": llm.describe(),
    }


# 供自检脚本复用：json 可序列化的用例清单
def dump_cases() -> str:
    return json.dumps(CASES, ensure_ascii=False, indent=2)
