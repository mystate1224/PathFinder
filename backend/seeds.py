# -*- coding: utf-8 -*-
"""seeds.py —— 幂等种子数据。

三条原则：
1. **幂等**：已播种过（users 非空）直接跳过，不会污染生产数据。
2. **走真实业务接口**：资源申请、作业批改、审核决策都调 ``services`` 里的真函数，
   而不是手写 INSERT。这样种子数据的"派生效应"（自动建任务、推导掌握度、写索引）
   与线上行为完全一致，避免"演示库和真库结构不一致"。
3. **断网可演示**：预置 4 份带正文的课程材料并跑完解析链，
   于是答疑/备课/批改在**没有任何 API Key** 的情况下也能检索到真实内容。

用法::

    python seeds.py          # 播种（已存在则跳过）
    python seeds.py --reset  # 清库重播（仅用于开发）
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # 允许 `python backend/seeds.py` 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import db  # noqa: E402
from services import (  # noqa: E402
    dashboard,
    extract,
    homework,
    matcher,
    resources,
    stratify,
)

DEFAULT_PASSWORD = "123456"

# ================================================================ 用户
# (username, 姓名, 行政班, 教学班)
TEACHERS = [
    ("teacher", "张明远", "CS2301", "CS2301"),
    ("teacher2", "李文静", "CS2302", "CS2302"),
    ("teacher3", "王海涛", "AI2301", "AI2301"),
]

# 任教班级：一位教师可以带多个行政班，驾驶舱右上角据此切换。
# users.class_id 仍是「主班」（作业分发、默认落点走它），这里只是可查看范围。
TEACHER_CLASSES: dict[str, list[str]] = {
    "teacher": ["CS2301", "CS2302", "CS2303", "SE2301"],
    "teacher2": ["AI2301", "AI2302"],
    "teacher3": ["SE2301", "AI2302"],
}

# 班级中文名统一在 services/dashboard.CLASS_LABELS 维护（展示层用）

# (username, 姓名, 行政班, gpa, 科研倾向, 就业倾向, 兴趣方向, 补充材料文本)
STUDENTS = [
    ("stu01", "陈嘉禾", "CS2301", 91.8, 4.5, 2.2, ["机器学习", "NLP"],
     "已完成机器学习课程设计，主题是文本分类；在实验室参与过中文问答数据集标注。"),
    ("stu02", "林思远", "CS2301", 88.4, 4.2, 2.6, ["多模态", "CV"],
     "参加过多模态检索的课程项目，做过图像描述生成实验；读英文论文较顺畅。"),
    ("stu03", "赵一鸣", "CS2301", 86.0, 3.9, 3.0, ["推荐系统", "数据挖掘"],
     "对推荐算法有兴趣，做过校园二手交易平台的商品推荐小项目。"),
    ("stu04", "周雨桐", "CS2301", 82.5, 3.6, 3.4, ["后端开发", "数据工程"],
     "熟悉 Java 与 MySQL，做过数据采集与清洗的实践项目。"),
    ("stu05", "吴启航", "CS2301", 78.0, 2.4, 4.3, ["前端开发", "移动开发"],
     "做过微信小程序开发，希望尽早进入企业实习积累工程经验。"),
    ("stu06", "郑雅琳", "CS2301", 84.6, 4.1, 3.2, ["NLP", "知识图谱"],
     "毕业设计方向想做知识图谱补全，已读过几篇相关综述。"),
    ("stu07", "孙博文", "CS2301", 71.2, 2.6, 4.0, ["产品", "数据工程"],
     "更偏向产品与运营方向，做过校园产品的需求梳理与数据分析。"),
    ("stu08", "徐若薇", "CS2301", 76.8, 3.0, 3.4, ["测试", "运维"],
     "在社团负责服务器维护，熟悉 Linux 基本操作与自动化脚本。"),
    ("stu09", "何泽宇", "CS2302", 68.5, 2.2, 4.4, ["后端开发", "运维"],
     "基础课成绩一般，但动手意愿强，做过课程用的小型服务端项目。"),
    ("stu10", "蒋雨欣", "CS2302", 79.4, 3.4, 3.6, ["推荐系统", "产品"],
     "对推荐系统的业务指标比较感兴趣，做过 A/B 实验的课程作业。"),
    ("stu11", "沈子墨", "CS2302", 87.2, 4.4, 2.4, ["知识图谱", "机器学习"],
     "已参与导师课题的图谱构建工作，能独立完成简单的实体抽取实验。"),
    ("stu12", "韩雪莹", "CS2302", 74.5, 2.8, 4.1, ["前端开发", "测试"],
     "做过多套管理后台的前端页面，希望走工程与交付方向。"),
    ("stu13", "冯浩宇", "AI2301", 90.6, 4.7, 1.8, ["CV", "多模态"],
     "有较完整的科研训练经历，完成过目标检测的复现实验并整理成报告。"),
    ("stu14", "唐晓菁", "AI2301", 65.0, 2.0, 3.2, ["产品", "前端开发"],
     "正在补编程基础，参与过学生团队的产品原型设计。"),
    ("stu15", "曹亦凡", "AI2301", 81.3, 3.5, 3.5, ["数据挖掘", "后端开发"],
     "做过数据可视化的课程作业，对数据链路上手较快。"),
    # ---- CS2301 补 4 人（共 12 人：学业型为主，高分段集中）
    ("stu16", "李子谦", "CS2301", 89.5, 4.3, 2.5, ["机器学习", "LLM"],
     "机器学习课程设计拿了优秀，正在复现一篇参数高效微调的论文。"),
    ("stu17", "范一诺", "CS2301", 87.6, 4.0, 2.8, ["数据挖掘", "知识图谱"],
     "跟着学长做过校园知识图谱的实体对齐，愿意继续读研深造。"),
    ("stu18", "袁子涵", "CS2301", 68.5, 2.5, 4.2, ["前端开发", "产品"],
     "在工作室接了两个企业官网的外包，更想早点进互联网公司做产品。"),
    ("stu19", "秦浩然", "CS2301", 92.4, 4.6, 1.9, ["CV", "多模态"],
     "目标检测竞赛拿过省二等奖，计划大四申请直博。"),
    # ---- CS2302 补 8 人（共 12 人：学业型与事业型接近对半）
    ("stu20", "崔文轩", "CS2302", 88.1, 4.1, 2.7, ["NLP", "LLM"],
     "复现过一个中文问答小模型，正在补 Transformer 的数学推导。"),
    ("stu21", "段雨泽", "CS2302", 76.3, 2.9, 3.8, ["后端开发", "运维"],
     "熟悉 Go 与 Docker，维护过社团的报名系统。"),
    ("stu22", "侯思远", "CS2302", 81.7, 3.7, 3.1, ["推荐系统", "数据挖掘"],
     "对召回排序链路感兴趣，正在补线性代数的证明部分。"),
    ("stu23", "雷雨萌", "CS2302", 69.8, 2.3, 4.3, ["测试", "产品"],
     "做过 App 的用例设计与回归测试，想走质量保障方向。"),
    ("stu24", "罗嘉懿", "CS2302", 90.2, 4.5, 2.1, ["知识图谱", "机器学习"],
     "在实验室做图谱补全，已能独立跑通基线模型。"),
    ("stu25", "宋佳琪", "CS2302", 78.9, 2.9, 3.9, ["数据工程", "前端开发"],
     "做过数据看板与埋点采集，喜欢把数据做成能用的东西。"),
    ("stu26", "汤博涛", "CS2302", 84.3, 3.9, 2.8, ["CV", "多模态"],
     "图像分割课程项目做得扎实，正在读英文原版教材。"),
    ("stu27", "汪静怡", "CS2302", 72.6, 2.6, 4.1, ["移动开发", "前端开发"],
     "独立上架过一个校园小程序，希望毕业后先进团队做工程。"),
    # ---- CS2303 新建 12 人（学业型为主，中段成绩居多）
    ("stu28", "方泽楷", "CS2303", 86.7, 4.2, 2.4, ["机器学习", "NLP"],
     "数学基础扎实，正在系统补概率论与最优化。"),
    ("stu29", "龚思彤", "CS2303", 79.5, 3.6, 2.9, ["数据挖掘", "知识图谱"],
     "做过课程的成绩预测小项目，倾向继续深造。"),
    ("stu30", "郝云飞", "CS2303", 68.9, 2.4, 4.2, ["运维", "测试"],
     "在机房做运维助理，动手能力强但理论基础薄弱。"),
    ("stu31", "贾一凡", "CS2303", 83.4, 3.8, 2.6, ["CV", "多模态"],
     "跟着课程做过图像检索实验，读论文速度在提升。"),
    ("stu32", "柯雨柔", "CS2303", 91.2, 4.4, 2.2, ["LLM", "NLP"],
     "参加过中文大模型评测志愿工作，对评测方法论有兴趣。"),
    ("stu33", "雷雨欣", "CS2303", 75.8, 2.8, 4.0, ["产品", "数据工程"],
     "做过用户访谈与需求梳理，更想做业务侧的数据产品。"),
    ("stu34", "马文博", "CS2303", 88.3, 4.3, 2.5, ["推荐系统", "机器学习"],
     "在导师组里跑过召回实验，计划申请夏令营。"),
    ("stu35", "牛子昂", "CS2303", 71.5, 2.7, 3.9, ["后端开发", "数据工程"],
     "做过课程用的订单服务，熟悉 MySQL 索引调优。"),
    ("stu36", "祁思佳", "CS2303", 80.6, 3.9, 2.7, ["知识图谱", "数据挖掘"],
     "整理过课程知识点的关联图谱，习惯做结构化笔记。"),
    ("stu37", "邵天佑", "CS2303", 66.4, 2.1, 4.4, ["移动开发", "运维"],
     "基础课挂过科，但在实训里能独立交付可运行版本。"),
    ("stu38", "石佳怡", "CS2303", 85.9, 4.1, 2.6, ["数据挖掘", "LLM"],
     "做过课设的文本聚类，正在补统计学基础。"),
    ("stu39", "苏晓峰", "CS2303", 77.2, 3.5, 2.8, ["推荐系统", "NLP"],
     "对推荐系统的冷启动感兴趣，读过几篇经典论文。"),
    # ---- AI2301 补 9 人（共 12 人：学业型为主，成绩两极）
    ("stu40", "毛俊杰", "AI2301", 89.8, 4.5, 2.3, ["CV", "多模态"],
     "复现过 DETR 并写了对比报告，动手与写作都稳。"),
    ("stu41", "潘雨桐", "AI2301", 82.1, 3.7, 2.9, ["机器学习", "知识图谱"],
     "课程项目做过图神经网络，正在补数学推导。"),
    ("stu42", "钱思远", "AI2301", 74.3, 2.6, 4.2, ["前端开发", "产品"],
     "做过社团活动页与报名流程，想做 AI 产品的落地。"),
    ("stu43", "任嘉禾", "AI2301", 92.6, 4.7, 1.8, ["LLM", "NLP"],
     "在实验室做指令微调数据清洗，目标直博。"),
    ("stu44", "邵文轩", "AI2301", 69.7, 2.2, 4.3, ["测试", "运维"],
     "做过接口自动化测试，理论课需要补前置知识。"),
    ("stu45", "宋子墨", "AI2301", 86.4, 4.2, 2.6, ["多模态", "CV"],
     "图文检索课设做得完整，能独立调参跑实验。"),
    ("stu46", "谭雨欣", "AI2301", 78.5, 3.4, 2.7, ["数据挖掘", "推荐系统"],
     "对特征工程感兴趣，做过比赛的数据预处理。"),
    ("stu47", "万泽宇", "AI2301", 71.8, 2.5, 4.1, ["移动开发", "数据工程"],
     "做过校园二手平台的客户端，熟悉埋点与上报。"),
    ("stu48", "夏一鸣", "AI2301", 84.7, 4.0, 2.8, ["NLP", "LLM"],
     "写过一个课程问答机器人，正在补检索增强的做法。"),
    # ---- AI2302 新建 12 人（事业型为主，工程与产品导向）
    ("stu49", "项思彤", "AI2302", 72.4, 2.5, 4.2, ["产品", "数据工程"],
     "组织过校园产品从需求到上线的全过程。"),
    ("stu50", "严子谦", "AI2302", 87.9, 4.3, 2.4, ["机器学习", "CV"],
     "课设做过瑕疵检测，愿意继续做科研训练。"),
    ("stu51", "杨雨泽", "AI2302", 76.1, 2.8, 4.0, ["后端开发", "运维"],
     "搭过课程用的模型推理服务，熟悉容器部署。"),
    ("stu52", "尹嘉懿", "AI2302", 67.8, 2.0, 4.5, ["测试", "移动开发"],
     "做过 App 的兼容性测试，动手快但理论基础弱。"),
    ("stu53", "岳文博", "AI2302", 81.3, 3.6, 2.9, ["知识图谱", "NLP"],
     "整理过行业知识库，对落地场景更感兴趣。"),
    ("stu54", "张思佳", "AI2302", 74.6, 2.7, 4.1, ["前端开发", "产品"],
     "做过数据标注平台的前端，关注交互细节。"),
    ("stu55", "赵天佑", "AI2302", 69.3, 2.3, 4.3, ["数据工程", "运维"],
     "维护过实验室的 GPU 服务器与作业队列。"),
    ("stu56", "周佳怡", "AI2302", 83.7, 3.9, 2.8, ["推荐系统", "数据挖掘"],
     "对推荐的业务指标敏感，做过离线评估作业。"),
    ("stu57", "朱晓峰", "AI2302", 78.2, 2.9, 3.9, ["移动开发", "前端开发"],
     "独立做过校园导览小程序，偏工程交付。"),
    ("stu58", "施展", "AI2302", 64.9, 1.9, 4.4, ["运维", "测试"],
     "基础课吃力，但在实训中能按时交付可运行版本。"),
    ("stu59", "邹雨萌", "AI2302", 80.4, 3.5, 2.8, ["LLM", "知识图谱"],
     "做过课程知识点问答的原型，想继续深造。"),
    ("stu60", "左一凡", "AI2302", 88.6, 4.4, 2.2, ["多模态", "CV"],
     "视频理解课设做得完整，计划申请硕士。"),
    # ---- SE2301 新建 12 人（软件工程：事业型为主，工程交付导向）
    ("stu61", "白文轩", "SE2301", 77.8, 2.8, 4.0, ["后端开发", "数据工程"],
     "做过课程用的权限系统，熟悉接口设计规范。"),
    ("stu62", "常雨泽", "SE2301", 89.1, 4.4, 2.3, ["数据工程", "机器学习"],
     "做过流水线的数据质量监控，理论基础也扎实。"),
    ("stu63", "陈思彤", "SE2301", 73.5, 2.6, 4.2, ["前端开发", "测试"],
     "做过组件库与单元测试，关注交付质量。"),
    ("stu64", "邓嘉禾", "SE2301", 85.3, 4.2, 2.7, ["数据工程", "推荐系统"],
     "课设做过日志分析平台，能独立完成数据链路。"),
    ("stu65", "冯天佑", "SE2301", 66.7, 2.1, 4.3, ["运维", "移动开发"],
     "在实训里负责部署与发版，理论基础待补。"),
    ("stu66", "高佳怡", "SE2301", 79.6, 3.3, 2.6, ["知识图谱", "NLP"],
     "整理过需求文档的术语表，表达能力较强。"),
    ("stu67", "郭晓峰", "SE2301", 82.4, 2.9, 3.9, ["后端开发", "运维"],
     "做过课程用的网关服务，熟悉性能压测。"),
    ("stu68", "韩雨萌", "SE2301", 71.2, 2.4, 4.1, ["产品", "数据工程"],
     "做过用户增长的数据看板，偏业务侧。"),
    ("stu69", "黄子昂", "SE2301", 86.8, 4.3, 2.5, ["LLM", "多模态"],
     "做过代码补全工具的调研，计划继续读研。"),
    ("stu70", "江思佳", "SE2301", 75.9, 2.7, 4.0, ["测试", "前端开发"],
     "做过自动化用例与页面走查，注重细节。"),
    ("stu71", "康博涛", "SE2301", 68.4, 2.2, 4.4, ["移动开发", "运维"],
     "基础课偏弱，但在实训中能独立完成打包发版。"),
    ("stu72", "李静怡", "SE2301", 81.5, 3.7, 2.9, ["数据挖掘", "推荐系统"],
     "对 A/B 实验的统计口径感兴趣，写过课程报告。"),
]

# ================================================================ 预置课程材料
# 这些正文会走「解析 → 知识点 → 向量 → FTS 索引」完整链路，
# 是让答疑/备课在离线状态下"有据可依"的关键。
SAMPLE_MATERIALS: list[dict] = [
    {
        "course": "机器学习",
        "filename": "机器学习-第5讲-注意力机制与Transformer.md",
        "category": "课件",
        "text": """# 第5讲 注意力机制与 Transformer

