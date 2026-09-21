# -*- coding: utf-8 -*-
"""smoke.py —— 全链路冒烟测试（不依赖 API Key，可反复运行）。

它做的事：
1. 在**子进程**里用 uvicorn 起一个隔离的测试服务（临时数据库 + 临时端口），
   不污染开发库，也不会因为你正在开着 app.py 而抢端口。
2. 用 HTTP 真实走一遍：登录 → 教师 11 条链路 → 学生 11 条链路 → 权限边界 → 页面可达性。
3. 逐条打印 PASS/FAIL，最后给出汇总；有失败则退出码为 1（可直接接 CI）。

用法：
    python backend/smoke.py                 # 完整跑一遍
    python backend/smoke.py --keep-open     # 跑完不关服务，方便手工点页面
    python backend/smoke.py --verbose       # 打印每个请求

设计约束：这个脚本**不改动任何生产数据**，只读 + 用临时目录。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
PYTHON = sys.executable


# ================================================================ 小工具
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Client:
    """极简 HTTP 客户端：带 Cookie 与 Bearer 双通道，自动解包 {ok,data}。"""

    def __init__(self, base: str, verbose: bool = False) -> None:
        self.base = base.rstrip("/")
        self.verbose = verbose
        self.cookie = ""
        self.token = ""
        self.fails: list[str] = []
        self.passes = 0

    # ---------------------------------------------------------- 原始请求
    def raw(self, method: str, path: str, body=None, form=None, expect: int | None = None):
        url = self.base + path
        data = None
        headers = {"Accept": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if form is not None:
            data = form
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                payload = resp.read()
                sc = resp.headers.get("Set-Cookie")
                if sc:
                    self.cookie = sc.split(";")[0]
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = exc.read()
        if self.verbose:
            print(f"      → {method} {path} [{status}]")
        if expect is not None and status != expect:
            raise AssertionError(f"{method} {path} 期望 HTTP {expect}，实际 {status}")
        return status, payload

    def json(self, method: str, path: str, body=None, form=None, expect: int = 200):
        status, payload = self.raw(method, path, body=body, form=form, expect=expect)
        try:
            return json.loads(payload.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"{method} {path} 返回的不是 JSON：{payload[:200]!r}") from exc

    def api(self, method: str, path: str, body=None, form=None):
        """调用业务接口，断言 ok=true 并返回 data。"""
        doc = self.json(method, path, body=body, form=form)
        if not doc.get("ok"):
            raise AssertionError(f"{method} {path} 业务失败：{doc.get('error')}")
        return doc.get("data")

    def page(self, path: str, expect: int = 200):
        status, payload = self.raw("GET", path, expect=expect)
        return status, payload.decode("utf-8", "replace")

    def form(self, path: str, body: bytes, content_type: str) -> dict:
        """发一个原始 multipart 请求，返回解包后的 JSON。"""
        headers = {"Accept": "application/json", "Content-Type": content_type}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        if not doc.get("ok"):
            raise AssertionError(f"POST {path} 业务失败：{doc.get('error')}")
        return doc["data"]

    def login(self, username: str, password: str = "123456") -> dict:
        data = self.api("POST", "/api/auth/login", {"username": username, "password": password})
        self.token = data.get("token") or ""
        return data

    def logout(self) -> None:
        try:
            self.api("POST", "/api/auth/logout", {})
        except Exception:  # noqa: BLE001 - 退出登录失败不影响后续
            pass
        self.token = ""
        self.cookie = ""

    # ---------------------------------------------------------- 断言
    def check(self, name: str, fn) -> bool:
        try:
            detail = fn()
            self.passes += 1
            print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))
            return True
        except Exception as exc:  # noqa: BLE001 - 冒烟测试要收集全部失败点
            self.fails.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"  [FAIL] {name}\n         {type(exc).__name__}: {exc}")
            return False


def need(cond, msg: str = "断言失败") -> None:
    if not cond:
        raise AssertionError(msg)


def multipart(fields: dict[str, str] | None = None,
              files: list[tuple[str, str, bytes]] | None = None,
              boundary: str = "----pfSmokeBoundary") -> tuple[bytes, str]:
    """构造 multipart/form-data 请求体，返回 ``(body, content_type)``。"""
    parts: list[bytes] = []
    for key, value in (fields or {}).items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n"
            .encode("utf-8")
        )
    for name, filename, blob in (files or []):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
            f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
            .encode("utf-8") + blob + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# ================================================================ 用例
def test_teacher(c: Client) -> None:
    print("\n=== 教师端 ===")
    c.check("登录（教师）", lambda: c.login("teacher").get("name"))

    c.check("健康检查含 FTS 与模型状态", lambda: (
        lambda d: f"FTS={'可用' if d['db']['fts_ok'] else '降级'}，模式={d['llm']['llm_mode']}"
    )(c.api("GET", "/api/health")))

    c.check("站点元数据齐全", lambda: (
        lambda d: f"方向 {len(d['directions'])} 个，资源类型 {len(d['resource_types'])} 种，"
                  f"口径说明 {len(d['caveats'])} 条"
    )(c.api("GET", "/api/meta")))

    # --- 驾驶舱 ---
    def overview():
        d = c.api("GET", "/api/teacher/overview")
        need(d["stats"]["students"] > 0, "本班没有学生")
        need(d["students"], "students 列表为空")
        need(d["advice"], "教学建议为空")
        first = d["students"][0]
        need(first.get("ability_pairs"), "学生缺少能力画像")
        return (f"学生 {d['stats']['students']} 人，平均绩点 {d['stats']['avg_gpa']}，"
                f"建议 {len(d['advice'])} 条（{d['advice_engine']}）")
    c.check("驾驶舱班级学情", overview)

    def overview_filter():
        d = c.api("GET", "/api/teacher/overview?level=A")
        need(all(s["grade_level"] == "A" for s in d["students"]), "按层次筛选未生效")
        return f"A 层 {len(d['students'])} 人"
    c.check("驾驶舱筛选（层次）", overview_filter)

    # --- 学生详情与掌握度 ---
    def student_detail():
        ov = c.api("GET", "/api/teacher/overview")
        sid = ov["students"][0]["id"]
        d = c.api("GET", f"/api/teacher/students/{sid}")
        need(d["student"]["name"], "缺少学生姓名")
        need(d["roadmap"]["stages"], "缺少成长路线阶段")
        need(d["profile"]["layer"], "缺少推荐内容深度")
        return f"{d['student']['name']}：路线 {len(d['roadmap']['stages'])} 阶段（{d['roadmap_engine']}）"
    c.check("学生详情 + 成长路线", student_detail)

    def mastery():
        ov = c.api("GET", "/api/teacher/overview")
        # 挑一个有已批改作业的学生
        for s in ov["students"]:
            res = c.api("POST", f"/api/teacher/students/{s['id']}/mastery", {})
            if res.get("count"):
                return f"{s['name']} 写入 {res['count']} 条掌握度观测"
        return "无可推导的观测（属正常：需要已批改且评语命中知识点的作业）"
    c.check("掌握度重算", mastery)

    # --- 备课 ---
    def lesson():
        d = c.api("POST", "/api/teacher/lesson",
                  {"topic": "注意力机制", "course": "机器学习", "periods": 2, "level": "B"})
        plan = d["plan"]
        need(plan["objectives"], "教案缺少教学目标")
        need(plan["outline"], "教案缺少教学环节")
        need(d.get("artifact"), "教案未落盘为 docx")
        return f"《{plan['title']}》：{len(plan['outline'])} 环节，docx {d['artifact'].get('size', 0)} 字节（{d['engine']}）"
    c.check("备课：教案 + docx", lesson)

    def slides():
        d = c.api("POST", "/api/teacher/slides", {"topic": "卷积神经网络", "pages": 8, "course": "深度学习"})
        slides_list = d["outline"]["slides"]
        need(len(slides_list) >= 4, "PPT 页数过少")
        need(all(s.get("title") for s in slides_list), "PPT 存在无标题页")
        need(d.get("artifact"), "PPT 未落盘")
        return f"{len(slides_list)} 页，pptx {d['artifact'].get('size', 0)} 字节（{d['engine']}）"
    c.check("备课：PPT 大纲 + pptx", slides)

    def artifacts():
        d = c.api("GET", "/api/teacher/artifacts")
        need(d["artifacts"], "备课文稿列表为空")
        first = d["artifacts"][0]
        blob = c.raw("GET", f"/api/teacher/artifacts/{first['id']}/download", expect=200)[1]
        need(len(blob) > 1000, "下载的文稿过小")
        # OOXML 是 zip，前两字节必须是 PK
        need(blob[:2] == b"PK", "下载内容不是有效的 OOXML 包")
        return f"{len(d['artifacts'])} 份文稿，下载《{first.get('title')}》{len(blob)} 字节，包头合法"
    c.check("备课文稿列表 + 下载校验", artifacts)

    # --- 备课：教案/PPT 归档、教案编辑、文件夹整理（一次备课的产物聚在一起） ---
    def slides_from_lesson():
        d = c.api("POST", "/api/teacher/lesson",
                  {"topic": "Dijkstra 最短路径", "course": "数据结构", "periods": 2, "level": "B",
                   "folder": "冒烟 · Dijkstra"})
        lesson_id = d["artifact"]["id"]
        folder = d.get("folder")
        need(folder == "冒烟 · Dijkstra", f"教案未归档到指定文件夹：{folder}")
        r = c.api("POST", "/api/teacher/slides/from-lesson", {"artifact_id": lesson_id, "pages": 8})
        page_list = r["outline"]["slides"]
        need(len(page_list) >= 5, f"PPT 页数过少：{len(page_list)}")
        need(all(s.get("title") for s in page_list), "PPT 存在无标题页")
        last = str(page_list[-1].get("title") or "")
        need("小结" in last or "作业" in last, f"末页应为小结与作业，实际：{last}")
        need(r.get("folder") == folder, f"PPT 未与教案归档到同一文件夹：{r.get('folder')}")
        need(r.get("artifact"), "PPT 未落盘")
        return (f"{len(page_list)} 页，末页「{last}」，教案与 PPT 同在「{folder}」"
                f"（{r['engine']}）")
    c.check("备课：教案 → PPT（自动归入同一文件夹）", slides_from_lesson)

    def slides_from_material():
        text = ("# 冒泡排序\n"
                "冒泡排序通过相邻元素的比较与交换，把当前最大的元素逐步移动到末尾，"
                "时间复杂度为 O(n^2)，空间复杂度为 O(1)。\n"
                "## 稳定性\n相等元素不发生交换，因此冒泡排序是稳定排序。\n"
                "## 适用场景\n适合规模较小或基本有序的数据；大规模数据应改用快速排序或归并排序。")
        body, ct = multipart({"topic": "冒泡排序", "pages": "8", "folder": "冒烟 · 冒泡排序"},
                             [("file", "冒泡排序讲义.md", text.encode("utf-8"))])
        d = c.form("/api/teacher/slides/from-material", body, ct)
        page_list = d["outline"]["slides"]
        need(len(page_list) >= 3, f"PPT 页数过少：{len(page_list)}")
        last = str(page_list[-1].get("title") or "")
        need("小结" in last or "作业" in last, f"末页应为小结与作业，实际：{last}")
        need(d.get("folder") == "冒烟 · 冒泡排序", "资料生成的 PPT 未归档到指定文件夹")
        # 可溯源：正文页的要点应来自资料原文，而不是凭空编的套话
        bullets = [b for s in page_list[1:-1] for b in (s.get("bullets") or [])]
        hit = sum(1 for b in bullets if str(b) in text)
        need(bullets, "PPT 正文页没有要点")
        need(hit / len(bullets) >= 0.6, f"要点可溯源率过低：{hit}/{len(bullets)}")
        return f"{len(page_list)} 页，要点溯源 {hit}/{len(bullets)}，来源《{d.get('material')}》"
    c.check("备课：上传资料 → PPT（要点可溯源）", slides_from_material)

    def edit_lesson():
        d = c.api("POST", "/api/teacher/lesson",
                  {"topic": "编辑验证课题", "periods": 1, "level": "B", "folder": "冒烟 · 编辑"})
        art = d["artifact"]
        before = c.api("GET", f"/api/teacher/artifacts/{art['id']}")
        need(before["content"].get("outline"), "产物内容缺失，无法验证编辑")
        plan = dict(before["content"])
        plan["homework"] = "课后第 1~3 题，并写出每一步的距离表"
        plan["objectives"] = ["理解算法思想", "能手算一次完整过程"]
        r = c.api("PUT", f"/api/teacher/artifacts/{art['id']}",
                  {"content": plan, "title": plan.get("title") or "教案", "course": ""})
        need(r["artifact"]["id"] == art["id"], "编辑保存后 id 变了（应原地覆盖，不新增一份）")
        after = c.api("GET", f"/api/teacher/artifacts/{art['id']}")
        need(after["content"]["homework"] == plan["homework"], "修改未持久化")
        need(after.get("folder") == "冒烟 · 编辑", f"编辑后文件夹变了：{after.get('folder')}")
        blob = c.raw("GET", f"/api/teacher/artifacts/{art['id']}/download", expect=200)[1]
        need(blob[:2] == b"PK", "按改后内容重新生成的 docx 不是合法 OOXML 包")
        return f"修改已持久化并重新出 docx（{len(blob)} 字节），仍在「{after.get('folder')}」"
    c.check("备课：教案编辑保存（原地覆盖 + 重新出文件）", edit_lesson)

    def folder_ops():
        name = "冒烟 · 整理中"
        name2 = "冒烟 · 已整理"
        c.api("POST", "/api/teacher/folders", {"name": name})
        # 建空文件夹也要能出现在列表里（老师可以先建好目录，再把产物移进来）
        listed = [f["name"] for f in c.api("GET", "/api/teacher/folders")["folders"]]
        need(name in listed, f"新建文件夹未出现在列表：{listed}")

        # 每次生成都会自动归档，所以这里不挑「未归档」的，直接拿最近一份产物来搬
        all_arts = c.api("GET", "/api/teacher/artifacts")["artifacts"]
        need(all_arts, "没有产物，无法验证移动")
        ids = [all_arts[0]["id"]]
        c.api("POST", "/api/teacher/artifacts/move", {"ids": ids, "folder": name})
        moved = [a for a in c.api("GET", "/api/teacher/artifacts")["artifacts"] if a["id"] in ids]
        need(moved and moved[0]["folder"] == name, f"移动后归属不对：{moved and moved[0]['folder']}")

        c.api("POST", "/api/teacher/folders/rename", {"old": name, "new": name2})
        renamed = [a for a in c.api("GET", "/api/teacher/artifacts")["artifacts"] if a["id"] in ids]
        need(renamed[0]["folder"] == name2, f"重命名后产物归属未跟着变：{renamed[0]['folder']}")

        c.api("DELETE", f"/api/teacher/folders/{quote(name2, safe='')}")
        back = [a for a in c.api("GET", "/api/teacher/artifacts")["artifacts"] if a["id"] in ids]
        need(back[0]["folder"] == "", "删除文件夹后文件应退回「未归档」，而不是被删掉")
        still = c.api("GET", f"/api/teacher/artifacts/{ids[0]}")
        need(still.get("kind"), "记录应保留")
        return f"新建 → 移入 → 重命名 → 取消归档，文件 {ids[0]} 仍可访问"
    c.check("备课：文件夹整理（新建 / 移动 / 重命名 / 取消归档）", folder_ops)

    # --- 批改 ---
    def grade_one():
        d = c.api("POST", "/api/teacher/grade/suggest",
                  {"text": "注意力机制通过查询与键的点积计算权重，再对值加权求和。"
                           "缩放点积注意力除以根号 d_k 是为了稳定梯度。",
                   "course": "机器学习", "topic": "注意力机制", "full_score": 100})
        need(0 <= d["score"] <= 100, "分数越界")
        need(d["comment"], "缺少评语")
        return f"建议分 {d['score']}（{d['level_text']}），engine={d['engine']}"
    c.check("批改：试批（自由文本）", grade_one)

    def homework_flow():
        created = c.api("POST", "/api/teacher/homework", {
            "title": "冒烟测试作业", "course": "机器学习", "class_name": "CS2301",
            "detail": "请说明注意力机制的作用", "full_score": 100, "deadline": "",
        })
        hid = created["homework_id"]
        roster = c.api("GET", f"/api/teacher/homework/{hid}/roster")
        need(roster["students"], "作业名单为空")
        target = roster["students"][0]

        # 让学生真实提交一次 —— 否则"AI 建议分"这一段是假验的
        stu = Client(c.base)
        stu.login(target["username"])
        body, ctype = multipart(
            fields={"content": "注意力机制用查询与键的点积算权重，再对值加权求和；"
                               "除以根号 d_k 是为了防止 softmax 进入饱和区导致梯度消失。"},
            files=[("files", "作答.txt", "我的作答正文。".encode("utf-8"))],
        )
        submitted = stu.form(f"/api/homework/{hid}/submit", body, ctype)
        need(submitted.get("submission_id"), "学生提交未成功")

        # 教师取 AI 建议分（学生已提交后才有东西可批）
        sug = c.api("POST", f"/api/teacher/homework/{hid}/suggest",
                    {"student_id": target["student_id"]})
        need(0 <= float(sug["score"]) <= 100, "建议分越界")
        need(sug.get("engine"), "建议分没有标注引擎")
        need(sug.get("comment"), "建议分没有评语")

        # 教师确认分数（最终分由教师定，AI 只给建议）
        c.api("POST", f"/api/teacher/homework/{hid}/grade", {
            "student_id": target["student_id"], "score": 88,
            "comment": "要点覆盖完整，结构清晰。", "level": "A",
        })
        # 缺交记零
        zeroed = c.api("POST", f"/api/teacher/homework/{hid}/grade-missing", {})
        stats = c.api("GET", f"/api/teacher/homework/{hid}/stats")
        need(stats["graded"] > 0, "统计里已批改数为 0")
        need(stats["dist"]["A"] >= 1, "层次分布未统计到刚才打的 A")
        csv = c.raw("GET", f"/api/teacher/homework/{hid}/export", expect=200)[1]
        need(b"\xe5\xad\xa6" in csv or len(csv) > 50, "导出 CSV 内容异常")
        # 清理
        c.api("DELETE", f"/api/teacher/homework/{hid}")
        return (f"名单 {len(roster['students'])} 人 → 学生提交《作答.txt》→ AI 建议分 "
                f"{sug['score']}（{sug['engine']}）→ 教师定 88 → 缺交记零 "
                f"{zeroed.get('count', 0)} 份 → CSV {len(csv)} 字节 → 删除")
    c.check("作业闭环：发布→提交→建议分→定分→统计→导出→删除", homework_flow)

    # --- 资源 ---
    def resource_flow():
        created = c.api("POST", "/api/teacher/resources", {
            "rtype": "contest", "title": "冒烟测试：算法竞赛集训", "detail": "为期两周的集训",
            "tags": ["算法", "竞赛"], "capacity": 5, "deadline": "",
        })
        rid = created["resource_id"]
        detail = c.api("GET", f"/api/resources/{rid}")
        need(detail["title"], "资源详情缺失")
        need(detail.get("teacher_name"), "资源详情缺少发布教师")
        view = c.api("GET", "/api/resources")       # 教师身份进来就是教师视角
        need(view["stats"]["total"] > 0, "教师资源统计为空")
        c.api("POST", f"/api/teacher/resources/{rid}/close", {})
        c.api("DELETE", f"/api/teacher/resources/{rid}")
        return f"发布→详情《{detail['title']}》→列表({view['stats']['total']} 条)→关闭→删除 全通过"
    c.check("资源管理闭环", resource_flow)

    # --- 匹配 ---
    def match():
        try:
            d = c.api("GET", "/api/match/recommend")
        except AssertionError as exc:
            # 没有团队是合法的业务状态，不算失败
            return f"无团队（业务上正常）：{exc}"
        groups = d["groups"]
        need(groups, "groups 为空")
        cands = groups[0]["candidates"]
        if cands:
            c.api("POST", "/api/match/decide", {
                "student_id": cands[0]["student_id"], "group_id": groups[0]["group_id"], "action": "accepted",
            })
        return f"{len(groups)} 个团队，首选候选 {cands[0]['name'] if cands else '—'}（{cands[0]['score'] if cands else 0}）"
    c.check("师生匹配（教师侧）", match)

    # --- 团队增删改（含类型字段）---
    def group_crud():
        name = "冒烟临时团队-" + str(int(time.time()))
        gid = c.api("POST", "/api/teacher/groups", {
            "name": name, "directions": "冒烟、临时",
            "requirement": "由 smoke.py 创建，测试完即删", "capacity": 1,
            "kind": "竞赛团队",
        })["group_id"]
        try:
            renamed = name + "（已改）"
            c.api("POST", f"/api/teacher/groups/{gid}", {
                "name": renamed, "directions": "冒烟、临时、改过",
                "requirement": "改过了", "capacity": 2, "kind": "横向项目",
            })
            rows = [g for g in c.api("GET", "/api/teacher/groups")["groups"] if int(g["id"]) == gid]
            need(rows, "新建的团队没出现在列表里")
            need(rows[0]["name"] == renamed, "名称没改成功")
            need(len(rows[0]["directions"]) == 3, "方向没改成功")
            need(int(rows[0]["capacity"]) == 2, "名额上限没改成功")
            need(rows[0]["kind"] == "横向项目", f"团队类型没改成功：{rows[0].get('kind')}")

            # 字典外的类型应被兜底成「其他」，而不是原样入库
            c.api("POST", f"/api/teacher/groups/{gid}", {"kind": "不存在的类型"})
            rows = [g for g in c.api("GET", "/api/teacher/groups")["groups"] if int(g["id"]) == gid]
            need(rows[0]["kind"] == "其他", f"字典外的类型应兜底为「其他」，实际 {rows[0].get('kind')}")

            status, _ = c.raw("POST", "/api/teacher/groups",
                              {"name": rows[0]["name"], "directions": "冒烟"})
            need(status == 400, f"同名团队应被拒（400），实际 {status}")
            status, _ = c.raw("POST", "/api/teacher/groups/99999999", {"capacity": 1})
            need(status == 404, f"不存在的团队应返回 404，实际 {status}")
            status, _ = c.raw("POST", f"/api/teacher/groups/{gid}", {"name": "", "capacity": 1})
            need(status == 400, f"空名称应被拒（400），实际 {status}")
        finally:
            c.api("DELETE", f"/api/teacher/groups/{gid}")
        rows = [g for g in c.api("GET", "/api/teacher/groups")["groups"] if int(g["id"]) == gid]
        need(not rows, "团队没被删掉")
        return (f"新建 #{gid}（竞赛团队）→ 改名/改方向/改名额/改类型 → 字典外类型兜底为「其他」"
                f" → 重名与空名被拒 → 删除，全部符合预期")
    c.check("团队增删改（教师）", group_crud)

    # --- Copilot 三条分支 ---
    def copilot():
        outs = []
        for q in ["帮我备一节注意力机制的课", "讲一下反向传播，要能直接上课用", "看看陈嘉禾的画像"]:
            d = c.api("POST", "/api/teacher/copilot/ask", {"question": q})
            need(d["answer"], "Copilot 回答为空")
            outs.append(d["intent"])
        need(len(set(outs)) >= 2, f"意图路由未区分场景：{outs}")
        return f"意图分别路由到 {outs}"
    c.check("Copilot 意图路由", copilot)

    # --- v7.9 备课演示：教案 → PPT（≤10 页）→ 作业，三步真实生成并入库 ---
    def prep_demo():
        """教师 Copilot「帮我备一节朴素贝叶斯的课」那一步要求产物是**真的**：
        这里把三步各跑一遍，并断言「教案与 PPT 归到同一个备课文件夹」+
        「每份都存进了资料库」。写死的产物一翻别的页面就穿帮，所以必须钉住。"""
        topic = "朴素贝叶斯"
        folder = topic + " · 冒烟"
        lp = c.api("POST", "/api/teacher/lesson",
                   {"topic": topic, "course": "机器学习", "periods": 1,
                    "level": "B", "folder": folder})
        need(lp.get("plan") and lp["plan"].get("title"), f"教案生成失败：{lp}")
        sl = c.api("POST", "/api/teacher/slides/from-lesson",
                   {"plan": lp["plan"], "course": "机器学习", "pages": 10, "folder": folder})
        slides = (sl.get("outline") or {}).get("slides") or []
        need(slides, f"PPT 大纲为空：{sl}")
        need(len(slides) <= 10, f"PPT 应不超过 10 页，实际 {len(slides)}")
        classes = c.api("GET", "/api/teacher/classes")
        hw = c.api("POST", "/api/teacher/homework", {
            "title": topic + "课后作业", "course": "机器学习",
            "class_name": classes.get("current") or "",
            "detail": "手算一封邮件属于正常邮件还是垃圾邮件，写出每一步。",
            "full_score": 100, "deadline": "2026-12-31 23:59",
        })
        need(hw.get("homework_id"), f"作业布置失败：{hw}")
        saved = []
        for title, body in [(topic + " 教案", "教案正文（冒烟）"),
                            (topic + " PPT 大纲", "PPT 正文（冒烟）"),
                            (topic + "课后作业", "作业正文（冒烟）")]:
            d = c.api("POST", "/api/materials/note",
                      {"title": title, "content": body, "category": "教学备课",
                       "course": "机器学习"})
            need(d.get("filename"), f"《{title}》未入库：{d}")
            saved.append(d["filename"])
            # 清理：教师新增的资料会进学生的「教师共享」池，
            # 不删会让后面的隔离用例以为「种子学生没有预导入全部公用资料」。
            c.api("DELETE", f"/api/materials/{d['material_id']}")
        arts = c.api("GET", "/api/teacher/artifacts")
        in_folder = [a for a in (arts.get("artifacts") or []) if a.get("folder") == folder]
        need(len(in_folder) >= 2,
             f"教案与 PPT 应同属文件夹「{folder}」，实际 {len(in_folder)} 件")
        return (f"教案 {len(lp['plan'].get('outline') or [])} 环节 → PPT {len(slides)} 页 → "
                f"作业 #{hw['homework_id']} → 入库 {len(saved)} 份 → "
                f"同文件夹产物 {len(in_folder)} 件")
    c.check("备课演示（教案 + PPT≤10 页 + 作业，真实生成并入库）", prep_demo)

    # --- 自检 ---
    def selfcheck():
        d = c.api("POST", "/api/selfcheck", {})
        need(d["passed"] == d["total"], f"未通过项：{d['failed']}")
        return f"{d['passed']}/{d['total']} 项通过"
    c.check("内置全链路自检", selfcheck)

    c.check("页面可达（教师）", lambda: (
        lambda pages: "、".join(pages)
    )([f"{p}={c.page(p)[0]}" for p in
       ["/teacher", "/teach", "/grade", "/tutor", "/resources", "/match", "/library", "/homework"]]))


def test_student(c: Client) -> None:
    print("\n=== 学生端 ===")
    c.check("登录（学生）", lambda: c.login("stu02").get("name"))

    c.check("我的画像", lambda: (
        lambda d: f"{d['user']['name']}｜{d['profile']['track']} · {d['profile']['grade_level']} 层 · "
                  f"{d['profile']['layer']}｜任务 {len(d['tasks'])} 条｜材料 {len(d['materials'])} 份"
    )(c.api("GET", "/api/student/profile")))

    def reason_branches():
        """画像理由必须写清判定依据。

        曾经出现过「科研倾向 3.6 / 就业倾向 3.4，却判为事业型」的画像 —— 逻辑没错
        （两者接近时改由兴趣方向定夺），但理由里不说，页面上就自相矛盾。
        因此两种分支都要锁住：悬殊写「明显高于」，接近写「按兴趣方向定夺」。
        """
        def _set(res: float, job: float) -> dict:
            c.api("POST", "/api/student/profile",
                  {"research_intent": res, "job_intent": job})
            return c.api("GET", "/api/student/profile")["profile"]

        far = _set(4.2, 2.6)
        need(far.get("track") == "学业型", f"4.2/2.6 应判学业型，实际 {far.get('track')}")
        need("明显高于" in str(far.get("reason") or ""),
             f"倾向悬殊却没写明依据：{far.get('reason')}")
        near = _set(3.2, 3.0)
        need("两项倾向接近" in str(near.get("reason") or ""),
             f"倾向接近却没说明按兴趣方向定夺：{near.get('reason')}")
        _set(4.2, 2.6)  # 复原，避免影响后续用例
        return "悬殊 → 「明显高于」；接近 → 「两项倾向接近，按兴趣方向定夺」（已复原 4.2/2.6）"
    c.check("画像理由写清判定依据（数字与结论不自相矛盾）", reason_branches)

    def intent_update():
        before = c.api("GET", "/api/student/profile")["profile"]
        d = c.api("POST", "/api/student/profile", {
            "research_intent": 5, "job_intent": 2,
            "interests": list(before.get("interests") or [])[:2],
            "extra_text": "我想读研做科研。",
        })
        after = c.api("GET", "/api/student/profile")["profile"]
        need(abs(float(after.get("research_intent") or 0) - 5) < 0.01, "科研倾向未持久化")
        need(abs(float(after.get("job_intent") or 0) - 2) < 0.01, "就业倾向未持久化")
        return f"科研倾向 {before.get('research_intent')}→{after.get('research_intent')}，" \
               f"就业倾向 {before.get('job_intent')}→{after.get('job_intent')}（{d.get('engine')}）"
    c.check("自评倾向可持久化（不被默认值覆盖）", intent_update)

    c.check("成长路线", lambda: (
        lambda d: f"{d['roadmap']['title']}：{len(d['roadmap']['stages'])} 阶段（{d['engine']}）"
    )(c.api("GET", "/api/student/roadmap")))

    def tasks():
        d = c.api("GET", "/api/student/tasks")
        created = c.api("POST", "/api/student/tasks",
                        {"title": "冒烟测试任务", "detail": "自动创建", "ttype": "todo"})
        tid = created["task_id"]
        c.api("POST", f"/api/student/tasks/{tid}", {"status": "doing", "progress": 40})
        mid = [t for t in c.api("GET", "/api/student/tasks")["tasks"] if t["id"] == tid][0]
        need(mid["status"] == "doing", "任务状态未更新")
        c.api("POST", f"/api/student/tasks/{tid}", {"status": "done"})
        done = [t for t in c.api("GET", "/api/student/tasks")["tasks"] if t["id"] == tid][0]
        need(int(done["progress"]) == 100, "标记完成后进度未联动为 100%")
        return f"原 {len(d['tasks'])} 条 → 新建并流转 todo→doing(40%)→done(100%)"
    c.check("成长任务读写与状态联动", tasks)

    # --- 答疑 ---
    def tutor():
        d = c.api("POST", "/api/tutor/ask", {"question": "为什么注意力机制要除以根号 d_k？", "top_k": 4})
        need(d["answer"], "答疑没有回答")
        need(d["layer"], "答疑没有带出分层标签")
        need(d["hits"], "答疑没有引用来源")
        return f"层级「{d['layer']}」，引用 {len(d['refs'])} 条，engine={d['engine']}"
    c.check("学生 Copilot", tutor)

    def tutor_scope():
        d = c.api("POST", "/api/tutor/ask", {"question": "卷积的池化有什么用？", "course": "深度学习"})
        need(d["answer"], "限定课程后没有回答")
        return f"限定课程命中 {len(d['hits'])} 条切片"
    c.check("答疑：限定课程范围", tutor_scope)

    c.check("答疑历史", lambda: (
        lambda d: f"{len(d['messages'])} 条记录"
    )(c.api("GET", "/api/tutor/history")))

    # --- 资料 ---
    def materials():
        ov = c.api("GET", "/api/materials/overview")
        need(ov["stats"]["materials"] > 0, "资料库统计为 0")
        need(ov["categories"], "缺少分类维度")
        lst = c.api("GET", "/api/materials")
        need(lst["materials"], "材料列表为空")
        return (f"{ov['stats']['materials']} 份材料，{ov['stats']['knowledge_points']} 个知识点，"
                f"{len(lst['materials'])} 条在列表中")
    c.check("资料总览与列表", materials)

    def knowledge():
        d = c.api("GET", "/api/materials/knowledge")
        need(d["count"] > 0, "知识点视图为空")
        first = d["knowledge"][0]
        need(first.get("name"), "知识点缺少名称")
        return f"{d['count']} 个知识点，覆盖 {len(d['courses'])} 门课程"
    c.check("知识点视图", knowledge)

    def search():
        d = c.api("POST", "/api/materials/search", {"query": "为什么注意力要除以 sqrt(d_k)", "top_k": 5})
        hits = d["hits"]
        need(hits, "检索无结果")
        need(hits[0].get("via"), "检索结果缺少召回通道标注")
        return f"命中 {len(hits)} 条，首位《{hits[0].get('ref')}》，via={hits[0].get('via')}"
    c.check("混合检索（BM25 + 向量 + RRF）", search)

    def upload():
        content = ("# 冒烟测试课件\n\n## 测试知识点 Alpha\n\n"
                   "Alpha 是一种用于验证上传链路的虚构概念，强调可重复与可观测。\n\n"
                   "## 测试知识点 Beta\n\nBeta 与 Alpha 成对出现，用于检验分片与索引。\n")
        body, ctype = multipart(
            fields={"category": "courseware", "save": "true"},
            files=[("files", "冒烟测试课件.md", content.encode("utf-8"))],
        )
        data = c.form("/api/materials/upload", body, ctype)
        results = data["files"]
        need(results and results[0].get("material_id"), f"上传结果异常：{results}")
        first = results[0]
        mid = first["material_id"]
        need(int(first.get("knowledge_saved") or 0) > 0, "解析没有产出知识点")
        need(int(first.get("indexed_chunks") or 0) > 0, "正文没有进入检索索引")

        c.api("POST", f"/api/materials/{mid}/category", {"category": "courseware"})
        before = c.api("GET", "/api/materials/overview")["stats"]["materials"]
        c.api("DELETE", f"/api/materials/{mid}")
        after = c.api("GET", "/api/materials/overview")["stats"]["materials"]
        need(after < before, "删除材料后数量未减少")
        return (f"上传→解析出 {first['knowledge_saved']} 个知识点、索引 "
                f"{first['indexed_chunks']} 个切片→改分类→删除（{before}→{after}）")
    c.check("材料上传→解析→索引→删除", upload)

    def note():
        """Copilot 演示的落点：把对话里整理的结果存成一篇笔记进「我的资料库」。
        必须真的能被检索到 —— 否则老师/学生下一次提问引用不到它，演示就是假的。"""
        body = ("# 线性代数 · 第3章 矩阵知识点整理\n\n"
                "1. 矩阵的定义与记法\n由 m×n 个数排成的矩形数表，记 A=(a_ij)。\n\n"
                "2. 矩阵乘法\nC=AB 要求 A 的列数等于 B 的行数，且一般不满足交换律。\n\n"
                "3. 矩阵的秩与初等变换\n初等行变换不改变矩阵的秩；行最简形可直接读出秩。\n")
        d = c.api("POST", "/api/materials/note", {
            "title": "线性代数 · 第3章 矩阵知识点整理",
            "content": body,
            "category": "课程资料",
            "course": "线性代数",
        })
        need(d.get("material_id"), "保存笔记未返回 material_id")
        need(int(d.get("knowledge_points") or 0) >= 2, f"笔记没抽出知识点：{d}")
        need(int(d.get("indexed") or 0) > 0, "笔记没进检索索引")
        lst = c.api("GET", "/api/materials")["materials"]
        row = [m for m in lst if m["id"] == d["material_id"]]
        need(row, "笔记不在资料库列表里")
        need(row[0].get("kind_label") == "学习笔记", f"笔记类型名不对：{row[0].get('kind_label')}")
        need(row[0].get("category") == "课程资料", f"保存路径不对：{row[0].get('category')}")
        hits = c.api("POST", "/api/materials/search",
                     {"query": "矩阵的秩 初等变换", "top_k": 5})["hits"]
        need(any(d["filename"] == h.get("filename") for h in hits), "存好的笔记检索不到")
        c.api("DELETE", f"/api/materials/{d['material_id']}")
        return (f"存成笔记《{d['filename']}》→ 路径「课程资料」→ 抽出 "
                f"{d['knowledge_points']} 个知识点、索引 {d['indexed']} 片 → 可被检索 → 清理")
    c.check("Copilot 整理结果存成笔记（可选择保存路径）", note)

    def guide_upload():
        """v7.8 引导问答里「我帮你批改作业」那一步：前端把 /static/img 下的演示作业图
        真的 POST 给上传接口。这里验证两件事 —— 静态素材可达，且上传链路跑得通；
        否则点了引导按钮只会看到「未真实入库」的降级文案，演示就假了。"""
        for name in ("matrix-hw.png", "c-hw.png"):
            c.raw("GET", f"/static/img/{name}", expect=200)
        blob = (HERE.parent / "frontend" / "img" / "matrix-hw.png").read_bytes()
        need(len(blob) > 5000, "演示作业图缺失或过小（先跑 tools/make_samples.py 生成）")
        body, ctype = multipart(
            fields={"category": "课程资料", "save": "true"},
            files=[("files", "线性代数-第3章作业-矩阵.png", blob)],
        )
        data = c.form("/api/materials/upload", body, ctype)
        item = (data.get("files") or [{}])[0]
        need(item.get("material_id"), f"演示作业图上传失败：{item}")
        c.api("DELETE", f"/api/materials/{item['material_id']}")
        return (f"演示作业图（{len(blob) // 1024} KB）→ 上传入库 #{item['material_id']}"
                f"（engine={item.get('engine')}）→ 清理")
    c.check("引导问答 · 演示作业图可真实上传入库", guide_upload)

    # --- 资源广场 ---
    def hub():
        d = c.api("GET", "/api/resources")
        need(d["teachers"], "资源广场为空")
        total = sum(len(t["resources"]) for t in d["teachers"])
        first = d["teachers"][0]["resources"][0]
        detail = c.api("GET", f"/api/resources/{first['id']}")
        need(detail["title"], "资源详情缺失")
        return f"{len(d['teachers'])} 位教师、{total} 条资源，首条《{first['title']}》"
    c.check("资源广场与详情", hub)

    def apply():
        d = c.api("GET", "/api/resources")
        target = None
        for t in d["teachers"]:
            for r in t["resources"]:
                if r.get("status") == "open" and not r.get("my_application"):
                    target = r
                    break
            if target:
                break
        if not target:
            return "没有可申请的资源（可能都已申请过），跳过"
        res = c.api("POST", f"/api/resources/{target['id']}/apply", {"reason": "冒烟测试申请"})
        mine = c.api("GET", "/api/resources/applications/mine")
        need(mine["applications"], "我的申请列表为空")
        return f"申请《{target['title']}》成功，我的申请 {len(mine['applications'])} 条"
    c.check("资源申请", apply)

    # --- v7.9 学生就业演示：引导里的「帮我申请」必须能真提交 ---
    def demo_apply():
        """学生 Copilot 就业例子里，点「帮我申请」会真调 apply —— 前提是这条资源
        在库里真实存在，后端也要挡住重复提交（前端靠 my_application 判定 dup）。
        少任何一条，演示都会退化成「没找到这个资源」的降级文案。"""
        title = "学业导航平台前端可视化（校企共建）"
        d = c.api("GET", "/api/resources")
        target = None
        for t in d["teachers"]:
            for r in t["resources"]:
                if r.get("title") == title:
                    target = r
                    break
            if target:
                break
        need(target, f"资源广场里没有《{title}》，演示会退化成「没找到」")
        if not target.get("my_application"):
            c.api("POST", f"/api/resources/{target['id']}/apply",
                  {"message": "冒烟：我已按前端路线学完 HTML/CSS 与 JS 基础"})
        mine = c.api("GET", "/api/resources/applications/mine")
        hit = [a for a in mine["applications"] if (a.get("resource_title") or "") == title]
        need(hit, f"申请后没出现在「我的申请」里：{[a.get('resource_title') for a in mine['applications']]}")
        status, _ = c.raw("POST", f"/api/resources/{target['id']}/apply", {"message": "再来一次"})
        need(status == 400, f"重复申请应被拒（400），实际 {status}")
        return (f"《{title}》→ 申请成功（{hit[0].get('status_text') or hit[0].get('status')}）"
                f" → 重复提交被拒")
    c.check("就业演示 · 项目可真实申请（含重复拦截）", demo_apply)

    # --- 作业 ---
    def homework():
        d = c.api("GET", "/api/homework/mine")
        need(d["stats"]["total"] > 0, "学生侧没有作业")
        todo = [h for h in d["homework"] if not h["submitted"]]
        if not todo:
            return f"{d['stats']['total']} 份作业，均已提交"
        target = todo[0]
        body, ctype = multipart(
            fields={"content": "注意力机制通过查询与键的点积得到权重，再对值加权求和。"
                               "缩放点积除以根号 d_k 以稳定梯度。"},
            files=[("files", "作答.txt", "我的作答正文。".encode("utf-8"))],
        )
        c.form(f"/api/homework/{target['id']}/submit", body, ctype)
        after = c.api("GET", "/api/homework/mine")
        sub = [h for h in after["homework"] if h["id"] == target["id"]][0]
        need(sub["submitted"], "提交后状态未变为已提交")
        return f"提交《{target['title']}》，状态已更新，附件 {len(sub.get('files') or [])} 个"
    c.check("作业提交（含附件）", homework)

    def match():
        d = c.api("GET", "/api/match/recommend")
        need(d["matches"], "匹配推荐为空")
        top = d["matches"][0]
        c.api("POST", "/api/match/decide", {"group_id": top["group_id"], "action": "accepted"})
        mine = c.api("GET", "/api/match/mine")
        need(mine["matches"], "我的匹配记录为空")
        return f"推荐 {len(d['matches'])} 个，首选《{top['name']}》匹配度 {top['score']}"
    c.check("师生匹配（学生侧双向确认）", match)

    c.check("页面可达（学生）", lambda: "、".join(
        f"{p}={c.page(p)[0]}" for p in ["/student", "/ask", "/hub", "/homework", "/match", "/library"]))


def test_agent_rag(c: Client) -> None:
    """能力⑦：五种 RAG 架构路由 + 智能体工具 + 会话管理（新开 / 回到某一次对话）。"""
    print("\n=== RAG 路由 · 智能体 · 会话 ===")
    c.logout()
    c.login("stu01")

    def strategies():
        d = c.api("GET", "/api/tutor/sessions")
        need(len(d["strategies"]) == 5, f"策略数量应为 5，实际 {len(d['strategies'])}")
        need(d["new_session"].startswith("s"), "new_session 格式不对")
        return "、".join(s["name"] for s in d["strategies"])
    c.check("五种 RAG 策略清单", strategies)

    # ---- 路由：同一种问题，不同问法应命中不同架构
    def auto_route():
        picked = {}
        for q in ["注意力机制和 Transformer 有什么关系？",
                  "课件里那张图说明了什么？",
                  "结合我的情况给我一个复习计划",
                  "那个到底为什么不work？",
                  "什么是反向传播？"]:
            d = c.api("POST", "/api/tutor/ask", {"question": q})
            picked[q[:6]] = d["rag"]["strategy"]
        need(picked["注意力机制和"] == "graph", f"关系类应走 graph，实际 {picked['注意力机制和']}")
        need(picked["课件里那张图"] == "multimodal", "图片类应走 multimodal")
        need(picked["结合我的情况"] == "agentic", "复合任务应走 agentic")
        need(picked["那个到底为什"] == "corrective", "口语指代应走 corrective")
        need(picked["什么是反向传"] == "hybrid", "概念类应走 hybrid")
        return "、".join(f"{k}→{v}" for k, v in picked.items())
    c.check("自动路由（五类问题五种架构）", auto_route)

    def forced():
        d = c.api("POST", "/api/tutor/ask",
                  {"question": "注意力机制和 Transformer 有什么关系？", "strategy": "graph"})
        need(d["rag"]["strategy"] == "graph", "手动指定 graph 未生效")
        need(d["rag"].get("auto") is False, "手动指定时 auto 应为 False")
        g = d["rag"]["extra"].get("graph") or {}
        need(g.get("nodes"), "graph 策略应带子图节点")
        return f"强制 graph：{d['rag']['strategy_name']}，" \
               f"子图 {len(g['nodes'])} 节点 / {len(g['edges'])} 边"
    c.check("手动指定策略（演示对比）", forced)

    def corrective_extra():
        d = c.api("POST", "/api/tutor/ask", {"question": "那个到底咋回事", "strategy": "corrective"})
        extra = d["rag"].get("extra") or {}
        need(extra.get("rounds"), "纠错式应带轮次")
        return f"轮次 {extra.get('rounds')}，质量 {extra.get('quality')}"
    c.check("纠错式两轮检索", corrective_extra)

    # ---- 综合生成：答案不是检索片段的拼接
    def synth_student():
        d = c.api("POST", "/api/tutor/ask", {"question": "过拟合和正则化是什么关系？"})
        s = d.get("synth") or {}
        need(s.get("steps"), "学生侧应返回综合生成视图（steps）")
        need(s.get("evidence"), "综合生成应带证据原文")
        need(s.get("conclusion"), "综合生成应先给结论")
        need("综合结论" in (d.get("answer") or ""), "答案里应先给出综合结论")
        need(len(s["steps"]) == 5, f"五个步骤，实际 {len(s['steps'])}")
        return (f"{s.get('mode')}：{s.get('evidence_count')} 条证据 / "
                f"命中 {s.get('hit_count')} 条，结论「{s['conclusion'][:22]}…」")
    c.check("综合生成（学生侧：证据 + 推理）", synth_student)

    def synth_teacher():
        c2 = Client(c.base)
        c2.login("teacher")
        d = c2.api("POST", "/api/teacher/copilot/ask", {"question": "讲一下正则化", "skill": "explain"})
        s = d.get("synth") or {}
        need(s.get("steps"), "教师侧应返回综合生成视图")
        need(s.get("intent") == "explain", f"教师侧应为讲解型推理，实际 {s.get('intent')}")
        return f"{s.get('mode')}：{s.get('evidence_count')} 条证据，提醒「{s['remind'][:20]}…」"
    c.check("综合生成（教师侧：讲解型推理）", synth_teacher)

    # ---- 会话：新开 / 回到某一次
    def sessions():
        s1 = c.api("POST", "/api/tutor/new")["session_id"]
        c.api("POST", "/api/tutor/ask", {"question": "什么是梯度下降？", "session_id": s1})
        c.api("POST", "/api/tutor/ask", {"question": "它和学习率有什么关系？", "session_id": s1})
        s2 = c.api("POST", "/api/tutor/new")["session_id"]
        c.api("POST", "/api/tutor/ask", {"question": "讲一下激活函数", "session_id": s2})

        lst = c.api("GET", "/api/tutor/sessions")["sessions"]
        ids = [x["session_id"] for x in lst]
        need(s1 in ids and s2 in ids, f"会话列表缺少新建会话：{ids}")
        one = [x for x in lst if x["session_id"] == s1][0]
        need(one["turns"] == 4, f"s1 应有 4 条消息，实际 {one['turns']}")
        need(one["title"], "会话标题为空")

        hist = c.api("GET", f"/api/tutor/history?session_id={s1}")["messages"]
        need(len(hist) == 4, f"按会话读历史应为 4 条，实际 {len(hist)}")
        need(all(m["session_id"] == s1 for m in hist), "历史里混入了别的会话")
        return f"{len(lst)} 个会话，s1「{one['title'][:14]}」{one['turns']} 条消息"
    c.check("会话（新开 / 回到某一次对话）", sessions)

    def clear_one():
        lst = c.api("GET", "/api/tutor/sessions")["sessions"]
        victim = [x for x in lst if x["session_id"]][0]["session_id"]
        before = len(lst)
        c.api("POST", "/api/tutor/clear", {"session_id": victim})
        after = c.api("GET", "/api/tutor/sessions")["sessions"]
        need(len(after) == before - 1, "按会话清空未生效")
        return f"清空 1 次对话，剩余 {len(after)} 个"
    c.check("只清空某一次对话", clear_one)

    # ---- 智能体工具
    def tool_upload():
        d = c.api("GET", "/api/agent/tools")
        need(len(d["tools"]) >= 2, "工具清单不足 2 个")
        r = c.api("POST", "/api/agent/tools/upload_material/run", {
            "title": "冒烟测试笔记", "category": "笔记",
            "text": "梯度下降是一种一阶优化方法。学习率控制每步步长，过大发散，过小收敛慢。"
                    "动量法通过累积历史梯度加速收敛，常用于深度学习训练。",
        })
        need(r["ok"] and r["material_id"], "上传资料未入库")
        need(r["indexed_chunks"] > 0, "上传后没有建索引片段")
        return f"入库 #{r['material_id']}，索引 {r['indexed_chunks']} 片段，" \
               f"知识点 {r['knowledge_saved']} 个"
    c.check("智能体工具 · 上传资料（入库+索引）", tool_upload)

    def tool_generate():
        r = c.api("POST", "/api/agent/tools/generate_material/run", {
            "topic": "梯度下降", "kind": "复习提纲", "save": True,
        })
        need(r["markdown"], "生成内容为空")
        need(r["material_id"], "未保存到资料库")
        need(r["refs"], "生成结果缺少可溯源引用")
        return f"生成 {len(r['markdown'])} 字，引用 {len(r['refs'])} 份资料，已存 #{r['material_id']}"
    c.check("智能体工具 · 生成资料（可溯源+保存）", tool_generate)

    def after_upload_answerable():
        d = c.api("POST", "/api/tutor/ask", {"question": "动量法是什么？"})
        need(d["refs"], "上传的资料没有被答疑引用到")
        return f"引用 {len(d['refs'])} 处：{d['refs'][0]}"
    c.check("上传的资料能被答疑引用（可溯源）", after_upload_answerable)

    # ---- 教师侧同样支持
    def teacher_side():
        c.logout()
        c.login("teacher")
        d = c.api("GET", "/api/teacher/copilot/sessions")
        need(d["strategies"], "教师侧拿不到策略清单")
        sid = d["new_session"]
        a = c.api("POST", "/api/teacher/copilot/ask",
                  {"question": "讲一下反向传播，要能直接上课用", "session_id": sid})
        need(a["session_id"] == sid, "教师侧会话未续上")
        need(a["rag"]["strategy"], "教师侧没有 RAG 路由结果")
        lst = c.api("GET", "/api/teacher/copilot/sessions")["sessions"]
        need(any(x["session_id"] == sid for x in lst), "教师侧会话列表缺少新建会话")
        hist = c.api("GET", f"/api/teacher/copilot/history?session_id={sid}")["messages"]
        need(len(hist) == 2, f"教师侧按会话读历史应为 2 条，实际 {len(hist)}")
        return f"教师侧 {a['rag']['strategy_name']}，会话 {len(lst)} 个"
    c.check("教师侧：路由 + 会话", teacher_side)


def test_isolation(c: Client) -> None:
    """数据隔离：同学之间检索互不可见；教师公用资料导入 / 移除即时生效。"""
    print("\n=== 数据隔离 ===")
    c.logout()
    c.login("stu02")

    def library_scope():
        d = c.api("GET", "/api/materials")
        names = [m["filename"] for m in d["materials"]]
        need(not any("陈嘉禾" in n for n in names), "stu02 的资料列表里出现了 stu01 的成绩单")
        shared = d.get("shared") or []
        need(shared, "教师共享列表为空")
        need(all(s.get("imported") for s in shared), "种子学生应已预导入全部公用资料")
        return f"我的 {len(d['materials'])} 份（无他人材料），教师共享 {len(shared)} 份（已预导入）"
    c.check("资料列表按用户隔离", library_scope)

    def no_leak():
        d = c.api("POST", "/api/materials/search", {"query": "陈嘉禾 平均成绩 成绩单", "top_k": 8})
        bad = [h for h in d["hits"] if "陈嘉禾" in str(h.get("ref") or "")]
        need(not bad, f"检索命中了他人成绩单：{[h['ref'] for h in bad]}")
        return f"命中 {len(d['hits'])} 条，均不含他人材料"
    c.check("检索不串库（他人成绩单不可见）", no_leak)

    def import_flow():
        shared = (c.api("GET", "/api/materials")).get("shared") or []
        target = next(s for s in shared if "注意力机制" in s["filename"])
        mid = target["id"]
        c.api("DELETE", f"/api/materials/{mid}/import")      # 移除导入
        d = c.api("POST", "/api/materials/search",
                  {"query": "缩放点积注意力 为什么要除以 sqrt(d_k)", "top_k": 8})
        need(not any("注意力机制与Transformer" in str(h.get("ref") or "") for h in d["hits"]),
             "移除导入后仍能检索到该资料")
        c.api("POST", f"/api/materials/{mid}/import")        # 再导入
        d2 = c.api("POST", "/api/materials/search",
                   {"query": "缩放点积注意力 为什么要除以 sqrt(d_k)", "top_k": 8})
        need(any("注意力机制与Transformer" in str(h.get("ref") or "") for h in d2["hits"]),
             "重新导入后应能检索到该资料")
        return "移除导入→检索不到；导入→立刻可引用"
    c.check("公用资料导入 / 移除即时生效", import_flow)

    def import_guard():
        # 同学的私人材料不允许被导入 —— 隔离的最后一道闸
        s1 = Client(c.base)
        s1.login("stu01")
        own = s1.api("GET", "/api/materials")["materials"]
        transcript = next(m for m in own if "成绩单" in m["filename"])
        status, _ = c.raw("POST", f"/api/materials/{transcript['id']}/import", {})
        need(status == 404, f"导入他人私人材料应被拒（404），实际 {status}")
        return "stu01 的成绩单对 stu02 不可导入（404）"
    c.check("导入权限边界（只能导入教师公用资料）", import_guard)


def test_guards(c: Client) -> None:
    print("\n=== 权限边界 ===")
    c.logout()

    c.check("未登录访问业务接口 → 401", lambda: (
        c.json("GET", "/api/teacher/overview", expect=401)["error"]
    ))

    c.check("未登录访问受保护页面 → 302 到登录页", lambda: (
        lambda r: f"HTTP {r[0]} → {r[1][:40]}" if r[0] in (302, 303, 307) else (_ for _ in ()).throw(
            AssertionError(f"期望跳转，实际 HTTP {r[0]}"))
    )(_raw_no_redirect(c.base + "/teacher")))

    c.check("错误密码被拒", lambda: (
        c.json("POST", "/api/auth/login", {"username": "teacher", "password": "wrong"}, expect=400)["error"]
    ))

    student = Client(c.base)
    student.login("stu02")
    c.check("学生访问教师接口 → 403", lambda: (
        student.json("GET", "/api/teacher/overview", expect=403)["error"]
    ))
    c.check("学生访问教师页面 → 跳转", lambda: (
        lambda r: f"HTTP {r[0]}" if r[0] in (302, 303, 307) else (_ for _ in ()).throw(
            AssertionError(f"期望跳转，实际 HTTP {r[0]}"))
    )(_raw_no_redirect(c.base + "/teach", cookie=student.cookie)))

    c.check("不存在的资源 → 404", lambda: (
        student.json("GET", "/api/resources/999999", expect=404)["error"]
    ))


def test_demo_accounts(c: Client) -> None:
    """登录页演示账号：卡片上写的类型必须等于登录后的真实画像（曾经不一致过）。"""
    print("\n=== 登录页演示账号一致性 ===")
    c.logout()

    data = c.api("GET", "/api/auth/demos")
    accounts = data.get("accounts") or []
    students = [a for a in accounts if a.get("role") == "student"]
    teachers = [a for a in accounts if a.get("role") == "teacher"]

    c.check("未登录也能取到演示账号", lambda:
            f"{len(teachers)} 个教师 + {len(students)} 个学生")

    c.check("学生恰好两个：学业型一个、事业型一个", lambda: (
        lambda ts: (ts == ["学业型", "事业型"] and "各 1 个") or
        (_ for _ in ()).throw(AssertionError(f"实际主标签 {ts}"))
    )([s.get("track") for s in students]))

    def _verify(s: dict):
        stu = Client(c.base)
        stu.login(s["username"])
        prof = stu.api("GET", "/api/student/profile").get("profile") or {}
        need(prof.get("track") == s.get("track"),
             f"{s['username']} 卡片写 {s.get('track')}，画像实际 {prof.get('track')}")
        stu.logout()
        return f"{s['username']} 卡片与画像一致（{prof.get('track')} · {prof.get('grade_level')} 层）"

    for _s in students:
        c.check(f"演示账号 {_s.get('username')} 类型一致", lambda _x=_s: _verify(_x))


def _raw_no_redirect(url: str, cookie: str = ""):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):  # noqa: D102
            return None
    opener = urllib.request.build_opener(NoRedirect)
    headers = {"Cookie": cookie} if cookie else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


# ================================================================ 启动/收尾
def start_server(port: int, workdir: Path) -> tuple[subprocess.Popen, Path]:
    """起一个隔离的测试服务。

    **必须把子进程的输出落到文件，不能用 ``subprocess.PIPE``** —— 管道缓冲区
    只有几 KB，uvicorn 的访问日志几百条就会把它填满，子进程阻塞在 write 上，
    于是所有后续请求集体超时（这个坑踩过：跑到第 30 个用例服务就不响应了）。
    """
    env = dict(os.environ)
    # 把数据目录指向临时目录：不动开发库，也不需要 --reset
    env["DB_PATH"] = str(workdir / "smoke.db")
    env["DATA_DIR"] = str(workdir)
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    env["LLM_MODE"] = "mock"          # 冒烟测试永远走规则版，保证可重复
    env["PF_AUTO_SEED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log_path = workdir / "server.log"
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [PYTHON, str(HERE / "app.py")],
        cwd=str(HERE), env=env,
        stdout=log_file, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):          # 最多等 20 秒
        if proc.poll() is not None:
            log_file.close()
            out = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            raise RuntimeError("服务启动即退出：\n" + out[:3000])
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=2):
                return proc, log_path
        except Exception:  # noqa: BLE001 - 还没起来，继续等
            time.sleep(0.25)
    log_file.close()
    raise RuntimeError("服务在 20 秒内没有就绪")


def main() -> int:
    ap = argparse.ArgumentParser(description="寻径教育 PathFinder · 全链路冒烟测试")
    ap.add_argument("--keep-open", action="store_true", help="跑完不关闭服务（便于手工点页面）")
    ap.add_argument("--verbose", action="store_true", help="打印每个 HTTP 请求")
    args = ap.parse_args()

    port = free_port()
    workdir = Path(tempfile.mkdtemp(prefix="pf_smoke_"))
    print("=" * 68)
    print("寻径教育 PathFinder · 全链路冒烟测试")
    print(f"临时数据目录：{workdir}")
    print(f"测试服务地址：http://127.0.0.1:{port}   引擎：mock（规则版，可重复）")
    print("=" * 68)

    proc = None
    log_path: Path | None = None
    try:
        proc, log_path = start_server(port, workdir)
        base = f"http://127.0.0.1:{port}"

        # 先播种：走 seeds 的真实业务接口，保证有画像/作业/资源
        seed = subprocess.run(
            [PYTHON, str(HERE / "seeds.py"), "--force"],
            cwd=str(HERE), env={**os.environ, "DB_PATH": str(workdir / "smoke.db"),
                                "DATA_DIR": str(workdir), "PYTHONIOENCODING": "utf-8"},
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if seed.returncode != 0:
            print(seed.stdout)
            print(seed.stderr)
            raise RuntimeError("播种失败")

        client = Client(base, verbose=args.verbose)
        test_teacher(client)
        test_student(client)
        test_agent_rag(client)
        test_isolation(client)
        test_guards(client)
        test_demo_accounts(client)

        total = client.passes + len(client.fails)
        print("\n" + "=" * 68)
        if client.fails:
            print(f"结果：{client.passes}/{total} 通过，{len(client.fails)} 项失败")
            for f in client.fails:
                print("  ✗ " + f)
            if log_path and log_path.exists():
                # 取足够多的行：500 要从 Traceback 开头才看得清，15 行常常只剩最后一句。
                tail = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-60:]
                print(f"\n--- 服务端日志（末尾 {len(tail)} 行）---")
                for line in tail:
                    print("  " + line)
        else:
            print(f"结果：{total}/{total} 全部通过 —— 无 API Key 也能完整演示。")
        print("=" * 68)
        if args.keep_open:
            print(f"服务保持运行：http://127.0.0.1:{port}   （Ctrl+C 结束）")
            print("账号：teacher / stu01（学业型）/ stu04（事业型），密码均为 123456")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        return 1 if client.fails else 0
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
