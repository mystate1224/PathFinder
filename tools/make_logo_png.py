# -*- coding: utf-8 -*-
"""把界面里的寻径 logo（指南针）导出成 PNG。

来源与界面保持一致：
  - 图形：frontend/js/common.js 第 20 行 compass 的 SVG path（圆 + 菱形指针，描边风格）
  - 配色：frontend/css/style.css .sidebar__mark（白底 + --brand-600 #3d4ce2 罗盘，
          描边 --brand-200 #cacfff，圆角 10/32）
用法：python tools/make_logo_png.py [输出目录]
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BRAND_600 = (61, 76, 226)      # #3d4ce2 罗盘蓝
BRAND_500 = (67, 83, 255)      # #4353ff 宝蓝
BRAND_200 = (202, 207, 255)    # #cacfff 描边
CYAN = (23, 201, 168)          # #17c9a8 辅助青
INK_950 = (24, 25, 28)         # #18191C 主文字
INK_500 = (122, 128, 143)      # 副文字（--ink-500 近似）

FONT_CN = "C:/Windows/Fonts/msyhbd.ttc"   # 微软雅黑 Bold
FONT_EN = "C:/Windows/Fonts/seguisb.ttf"  # Segoe UI Semibold


def round_rect(size, radius, fill, outline=None, width=0):
    """返回一张圆角矩形 RGBA 图。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = [width / 2, width / 2, size - 1 - width / 2, size - 1 - width / 2]
    d.rounded_rectangle(box, radius=radius, fill=fill,
                        outline=outline, width=width)
    return img


def gradient(size, c0, c1):
    """CSS linear-gradient(150deg, c0 55%, c1 100%) 的近似：左上→右下对角渐变。"""
    t = np.linspace(0, 1, size * 2, dtype=np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    p = np.clip((xx + yy) / (2.0 * size - 2), 0, 1)
    # 55% 之前维持 c0，之后过渡到 c1
    p = np.clip((p - 0.55) / 0.45, 0, 1)
    r = (c0[0] + (c1[0] - c0[0]) * p).astype(np.uint8)
    g = (c0[1] + (c1[1] - c0[1]) * p).astype(np.uint8)
    b = (c0[2] + (c1[2] - c0[2]) * p).astype(np.uint8)
    a = np.full((size, size), 255, dtype=np.uint8)
    return Image.fromarray(np.dstack([r, g, b, a]), "RGBA")


def draw_compass(d, size, color, stroke):
    """在 size×size 的画布中心画罗盘；图形按 SVG viewBox 24 等比缩放。"""
    s = size / 24.0
    cx = cy = size / 2.0
    r = 9 * s
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=stroke)
    # M15.5 8.5 l-2 5 -5 2 2-5 z
    pts = [(15.5, 8.5), (13.5, 13.5), (8.5, 15.5), (10.5, 10.5)]
    pts = [(cx + (x - 12) * s, cy + (y - 12) * s) for x, y in pts]
    for i in range(len(pts)):
        d.line([pts[i], pts[(i + 1) % len(pts)]], fill=color,
               width=stroke, joint="curve")
    rr = stroke / 2.0  # 顶点补圆，消除折线接缝豁口
    for x, y in pts:
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=color)


