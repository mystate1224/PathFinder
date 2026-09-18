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

from services import agenttools
from services import interaction as ia
from services import kprules
from services import parsekit
from services import ragroute
from services import synth

VERSION = "v4.1"

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
    {"module": "services/tutor.py", "symbol": "ask(user, question, course, top_k, session_id, strategy)",
     "purpose": "学生分层答疑入口，返回 answer + intent + protocol + followups + actions + session_id + rag"},
    {"module": "services/copilot.py", "symbol": "ask(teacher, question, skill, session_id, strategy)",
     "purpose": "教师 Copilot 入口，意图路由 + plan + actions + session_id + rag"},
    {"module": "services/ragroute.py", "symbol": "STRATEGIES / route(question, side) / resolve(question, side, strategy)",
     "purpose": "五种 RAG 架构的字典与路由；strategy 为 auto 时自动路由，否则按演示指定"},
    {"module": "services/ragroute.py", "symbol": "execute(strategy, question, user, top_k, course)",
     "purpose": "按策略取证据，返回 {strategy, hits, extra}，hits 与 hybrid_search 同构"},
    {"module": "services/ragroute.py", "symbol": "route_llm(question, side)",
     "purpose": "模型路由接口（已留好）：让模型五选一并给理由，规则路由作 mock 兜底"},
    {"module": "services/agenttools.py", "symbol": "TOOLS / GEN_KINDS",
     "purpose": "智能体工具注册表与生成类型表（数据）。加工具只 append，路由不用动"},
    {"module": "services/agenttools.py", "symbol": "tools_view(side) / run_tool(tool_id, args, user)",
     "purpose": "工具清单（给前端渲染表单）与统一执行入口"},
    {"module": "db.py", "symbol": "chat_sessions(user_id, scene, limit) / first_question(...)",
     "purpose": "会话目录：按 session_id 聚合出轮次、最后时间、首条提问"},
    {"module": "services/synth.py", "symbol": "compose(role, question, hits, ...)",
     "purpose": "综合生成层：检索之后组织推理，返回 (答案, engine, 视图)；模型可用走 LLM，否则规则版改写"},
    {"module": "services/synth.py", "symbol": "rule_compose(...) / REASON_RULES / INFER_RULES",
     "purpose": "规则版综合：按问题类型把证据串成推理链（数据驱动，加讲法只 append）"},
    {"module": "services/synth.py", "symbol": "evidence_of(hits, question, limit)",
     "purpose": "证据归集：每份资料留一句最相关的，重复内容自动合并"},
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
        "title": "① 资料怎么被读懂",
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
        "title": "② 知识点怎么抽出来",
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
        "title": "③ 提问后会发生什么",
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


def _chapter_rag() -> dict[str, Any]:
    rows = [[s["name"], s["when"], s["desc"]] for s in ragroute.STRATEGIES]
    return {
        "id": "rag",
        "title": "④ 怎么找材料",
        "summary": "找材料不是只有一种办法。系统会先看你问的是哪一类问题，再决定用哪种办法去查——查得对，才答得准。",
        "sections": [
            {"type": "text", "title": "为什么不能只用一种办法",
             "body": "「知识点怎么解释」「A 和 B 什么关系」「结合我的情况给我个计划」「那个为什么不行」"
                     "「课件里那张图讲的什么」——这五类问题要找的东西根本不一样。"
                     "只用一种办法去查，总有几类问题会查不到点上。所以系统先判断你问的是哪一类，再选对应的查法。"},
            {"type": "table", "title": "五种查法",
             "columns": ["查法", "什么时候用它", "它怎么做"], "rows": rows},
            {"type": "list", "title": "判断的过程是透明的", "items": [
                "每一条回答下面都会标出这次用的是哪种查法，以及为什么选它",
                "想对比效果，可以在输入框旁边手动切换成某一种查法再问一次",
                "判断错了也不怕：有些查法（比如口语指代那类）会自查一遍，发现没查到就换个说法再查一次",
                "断网、没有模型接口时，这套判断依然照常工作，不会卡住",
            ]},
            {"type": "text", "title": "为什么有时候它会多想一步",
             "body": "遇到「结合我的情况」这类问题，它会先把任务拆成几步——看看你目前的学情、"
                     "查一查相关资料、再汇总成一份能直接用的东西。这一步一步的中间过程在界面上是能看到的。"},
        ],
    }


def _chapter_agent() -> dict[str, Any]:
    tool_rows = [[t["name"], t["desc"]] for t in agenttools.TOOLS]
    gen_rows = [[k["label"], k["desc"]] for k in agenttools.GEN_KINDS]
    return {
        "id": "agent",
        "title": "⑤ 不止聊天，还能干活",
        "summary": "除了回答问题，它还能帮你把资料收进来、把材料做出来。做出来的东西每一句都能追到出处。",
        "sections": [
            {"type": "text", "title": "先说清楚：它是对话，也是能干活的助手",
             "body": "光聊天解决不了实际问题。学生需要「把我手上的资料喂给它、让它替我整理」；"
                     "教师需要「基于我上传的课件出一版备课草稿」。这些动作被做成了明确的按钮，"
                     "点开填一点信息就能跑，跑完的结果可以直接用。"},
            {"type": "table", "title": "它能做的两件事", "columns": ["动作", "做完会得到什么"], "rows": tool_rows},
            {"type": "table", "title": "生成资料可以选这些类型", "columns": ["类型", "适合什么时候用"], "rows": gen_rows},
            {"type": "list", "title": "做出来的东西怎么保证可信", "items": [
                "生成时会先去查你（或老师）上传过的资料，拿真实材料当依据，不是凭空写",
                "正文里标出引用了哪几份资料，能点回去核对——这就是「可溯源」",
                "回答里还会结合你目前的学情：哪里薄弱、进度到哪，讲法和推荐就不一样",
                "生成完可以一键存进资料库，之后提问时它也能引用这份新资料",
            ]},
            {"type": "text", "title": "上传进去的资料去哪了",
             "body": "会走一遍和教师上传资料一样的处理：清理没用的内容 → 认出结构 → 抽出知识点 → 建立索引。"
                     "处理完立刻就能被检索到，下一轮提问就能引用它。"},
        ],
    }


