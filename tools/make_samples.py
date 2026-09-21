# -*- coding: utf-8 -*-
"""make_samples.py —— 生成演示用的**图片素材**（写给要复现/改素材的人看）。

为什么要自己造图而不是随便找几张：
演示「图文智能解析」时，图片里必须**同时**包含「要学的正文」和「该被清掉的噪声」
（页眉页脚、页码、水印、目录点线、扫描噪点）。随便找一张干净图，去杂规则一条都命中不了，
演示就变成了"看不出它在干什么"。

三张图各自对应一条真实的教学场景：
  · 课件扫描页 —— 带页眉 / 页码 / 水印 / 目录点线 / 表格，测去杂 + 课件规则集
  · 手写作业   —— 带红笔批注，测视觉批改与作业规则集
  · 论文截图   —— 带摘要 / 关键词 / 方法段，测论文规则集

生成参数是可调的：改下面的 CONFIG 重新跑即可，不需要动绘图逻辑。
运行：python tools/make_samples.py
"""
from __future__ import annotations

import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"

FONT_FILES = {
    "regular": ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc"],
    "bold": ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf"],
    "hand": ["C:/Windows/Fonts/simkai.ttf", "C:/Windows/Fonts/simsun.ttc"],
}

PAPER = (253, 252, 247)      # 略偏暖的纸白
INK = (32, 41, 58)
INK_SOFT = (96, 108, 128)
RED = (200, 60, 60)
BLUE = (37, 99, 235)


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_FILES[kind]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> list[str]:
    """按像素宽度断行（中文没有空格，只能逐字量）。"""
    lines, buf = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(buf)
            buf = ""
            continue
        trial = buf + ch
        if draw.textlength(trial, font=fnt) > max_w and buf:
            lines.append(buf)
            buf = ch
        else:
            buf = trial
    if buf:
        lines.append(buf)
    return lines


def paragraph(draw, xy, text, fnt, max_w, line_h, fill=INK):
    x, y = xy
    for line in wrap(draw, text, fnt, max_w):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += line_h
    return y


def paper(w: int, h: int, tint=PAPER) -> Image.Image:
    return Image.new("RGB", (w, h), tint)


def watermark(img: Image.Image, text: str) -> None:
    """斜向半透明水印 —— 演示时会被「水印」去杂规则命中。"""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font("bold", 46)
    w = d.textlength(text, font=f)
    d.text(((img.width - w) / 2, img.height / 2), text, font=f, fill=(150, 160, 180, 58))
    img.paste(Image.alpha_composite(img.convert("RGBA"), layer.rotate(28, resample=Image.BICUBIC,
                                                                     center=(img.width / 2, img.height / 2)))
              .convert("RGB"), (0, 0))


