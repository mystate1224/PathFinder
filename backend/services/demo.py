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
from services import extract, interaction as ia, kprules, parsekit, teaching

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"

# 备课演示用的示例讲义：教师点「上传示例讲义生成 PPT」时直接拿它当素材，
# 免得演示前还得先找一份资料。文件内容确定，用例才能写死期望。
LECTURE_FILE = SAMPLES_DIR / "备课示例讲义.md"
LECTURE_FALLBACK = (
    "注意力机制通过查询与键的点积计算权重，再对值加权求和。\n"
    "缩放点积注意力把点积结果除以根号 d_k，避免 softmax 进入饱和区导致梯度消失。\n"
    "多头注意力用多个头并行关注不同子空间，最后拼接并做一次线性投影。\n"
)


def lecture_text() -> str:
    """读取示例讲义正文（文件缺失时退回内置短文本，保证演示不中断）。"""
    try:
        text = LECTURE_FILE.read_text(encoding="utf-8")
        return text if len(text.strip()) >= 20 else LECTURE_FALLBACK
    except OSError:
        return LECTURE_FALLBACK


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
    # ---- 问答集：不跑解析，直接给一批可以直接粘进输入框的问题与验收点
    {
        "id": "qa-set-student",
        "title": "学生侧 · 答疑问答集（含验收点）",
        "ability": "qa",
        "type": "qa",
        "file": "答疑问答集-学生.md",
        "side": "student",
        "points": "每条写清了期望的答疑类型与应走的 RAG 架构，可一键填入对话框逐条验收。",
    },
    {
        "id": "qa-set-teacher",
        "title": "教师侧 · Copilot 问答集（含验收点）",
        "ability": "qa",
        "type": "qa",
        "file": "答疑问答集-教师.md",
        "side": "teacher",
        "points": "覆盖备课 / 讲知识点 / 查学生 / 批改标准四类技能，并含多模态与纠错的路由验证。",
    },
    {
        "id": "qa-rag-route",
        "title": "RAG 路由测试题（五种架构各一组）",
        "ability": "qa",
        "type": "qa",
        "file": "RAG路由测试题.md",
        "side": "student",
        "points": "同一问题换种问法就该走不同 RAG。策略选「自动选择」逐条问，看徽标是否与判据一致。",
    },
]

