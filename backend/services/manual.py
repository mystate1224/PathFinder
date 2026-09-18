# -*- coding: utf-8 -*-
"""manual.py —— 三项能力的**说明手册数据源**。

写法约定：**给老师和学生看的，不是给开发看的。**
不出现字段名、正则、模块路径；每一条都回答"这对我有什么用 / 我该怎么理解"。
只有最后一个「给开发者的接口清单」保留技术细节，并在页面上明确标注
「使用者可以忽略」，避免把实现细节塞给不需要它的人。

规则表仍然来自代码（``parsekit.NOISE_RULES`` / ``kprules.KP_RULE_SETS`` /
``interaction``），所以改了规则，手册里列出的条目跟着变。

接口：``GET /api/manual`` → ``{version, chapters:[...], api:[...], agents:{...}}``
章节支持三种块：``text``（段落） / ``list``（条目） / ``table``（表格）。
"""
from __future__ import annotations

from typing import Any

from services import interaction as ia
from services import kprules
from services import parsekit

VERSION = "v3.1"

# 接口清单：留给要接手代码的人。使用者可以忽略这一页。
API_INDEX: list[dict[str, str]] = [
    {"module": "services/parsekit.py", "symbol": "parse_document(filename, kind, text)",
     "purpose": "解析主入口，返回 ParseResult（blocks / chunks / assets / noise / outline）"},
    {"module": "services/parsekit.py", "symbol": "denoise(text, rules)",
     "purpose": "去杂。rules 可传入子集做开关对比，返回 (清洗文本, 命中报告)"},
    {"module": "services/parsekit.py", "symbol": "NOISE_RULES",
     "purpose": "去杂规则表（数据）。加规则只需 append，不动流程"},
    {"module": "services/parsekit.py", "symbol": "chunk_blocks(blocks, size, overlap)",
     "purpose": "语义切片：标题边界优先、句边界兜底，切片带 block_ids 可回溯"},
    {"module": "services/kprules.py", "symbol": "extract(text, kind, category, blocks, limit)",
     "purpose": "场景化知识点抽取，返回 KPResult（含 rule_set 标识）"},
    {"module": "services/kprules.py", "symbol": "KP_RULE_SETS",
     "purpose": "五套场景规则集（课件 / 论文 / 作业 / 教案 / 岗位 JD）+ 通用兜底"},
    {"module": "services/kprules.py", "symbol": "bloom_of / difficulty_of",
     "purpose": "按题干动词定布鲁姆层级；A/B/C 只表示内容深度"},
    {"module": "services/interaction.py", "symbol": "classify(question, side)",
     "purpose": "问题分类（学生 7 类 / 教师 6 类），返回 type + confidence"},
    {"module": "services/interaction.py", "symbol": "needs_clarify(question, hits)",
     "purpose": "协议第一段：判断是否需要先澄清，并给出澄清问题"},
    {"module": "services/interaction.py", "symbol": "scaffold_of(level)",
     "purpose": "协议第二段：按层次取脚手架强度（只影响讲解深度，不分班）"},
    {"module": "services/interaction.py", "symbol": "followups_of / actions_of",
     "purpose": "协议第四段：生成追问建议与可执行下一步"},
    {"module": "services/tutor.py", "symbol": "ask(user, question, course, top_k)",
     "purpose": "学生分层答疑入口，返回 answer + intent + protocol + followups + actions"},
    {"module": "services/copilot.py", "symbol": "ask(teacher, question, skill)",
     "purpose": "教师 Copilot 入口，意图路由 + plan + actions"},
]

# 去杂规则的白话解释（与代码里的规则一一对应，只是换成使用者读得懂的话）
_NOISE_PLAIN: dict[str, str] = {
    "ctrl": "扫描或转换时产生的乱码",
    "page_number": "页码",
    "watermark": "「内部资料」「样章」这类水印和密级字样",
    "toc": "目录里那些带点线的标题行",
    "nav": "「上一页 / 返回目录」这类网页残留",
    "url": "单独的网址链接和扫码提示",
    "dup_line": "重复出现的页眉页脚",
    "blank": "多余的空行",
    "short_frag": "换行断掉的零碎字",
}


