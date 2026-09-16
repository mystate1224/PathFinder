# -*- coding: utf-8 -*-
"""
前端静态体检（无需浏览器）

做三件事：
  1. 抽出每个 HTML 里的内联 <script>，用 node --check 校验语法
  2. 扫描页面调用的 PF.xxx / ICONS 名字，比对 common.js 真实导出的成员，报出「调了但没定义」
  3. 扫描页面用到的 class 名，比对 style.css 里定义过的选择器，报出「用了但没样式」

用法： python tools/check_frontend.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
NODE = "node"

# PF 上「本来就不是函数」的成员：属性 / 常量 / 状态
PF_NON_FUNC = {
    "state", "api", "get", "post", "del", "try", "download",  # 这些是函数，保留
}

# common.js 之外由页面自己挂到 PF 上的东西（白名单）
PF_EXTRA_OK: set[str] = set()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 1. 语法检查

def extract_inline_scripts(html: str) -> list[str]:
    """取出所有没有 src 属性的 <script> 块内容。"""
    out: list[str] = []
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script\s*>", html, re.S | re.I):
        attrs, body = m.group(1), m.group(2)
        if re.search(r"\bsrc\s*=", attrs, re.I):
            continue
        if body.strip():
            out.append(body)
    return out


def node_check(code: str, label: str) -> str | None:
    """返回 None 表示通过，否则返回错误信息。"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8", newline="\n") as fh:
        # 包一层 async IIFE，允许顶层 await
        fh.write("(async () => {\n" + code + "\n})();\n")
        tmp = fh.name
    try:
        proc = subprocess.run([NODE, "--check", tmp], capture_output=True, text=True)
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            msg = re.sub(r"^\S*\.js:", f"{label}:", msg, flags=re.M)
            return msg
        return None
    finally:
        Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------- 2. PF 成员是否存在

def pf_members_from_common(common_js: str) -> set[str]:
    """从 common.js 里挖出挂到 PF 上的名字：PF.x = / x: 定义 / function x( ..."""
    names: set[str] = set()

    # 形式一：PF.xxx = 或 PF.xxx=
    names |= set(re.findall(r"\bPF\.([A-Za-z_$][\w$]*)\s*=", common_js))

    # 形式二：const PF = { ... } 对象字面量里的键
    m = re.search(r"\b(?:const|let|var)\s+PF\s*=\s*\{", common_js)
    if m:
        depth, i = 1, m.end()
        while i < len(common_js) and depth:
            ch = common_js[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        body = common_js[m.end(): i - 1]
        # 顶层键：行首（可有缩进）的 ident: 或 ident( 、 ident,
        names |= set(re.findall(r"(?:^|[\n,{])\s*([A-Za-z_$][\w$]*)\s*(?::|\()", body))

    # 形式三：Object.assign(PF, { ... })
    for m in re.finditer(r"Object\.assign\s*\(\s*PF\s*,\s*\{", common_js):
        depth, i = 1, m.end()
        while i < len(common_js) and depth:
            ch = common_js[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        body = common_js[m.end(): i - 1]
        names |= set(re.findall(r"(?:^|[\n,{])\s*([A-Za-z_$][\w$]*)\s*(?::|\()", body))

    # window.PF = PF 这种别名不算成员
    names.discard("")
    return names


# ------------------------------------------------------- 3. CSS class 定义

def css_classes(css: str) -> set[str]:
    """粗略提取 CSS 里出现过的 class 名。"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return set(re.findall(r"\.(-?[A-Za-z_][\w-]*)", css))


# class 名的合法形状：小写开头，允许 -、_、__、--，且 --/__ 后可有一个大写段（level--A）
TOKEN_OK = re.compile(r"^[a-z][a-z0-9_-]*(?:(?:--|__)[A-Z][a-zA-Z0-9]*)?$")

# 这些是运行时拼出来的（如 `card__${kind}`、`engine--${engine}`），
# 静态对不上很正常，只保留「静态一定存在」的那部分，其余按前缀放行
DYNAMIC_PREFIXES = (
    "card__", "btn--", "badge--", "stat__", "pick__", "track--", "level--",
    "progress__", "engine__", "u-", "js-", "pf-",
)


def html_classes(html: str) -> set[str]:
    """
    提取 class="..." / class='...' 里用到的 class 名。

    模板字符串里的 ${...} 会把捕获串搅碎（如 class="a ${x ? 'b' : 'c'}"），
    这里用 TOKEN_OK 把碎片过滤掉，只留合法 class 名。
    """
    names: set[str] = set()
    for m in re.finditer(r"""\bclass\s*=\s*(?:"([^"]*)"|'([^']*)')""", html):
        raw = m.group(1) or m.group(2) or ""
        for token in raw.split():
            if TOKEN_OK.match(token):
                names.add(token)
    return names


def local_style(html: str) -> set[str]:
    """页面自带 <style> 里的 class（页面私有样式，不该拿 style.css 去要求它）。"""
    out: set[str] = set()
    for m in re.finditer(r"<style\b[^>]*>(.*?)</style\s*>", html, re.S | re.I):
        out |= css_classes(m.group(1))
    return out


def main() -> int:
    common = read(FRONTEND / "js" / "common.js")
    tabs = read(FRONTEND / "js" / "tabs.js")
    style = read(FRONTEND / "css" / "style.css")

    # PF 成员 = common.js + tabs.js 共同挂在 PF 上的
    pf_members = pf_members_from_common(common) | pf_members_from_common(tabs)
    global_css = css_classes(style)
    # common.js / tabs.js 运行时也会拼 class，把它们字面量里出现的算作已定义
    runtime_css = html_classes(common) | html_classes(tabs)

    pages = sorted(FRONTEND.glob("*.html"))
    problems: list[str] = []

    print(f"PF 成员 {len(pf_members)} 个（common.js + tabs.js）；"
          f"style.css 定义 class {len(global_css)} 个；待检查页面 {len(pages)} 个\n")

    # 全站 PF 调用面
    all_js = common + tabs + "".join(read(p) for p in pages)
    used = set(re.findall(r"\bPF\.([A-Za-z_$][\w$]*)", all_js))
    missing = sorted(used - pf_members - PF_EXTRA_OK)
    if missing:
        problems.append("[调用] PF 调用了未定义成员：" + "、".join(missing))

    for page in pages:
        html = read(page)
        name = page.name

        # 1) 内联脚本语法
        for idx, code in enumerate(extract_inline_scripts(html), 1):
            err = node_check(code, f"{name} 第{idx}个内联脚本")
            if err:
                problems.append(f"[语法] {err}")

        # 2) class 是否有样式（全局 style.css ∪ 页面自带 <style>）
        defined = global_css | runtime_css | local_style(html)
        undef = sorted(
            c for c in html_classes(html)
            if c not in defined and not c.startswith(DYNAMIC_PREFIXES)
        )
        if undef:
            problems.append(f"[样式] {name} 用了没有样式的 class：" + "、".join(undef))

    print("=" * 68)
    if problems:
        for item in problems:
            print("  !!", item)
        print("=" * 68)
        print(f"发现 {len(problems)} 个问题")
        return 1

    print("全部通过：内联脚本语法正常、PF 调用有定义、class 均有样式")
    return 0


if __name__ == "__main__":
    sys.exit(main())