# ================================================================ 测试用例
# expected 全部写死；runner 指向真实实现入口 —— live=True 时才会真的执行。
CASES: list[dict[str, Any]] = [
    # ---- 学生智能体三类高频需求（v7.5）：演示与验收都从这三类开始 ----
    {
        "id": "qa-agent-note",
        "ability": "qa",
        "title": "学生 · 上传手写笔记 → 解析知识点",
        "input": {"question": "我上传了一份手写笔记，帮我解析里面的知识点", "side": "student"},
        "expected": {"intent_type": "material"},
        "runner": "interaction.classify",
        "note": "三类高频需求之一。应归入「资料解析」意图并触发上传解析链路"
                "（读图 / 去杂 → 抽知识点 → 入索引），而不是当成闲聊。",
    },
    {
        "id": "qa-agent-doc",
        "ability": "qa",
        "title": "学生 · 上传计算机网络文档 → 总结要点",
        "input": {"question": "我上传了一份计算机网络的文档，帮我总结一下要点", "side": "student"},
        "expected": {"intent_type": "material"},
        "runner": "interaction.classify",
        "note": "总结要点必须可溯源：要点应能在原文找到出处，材料之外的延伸要标明是推理。",
    },
    {
        "id": "qa-agent-career",
        "ability": "qa",
        "title": "学生 · 应聘前端 → 就业信息规划问答",
        "input": {"question": "我想应聘前端开发岗，结合我的情况给我一份求职规划", "side": "student"},
        "expected": {"intent_type": "path"},
        "runner": "interaction.classify",
        "note": "就业类路径规划：应对照前端岗位的任职要求与学生画像找差距，给分阶段计划。",
    },
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
    # ---- 批改建议分（链路 E 的演示用例，v7.5）：图片在前、文字在后 ----
    {
        "id": "grade-image",
        "ability": "grade",
        "title": "批改 · 图片作业应给出 AI 建议分（手写作业）",
        "input": {"image_sample": "img-homework", "course": "机器学习",
                  "title": "作业三 · 梯度下降", "full_score": 20},
        "expected": {
            "score": "0~20 分（配了视觉模型真读图）；未配置时 = -1 并如实提示人工批改",
            "level": "A / B / C（仅真读图时有）",
            "comment": "非空，说明给分依据或转人工原因",
        },
        "runner": "homework.suggest_image_bytes",
        "note": "图片是仓库自带素材（手写作业.png）。两种结果都算 PASS：真读图给分，"
                "或未配视觉模型时如实转人工 —— 唯独不许没读图还编一个分数。",
    },
    {
        "id": "grade-text",
        "ability": "grade",
        "title": "批改 · 文字作业应给出 AI 建议分（试批）",
        "input": {"sample": "md-homework", "course": "机器学习", "full_score": 100},
        "expected": {
            "score_in": [0, 100],
            "level_in": ["A", "B", "C"],
            "has_comment": True,
            "has_highlights": True,
            "full_score": 100,
        },
        "runner": "homework.suggest_text",
        "note": "试批不落库：输入是仓库里的作业样本（优），要点覆盖 + 结构 + 篇幅三路给分，"
                "双引擎返回结构一致。",
    },
    # ---- RAG 路由（能力⑦）：五种架构各一条，判据就是"该走哪种"
    {
        "id": "rag-route-hybrid",
        "ability": "rag",
        "title": "路由：概念题应走混合式 RAG",
        "input": {"question": "什么是反向传播？"},
        "expected": {"strategy": "hybrid"},
        "runner": "ragroute.route",
        "note": "短问题不能因为字数少就被当成口语指代，否则会误走纠错式。",
    },
    {
        "id": "rag-route-graph",
        "ability": "rag",
        "title": "路由：问关系应走图谱 RAG",
        "input": {"question": "注意力机制和 Transformer 有什么关系？"},
        "expected": {"strategy": "graph"},
        "runner": "ragroute.route",
        "note": "关系类问题靠字面检索答不好，要先取子图再取证据。",
    },
    {
        "id": "rag-route-agentic",
        "ability": "rag",
        "title": "路由：要结合我的情况应走智能体式 RAG",
        "input": {"question": "结合我的情况给我一个复习计划"},
        "expected": {"strategy": "agentic"},
        "runner": "ragroute.route",
        "note": "复合任务要先规划，再逐个调资料 / 知识点库 / 学情画像。",
    },
    {
        "id": "rag-route-corrective",
        "ability": "rag",
        "title": "路由：口语指代应走纠错型 RAG",
        "input": {"question": "那个到底为什么不work？"},
        "expected": {"strategy": "corrective"},
        "runner": "ragroute.route",
        "note": "首查大概率落空，得先改写再查，而不是硬答。",
    },
    {
        "id": "rag-route-multimodal",
        "ability": "rag",
        "title": "路由：问图片应走多模态 RAG",
        "input": {"question": "课件里那张图说明了什么？"},
        "expected": {"strategy": "multimodal"},
        "runner": "ragroute.route",
        "note": "只检索文本块会漏掉图片素材，必须把图片一起召回。",
    },
    {
        "id": "synth-student",
        "ability": "synth",
        "title": "综合生成（学生侧）：答案应是结论 + 推理，不是原文拼接",
        "input": {
            "role": "student",
            "question": "过拟合和正则化是什么关系？",
            "intent": "concept",
            "track": "学业型",
            "level": "B",
            "hits": [
                {"ref": "机器学习-第3讲.md#1",
                 "content": "正则化通过在损失函数中加入惩罚项限制模型复杂度，从而缓解过拟合。"},
                {"ref": "作业讲评-第2次.md#1",
                 "content": "正则化系数越大，模型越简单，偏差越大、方差越小。"},
            ],
        },
        "expected": {"steps": 5, "evidence": 2, "has_conclusion": True, "has_infer": True},
        "runner": "synth.rule_compose",
        "note": "五步视图 + 两条证据 + 一句推断句，缺一项就说明退化成了片段罗列。",
    },
    {
        "id": "synth-teacher",
        "ability": "synth",
        "title": "综合生成（教师侧）：讲解型推理要给出课堂讲法",
        "input": {
            "role": "teacher",
            "question": "讲一下正则化",
            "intent": "explain",
            "level": "A",
            "hits": [
                {"ref": "课件-正则化.md#1",
                 "content": "正则化的作用是在经验风险上加入结构风险，控制模型复杂度。"},
                {"ref": "课件-正则化.md#2",
                 "content": "L1 倾向产生稀疏解，L2 让权重整体变小，两者适用场景不同。"},
            ],
        },
        "expected": {"steps": 5, "evidence": 2, "has_conclusion": True, "has_infer": True},
        "runner": "synth.rule_compose",
        "note": "教师侧同一套综合层，只是讲法换成课堂上先给结论、再展开。",
    },
    # ---- 备课（教案 / 教案转 PPT / 资料转 PPT）----
    {
        "id": "teach-lesson",
        "ability": "teach",
        "title": "备课（教案）：环节分钟数必须凑满总课时",
        "input": {"topic": "Dijkstra 算法", "course": "数据结构", "periods": 2, "level": "B"},
        "expected": {"segments": 4, "minutes_sum": 90, "has_homework": True},
        "runner": "teaching.rule_lesson_plan",
        "note": "2 课时 = 90 分钟。四个环节的分钟数加起来必须正好等于 90，" +
                "否则界面上的时间分配条与总时长对不上，老师一眼就能看出破绽。",
    },
    {
        "id": "teach-slides-from-lesson",
        "ability": "teach",
        "title": "备课（教案转 PPT）：沿用教案节奏，末尾固定小结页",
        "input": {
            "plan": {
                "title": "Dijkstra 算法 教案",
                "objectives": ["理解最短路的贪心选择性质", "能手算 Dijkstra 的每一步"],
                "key_points": ["每次取距离最小的未确定点", "优先队列的作用"],
                "difficulties": ["负权边不适用", "松弛操作的更新时机"],
                "outline": [
                    {"step": "导入", "content": "回顾 BFS 与最短路问题，抛出带权图怎么算", "minutes": 9},
                    {"step": "讲授", "content": "讲清贪心选择性质与优先队列的实现", "minutes": 41},
                    {"step": "演练", "content": "学生手算两道带权图最短路", "minutes": 27},
                    {"step": "小结", "content": "归纳步骤并布置作业", "minutes": 13},
                ],
                "homework": "课后第 1~5 题，写出每一步的距离表",
            },
            "pages": 8,
        },
        "expected": {"min_pages": 5, "last_title": "课堂小结与作业", "titles_all_filled": True},
        "runner": "teaching.rule_slides_from_plan",
        "note": "教案本身就是最好的提纲：环节页直接沿用教案的分钟配比，不另起一套节奏。",
    },
    {
        "id": "teach-slides-from-material",
        "ability": "teach",
        "title": "备课（资料转 PPT）：要点必须能在原文里找到出处",
        # text 用示例讲义文件（见 lecture_text），不在此处复制一份正文，避免两处不一致。
        "input": {"topic": "注意力机制", "pages": 8, "lecture_sample": True},
        "expected": {"min_pages": 3, "last_title": "课堂小结与作业", "grounded": True},
        "runner": "teaching.rule_slides_from_text",
        "note": "grounded = 内容页的每个要点都能在讲义原文里找到；" +
                "开场页与小结页是通用引导语，刻意不计入。",
    },
]