def _chapter_parse() -> dict[str, Any]:
    elements = [
        ["标题", "哪是章、哪是节，先分清层次"],
        ["正文", "真正要学的内容"],
        ["列表 / 条目", "并列列举的步骤和要求"],
        ["表格", "会整张保留，不会被切碎"],
        ["代码 / 公式", "单独留出来，方便原样展示"],
        ["图片与图注", "记下图片和它的说明文字"],
    ]
    rows = [[_NOISE_PLAIN.get(r["id"], r["name"]), r["why"].replace("会污染切分与向量", "会影响后面的查找")]
            for r in parsekit.NOISE_RULES]
    return {
        "id": "parse",
        "title": "① 上传的资料是怎么被读懂的",
        "summary": "你把资料传上来，系统会先看清楚它是什么、哪些有用、哪些该扔掉，再整理成方便查找的样子。",
        "sections": [
            {"type": "text", "title": "第一步：看清楚里面有什么",
             "body": "文档里的标题、正文、列表、表格、代码、公式、图片，会被一样一样认出来。"
                     "认出来之后才知道哪些是重点、哪些只是排版。"},
            {"type": "table", "title": "它会认出这些", "columns": ["内容", "认出来有什么用"], "rows": elements},
            {"type": "text", "title": "第二步：先把没用的清掉",
             "body": "页码、水印、目录、重复的页眉页脚这些不会影响学习，但会干扰查找。"
                     "系统会先把它们清掉，并且告诉你清掉了多少——不是悄悄删。"},
            {"type": "table", "title": "会被清掉的东西", "columns": ["清掉什么", "为什么要清掉"], "rows": rows},
            {"type": "list", "title": "第三步：整理成好用的样子", "items": [
                "按章节切成一个个小块，查找时能精确定位，而不是整篇糊在一起",
                "整理出一份目录大纲，一眼看到这份资料讲了哪几块",
                "表格、代码、公式、图片单独登记，不会被切成碎片",
                "以后无论抽知识点还是回答提问，都能指回原文位置",
            ]},
        ],
    }


def _chapter_kp() -> dict[str, Any]:
    return {
        "id": "kp",
        "title": "② 知识点是怎么抽出来的",
        "summary": "不同类型的资料，抽法不一样。课件看「讲了哪几个概念」，作业看「考的是哪个点」。",
        "sections": [
            {"type": "text", "title": "一套方法套不住所有资料",
             "body": "如果用同一种办法去抽，课件会把目录当知识点，论文会把参考文献当知识点，"
                     "抽出来的东西没法用。所以系统会先判断这是哪一类资料，再换对应的抽法。"},
            {"type": "list", "title": "五类资料，五种抽法", "items": [
                "课件 / 讲义：抓章节标题，再补上「……是指……」这类定义句 → 抽出来的是概念",
                "论文 / 报告：看摘要、方法、实验、结论各说了什么，重点抓研究方法 → 抽出来的是方法和术语",
                "作业 / 试题：按题号一道一道看，从「求 / 证明 / 设计」这类词判断考到哪一层 → 抽出来的是考点",
                "教案：围绕教学目标和重难点 → 抽出来的是这节课要达成的目标",
                "岗位要求：从任职要求里抓技能词 → 抽出来的是岗位需要的技能",
                "认不出来是哪一类的：退回到「抓标题」的通用办法，保证不会什么都抽不出来",
            ]},
            {"type": "text", "title": "抽出来的每一条长什么样",
             "body": "一条知识点 = 名称 + 属于哪一类 + 深浅程度 + 原文依据。"
                     "有原文依据这一项很关键：任何一条都能点回材料里看它到底出自哪里，不是凭空生成的。"},
            {"type": "text", "title": "深浅程度是什么意思",
             "body": "标成 A / B / C 只表示这个内容本身有多深（要不要推导、是不是前沿），"
                     "用来决定推荐多深的内容和布置多难的任务。**它不代表学生被分成几等，也不用于分班。**"},
        ],
    }