## 5.1 为什么需要注意力机制
循环网络按时间步串行处理序列，长距离依赖会被逐步稀释，且无法并行。
注意力机制的核心思想是：让每个位置直接"看"到序列中所有位置，按相关性加权聚合信息。
它把"信息传递"从串行链式结构变成了两两直接相连的加权求和，路径长度从 O(n) 降为 O(1)。

## 5.2 缩放点积注意力
查询 Q、键 K、值 V 三个矩阵由输入分别乘上可学习权重得到。
注意力权重由 Q 与 K 的点积经 softmax 归一化得到，再对 V 加权求和。
点积结果要除以 sqrt(d_k)，原因是维度增大时点积方差随之增大，
softmax 会进入梯度极小的饱和区，缩放使梯度保持稳定。
公式为 softmax(QK^T / sqrt(d_k))V。

## 5.3 多头注意力
单一注意力只能刻画一种相关性模式。多头注意力把 Q、K、V 投影到 h 组低维子空间，
各自独立计算注意力后再拼接并线性变换。不同头可以分别关注语法依赖、
指代关系、位置邻近等不同模式，类似卷积中的多通道。

## 5.4 位置编码
注意力对序列顺序本身不敏感，打乱输入顺序结果不变。
因此需要显式加入位置信息。正弦位置编码用不同频率的三角函数生成，
使模型能通过线性变换表达相对位置关系，并可外推到训练时未见过更长的序列。