def make_icon(size, plate=True, reverse=False):
    """方形图标。plate=True 画白底圆角块；reverse=True 蓝底白罗盘。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if plate:
        radius = int(round(10 / 32.0 * size))
        grad = gradient(size, (255, 255, 255), (238, 241, 255))
        mask = round_rect(size, radius, (255, 255, 255, 255))
        img.paste(grad, (0, 0), mask)
        bw = max(1, int(round(size / 32.0)))          # 1px on 32px
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([bw / 2, bw / 2, size - 1 - bw / 2, size - 1 - bw / 2],
                            radius=radius, outline=BRAND_200, width=bw)
        # 罗盘占 18/32
        inner = int(round(18 / 32.0 * size))
        mark = Image.new("RGBA", (inner, inner), (0, 0, 0, 0))
        draw_compass(ImageDraw.Draw(mark), inner, BRAND_600,
                     max(2, int(round(inner / 12.0))))
        img.alpha_composite(mark, ((size - inner) // 2, (size - inner) // 2))
    else:
        if reverse:  # 蓝底白罗盘
            radius = int(round(10 / 32.0 * size))
            g = gradient(size, BRAND_500, BRAND_600)
            mask = round_rect(size, radius, (255, 255, 255, 255))
            img.paste(g, (0, 0), mask)
            icon_color = (255, 255, 255)
        else:        # 纯罗盘（透明底）
            icon_color = BRAND_500
        inner = int(round(18 / 32.0 * size)) if reverse else int(round(size * 0.86))
        mark = Image.new("RGBA", (inner, inner), (0, 0, 0, 0))
        draw_compass(ImageDraw.Draw(mark), inner, icon_color,
                     max(2, int(round(inner / 12.0))))
        img.alpha_composite(mark, ((size - inner) // 2, (size - inner) // 2))
    return img


def text_w(d, s, font, spacing=0.0):
    if spacing <= 0:
        return d.textlength(s, font=font)
    return sum(d.textlength(ch, font=font) + spacing for ch in s)


def draw_tracked(d, xy, s, font, fill, spacing=0.0):
    x, y = xy
    for ch in s:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + spacing
    return x


def make_horizontal(w=1600, h=420):
    """图标 + 寻径教育 / PathFinder 横版，透明背景。"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    icon_size = int(h * 0.62)
    icon = make_icon(icon_size, plate=True)
    pad = int(h * 0.10)
    img.alpha_composite(icon, (pad, (h - icon_size) // 2))

    d = ImageDraw.Draw(img)
    f_cn = ImageFont.truetype(FONT_CN, int(h * 0.30))
    f_en = ImageFont.truetype(FONT_EN, int(h * 0.115))
    x = pad + icon_size + int(h * 0.16)

    cn = "寻径教育"
    y_cn = int(h * 0.22)
    d.text((x, y_cn), cn, font=f_cn, fill=INK_950)

    en = "PATHFINDER"
    sp = f_en.size * 0.14
    y_en = y_cn + int(h * 0.36)
    draw_tracked(d, (x + 2, y_en), en, f_en, INK_500, sp)

    # 品牌渐变短条（对应 .sidebar__brand::after）
    bar_w = int(icon_size * 2.0)
    bar_h = max(3, int(h * 0.022))
    bar = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    for i in range(bar_w):
        t = i / max(1, bar_w - 1)
        bd.line([(i, 0), (i, bar_h)],
                fill=tuple(int(a + (b - a) * t) for a, b in zip(BRAND_500, CYAN)))
    img.alpha_composite(bar, (x + 2, y_en + int(h * 0.20)))
    return img


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "C:/Users/Hejinwen/Desktop/寻径教育-logo"
    os.makedirs(out, exist_ok=True)

    files = []
    p = os.path.join(out, "寻径教育-标志-512.png")
    make_icon(512, plate=True).save(p); files.append(p)

    p = os.path.join(out, "寻径教育-标志-反色-512.png")
    make_icon(512, plate=False, reverse=True).save(p); files.append(p)

    p = os.path.join(out, "寻径教育-标志-单色-512.png")
    make_icon(512, plate=False, reverse=False).save(p); files.append(p)

    p = os.path.join(out, "寻径教育-标志-横版-1600.png")
    make_horizontal().save(p); files.append(p)

    p = os.path.join(out, "favicon-64.png")
    make_icon(64, plate=False, reverse=True).save(p); files.append(p)

    for f in files:
        print("%8d B  %s" % (os.path.getsize(f), f))


if __name__ == "__main__":
    main()