def _chapter_qa() -> dict[str, Any]:
    student_labels = "、".join(t["label"] for t in ia.QUESTION_TYPES["student"])
    teacher_labels = "、".join(t["label"] for t in ia.QUESTION_TYPES["teacher"])
    return {
        "id": "qa",
        "title": "③ 提问之后会发生什么",
        "summary": "不是问一句答一句就结束。系统会先判断你问的是哪一类，再决定怎么讲、讲多深，最后给你下一步。",
        "sections": [
            {"type": "table", "title": "可以问什么", "columns": ["谁在问", "适合问这些"],
             "rows": [["学生", student_labels], ["教师", teacher_labels]]},
            {"type": "list", "title": "回答的四步", "items": [
                "先确认：问题太笼统、看不出问的是什么时，会先请你说具体一点，而不是硬答",
                "搭梯子：按你目前的进度决定讲多深——基础薄弱就拆细一点配示范，学有余力就给方向留思考空间",
                "正式回答：说清楚，并且标出这句话出自哪份资料",
                "给下一步：附上还能接着问什么，以及接下来可以做什么（练一道、看原文、转问老师）",
            ]},
            {"type": "text", "title": "回答里一定会带上的三样东西",
             "body": "① 依据出处——哪句话来自哪份资料，能点回去核对；"
                     "② 还能接着问什么——一键就能继续追问；"
                     "③ 下一步做什么——把一次问答变成一次推进，而不是看完就结束。"},
            {"type": "text", "title": "没有依据时会怎么办",
             "body": "如果资料库里确实没有相关内容，它会直接说明「没找到」，不会编一个看起来像答案的东西。"
                     "这一点比答得漂亮更重要。"},
            {"type": "text", "title": "关于分层",
             "body": "同一个问题，不同人看到的讲解深度可能不同。这只是内容深浅和任务难度的区别，"
                     "不影响你能问什么、能看什么，也不用于分班。"},
        ],
    }


def build() -> dict[str, Any]:
    """组装手册。前端「查看说明手册」按钮读的就是这份数据。"""
    return {
        "version": VERSION,
        "updated_note": "这本手册讲「它是怎么工作的」，不涉及任何技术细节；最后一页是给开发者的接口清单。",
        "chapters": [_chapter_parse(), _chapter_kp(), _chapter_qa()],
        "api": API_INDEX,
        "api_note": "这一页是给要接手代码的人看的。使用平台的老师和同学可以直接跳过。",
    }


def agents() -> dict[str, Any]:
    """两个智能体的简介卡数据（界面右侧紧凑展示），用大白话写。"""
    return {
        "student": {
            "name": "学习助手",
            "entry": "/ask",
            "one_line": "卡住了就问它。它会按你现在的进度决定从哪里讲起、讲多深。",
            "answers": [t["label"] for t in ia.QUESTION_TYPES["student"]],
            "how": "先确认你问的是什么 → 按你的进度讲 → 标出出处 → 给你下一步",
            "ground": "只引用老师上传的资料，没找到会直接说明，不会编",
            "caveat": "讲解深度因人而异，这只是内容深浅，不代表分班。",
        },
        "teacher": {
            "name": "教师助手",
            "entry": "/tutor",
            "one_line": "一句话让它干活：查学生、备课、讲知识点、定评分标准。",
            "answers": [t["label"] for t in ia.QUESTION_TYPES["teacher"]],
            "how": "判断你想做什么 → 取数据或查资料 → 给出可直接用的结果",
            "ground": "查事实用班里的真实数据，讲内容用你上传的资料，两者分开展示",
            "caveat": "它按固定流程工作，不会自己去做你没让它做的事。",
        },
    }