## 5.5 残差连接与层归一化
每个子层外面包一层残差连接，缓解深层网络的梯度消失。
层归一化在特征维度上做归一化，与批量大小无关，更适合序列长度可变的场景。
Transformer 通常采用 Post-LN 或 Pre-LN 两种排列，Pre-LN 训练更稳定。

## 5.6 编码器与解码器结构
编码器由多层自注意力加前馈网络构成，输出每个位置的上下文表征。
解码器额外引入掩码自注意力保证自回归生成时看不到未来位置，
并通过交叉注意力读取编码器输出。前馈网络通常是两层线性变换夹一个非线性激活。
""",
    },
    {
        "course": "机器学习",
        "filename": "机器学习-第3讲-梯度下降与优化.md",
        "category": "课件",
        "text": """# 第3讲 梯度下降与优化

## 3.1 梯度下降的基本形式
参数更新为 theta = theta - lr * grad，其中 lr 是学习率。
学习率过大时损失会在最优点附近震荡甚至发散；
学习率过小时收敛缓慢且容易长时间停在平坦区域。
批量梯度下降用全量数据计算梯度，方向准确但每步代价高；
随机梯度下降每次只用一个样本，更新频繁但方差大；
小批量梯度下降在两者之间折中，是实际训练中的默认选择。

