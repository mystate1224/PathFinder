# -*- coding: utf-8 -*-
"""taxonomy.py —— 学科方向词典（单一事实来源）。

三处共用，避免各写一份导致口径不一致：
1. 知识点抽取（``extract.rule_knowledge_points``）给每个知识点打方向关键词；
2. 学生画像（``stratify``）识别兴趣方向、判定科研/工程属性；
3. 检索召回（``rag``）把问句里的概念对齐到课件已出现的方向词。
"""

# 15 个方向 × 关键词表。命中次数排序取前 N。
DIRECTION_KEYWORDS: dict[str, list[str]] = {
    "LLM": [
        "大语言模型", "大模型", "LLM", "GPT", "Transformer", "提示工程", "Prompt",
        "微调", "指令微调", "预训练", "涌现", "RAG", "检索增强", "上下文学习",
        "注意力机制", "自回归", "token", "对齐", "思维链",
    ],
    "NLP": [
        "自然语言处理", "NLP", "分词", "词向量", "句法分析", "语义理解", "情感分析",
        "命名实体", "机器翻译", "文本分类", "问答系统", "BERT", "语言模型", "语料",
    ],
    "CV": [
        "计算机视觉", "CV", "图像识别", "目标检测", "图像分割", "人脸识别",
        "卷积神经网络", "CNN", "图像分类", "姿态估计", "视频理解", "OCR", "特征图",
    ],
    "多模态": [
        "多模态", "跨模态", "图文", "视觉语言", "VLM", "CLIP", "文生图", "图文检索",
        "视觉问答", "模态对齐", "多模态融合",
    ],
    "推荐系统": [
        "推荐系统", "协同过滤", "召回", "排序", "CTR", "点击率", "用户画像",
        "个性化推荐", "冷启动", "矩阵分解", "排序模型", "embedding 召回",
    ],
    "知识图谱": [
        "知识图谱", "实体", "关系抽取", "三元组", "图数据库", "本体", "图谱补全",
        "知识推理", "链接预测", "Neo4j", "实体对齐",
    ],
    "机器学习": [
        "机器学习", "监督学习", "无监督", "分类", "回归", "聚类", "决策树",
        "随机森林", "SVM", "梯度提升", "模型评估", "过拟合", "交叉验证",
        "特征工程", "损失函数", "正则化", "神经网络", "反向传播",
    ],
    "数据挖掘": [
        "数据挖掘", "关联规则", "频繁项集", "异常检测", "时间序列", "序列模式",
        "数据预处理", "降维", "聚类分析", "统计推断",
    ],
    "后端开发": [
        "后端", "服务端", "API", "接口", "REST", "FastAPI", "Django", "Flask",
        "Spring", "微服务", "数据库设计", "事务", "缓存", "Redis", "消息队列",
        "并发", "分布式", "鉴权", "性能优化",
    ],
    "前端开发": [
        "前端", "HTML", "CSS", "JavaScript", "TypeScript", "React", "Vue",
        "组件", "响应式", "浏览器", "DOM", "打包", "工程化", "小程序", "动画",
    ],
    "数据工程": [
        "数据仓库", "ETL", "数据湖", "数仓", "数据管道", "Spark", "Hive", "Flink",
        "离线计算", "实时计算", "数据治理", "数据质量", "调度", "血缘",
    ],
    "运维": [
        "运维", "部署", "容器", "Docker", "Kubernetes", "K8s", "CI/CD", "监控",
        "日志", "负载均衡", "云原生", "自动化运维", "服务器", "灰度发布",
    ],
    "测试": [
        "测试", "单元测试", "集成测试", "自动化测试", "性能测试", "用例", "缺陷",
        "质量保障", "回归测试", "断言", "覆盖率",
    ],
    "产品": [
        "产品", "需求分析", "原型", "用户体验", "用户研究", "竞品分析", "产品设计",
        "交互设计", "增长", "运营", "指标体系", "需求评审",
    ],
    "移动开发": [
        "移动开发", "Android", "iOS", "鸿蒙", "HarmonyOS", "客户端", "原生开发",
        "跨端", "Flutter", "React Native", "移动端适配",
    ],
}

# 方向属性：决定"科研 vs 工程"的判定，进而影响主标签（学业型 / 事业型）
RESEARCH_DIRECTIONS: set[str] = {
    "LLM", "NLP", "CV", "多模态", "推荐系统", "知识图谱", "机器学习", "数据挖掘",
}
ENGINEERING_DIRECTIONS: set[str] = {
    "后端开发", "前端开发", "数据工程", "运维", "测试", "产品", "移动开发",
}

# 课程/教学班常用的"技术类"关键词，用于课件方向识别
ALL_DIRECTIONS: list[str] = list(DIRECTION_KEYWORDS.keys())


def directions_from_text(text: str, top: int = 5) -> list[str]:
    """按命中次数排序取前 ``top`` 个方向。命中为 0 的方向不返回。"""
    if not text:
        return []
    scores: dict[str, int] = {}
    for direction, words in DIRECTION_KEYWORDS.items():
        hits = 0
        for word in words:
            # 长词优先：同一方向内重复出现的不同写法都算命中
            hits += text.count(word)
        if hits > 0:
            scores[direction] = hits
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [d for d, _ in ordered[: max(1, top)]]


def score_direction(text: str, direction: str) -> int:
    return sum(text.count(w) for w in DIRECTION_KEYWORDS.get(direction, []))


def is_research(direction: str) -> bool:
    return direction in RESEARCH_DIRECTIONS


def keywords_of(direction: str) -> list[str]:
    return list(DIRECTION_KEYWORDS.get(direction, []))