# ================================================================ 内部工具
def parse_qa_file(text: str) -> list[dict[str, str]]:
    """把问答集文件解析成 ``[{section, question, expect, source}]``。

    格式刻意做得像人写的笔记（``## 小节`` / ``Q: 问题`` / ``期望：…`` / ``依据：…``），
    既能直接读，也能被机器解析 —— 素材与用例不脱节。
    """
    items: list[dict[str, str]] = []
    section = ""
    cur: dict[str, str] | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if line.startswith("Q:"):
            if cur:
                items.append(cur)
            cur = {"section": section, "question": line[2:].strip(), "expect": "", "source": ""}
            continue
        if cur is None:
            continue
        if line.startswith("期望："):
            cur["expect"] = line[3:].strip()
        elif line.startswith("依据："):
            cur["source"] = line[3:].strip()
    if cur:
        items.append(cur)
    return items


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

    # 问答集：不跑解析，把文件里的 Q: / 期望：/ 依据：解析成可直接填入的列表
    if sample.get("type") == "qa":
        return {"sample_id": sid, "type": "qa", "engine": "rule", "source": "file",
                "title": sample["title"], "side": sample.get("side", "student"),
                "pairs": parse_qa_file(text)}

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
    elif ability == "teach":
        # 教案与 PPT 的期望各不相同，逐项比对（比通用字典相等好读，也便于定位是哪一项没做到）
        def add(name: str, good: bool, value: Any) -> None:
            nonlocal ok
            checks.append({"name": name, "pass": bool(good), "actual": value})
            ok = ok and bool(good)

        if "segments" in expected:
            segments = actual.get("outline") or []
            add(f"环节数 = {expected['segments']}", len(segments) == expected["segments"],
                len(segments))
            minutes = sum(int(s.get("minutes") or 0) for s in segments)
            add(f"分钟合计 = {expected['minutes_sum']}", minutes == expected["minutes_sum"], minutes)
        if "has_homework" in expected:
            add("有作业布置", bool(str(actual.get("homework") or "").strip()),
                str(actual.get("homework") or "")[:20])
        slides = actual.get("slides") or []
        if "min_pages" in expected:
            add(f"页数 ≥ {expected['min_pages']}", len(slides) >= expected["min_pages"], len(slides))
        if "last_title" in expected and slides:
            last = str(slides[-1].get("title") or "")
            add(f"末页 = {expected['last_title']}", last == expected["last_title"], last)
        if expected.get("titles_all_filled"):
            blank = sum(1 for s in slides if not str(s.get("title") or "").strip())
            add("每页都有标题", blank == 0, f"空标题 {blank} 页")
        if "grounded" in expected:
            hay = str(inp_text(case) or "")
            add("内容页要点均可溯源", _grounded(slides, hay), _grounded_rate(slides, hay))
    elif ability == "kp":
        rs = (actual.get("rule_set") or {}).get("id")
        good = rs == expected.get("rule_set")
        checks.append({"name": f"规则集 = {expected.get('rule_set')}", "pass": good, "actual": rs})
        ok = ok and good
        count = len(actual.get("items") or [])
        good = count >= expected.get("min_items", 1)
        checks.append({"name": f"知识点数 ≥ {expected.get('min_items')}", "pass": good, "actual": count})
        ok = ok and good
    elif ability == "grade":
        # 建议分不能断言"等于某个分数"——双引擎与模型都会让分数浮动，
        # 这里验的是**结构诚实**：给分有依据、越界不允许、没配视觉模型时如实转人工。
        def add(name: str, good: bool, value: Any) -> None:
            nonlocal ok
            checks.append({"name": name, "pass": bool(good), "actual": value})
            ok = ok and bool(good)

        score = float(actual.get("score") or 0)
        level = str(actual.get("level") or "")
        comment = str(actual.get("comment") or "").strip()
        inp = case.get("input") or {}
        if "image_sample" in inp:
            full = float(inp.get("full_score") or 20)
            if score < 0:
                add("未配视觉模型时如实转人工（score = -1）", bool(actual.get("manual")),
                    actual.get("manual"))
                add("转人工时说明原因", ("人工" in comment) or ("视觉" in comment), comment[:30])
            else:
                add(f"0 ≤ 建议分 ≤ {full}", 0 <= score <= full, score)
                add("层次 ∈ A/B/C", level in ("A", "B", "C"), level)
            add("有评语", bool(comment), comment[:30])
            add("引擎标识存在", actual.get("engine") in ("llm", "rule"), actual.get("engine"))
        else:
            full = float(inp.get("full_score") or 100)
            add(f"0 ≤ 建议分 ≤ {full}", 0 <= score <= full, score)
            add("层次 ∈ A/B/C", level in ("A", "B", "C"), level)
            add("有评语", bool(comment), comment[:30])
            hl, ms = actual.get("highlights") or [], actual.get("missing") or []
            add("有亮点与缺漏项", bool(hl) and bool(ms), f"亮点 {len(hl)} / 缺漏 {len(ms)}")
            add("满分口径一致", float(actual.get("full_score") or 0) == full, actual.get("full_score"))
    else:
        for key, want in expected.items():
            value = actual.get(key)
            good = value == want
            checks.append({"name": f"{key} = {want}", "pass": good, "actual": value})
            ok = ok and good

    return {"mode": "live", "status": "PASS" if ok else "FAIL", "case_id": cid,
            "expected": expected, "checks": checks, "actual": actual,
            "runner": case["runner"]}