## 3.2 动量与自适应方法
动量法累积历史梯度方向，抑制震荡并加速沿一致方向的移动，
更新量可以理解为速度而非位移。
RMSProp 用梯度平方的滑动平均缩放每个维度的步长，
使不同量纲的参数获得接近的更新幅度。
Adam 结合动量与 RMSProp，并对一阶二阶矩做偏差修正，是常用的默认优化器。

## 3.3 学习率调度
常见策略包括阶梯衰减、余弦退火与预热加衰减。
预热在训练初期把学习率从很小的值线性升高，避免初期梯度不稳导致发散，
在 Transformer 类模型上几乎是标配。

## 3.4 过拟合与正则化
过拟合表现为训练损失持续下降而验证损失回升，两者出现明显分叉。
应对手段包括增加数据或做数据增强、降低模型容量、早停、
L2 权重衰减、Dropout 随机丢弃神经元、以及批归一化带来的隐式正则效果。
判断依据要看验证集而非训练集，训练集指标不能作为泛化能力的证据。

## 3.5 诊断训练过程
损失曲线不下降先查学习率与数据预处理；
损失变成 NaN 通常是学习率过大或出现除零与对数零；
训练快验证差说明过拟合；训练与验证都差说明欠拟合或数据有问题。
""",
    },
    {
        "course": "数据结构",
        "filename": "数据结构-第6讲-图与最短路径.md",
        "category": "课件",
        "text": """# 第6讲 图与最短路径

## 6.1 图的存储
邻接矩阵用二维数组表示边，判断两点相邻是 O(1)，空间是 O(n^2)，适合稠密图。
邻接表为每个顶点维护出边链表，空间是 O(n+m)，遍历邻居高效，适合稀疏图。
实际工程中的路网、社交关系大多是稀疏图，因此邻接表更常用。

## 6.2 图的遍历
深度优先搜索沿一条路径走到底再回溯，依靠递归或显式栈实现，
可用来求连通分量、判断环、做拓扑排序。
广度优先搜索按层扩展，依靠队列实现，在无权图上第一次到达某点即是最短路径。

## 6.3 Dijkstra 算法
适用于边权非负的单源最短路。维护一个已确定最短距离的集合，
每轮从未确定集合中取出距离最小的顶点，用它松弛相邻顶点的距离。
配合优先队列（二叉堆）时时间复杂度为 O((n+m) log n)。
关键前提是边权非负：一旦存在负权边，已确定集合的"最短性"不再成立。

## 6.4 负权边与 Bellman-Ford
Bellman-Ford 对所有边做 n-1 轮松弛，能处理负权边并检测负权环。
若第 n 轮仍能松弛，说明存在负权环，此时最短路无定义。
SPFA 是它的队列优化版本，平均更快但在特定图上会退化。

## 6.5 多源最短路与拓扑排序
Floyd 算法用三层循环做动态规划，求任意两点间最短路，时间复杂度 O(n^3)，
适合顶点数较少的稠密图。
拓扑排序只存在于有向无环图，用入度表配合队列实现，
在任务调度与依赖解析中用于确定合法的执行顺序。
""",
    },
    {
        "course": "深度学习",
        "filename": "深度学习-第2讲-卷积神经网络.md",
        "category": "课件",
        "text": """# 第2讲 卷积神经网络

## 2.1 卷积操作的动机
全连接层把图像展平，参数量随分辨率平方增长且丢失空间结构。
卷积利用局部连接与权值共享两个先验：相邻像素相关性更强，
同一模式在不同位置应被同样的检测器识别。参数量因此与图像大小无关。

## 2.2 卷积核与感受野
输出特征图上的一个点对应输入区域的大小称为感受野。
单层 3x3 卷积的感受野是 3x3，堆叠两层等效感受野为 5x5。
用两层 3x3 代替一层 5x5 可以在参数量更少的同时增加非线性表达。

## 2.3 步长、填充与池化
步长控制滑窗移动间隔，步长大于 1 会下采样输出尺寸。
填充在边界补零以保持输出尺寸，避免边缘信息被过度削弱。
池化做局部聚合，最大池化保留最强响应，平均池化平滑噪声，二者都不含可学习参数。

## 2.4 批归一化
在通道维度对一个小批次的激活做标准化，并引入可学习的缩放与平移。
它缓解内部协变量偏移，允许更大的学习率，并带来轻微正则效果。
推理阶段使用训练期累积的滑动均值与方差，而不是当前批次的统计量。

## 2.5 经典结构演进
LeNet 确立了卷积加池化加全连接的基本范式。
AlexNet 引入 ReLU 与 Dropout 并借助 GPU 训练。
VGG 用连续小卷积核堆叠加深网络。
ResNet 用恒等残差连接解决深层网络退化问题，使上百层网络可训练。
""",
    },
    {
        "course": "",
        "filename": "林思远-个人简历.md",
        "category": "简历",
        "owner": "stu02",
        "text": """# 林思远 个人简历

教育背景：计算机科学与技术专业，在读本科三年级。