def grain(img: Image.Image, amount: int = 6, seed: int = 7) -> None:
    """极轻的扫描噪点：只加一点点，别把字糊了。"""
    rnd = random.Random(seed)
    px = img.load()
    for _ in range(img.width * img.height // 260):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        r, g, b = px[x, y]
        k = rnd.randint(-amount, amount)
        px[x, y] = (max(0, min(255, r + k)), max(0, min(255, g + k)), max(0, min(255, b + k)))


# ================================================================ 图一：课件扫描页
def make_courseware() -> Path:
    W, H = 1240, 1754
    img = paper(W, H)
    d = ImageDraw.Draw(img)
    f_h1, f_h2, f_body, f_small = font("bold", 40), font("bold", 30), font("regular", 26), font("regular", 22)

    # 页眉（高频重复行 → 命中 dup_line 思路）
    d.text((90, 60), "机器学习导论 · 课件", font=f_small, fill=INK_SOFT)
    d.text((W - 250, 60), "CS2301", font=f_small, fill=INK_SOFT)
    d.line([(90, 92), (W - 90, 92)], fill=(214, 224, 238), width=2)

    y = 130
    y = paragraph(d, (90, y), "三、逻辑回归与分类", f_h1, W - 180, 52)
    y += 14

    # 目录点线（命中 toc 规则）
    d.text((90, y), "3.1 Sigmoid 函数", font=f_small, fill=INK_SOFT)
    d.text((90 + 170, y), ". . . . . . . . . . . . . . . . . . . . . . . . .", font=f_small, fill=(190, 200, 214))
    d.text((W - 150, y), "42", font=f_small, fill=INK_SOFT)
    y += 40
    d.text((90, y), "3.2 决策边界", font=f_small, fill=INK_SOFT)
    d.text((90 + 170, y), ". . . . . . . . . . . . . . . . . . . . . . . . .", font=f_small, fill=(190, 200, 214))
    d.text((W - 150, y), "45", font=f_small, fill=INK_SOFT)
    y += 60

    y = paragraph(d, (90, y), "3.1  Sigmoid 函数", f_h2, W - 180, 40, BLUE)
    y += 10
    # 定义句：命中课件规则集的 definition 锚点
    y = paragraph(d, (90, y),
                  "Sigmoid 函数是指把任意实数映射到 (0, 1) 区间的单调可微函数，"
                  "定义为  sigma(z) = 1 / (1 + e^(-z))。",
                  f_body, W - 200, 42)
    y += 8
    y = paragraph(d, (90, y),
                  "它把线性模型的输出压缩成概率，因此逻辑回归可以直接用极大似然估计求解，"
                  "而不需要像感知机那样处理不可导的阶跃函数。",
                  f_body, W - 200, 42)
    y += 24

    # 表格
    y = paragraph(d, (90, y), "3.2  决策边界", f_h2, W - 180, 40, BLUE)
    y += 12
    rows = [("sigma(z) 取值", "判定类别", "含义"),
            ("sigma(z) > 0.5", "正类  y = 1", "模型倾向正类"),
            ("sigma(z) < 0.5", "负类  y = 0", "模型倾向负类"),
            ("sigma(z) = 0.5", "分界", "落在决策边界上")]
    cols = [90, 90 + 260, 90 + 520]
    for i, row in enumerate(rows):
        fnt = f_small if i == 0 else f_body
        for cx, cell in zip(cols, row):
            d.text((cx, y), cell, font=fnt, fill=INK_SOFT if i == 0 else INK)
        d.line([(90, y + 34), (W - 120, y + 34)], fill=(226, 232, 240), width=1)
        y += 40
    y += 16

    # 小结：命中 summary 锚点
    y = paragraph(d, (90, y), "本节要点：", f_h2, W - 180, 40)
    y = paragraph(d, (90, y),
                  "① Sigmoid 把线性输出压成概率；② 决策边界由 sigma(z)=0.5 决定；"
                  "③ 逻辑回归用交叉熵损失，是凸函数，可用梯度下降求全局最优。",
                  f_body, W - 200, 42)

    watermark(img, "内部资料  请勿外传")
    grain(img, 5, seed=11)
    # 页脚
    d = ImageDraw.Draw(img)
    d.line([(90, H - 96), (W - 90, H - 96)], fill=(214, 224, 238), width=2)
    d.text((90, H - 74), "机器学习导论 课件", font=f_small, fill=INK_SOFT)
    d.text((W - 200, H - 74), "第 42 页", font=f_small, fill=INK_SOFT)   # 命中 page_number

    path = OUT / "课件扫描页.png"
    img.save(path, quality=94)
    return path


# ================================================================ 图二：手写作业
def make_homework() -> Path:
    W, H = 1240, 1560
    img = paper(W, H)
    d = ImageDraw.Draw(img)
    f_title, f_body, f_hand, f_red = font("bold", 32), font("regular", 24), font("hand", 30), font("hand", 27)

    d.text((80, 56), "作业三 · 梯度下降", font=f_title, fill=INK)
    d.text((80, 104), "姓名：林思远        学号：stu02        班级：CS2301", font=f_body, fill=INK_SOFT)
    d.line([(80, 150), (W - 80, 150)], fill=(214, 224, 238), width=2)

    y = 190
    y = paragraph(d, (80, y),
                  "第 2 题：请推导批量梯度下降的更新公式，并说明学习率过大时会发生什么。（20 分）",
                  f_body, W - 200, 38)
    y += 24

    # 手写答案：逐字轻微抖动 + 旋转，模拟真实书写
    hand = [
        "解：设损失函数 J(θ) = (1/2m) Σ (hθ(x) - y)^2，",
        "对 θ 求偏导得 dJ/dθ = (1/m) Σ (hθ(x) - y) x，",
        "因此更新公式为 θ := θ - α · dJ/dθ。",
        "",
        "若学习率 α 过大，损失会在最优点附近来回震荡，",
        "甚至逐步发散，无法收敛。",
    ]
    rnd = random.Random(3)
    for line in hand:
        if not line:
            y += 20
            continue
        x = 96
        for ch in line:
            ch_img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
            ImageDraw.Draw(ch_img).text((6, 4), ch, font=f_hand, fill=(34, 48, 74, 255))
            ch_img = ch_img.rotate(rnd.uniform(-3.2, 3.2), resample=Image.BICUBIC)
            img.paste(ch_img, (int(x), int(y) + rnd.randint(-2, 2)), ch_img)
            x += f_hand.getlength(ch) + rnd.uniform(-1.0, 1.6)
        y += 54

    # 红笔批注
    d = ImageDraw.Draw(img)
    d.text((W - 430, y + 10), "推导正确，但未说明凸性假设  -3", font=f_red, fill=RED)
    d.text((W - 430, y + 52), "得分：17 / 20", font=f_red, fill=RED)

    grain(img, 7, seed=5)
    img = img.rotate(-1.1, resample=Image.BICUBIC, fillcolor=PAPER, expand=False)  # 扫描略微倾斜
    path = OUT / "手写作业.png"
    img.save(path, quality=94)
    return path


# ================================================================ 图三：论文截图
def make_paper() -> Path:
    W, H = 1240, 1480
    img = paper(W, H, (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_h1, f_h2, f_body, f_small = font("bold", 34), font("bold", 27), font("regular", 23), font("regular", 20)

    y = 70
    y = paragraph(d, (90, y), "面向课程知识点的多模态检索增强问答方法", f_h1, W - 180, 46)
    y += 6
    d.text((90, y), "陈嘉禾，张明远", font=f_small, fill=INK_SOFT)
    d.text((90, y + 28), "计算机科学与技术学院", font=f_small, fill=INK_SOFT)
    y += 76

    y = paragraph(d, (90, y), "摘  要", f_h2, W - 180, 36, BLUE)
    y = paragraph(d, (90, y),
                  "针对课程答疑中知识点粒度不一致、单路检索召回不足的问题，"
                  "本文提出一种融合关键词检索与稠密向量检索的多模态检索增强方法，"
                  "并引入倒数排序融合（RRF）对两路结果重排序。在自建的课程问答数据集上，"
                  "该方法相较单路 BM25 基线的召回率提升 12.4 个百分点。",
                  f_body, W - 200, 38)
    y += 14
    y = paragraph(d, (90, y), "关键词：多模态检索；检索增强生成；知识点抽取；重排序", f_body, W - 200, 38)
    y += 26

    y = paragraph(d, (90, y), "3  方法", f_h2, W - 180, 36, BLUE)
    y = paragraph(d, (90, y),
                  "本文方法由三部分组成：知识点抽取模块、双路检索模块与融合重排模块。"
                  "知识点抽取采用章节标题与定义句双重锚点；检索阶段并行执行 BM25 稀疏检索与"
                  "基于对比学习训练句向量的稠密检索；融合阶段使用 RRF 计算最终得分：",
                  f_body, W - 200, 38)
    y += 10
    d.text((110, y), "score(d) = Σ  1 / (k + rank_i(d))", font=font("bold", 26), fill=INK)
    y += 56
    y = paragraph(d, (90, y),
                  "实验设置：基线模型为 BM25 与单独使用稠密检索两个版本，"
                  "评价指标采用召回率与 F1。消融实验表明，去掉重排序模块后召回率下降 6.1 个百分点，"
                  "说明融合策略是有效的。显著性检验采用配对 t 检验，p < 0.05。",
                  f_body, W - 200, 38)
    y += 24
    y = paragraph(d, (90, y), "5  结论", f_h2, W - 180, 36, BLUE)
    y = paragraph(d, (90, y),
                  "实验表明，双路融合检索能显著提升课程知识点的召回效果，"
                  "知识点粒度的统一是其中贡献最大的因素。",
                  f_body, W - 200, 38)

    grain(img, 3, seed=9)
    path = OUT / "论文截图.png"
    img.save(path, quality=95)
    return path


# ================================================================ 图四：C 语言手写笔记
def make_c_notes() -> Path:
    """Copilot 图片演示用的素材：一页 C 语言「指针」手写笔记。

    放在 ``frontend/img/`` 下而不是 samples/ —— 它要被页面用
    ``/static/img/c-notes.png`` 直接引用（samples/ 没有静态挂载）。
    同样刻意带页眉 / 页码 / 水印 / 红笔批注，好让图文解析的去杂规则有东西可去。
    """
    W, H = 1100, 1420
    img = paper(W, H)
    d = ImageDraw.Draw(img)
    f_title, f_h2, f_body, f_hand, f_red = (font("bold", 34), font("bold", 25),
                                           font("regular", 22), font("hand", 27), font("hand", 25))

    # 页眉 + 页码（会被「页眉页脚 / 页码」规则清掉）
    d.text((70, 48), "C 语言程序设计 · 课堂笔记", font=f_title, fill=INK_SOFT)
    d.text((W - 190, 56), "第 8 章", font=f_body, fill=INK_SOFT)
    d.line([(70, 96), (W - 70, 96)], fill=(214, 224, 238), width=2)

    y = 130
    y = paragraph(d, (70, y), "8  指  针", f_title, W - 140, 46, BLUE)
    y += 18

    blocks = [
        ("8.1 什么是指针",
         "存放变量地址的变量。int a = 5;  int *p = &a;  此时 *p 就是 5，&a 是 a 的地址。"),
        ("8.2 指针与数组",
         "数组名就是首元素地址。a[i] 完全等价于 *(a + i)；p = a 之后，p[i] 与 a[i] 一样用。"),
        ("8.3 指针算术",
         "p + 1 不是地址加 1，而是向后移动 sizeof(*p) 个字节 —— 步长由指针类型决定。"),
        ("8.4 指针作参数",
         "C 语言只有值传递。想让函数改到实参，必须传地址：swap(&x, &y)，形参写 int *x。"),
        ("8.5 二级指针",
         "int **pp 指向一个 int*。char *argv[] 是指针数组，main 的命令行参数就是它。"),
    ]
    for head, body in blocks:
        y = paragraph(d, (70, y), head, f_h2, W - 140, 36)
        y = paragraph(d, (80, y), body, f_body, W - 160, 36)
        y += 16

    # 手写补充（易错点）
    y += 6
    y = paragraph(d, (70, y), "易错：", f_h2, W - 140, 36, RED)
    for line in ["声明 int* p, q;  只有 p 是指针，q 是 int —— * 绑定变量名。",
                 "野指针、空指针解引用、越界，调试时表现都是「偶尔崩一下」。"]:
        x = 84
        for ch in line:
            ch_img = Image.new("RGBA", (56, 56), (0, 0, 0, 0))
            ImageDraw.Draw(ch_img).text((6, 4), ch, font=f_hand, fill=(34, 48, 74, 255))
            ch_img = ch_img.rotate(random.Random(hash(ch) % 97).uniform(-2.6, 2.6),
                                   resample=Image.BICUBIC)
            img.paste(ch_img, (int(x), int(y)), ch_img)
            x += f_hand.getlength(ch)
        y += 46

    watermark(img, "课堂笔记  仅供参考")
    grain(img, 5, seed=13)
    d = ImageDraw.Draw(img)
    # 红笔批注
    d.text((W - 470, y + 18), "老师批：p+1 的步长要记牢！", font=f_red, fill=RED)
    d.line([(70, H - 92), (W - 70, H - 92)], fill=(214, 224, 238), width=2)
    d.text((70, H - 70), "C 语言程序设计 课堂笔记", font=f_body, fill=INK_SOFT)
    d.text((W - 190, H - 70), "第 86 页", font=f_body, fill=INK_SOFT)

    target = ROOT / "frontend" / "img"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "c-notes.png"
    img.save(path, quality=92)
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in (make_courseware, make_homework, make_paper, make_c_notes):
        p = fn()
        print("生成", p, f"{p.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