def inp_text(case: dict[str, Any]) -> str:
    """用例输入里的正文：备课的资料用例直接读示例讲义，避免正文在两处各写一份。"""
    inp = case.get("input") or {}
    if inp.get("lecture_sample"):
        return lecture_text()
    return str(inp.get("text") or "")


def _grounded(slides: list[dict[str, Any]], hay: str) -> bool:
    """内容页的每个要点都能在原文里找到出处（开场页与小结页是通用引导语，不计入）。"""
    return _grounded_rate(slides, hay) >= 1.0


def _grounded_rate(slides: list[dict[str, Any]], hay: str) -> float:
    """可溯源要点占比 —— 比布尔值更好定位问题（差在哪一页能直接看出来）。"""
    inner = slides[1:-1] if len(slides) > 2 else slides
    bullets = [str(b).strip() for s in inner for b in (s.get("bullets") or []) if str(b).strip()]
    if not bullets:
        return 0.0
    hit = sum(1 for b in bullets if _in_text(b, hay))
    return round(hit / len(bullets), 2)


def _in_text(bullet: str, hay: str) -> bool:
    """整句命中，或其中任意 8 字片段命中 —— 允许要点被改写，但不允许凭空新增。"""
    if len(bullet) < 6:
        return True
    if bullet in hay:
        return True
    return any(bullet[i:i + 8] in hay for i in range(max(1, len(bullet) - 7)))