技能：Python、PyTorch、OpenCV，熟悉多模态检索与图像描述生成任务。

项目经历：多模态图文检索课程项目，负责图像编码分支与检索评估，
使用预训练视觉编码器加文本编码器做对比学习，Recall@10 提升约 8 个百分点。

论文阅读：读过 CLIP 与 BLIP 系列论文，能复现其中的零样本分类实验。

求职意向：多模态算法方向研究型岗位，或科研课题组长期参与。
""",
    },
    {
        "course": "",
        "filename": "陈嘉禾-成绩单.md",
        "category": "成绩单",
        "owner": "stu01",
        "text": """# 陈嘉禾 成绩单（已修课程）

高等数学 96
线性代数 93
概率论与数理统计 90
程序设计基础 95
数据结构 92
机器学习 94
自然语言处理 91
数据库系统 88

平均成绩：92.4
备注：机器学习课程设计为文本分类，获课程优秀项目。
""",
    },
]

# ================================================================ 课题组 / 资源
# (教师 username, 团队名, 类型, 方向, 招募要求, 名额上限)
# 老师带的不只是科研课题组 —— 横向项目、竞赛团队、实习组同样要在驾驶舱里管，
# 所以每条种子都带类型，前端按类型给徽章与筛选。
GROUPS = [
    ("teacher", "多模态内容理解课题组", "科研课题组", ["多模态", "CV", "LLM"],
     "熟悉 PyTorch 基础，能读英文论文；每周可投入 6 小时以上；先做复现再谈创新。", 3),
    ("teacher", "智能教育数据挖掘课题组", "科研课题组", ["数据挖掘", "知识图谱", "推荐系统"],
     "掌握基本的数据处理与可视化，对教学场景的数据分析有兴趣。", 4),
    ("teacher2", "自然语言处理与智能问答课题组", "科研课题组", ["NLP", "LLM", "知识图谱"],
     "有文本处理经验，了解 Transformer 基本结构；愿意承担数据标注与评测工作。", 3),
    ("teacher3", "推荐系统与用户增长课题组", "科研课题组", ["推荐系统", "数据挖掘"],
     "理解基本的推荐算法，对 A/B 实验与指标分析有耐心。", 2),

    # 三类非科研团队：让「类型」这个维度在演示数据里就能看出差别
    ("teacher", "教辅问答机器人研发组（校企合作）", "横向项目",
     ["检索增强", "知识库", "后端开发"],
     "能写 Python 后端、愿意与企业侧对需求；有交付节点意识，学期末要能上线试用。", 2),
    ("teacher", "计算机设计大赛·AI 应用赛道队", "竞赛团队",
     ["人工智能", "算法", "系统实现"],
     "面向 10 月校内选拔，能接受每周一次集中打磨；有作品集或可跑通的 Demo 优先。", 5),
    ("teacher2", "NLP 算法实习预备组（内推）", "实习实践",
     ["NLP", "PyTorch", "工程实践"],
     "面向大三以上，先把 PyTorch 与基本 NLP 任务练熟，再走内推渠道面试。", 2),
]

# (教师 username, 类型, 标题, 说明, 标签, 名额, 截止日期)
RESOURCES = [
    ("teacher", "group", "多模态内容理解课题组（长期招募）",
     "方向为图文检索与多模态大模型应用，每周组会一次，先跟一次完整复现再定方向。",
     ["多模态", "CV", "科研训练"], 3, ""),
    ("teacher", "contest", "全国大学生计算机设计大赛 校内选拔",
     "面向人工智能应用赛道组建 5 人队伍，负责算法与系统实现。",
     ["竞赛", "人工智能", "团队协作"], 5, "2026-10-31"),
    ("teacher", "project", "教辅问答机器人（校企合作项目）",
     "为学院做一套基于知识库的答疑助手，需要 2 名同学负责检索与后端。",
     ["项目", "检索增强", "后端开发"], 2, "2026-11-15"),
    ("teacher2", "group", "NLP 与智能问答课题组",
     "研究面向教育场景的问答与知识抽取，提供数据集与算力支持。",
     ["NLP", "知识图谱"], 3, ""),
    ("teacher2", "internship", "字节跳动 NLP 算法实习（内推）",
     "面向本科三年级以上，要求熟悉 PyTorch 与基本 NLP 任务，内推渠道优先面试。",
     ["实习", "NLP", "内推"], 2, "2026-10-20"),
    ("teacher2", "contest", "中国大学生计算机设计大赛 文本赛道",
     "选题围绕中文长文本理解，可结合实验室现有数据。",
     ["竞赛", "NLP"], 4, "2026-11-30"),
    ("teacher3", "group", "推荐系统课题组",
     "研究推荐算法与用户行为建模，重视实验设计与指标解读能力。",
     ["推荐系统", "数据挖掘"], 2, ""),
    ("teacher3", "internship", "腾讯广告算法实习（内推）",
     "负责广告排序模型的离线评估与特征工程，要求掌握 Python 与 SQL。",
     ["实习", "推荐系统", "内推"], 3, "2026-10-25"),
]

# (学生 username, 资源标题, 申请留言, 教师处理, 教师回复)
APPLICATIONS = [
    ("stu02", "多模态内容理解课题组（长期招募）", "做过图文检索课程项目，想继续做多模态方向。",
     "accepted", "欢迎加入，先把 CLIP 的零样本分类复现一遍，周五组会讲一下结果。"),
    ("stu06", "多模态内容理解课题组（长期招募）", "我主要做知识图谱，但想了解多模态与图谱的结合。",
     "pending", ""),
    ("stu05", "教辅问答机器人（校企合作项目）", "我做过小程序和前端对接，可以负责系统集成部分。",
     "accepted", "很好，先跟后端同学对齐接口，本周内出一版联调计划。"),
    ("stu07", "字节跳动 NLP 算法实习（内推）", "对 NLP 感兴趣，做过文本数据分析。",
     "declined", "这个岗位要求有一定的模型训练经验，建议先完成一门 NLP 课程项目再来，我帮你看简历。"),
    ("stu01", "NLP 与智能问答课题组", "做过文本分类课程设计，希望能参与问答方向的研究。",
     "accepted", "同意，先读三篇检索增强问答的论文，下周组会做一次综述汇报。"),
    ("stu11", "NLP 与智能问答课题组", "正在做实体抽取实验，想参与知识库相关的工作。", "pending", ""),
    ("stu13", "推荐系统课题组", "我对实验设计与指标分析有兴趣，想从排序模型入手。",
     "pending", ""),
    ("stu09", "腾讯广告算法实习（内推）", "Python 和 SQL 都比较熟练，做过小型服务端项目。",
     "pending", ""),
]

# ================================================================ 作业
# (标题, 课程, 教学班, 说明, 满分, 截止日期)
HOMEWORK = [
    ("注意力机制的原理与实现", "机器学习", "CS2301",
     "请用自己的话解释缩放点积注意力中为什么要除以 sqrt(d_k)，并说明多头注意力的作用。要求 300 字以上，可分点作答。",
     100, "2026-10-10 23:59"),
    ("梯度下降与学习率调参实验报告", "机器学习", "CS2301",
     "记录不同学习率下的损失曲线形态，说明学习率过大与过小的表现，并给出你最终选定的学习率及依据。",
     100, "2026-10-17 23:59"),
    ("图的最短路径算法实现", "数据结构", "CS2301",
     "实现 Dijkstra 算法并说明为什么它不能处理负权边；给出你的时间复杂度和测试用例。",
     100, "2026-10-24 23:59"),
]

# (作业序号, 学生 username, 作答正文)
SUBMISSIONS = [
    (0, "stu01",
     "缩放点积注意力中除以 sqrt(d_k) 是为了控制点积结果的数值范围。"
     "当维度 d_k 增大时，Q 与 K 的点积方差会随维度线性增长，数值变大后 softmax 会进入饱和区，"
     "输出接近 one-hot，梯度趋近于零，训练难以推进。除以 sqrt(d_k) 使方差回到 1 附近，梯度保持稳定。\n"
     "多头注意力的作用是把 Q、K、V 投影到多组低维子空间分别计算注意力，再拼接后线性变换。"
     "不同子空间可以关注不同的相关性模式，例如语法依赖、指代关系和位置邻近，"
     "类似卷积中多通道提取不同特征，比单头表达更丰富。"),
    (0, "stu02",
     "除以 sqrt(d_k) 的原因与点积的方差有关：假设 Q 与 K 各维独立同分布，点积的方差正比于 d_k，"
     "维度越高点积绝对值越大，softmax 的分布越尖锐，反向传播时梯度越小。缩放后数值稳定。\n"
     "多头注意力相当于并行做多次注意力，每个头学习一种独立的关注模式，最后融合。"
     "这让模型同时捕捉局部与全局的依赖关系。"),
    (0, "stu03",
     "缩放是为了防止梯度消失，除以维度的平方根进行归一化。多头就是多个注意力并行。"),
    (0, "stu04",
     "注意力机制让每个位置直接看到全部位置，按相关性加权求和，路径长度从 O(n) 降到 O(1)。"
     "缩放点积注意力需要除以 sqrt(d_k)，否则点积数值过大会让 softmax 饱和、梯度消失。"
     "多头注意力把表示空间拆成多个子空间，每个头关注不同的模式，"
     "拼接后再做一次线性变换融合，效果优于单头。"),
    (1, "stu01",
     "实验设置：学习率分别取 0.001、0.01、0.1、1.0，小批量大小 32，训练 50 轮。\n"
     "结果：0.001 时损失下降缓慢，50 轮后仍在 0.6 以上，属于学习率过小；"
     "0.01 时损失平稳下降并收敛到 0.12 左右，验证损失与训练损失同步下降；"
     "0.1 时前期下降很快但后期在 0.3 附近震荡，训练损失低于验证损失，出现过拟合迹象；"
     "1.0 时第 3 轮损失变成 NaN，属于学习率过大致使更新发散。\n"
     "结论：选择 0.01。依据是收敛稳定且验证损失最低；同时加上余弦退火进一步降低末期学习率。"),
    (1, "stu02",
     "学习率 0.001 太慢，0.1 会震荡，1.0 直接发散。最后选 0.01，收敛比较平稳。"),
    (2, "stu01",
     "实现思路：用邻接表存图，优先队列维护候选顶点，每次取出当前距离最小的未确定顶点，"
     "对其邻边做松弛。时间复杂度 O((n+m) log n)，主要开销在堆操作。\n"
     "不能处理负权边的原因：Dijkstra 每轮把距离最小的顶点标记为已确定，"
     "这一结论依赖边权非负。若存在负权边，后面经过其他顶点可能出现更短路径，"
     "而该顶点已经被确定，不会再被更新，结果就错了。"),
]


# ================================================================ 工具
def _user_id(username: str) -> int:
    row = db.query_one("SELECT id FROM users WHERE username = ?", (username,))
    return int(row["id"]) if row else 0


def _create_user(username: str, password: str, role: str, name: str,
                 class_id: str, class_name: str = "") -> int:
    return db.execute(
        "INSERT INTO users (username, pwd_hash, role, name, class_id, class_name) "
        "VALUES (?,?,?,?,?,?)",
        (username, db.hash_password(password), role, name, class_id, class_name or class_id),
    )


# ================================================================ 分步播种
def seed_users() -> dict:
    made = {"teachers": 0, "students": 0}
    for username, name, class_id, class_name in TEACHERS:
        if not db.user_by_username(username):
            _create_user(username, DEFAULT_PASSWORD, "teacher", name, class_id, class_name)
            made["teachers"] += 1

    for row in STUDENTS:
        username, name, class_id = row[0], row[1], row[2]
        if not db.user_by_username(username):
            _create_user(username, DEFAULT_PASSWORD, "student", name, class_id, class_id)
            made["students"] += 1
    return made


def seed_teacher_classes() -> int:
    """任教班级：驾驶舱右上角「切换班级」的数据来源。

    一位教师可以带多个行政班；``users.class_id`` 仍是默认落点（作业分发等），
    这里只决定「我能看哪些班」。
    """
    made = 0
    for username, classes in TEACHER_CLASSES.items():
        teacher_id = _user_id(username)
        if not teacher_id:
            continue
        for class_id in classes:
            exists = db.query_one(
                "SELECT 1 AS hit FROM teacher_classes WHERE teacher_id = ? AND class_id = ?",
                (teacher_id, class_id),
            )
            if exists:
                continue
            db.execute(
                "INSERT INTO teacher_classes (teacher_id, class_id) VALUES (?,?)",
                (teacher_id, class_id),
            )
            made += 1
        # 兜底：配置漏了自己的主班时补上，避免登录进去看不到本班
        own = db.scalar("SELECT class_id FROM users WHERE id = ?", (teacher_id,), "")
        if own:
            has = db.query_one(
                "SELECT 1 AS hit FROM teacher_classes WHERE teacher_id = ? AND class_id = ?",
                (teacher_id, str(own)),
            )
            if not has:
                db.execute(
                    "INSERT INTO teacher_classes (teacher_id, class_id) VALUES (?,?)",
                    (teacher_id, str(own)),
                )
                made += 1
    return made


def seed_profiles() -> int:
    """学生画像 + 教师画像。走 ``stratify`` 规则引擎，保证口径与线上一致。"""
    count = 0
    for row in STUDENTS:
        username, _, _, gpa, research, job, interests, extra = row
        user_id = _user_id(username)
        if not user_id:
            continue
        profile = stratify.rule_stratify(gpa, research, job, interests, extra)
        stratify.save_profile(user_id, profile, engine="rule")
        count += 1

    for username, directions, summary in (
        ("teacher", ["多模态", "CV", "LLM", "数据挖掘"],
         "研究方向为多模态内容理解与教育数据挖掘，长期指导本科生科研训练。"),
        ("teacher2", ["NLP", "LLM", "知识图谱"],
         "研究方向为自然语言处理与智能问答，主持教育场景问答系统建设。"),
        ("teacher3", ["推荐系统", "数据挖掘"],
         "研究方向为推荐系统与用户行为建模，关注离线评估与在线实验的方法论。"),
    ):
        user_id = _user_id(username)
        if not user_id:
            continue
        db.execute(
            "INSERT INTO teacher_profiles (user_id, directions, expertise, projects, summary) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET directions=excluded.directions, "
            "expertise=excluded.expertise, summary=excluded.summary",
            (
                user_id,
                db.jdump(directions),
                db.jdump(["课程教学", "科研训练指导", "竞赛指导"]),
                db.jdump([]),
                summary,
            ),
        )
    return count


def seed_groups() -> int:
    made = 0
    for teacher_username, name, kind, directions, requirement, capacity in GROUPS:
        teacher_id = _user_id(teacher_username)
        if not teacher_id:
            continue
        exists = db.query_one(
            "SELECT id FROM research_groups WHERE teacher_id = ? AND name = ?",
            (teacher_id, name),
        )
        if exists:
            continue
        db.execute(
            "INSERT INTO research_groups (teacher_id, name, kind, directions, requirement, capacity) "
            "VALUES (?,?,?,?,?,?)",
            (teacher_id, name, kind, db.jdump(directions), requirement, capacity),
        )
        made += 1
    return made


def seed_resources() -> int:
    """资源 + 申请 + 教师处理。处理走 ``resources.decide``，会自动建跟进任务。"""
    made = 0
    for teacher_username, rtype, title, detail, tags, capacity, deadline in RESOURCES:
        teacher_id = _user_id(teacher_username)
        if not teacher_id:
            continue
        exists = db.query_one(
            "SELECT id FROM teacher_resources WHERE teacher_id = ? AND title = ?",
            (teacher_id, title),
        )
        if exists:
            continue
        resources.create_resource(
            teacher_id, rtype, title, detail, tags=tags,
            capacity=capacity, deadline=deadline,
        )
        made += 1

    for student_username, title, message, action, reply in APPLICATIONS:
        student_id = _user_id(student_username)
        if not student_id:
            continue
        resource = db.query_one("SELECT * FROM teacher_resources WHERE title = ?", (title,))
        if not resource:
            continue
        if db.query_one(
            "SELECT id FROM resource_applications WHERE resource_id = ? AND student_id = ?",
            (resource["id"], student_id),
        ):
            continue
        try:
            application = resources.apply(student_id, int(resource["id"]), message)
        except resources.ResourceError:
            continue
        if action == "pending":
            continue
        try:
            resources.decide(
                int(resource["teacher_id"]),
                int(application["application_id"]),
                action,
                reply,
            )
        except resources.ResourceError:
            pass
    return made


def seed_matches() -> int:
    """少量师生匹配记录：一条已双向确认，若干条待确认。"""
    made = 0
    pairs = [
        ("stu02", "teacher", "多模态内容理解课题组", "accepted", "accepted"),
        ("stu01", "teacher", "智能教育数据挖掘课题组", "accepted", "pending"),
        ("stu13", "teacher3", "推荐系统与用户增长课题组", "pending", "pending"),
        ("stu11", "teacher2", "自然语言处理与智能问答课题组", "accepted", "pending"),
    ]
    for student_username, teacher_username, group_name, teacher_action, student_action in pairs:
        student_id = _user_id(student_username)
        teacher_id = _user_id(teacher_username)
        if not student_id or not teacher_id:
            continue
        group = db.query_one(
            "SELECT * FROM research_groups WHERE teacher_id = ? AND name = ?",
            (teacher_id, group_name),
        )
        if not group:
            continue
        exists = db.query_one(
            "SELECT id FROM match_records WHERE student_id = ? AND group_id = ?",
            (student_id, int(group["id"])),
        )
        if not exists and teacher_action != "pending":
            try:
                matcher.decide("teacher", student_id, int(group["id"]), teacher_action)
            except matcher.MatchError:
                continue
        if student_action != "pending":
            try:
                matcher.decide("student", student_id, int(group["id"]), student_action)
            except matcher.MatchError:
                continue
        made += 1
    return made


def seed_homework() -> dict:
    """作业 + 提交 + 批改。批改走 ``homework.grade``，顺带推导知识掌握度。"""
    teacher_id = _user_id("teacher")
    made = {"homework": 0, "submissions": 0, "graded": 0}
    if not teacher_id:
        return made

    ids: list[int] = []
    for title, course, class_name, detail, full_score, deadline in HOMEWORK:
        exists = db.query_one(
            "SELECT id FROM homework WHERE teacher_id = ? AND title = ?", (teacher_id, title)
        )
        if exists:
            ids.append(int(exists["id"]))
            continue
        try:
            ids.append(homework.create(
                teacher_id, title, course, class_name, detail, full_score, deadline
            ))
            made["homework"] += 1
        except homework.HomeworkError:
            ids.append(0)

    for index, student_username, content in SUBMISSIONS:
        if index >= len(ids) or not ids[index]:
            continue
        student_id = _user_id(student_username)
        if not student_id:
            continue
        try:
            homework.submit(student_id, ids[index], content)
            made["submissions"] += 1
        except homework.HomeworkError:
            continue

    # 只批改第一份作业的前两名，故意留下"待批改"，方便演示批改台
    if ids and ids[0]:
        for student_username, score, comment in (
            ("stu01", 94, "对缩放原因的解释准确，把方差与梯度饱和联系起来，很到位；"
                           "多头部分建议再补一句「为什么拼接后还要线性变换」就更完整了。"),
            ("stu02", 86, "要点齐全，表述清楚；如果能举例说明不同头关注不同模式，说服力会更强。"),
        ):
            student_id = _user_id(student_username)
            if not student_id:
                continue
            try:
                homework.grade(teacher_id, ids[0], student_id, score, comment)
                made["graded"] += 1
            except homework.HomeworkError:
                continue

    for index in (0, 1, 2):
        if index < len(ids) and ids[index]:
            dashboard.recompute_mastery(_user_id("stu01"), "")
    return made


def seed_materials() -> dict:
    """预置材料 → 解析 → 知识点 → 向量 → FTS 索引。离线演示的底气在这里。"""
    made = {"materials": 0, "knowledge_points": 0, "chunks": 0}
    for item in SAMPLE_MATERIALS:
        owner_username = item.get("owner") or "teacher"
        owner_id = _user_id(owner_username)
        if not owner_id:
            continue
        filename = item["filename"]
        exists = db.query_one(
            "SELECT id FROM materials WHERE owner_id = ? AND filename = ?",
            (owner_id, filename),
        )
        if exists:
            continue

        text = item["text"]
        user = db.user_by_id(owner_id) or {}
        kind = extract.kind_by_ext(filename)
        parsed = extract.rule_parse(kind, filename, text)

        stored = ""
        try:
            folder = extract.ensure_upload_dir(owner_id)
            target = folder / extract.safe_name(filename)
            target.write_text(text, encoding="utf-8")
            stored = str(target.relative_to(config.DATA_DIR)).replace("\\", "/")
        except OSError:
            stored = ""

        material_id = extract.save_material(
            owner_id, kind, item.get("category") or "未分类", filename,
            stored, text, parsed, "rule",
        )
        if not material_id:
            continue
        touched = extract.apply_parse_result(user, material_id, kind, filename, text, parsed)
        made["materials"] += 1
        made["knowledge_points"] += int(touched.get("knowledge_points") or 0)
        made["chunks"] += int(touched.get("indexed") or 0)
    return made


def seed_imports() -> int:
    """预导入：给每个学生导入全部教师公用资料。

    数据隔离后的「空库陷阱」保险 —— 演示账号登录即可提问（课件本来就该被引用），
    而同学之间的私人材料（成绩单 / 简历）依然互不可见。
    真实新用户则走「我的资料库 → 教师共享 → 导入」的显式流程。
    """
    teacher_ids = [int(r["id"]) for r in db.query(
        "SELECT id FROM users WHERE role = 'teacher'")]
    student_ids = [int(r["id"]) for r in db.query(
        "SELECT id FROM users WHERE role = 'student'")]
    with db.connect() as conn:
        for sid in student_ids:
            for tid in teacher_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO material_imports (user_id, material_id, created_at) "
                    "SELECT ?, id, ? FROM materials WHERE owner_id = ?",
                    (sid, db.now(), tid),
                )
    return db.scalar("SELECT COUNT(*) FROM material_imports", (), 0)


# ================================================================ 入口
def is_seeded() -> bool:
    return int(db.scalar("SELECT COUNT(*) FROM users", (), 0) or 0) > 0


def reset() -> None:
    """清空所有业务数据（**开发用**，会删掉用户与材料）。"""
    tables = [
        "sessions", "student_profiles", "teacher_profiles", "teacher_classes", "materials",
        "knowledge_points", "kb_vec", "research_groups", "match_records", "tasks",
        "chat_messages", "teacher_resources", "resource_applications", "homework",
        "homework_submissions", "artifacts", "kp_mastery", "material_imports", "users",
    ]
    with db.connect() as conn:
        for table in tables:
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:  # noqa: BLE001 - 表可能不存在
                pass
        try:
            conn.execute("DELETE FROM kb_fts")
        except Exception:  # noqa: BLE001 - FTS 可能不可用
            pass
    print("[seeds] 已清空业务数据（uploads 下的文件未删除）")


def seed(force: bool = False) -> dict:
    """播种全部演示数据。幂等：``force=True`` 时先清库。"""
    db.init_db()
    if force:
        reset()
    if is_seeded():
        return {"skipped": True, "reason": "数据库已有用户，跳过播种"}

    report: dict = {}
    report["users"] = seed_users()
    report["classes"] = seed_teacher_classes()
    report["profiles"] = seed_profiles()
    report["groups"] = seed_groups()
    report["resources"] = seed_resources()
    report["matches"] = seed_matches()
    report["homework"] = seed_homework()
    report["materials"] = seed_materials()
    report["imports"] = seed_imports()
    report["accounts"] = {
        "teacher": "teacher / 123456",
        "teachers": "teacher2, teacher3 / 123456",
        "students": "stu01 ~ stu72 / 123456（6 个班，每班 12 人）",
        "classes": "CS2301 / CS2302 / CS2303 / AI2301 / AI2302 / SE2301",
    }
    return report


def main() -> None:  # pragma: no cover - 命令行入口
    force = "--reset" in sys.argv
    report = seed(force=force)
    print("[seeds] 播种结果：")
    for key, value in report.items():
        print(f"  - {key}: {value}")
    print(f"[seeds] 数据库：{config.DB_PATH}")


if __name__ == "__main__":  # pragma: no cover
    main()