def _chapter_session() -> dict[str, Any]:
    return {
        "id": "session",
        "title": "⑥ 对话管理",
        "summary": "一次对话解决一件事。想换个话题就新开一次，想接着上次聊就回到那一次。",
        "sections": [
            {"type": "list", "title": "左边那一栏是这么安排的", "items": [
                "最上面是「全部会话」：按时间倒序列出每一次对话，点一条就回到那次",
                "下面是「本次对话」：当前这一次聊过的每一轮问答，点一下就能回看",
                "只想看内容：拖动中间的竖条可以调宽调窄",
            ]},
            {"type": "list", "title": "新开 / 切换 / 清空", "items": [
                "点「新开对话」就起一条全新的线，之前的都还留在列表里",
                "每次提问都会记在当前这一次对话下，不会串到别的话题里",
                "「清空」只清当前这一次，别的对话不受影响",
            ]},
            {"type": "text", "title": "为什么要把对话分开",
             "body": "一个话题一个上下文，回答才会连贯、不会把上一个话题的内容混进来；"
                     "回头复习的时候也更容易找到当时在聊什么。"},
        ],
    }


def _chapter_synth() -> dict[str, Any]:
    steps = [[s["name"], s["desc"]] for s in synth.SYNTH_STEPS]
    kinds = [r["label"] for r in synth.REASON_RULES if r["id"] != "_default"]
    return {
        "id": "synth",
        "title": "⑦ 怎么组织成回答",
        "summary": "查到的资料只是证据，不能直接端给你。中间还有一步：把证据串成一条讲得通的推理。",
        "sections": [
            {"type": "text", "title": "为什么不能直接把原文给你",
             "body": "把资料里的几句话原样拼起来，看着有出处，其实没有理解——"
                     "换个问法就会露出破绽。所以检索之后还有一步：先给结论，"
                     "再把几条证据串成一条推理，最后提醒你哪里最容易理解错。"},
            {"type": "table", "title": "这一步做了五件事", "columns": ["动作", "具体做了什么"],
             "rows": steps},
            {"type": "list", "title": "不同问题，推理的写法不一样", "items":
                ["会先看你问的是哪一类——" + "、".join(kinds) + "，再决定怎么把证据串起来",
                 "先给一句综合结论，让你一眼知道答案是什么",
                 "接着讲它为什么成立，用「也就是说 / 因此 / 反过来讲」把几条证据连起来",
                 "再补一条这个知识点最容易踩的坑，通常比结论本身更有用",
                 "最后给下一步：接着做什么、练什么、看哪份原文"]},
            {"type": "text", "title": "哪句是资料里的，哪句是它推的",
             "body": "来自资料的内容会标出具体出处，可以点回去核对；"
                     "把几条资料连起来的那一句判断，属于推断，界面上会单独标注。"
                     "资料没覆盖的部分，它会明说，不会替资料延伸。"},
            {"type": "text", "title": "断网或没有模型接口时",
             "body": "推理的组织照常进行，只是换一套固定的写法，答案结构和有模型时完全一致；"
                     "界面上的徽标会显示这一条是「AI 生成」还是「规则生成」，不会混着展示。"},
        ],
    }


def build() -> dict[str, Any]:
    """组装手册。前端「查看说明手册」按钮读的就是这份数据。"""
    return {
        "version": VERSION,
        "updated_note": "这本手册讲「它是怎么工作的」，不涉及任何技术细节；最后一页是给开发者的接口清单。",
        "chapters": [_chapter_parse(), _chapter_kp(), _chapter_qa(), _chapter_rag(),
                     _chapter_agent(), _chapter_session(), _chapter_synth()],
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
            "how": "先判断你问的是哪一类 → 选合适的查法 → 把查到的证据串成一条推理 → 按你的进度讲 → 标出出处 → 给你下一步",
            "ground": "只引用老师上传的资料和你自己收进来的资料，没找到会直接说明，不会编",
            "can": "上传资料、生成复习提纲 / 错题卡 / 小结，结果都能点回出处",
            "caveat": "讲解深度因人而异，这只是内容深浅，不代表分班。",
        },
        "teacher": {
            "name": "教师助手",
            "entry": "/tutor",
            "one_line": "一句话让它干活：查学生、备课、讲知识点、定评分标准。",
            "answers": [t["label"] for t in ia.QUESTION_TYPES["teacher"]],
            "how": "判断你想做什么 → 选合适的查法 → 把证据组织成能上课用的讲法 → 给出可直接用的结果",
            "ground": "查事实用班里的真实数据，讲内容用你上传的资料，两者分开展示",
            "can": "上传资料、基于你的课件生成教案要点 / 练习题，引用了哪几份一目了然",
            "caveat": "它按固定流程工作，不会自己去做你没让它做的事。",
        },
    }