def _execute(case: dict[str, Any]) -> dict[str, Any]:
    """真实链路。接真实模型后只需在对应分支补模型调用，用例与比对逻辑不用动。"""
    ability, inp = case["ability"], case.get("input") or {}
    if ability == "teach":
        runner = str(case.get("runner") or "")
        if runner.endswith("rule_lesson_plan"):
            return teaching.rule_lesson_plan(
                inp.get("topic", ""), inp.get("course", ""),
                int(inp.get("periods") or 1), inp.get("level", "B"),
            )
        if runner.endswith("rule_slides_from_plan"):
            return teaching.rule_slides_from_plan(inp.get("plan") or {}, int(inp.get("pages") or 0))
        return teaching.rule_slides_from_text(
            inp.get("topic", ""), inp_text(case), int(inp.get("pages") or 8))
    if ability == "rag":
        from services import ragroute
        return {"strategy": ragroute.route(str(inp.get("question") or ""), "student")["strategy"]}
    if ability == "parse":
        doc = parsekit.parse_document("case-input.txt", "other", str(inp.get("text") or ""))
        return {"doc": doc["doc"], "noise": doc["noise"]}
    if ability == "kp":
        sample = _sample_by_id(str(inp.get("sample") or "")) or {}
        _, text = _read_sample(sample)
        kp = kprules.extract(text, kind=sample.get("kind", ""), category=sample.get("category", ""),
                             limit=8)
        return {"rule_set": kp["rule_set"], "items": kp["items"], "stats": kp["stats"]}
    if ability == "synth":
        from services import synth as _synth
        hits = inp.get("hits") or []
        text, view = _synth.rule_compose(
            str(inp.get("role") or "student"), str(inp.get("question") or ""), hits,
            track=str(inp.get("track") or "学业型"), level=str(inp.get("level") or "B"),
            intent=str(inp.get("intent") or ""),
        )
        return {
            "steps": len(view["steps"]),
            "evidence": view["evidence_count"],
            "has_conclusion": text.startswith("综合结论"),
            "has_infer": any(line in text for line in (
                _synth.infer_of(str(inp.get("intent") or "")),)),
            "answer": text,
        }
    if ability == "grade":
        # 批改建议分：图片用例直接读仓库自带素材的字节，文字用例读样本文件，
        # 都走 homework 的真实实现（与批改中心同一条代码路径）。
        from services import homework as hw
        if inp.get("image_sample"):
            sample = _sample_by_id(str(inp["image_sample"])) or {}
            path = SAMPLES_DIR / str(sample.get("file") or "")
            raw = path.read_bytes() if path.exists() else b""
            hwk = {"course": str(inp.get("course") or ""), "title": str(inp.get("title") or "")}
            return hw.suggest_image_bytes(raw, "image/png", hwk,
                                          float(inp.get("full_score") or 20), [])
        sample = _sample_by_id(str(inp.get("sample") or "")) or {}
        _, text = _read_sample(sample)
        return hw.suggest_text(text, course=str(inp.get("course") or ""),
                               full_score=float(inp.get("full_score") or 100))
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
            "rag": sum(1 for c in CASES if c["ability"] == "rag"),
            "synth": sum(1 for c in CASES if c["ability"] == "synth"),
            "teach": sum(1 for c in CASES if c["ability"] == "teach"),
            "grade": sum(1 for c in CASES if c["ability"] == "grade"),
        },
        "llm_mode": llm.describe(),
    }


# 供自检脚本复用：json 可序列化的用例清单
def dump_cases() -> str:
    return json.dumps(CASES, ensure_ascii=False, indent=2)
