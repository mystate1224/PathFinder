# -*- coding: utf-8 -*-
"""app.py —— FastAPI 主程序（路由层）。

分层纪律：
* 路由层只做四件事：**鉴权 → 取参 → 调 services → 包装响应**。
* 业务规则一行都不许写在这里；凡是"先判断再决定"的逻辑都在 ``services/``。
* 所有模型调用都发生在 services 内部，路由层对"这条结果来自 LLM 还是规则"
  只负责把 ``engine`` 字段透出去，前端据此显示「模型生成 / 规则兜底」徽标。

自带 Web 界面：``frontend/`` 下的原生 HTML/CSS/JS，零构建、零框架。
启动：``python backend/app.py``（等价于 ``uvicorn app:app``）。
"""
from __future__ import annotations

import re
import sys
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

if __package__ in (None, ""):  # 允许 `python backend/app.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
import llm  # noqa: E402
from services import (  # noqa: E402
    agenttools,
    copilot,
    dashboard,
    demo,
    extract,
    homework,
    interaction,
    kprules,
    manual,
    matcher,
    mylibrary,
    office,
    parsekit,
    planner,
    rag,
    ragroute,
    resources,
    retriever,
    stratify,
    tasks,
    taxonomy,
    teaching,
    tutor,
)

COOKIE = "pf_token"
API = "/api"

# ================================================================ 启动 / 关闭
@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    if not db.scalar("SELECT COUNT(*) FROM users", (), 0):
        try:
            import seeds
            report = seeds.seed()
            print(f"[seeds] 首次启动自动播种：{report}")
        except Exception as exc:  # noqa: BLE001 - 播种失败不该阻塞启动
            print(f"[seeds] 自动播种失败（可手动执行 python backend/seeds.py）：{exc}")
    print("=" * 68)
    print("寻径教育 PathFinder · LearnBuddy 已启动")
    print(llm.describe())
    print(f"数据库：{config.DB_PATH}    FTS5：{'可用' if db.FTS_OK else '不可用（已降级 LIKE）'}")
    print(f"界面：http://{config.HOST}:{config.PORT}/   账号：teacher / stu01（密码 123456）")
    print("=" * 68)
    yield
    print("[app] 已停止")


app = FastAPI(title="寻径教育 PathFinder", version="1.0", lifespan=lifespan,
              docs_url="/docs", redoc_url=None)


# ================================================================ 响应包装
def ok(data: Any = None, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {"ok": True, "data": data}
    body.update(extra)
    return JSONResponse(body)


def fail(message: str, status: int = 400, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {"ok": False, "error": message}
    body.update(extra)
    return JSONResponse(body, status_code=status)


def download(content: bytes | str, filename: str, media_type: str) -> Response:
    """带中文文件名的下载响应（``filename*`` 才能被浏览器正确解码）。"""
    payload = content.encode("utf-8-sig") if isinstance(content, str) else content
    quoted = quote(filename)
    return Response(
        payload,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=\"{quoted}\"; filename*=UTF-8''{quoted}"},
    )


# ---------------------------------------------------------------- 异常处理
@app.exception_handler(HTTPException)
async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code == 401:
        return fail(str(exc.detail or "请先登录"), 401)
    if exc.status_code == 404:
        return fail(str(exc.detail or "资源不存在"), 404)
    return fail(str(exc.detail or "请求失败"), exc.status_code)


@app.exception_handler(llm.LLMError)
async def _llm_error(_request: Request, exc: llm.LLMError) -> JSONResponse:
    return fail(
        f"模型调用失败：{exc}。可把 .env 里的 LLM_MODE 切回 mock 后继续演示（规则版结果结构完全一致）。",
        502,
    )


def _biz_handler(_request: Request, exc: Exception) -> JSONResponse:
    """业务异常 → HTTP。状态码由异常自己的 ``status`` 决定（缺省 400）。

    这样 "资源不存在" 是 404、"尚未提交无法给建议分" 是 400，前端可以据此
    区分"没找到"与"操作不合法"，而不是一律弹同一个错。
    """
    return fail(str(exc), int(getattr(exc, "status", 400) or 400))


@app.exception_handler(ValueError)
async def _value_error(_request: Request, exc: ValueError) -> JSONResponse:
    # services 里的业务异常都继承 ValueError，统一当 400；非业务 ValueError 也是入参问题
    return fail(str(exc) or "参数不合法", 400)


@app.exception_handler(Exception)
async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    traceback.print_exc()
    return fail(f"服务器内部错误：{type(exc).__name__}: {exc}", 500)


for _exc_type in (homework.HomeworkError, resources.ResourceError,
                  matcher.MatchError, tasks.TaskError):
    app.add_exception_handler(_exc_type, _biz_handler)


# ================================================================ 鉴权
def _token_of(request: Request) -> str:
    token = request.cookies.get(COOKIE) or ""
    if token:
        return token
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def current_user_optional(request: Request) -> dict | None:
    return db.session_user(_token_of(request))


def current_user(request: Request) -> dict:
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "请先登录")
    return user


def require_student(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "student":
        raise HTTPException(403, "该功能仅学生可用")
    return user


def require_teacher(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "teacher":
        raise HTTPException(403, "该功能仅教师可用")
    return user


def _int(payload: dict, key: str, default: int = 0) -> int:
    try:
        return int(float(payload.get(key, default)))
    except (TypeError, ValueError):
        return default


def _str(payload: dict, key: str, default: str = "") -> str:
    value = payload.get(key)
    return default if value is None else str(value).strip()


# ================================================================ 页面
PAGES: list[tuple[str, str, str]] = [
    # (路径, 文件, 需要的角色；空串=登录即可)
    ("/teacher", "teacher.html", "teacher"),
    ("/student", "student.html", "student"),
    ("/library", "library.html", ""),
    ("/ask", "ask.html", "student"),
    ("/homework", "homework.html", ""),
    ("/hub", "hub.html", "student"),
    ("/match", "match.html", ""),
    ("/teach", "teach.html", "teacher"),
    ("/tutor", "tutor.html", "teacher"),
    ("/resources", "resources.html", "teacher"),
    ("/grade", "grade.html", "teacher"),
    ("/profile", "profile.html", ""),
]


def _make_page_route(filename: str, role: str, path: str):
    """闭包工厂：把文件名/角色/路径捕获进局部变量。

    注意不要把它们写成带默认值的形参 —— FastAPI 会把形参当查询参数解析，
    于是页面上会多出 ``?_f=x&_r=y`` 这类无意义的参数。
    """
    def _serve(request: Request):
        user = current_user_optional(request)
        if role and (not user or user.get("role") != role):
            return RedirectResponse(f"/login?next={quote(path)}")
        target = config.FRONTEND_DIR / filename
        if not target.exists():
            return fail(f"页面文件缺失：frontend/{filename}，请先创建该文件", 404)
        return FileResponse(str(target), media_type="text/html; charset=utf-8")
    _serve.__name__ = f"page_{filename.replace('.', '_')}"
    return _serve


for _path, _filename, _role in PAGES:
    app.get(_path, include_in_schema=False)(_make_page_route(_filename, _role, _path))


@app.get("/login", include_in_schema=False)
def page_login(request: Request):
    user = current_user_optional(request)
    if user:
        return RedirectResponse("/teacher" if user.get("role") == "teacher" else "/student")
    target = config.FRONTEND_DIR / "login.html"
    if not target.exists():
        return fail("页面文件缺失：frontend/login.html", 404)
    return FileResponse(str(target), media_type="text/html; charset=utf-8")


@app.get("/", include_in_schema=False)
def page_root(request: Request):
    user = current_user_optional(request)
    if not user:
        return RedirectResponse("/login")
    return RedirectResponse("/teacher" if user.get("role") == "teacher" else "/student")


app.mount("/static", StaticFiles(directory=str(config.FRONTEND_DIR)), name="static")


# ================================================================ 鉴权接口
@app.post(f"{API}/auth/login")
def api_login(payload: dict = Body(default={})):
    username = _str(payload, "username")
    password = payload.get("password") or ""
    if not username or not password:
        return fail("请输入账号与密码")

    user = db.user_by_username(username)
    if not user or not db.verify_password(str(password), str(user.get("pwd_hash") or "")):
        return fail("账号或密码不正确")

    token = db.create_session(int(user["id"]))
    response = ok({
        "token": token,
        "role": user.get("role"),
        "name": user.get("name"),
        "username": user.get("username"),
        "home": "/teacher" if user.get("role") == "teacher" else "/student",
    })
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="lax",
        max_age=config.SESSION_DAYS * 24 * 3600,
    )
    return response


@app.get(f"{API}/account/profile")
def api_account_profile(user: dict = Depends(current_user)):
    """个人中心：账号信息 + 画像 + 统计（教师/学生两套字段）。"""
    return ok(dashboard.account_profile(user))


@app.post(f"{API}/auth/logout")
def api_logout(request: Request):
    db.delete_session(_token_of(request))
    response = ok({"message": "已退出登录"})
    response.delete_cookie(COOKIE)
    return response


@app.get(f"{API}/auth/me")
def api_me(user: dict = Depends(current_user)):
    profile: dict | None = None
    if user.get("role") == "student":
        row = db.student_profile(int(user["id"])) or {}
        profile = {
            "track": row.get("track") or "学业型",
            "grade_level": row.get("grade_level") or "B",
            "layer": stratify.layer_badge(
                str(row.get("track") or "学业型"), str(row.get("grade_level") or "B")
            ),
        }
    else:
        row = db.teacher_profile(int(user["id"])) or {}
        profile = {"directions": row.get("directions") or []}

    return ok({
        "id": user.get("id"),
        "username": user.get("username"),
        "name": user.get("name"),
        "role": user.get("role"),
        "class_id": user.get("class_id"),
        "class_name": user.get("class_name"),
        "profile": profile,
    })


# ================================================================ 元数据 / 健康
@app.get(f"{API}/health")
def api_health():
    return ok({
        "config": config.snapshot(),
        "llm": llm.status(),
        "db": db.health_snapshot(),
        "retrieval": rag.stats(),
    })


@app.get(f"{API}/llm/probe")
def api_llm_probe(user: dict = Depends(current_user)):
    """点一下"测试模型连通性"。未配 Key 时如实返回 mock 模式。"""
    return ok(llm.probe())


@app.get(f"{API}/meta")
def api_meta(user: dict = Depends(current_user)):
    role = str(user.get("role") or "")
    data: dict[str, Any] = {
        "llm": llm.status(),
        "role": role,
        "directions": taxonomy.ALL_DIRECTIONS,
        "orientation_options": teaching.orientation_options(),
        "resource_types": resources.rtype_options(),
        "material_kinds": [{"value": k, "label": v} for k, v in extract.KINDS.items()],
        "material_categories": mylibrary.DEFAULT_CATEGORIES,
        "copilot_skills": copilot.SKILLS,
        "task_status": [{"value": k, "label": v} for k, v in tasks.STATUS_TEXT.items()],
        "caveats": {
            "layer": planner.LAYER_CAVEAT,
            "engine": "「规则兜底」不是假数据：结论由真实输入推导，结构与大模型版完全一致，"
                      "断网也能完整演示。",
        },
    }
    if role == "teacher":
        data["classes"] = homework.classes()
        data["courses"] = homework.courses(int(user["id"]))
    else:
        # 课程下拉也要按可见范围取：否则学生能在筛选里看到同学私人材料（成绩单 / 简历）的课程名，
        # 等于变相泄露"谁上传了什么"。规则与检索层保持一致。
        clause, args = rag.search_scope(int(user["id"]), False)
        data["my_courses"] = [
            r["course"] for r in db.query(
                "SELECT DISTINCT course FROM knowledge_points WHERE course <> ''" +
                clause + " ORDER BY course",
                tuple(args),
            )
        ]
    return ok(data)


# ================================================================ 学生 · 画像
@app.get(f"{API}/student/profile")
def api_student_profile(user: dict = Depends(require_student)):
    return ok(dashboard.student_self(int(user["id"])))


@app.post(f"{API}/student/profile")
def api_student_profile_update(payload: dict = Body(default={}), user: dict = Depends(require_student)):
    """学生自评：科研/就业倾向与兴趣方向。会立刻重算画像与成长路线。"""
    def _num(key: str):
        if key not in payload or payload.get(key) in (None, ""):
            return None
        try:
            return float(payload[key])
        except (TypeError, ValueError):
            return None

    interests = payload.get("interests") or []
    if isinstance(interests, str):
        interests = [i.strip() for i in interests.replace("，", ",").split(",") if i.strip()]

    profile, engine = stratify.update_intent(
        int(user["id"]),
        research_intent=_num("research_intent"),
        job_intent=_num("job_intent"),
        interests=interests,
        extra_text=_str(payload, "extra_text")[:500],
    )
    return ok({"profile": profile, "engine": engine}, message="自评已保存，画像与路线已同步更新")


@app.get(f"{API}/student/roadmap")
def api_student_roadmap(user: dict = Depends(require_student)):
    student_id = int(user["id"])
    profile = db.student_profile(student_id) or {}
    profile["track"] = str(profile.get("track") or "学业型")
    profile["grade_level"] = str(profile.get("grade_level") or "B")
    mastery = db.query(
        "SELECT * FROM kp_mastery WHERE student_id = ? ORDER BY mastery", (student_id,)
    )
    route, engine = planner.roadmap(profile, mastery)
    return ok({"roadmap": route, "engine": engine, "layer": tutor.layer_label(
        profile["track"], profile["grade_level"])})


# ================================================================ 学生 · 任务
@app.get(f"{API}/student/tasks")
def api_student_tasks(status: str = "", user: dict = Depends(require_student)):
    return ok(tasks.list_for_student(int(user["id"]), status))


@app.post(f"{API}/student/tasks/{{task_id}}")
def api_student_task_update(task_id: int, payload: dict = Body(default={}),
                           user: dict = Depends(require_student)):
    progress = payload.get("progress")
    return ok(tasks.update(
        int(user["id"]), task_id,
        status=_str(payload, "status"),
        progress=None if progress in (None, "") else _int(payload, "progress", 0),
    ))


@app.post(f"{API}/student/tasks")
def api_student_task_create(payload: dict = Body(default={}), user: dict = Depends(require_student)):
    """把成长路线的某一阶段「加入我的计划」，落成一条可勾选的任务。"""
    task_id = tasks.create(
        int(user["id"]),
        title=_str(payload, "title"),
        detail=_str(payload, "detail"),
        ttype=_str(payload, "type", "roadmap") or "roadmap",
        due_date=_str(payload, "due_date"),
    )
    return ok({"task_id": task_id}, message="已加入我的计划")


# ================================================================ 学生 · 答疑（能力③）
@app.post(f"{API}/tutor/ask")
def api_tutor_ask(payload: dict = Body(default={}), user: dict = Depends(require_student)):
    result = tutor.ask(
        user,
        _str(payload, "question"),
        course=_str(payload, "course"),
        scope=_str(payload, "scope"),
        top_k=_int(payload, "top_k", 4) or 4,
        session_id=_str(payload, "session_id"),
        strategy=_str(payload, "strategy") or "auto",
    )
    return ok(result)


@app.get(f"{API}/tutor/sessions")
def api_tutor_sessions(limit: int = 30, user: dict = Depends(require_student)):
    """会话列表：支持「新开对话」与「回到某一次对话」。"""
    return ok({"sessions": tutor.sessions(int(user["id"]), max(1, min(100, limit))),
               "new_session": tutor.new_session(),
               "strategies": ragroute.strategies_view()})


@app.post(f"{API}/tutor/new")
def api_tutor_new(user: dict = Depends(require_student)):
    return ok({"session_id": tutor.new_session()}, message="已新开一次对话")


@app.get(f"{API}/tutor/history")
def api_tutor_history(limit: int = 30, session_id: str = "",
                      user: dict = Depends(require_student)):
    return ok({"messages": tutor.history_view(int(user["id"]), max(1, min(100, limit)),
                                              session_id)})


@app.post(f"{API}/tutor/clear")
def api_tutor_clear(payload: dict = Body(default={}), user: dict = Depends(require_student)):
    """清空全部对话，或只清某一次（传 session_id）。"""
    tutor.clear_history(int(user["id"]), _str(payload, "session_id"))
    return ok(message="对话已清空")


# ================================================================ 智能体工具（Agent）
@app.get(f"{API}/agent/tools")
def api_agent_tools(side: str = "", user: dict = Depends(current_user)):
    """两个智能体共用的工具清单（上传资料 / 生成资料）。"""
    role = "teacher" if str(user.get("role")) == "teacher" else "student"
    return ok({"tools": agenttools.tools_view(side or role),
               "strategies": ragroute.strategies_view()})


@app.post(f"{API}/agent/tools/{{tool_id}}/run")
def api_agent_tool_run(tool_id: str, payload: dict = Body(default={}),
                       user: dict = Depends(current_user)):
    result = agenttools.run_tool(tool_id, payload or {}, user)
    if result.get("error"):
        return fail(result["error"], 404)
    return ok(result)


# ================================================================ 说明手册（三项能力口径）
@app.get(f"{API}/manual")
def api_manual(user: dict = Depends(current_user)):
    """能力①②③ 的说明手册 + 接口清单 + 两个智能体简介卡。

    内容由 ``services/manual.py`` 从代码里的规则表读出来，改规则即改手册，
    不会出现文档与实现对不上的情况。
    """
    data = manual.build()
    data["agents"] = manual.agents()
    return ok(data)


# ================================================================ 演示例子与测试用例
@app.get(f"{API}/demo/samples")
def api_demo_samples(user: dict = Depends(current_user)):
    return ok(demo.list_samples())


@app.post(f"{API}/demo/samples/{{sid}}/run")
def api_demo_run_sample(sid: str, user: dict = Depends(current_user)):
    result = demo.run_sample(sid)
    if result.get("error"):
        return fail(result["error"], 404)
    return ok(result)


@app.get(f"{API}/demo/cases")
def api_demo_cases(user: dict = Depends(current_user)):
    return ok({"cases": demo.list_cases(), "overview": demo.overview()})


@app.get(f"{API}/demo/lecture")
def api_demo_lecture(user: dict = Depends(current_user)):
    """备课演示用的示例讲义正文 —— 教师点「上传示例讲义」时前端拿它造一个文件，
    省去演示前先找资料的麻烦。"""
    return ok({"name": demo.LECTURE_FILE.name, "text": demo.lecture_text()})


@app.post(f"{API}/demo/cases/{{cid}}/run")
def api_demo_run_case(cid: str, payload: dict = Body(default={}),
                      user: dict = Depends(current_user)):
    result = demo.run_case(cid, live=bool(payload.get("live")))
    if result.get("error"):
        return fail(result["error"], 404)
    return ok(result)


# ================================================================ 资料库（能力①②）
@app.get(f"{API}/materials/overview")
def api_materials_overview(user: dict = Depends(current_user)):
    return ok(mylibrary.overview(int(user["id"]), teacher_scope=str(user.get("role")) == "teacher"))


@app.get(f"{API}/materials")
def api_materials(category: str = "", course: str = "", keyword: str = "",
                  user: dict = Depends(current_user)):
    return ok(mylibrary.materials(
        int(user["id"]), category, course, keyword,
        teacher_scope=str(user.get("role")) == "teacher",
    ))


@app.post(f"{API}/materials/{{material_id}}/import")
def api_material_import(material_id: int, user: dict = Depends(current_user)):
    """把教师上传的公用资料导入我的检索库（数据隔离下的显式授权）。"""
    okk, msg = mylibrary.import_material(int(user["id"]), material_id)
    if not okk:
        return fail(msg, 404)
    return ok(message=msg)


@app.delete(f"{API}/materials/{{material_id}}/import")
def api_material_unimport(material_id: int, user: dict = Depends(current_user)):
    """移除导入：只删引用记录，公用资料本体不受影响。"""
    if not mylibrary.remove_import(int(user["id"]), material_id):
        return fail("尚未导入该资料", 404)
    return ok(message="已移除导入：这份资料不再进入你的检索范围")


@app.get(f"{API}/materials/knowledge")
def api_knowledge(course: str = "", difficulty: str = "", keyword: str = "",
                  user: dict = Depends(current_user)):
    return ok(mylibrary.knowledge(
        int(user["id"]), course, difficulty, keyword,
        teacher_scope=str(user.get("role")) == "teacher",
    ))


@app.post(f"{API}/materials/upload")
async def api_materials_upload(
    files: list[UploadFile] = File(default=[]),
    category: str = Form("未分类"),
    save: bool = Form(True),
    user: dict = Depends(current_user),
):
    """上传 → 解析 → 知识点 → 索引。``save=false`` 时只预览解析结果不落库。"""
    if not files:
        return fail("没有收到文件")

    user_id = int(user["id"])
    results: list[dict] = []
    for upload in files:
        name = extract.safe_name(upload.filename or "未命名")
        ext = extract.ext_of(name)
        item: dict[str, Any] = {"filename": name, "kind": extract.KINDS.get(
            extract.kind_by_ext(name), "其它材料")}

        if ext not in extract.ALLOWED_EXTS:
            item["error"] = f"不支持的文件类型 .{ext}（支持：{'、'.join(sorted(extract.ALLOWED_EXTS))}）"
            results.append(item)
            continue

        data = await upload.read()
        if len(data) > config.MAX_UPLOAD_BYTES:
            item["error"] = f"文件超过 {config.MAX_UPLOAD_MB}MB 上限"
            results.append(item)
            continue

        try:
            text = extract.read_text(name, data)
        except Exception as exc:  # noqa: BLE001 - 不同格式的解析异常都要如实反馈
            item["error"] = f"读取失败：{exc}"
            results.append(item)
            continue

        kind = extract.kind_by_ext(name)
        if text.strip():
            parsed, engine = extract.parse_material(kind, name, text)
        else:
            parsed, engine = extract.parse_material(
                kind, name, "", image_b64=extract.to_base64(data)
            )
        item["engine"] = engine

        # 能力①：解析契约 —— 去杂报告 / 版面分块 / 素材登记 / 语义切片
        parsed_doc = parsekit.parse_document(name, kind, text)
        item["parse"] = parsekit.preview_report(parsed_doc)
        # 能力②：场景化知识点抽取 —— 返回所用规则集与命中锚点，界面直接可见
        kp_result = kprules.extract(text, kind=kind, category=category,
                                    blocks=parsed_doc["blocks"], limit=8)
        item["kp_rule"] = {
            "rule_set": kp_result["rule_set"],
            "stats": kp_result["stats"],
            "items": kp_result["items"][:6],
        }
        item["summary"] = parsed.get("summary") or ""
        item["knowledge_points"] = len(parsed.get("knowledge_points") or [])
        item["directions"] = parsed.get("directions") or []
        item["text_chars"] = len(text)
        if parsed.get("note"):
            item["note"] = parsed["note"]

        if not save:
            item["parsed"] = parsed
            results.append(item)
            continue

        stored = ""
        try:
            folder = extract.ensure_upload_dir(user_id)
            target = folder / name
            if target.exists():
                target = folder / f"{target.stem}_{db.now().replace(':', '').replace(' ', '')[:14]}{target.suffix}"
            target.write_bytes(data)
            stored = str(target.relative_to(config.DATA_DIR)).replace("\\", "/")
        except OSError as exc:
            item["error"] = f"落盘失败：{exc}"

        material_id = extract.save_material(
            user_id, kind, category or "未分类", name, stored, text, parsed, engine
        )
        touched = extract.apply_parse_result(user, material_id, kind, name, text, parsed)
        item["material_id"] = material_id
        item["indexed_chunks"] = int(touched.get("indexed") or 0)
        item["knowledge_saved"] = int(touched.get("knowledge_points") or 0)
        item["profile_update"] = {
            k: v for k, v in touched.items()
            if k in ("directions", "interests", "gpa", "grade_level")
        }
        results.append(item)

    good = [r for r in results if not r.get("error")]
    return ok({
        "files": results,
        "summary": {
            "total": len(results),
            "ok": len(good),
            "failed": len(results) - len(good),
            "knowledge_points": sum(int(r.get("knowledge_saved") or 0) for r in good),
            "chunks": sum(int(r.get("indexed_chunks") or 0) for r in good),
        },
    })


@app.post(f"{API}/materials/{{material_id}}/category")
def api_material_category(material_id: int, payload: dict = Body(default={}),
                          user: dict = Depends(current_user)):
    mylibrary.set_category(int(user["id"]), material_id, _str(payload, "category", "未分类"))
    return ok(message="分类已更新")


@app.delete(f"{API}/materials/{{material_id}}")
def api_material_delete(material_id: int, user: dict = Depends(current_user)):
    if not mylibrary.delete(int(user["id"]), material_id):
        return fail("资料不存在，或不属于你", 404)
    return ok(message="资料已删除（知识点与索引同步清理）")


@app.post(f"{API}/materials/search")
def api_materials_search(payload: dict = Body(default={}), user: dict = Depends(current_user)):
    """手动体验混合检索：看 BM25 路与向量路各命中了什么。"""
    query = _str(payload, "query")
    if not query:
        return fail("请输入检索内容")
    hits = retriever.hybrid_search(
        query, top_k=_int(payload, "top_k", 5) or 5, course=_str(payload, "course"),
        owner_id=int(user["id"]), teacher=str(user.get("role")) == "teacher",
    )
    return ok({
        "query": query,
        "terms": rag.candidate_terms(query),
        "hits": [
            {
                "ref": h.get("ref"), "course": h.get("course"), "filename": h.get("filename"),
                "via": h.get("via"), "score": h.get("fused_score"),
                "content": str(h.get("content") or "")[:400],
            }
            for h in hits
        ],
    })


# ================================================================ 资源闭环（链路 D）
@app.get(f"{API}/resources")
def api_resources(user: dict = Depends(current_user)):
    user_id = int(user["id"])
    if user.get("role") == "teacher":
        return ok(resources.teacher_view(user_id))
    return ok(resources.board(user_id))


@app.get(f"{API}/resources/{{resource_id}}")
def api_resource_detail(resource_id: int, user: dict = Depends(current_user)):
    return ok(resources.resource_detail(resource_id, int(user["id"])))


@app.post(f"{API}/resources/{{resource_id}}/apply")
def api_resource_apply(resource_id: int, payload: dict = Body(default={}),
                       user: dict = Depends(require_student)):
    return ok(resources.apply(int(user["id"]), resource_id, _str(payload, "message")),
              message="申请已提交，等待教师处理")


@app.get(f"{API}/resources/applications/mine")
def api_my_applications(user: dict = Depends(require_student)):
    return ok({"applications": resources.student_applications(int(user["id"]))})


@app.post(f"{API}/teacher/resources")
def api_teacher_resource_create(payload: dict = Body(default={}), user: dict = Depends(require_teacher)):
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
    resource_id = resources.create_resource(
        int(user["id"]),
        rtype=_str(payload, "rtype", "group"),
        title=_str(payload, "title"),
        detail=_str(payload, "detail"),
        tags=tags,
        capacity=_int(payload, "capacity", 0),
        deadline=_str(payload, "deadline"),
    )
    return ok({"resource_id": resource_id}, message="资源已发布")


@app.post(f"{API}/teacher/resources/{{resource_id}}")
def api_teacher_resource_update(resource_id: int, payload: dict = Body(default={}),
                               user: dict = Depends(require_teacher)):
    fields: dict[str, Any] = {}
    for key in ("title", "detail", "deadline"):
        if key in payload:
            fields[key] = _str(payload, key)
    if "rtype" in payload:
        fields["rtype"] = _str(payload, "rtype")
    if "capacity" in payload:
        fields["capacity"] = _int(payload, "capacity", 0)
    if "tags" in payload:
        tags = payload.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
        fields["tags"] = tags
    return ok(resources.update_resource(int(user["id"]), resource_id, **fields),
              message="资源已更新")


@app.delete(f"{API}/teacher/resources/{{resource_id}}")
def api_teacher_resource_delete(resource_id: int, user: dict = Depends(require_teacher)):
    resources.delete_resource(int(user["id"]), resource_id)
    return ok(message="资源已删除")


@app.post(f"{API}/teacher/resources/{{resource_id}}/close")
def api_teacher_resource_close(resource_id: int, user: dict = Depends(require_teacher)):
    return ok(resources.close_resource(int(user["id"]), resource_id), message="状态已切换")


@app.post(f"{API}/teacher/applications/{{application_id}}/decide")
def api_teacher_application_decide(application_id: int, payload: dict = Body(default={}),
                                   user: dict = Depends(require_teacher)):
    return ok(resources.decide(
        int(user["id"]), application_id,
        _str(payload, "action"), _str(payload, "reply"),
    ))


# ================================================================ 作业闭环（链路 E）
@app.get(f"{API}/teacher/homework")
def api_teacher_homework(user: dict = Depends(require_teacher)):
    return ok(homework.teacher_list(int(user["id"])))


@app.post(f"{API}/teacher/homework")
def api_teacher_homework_create(payload: dict = Body(default={}), user: dict = Depends(require_teacher)):
    homework_id = homework.create(
        int(user["id"]),
        title=_str(payload, "title"),
        course=_str(payload, "course"),
        class_name=_str(payload, "class_name"),
        detail=_str(payload, "detail"),
        full_score=float(_int(payload, "full_score", 100) or 100),
        deadline=_str(payload, "deadline"),
    )
    return ok({"homework_id": homework_id}, message="作业已布置")


@app.post(f"{API}/teacher/homework/{{homework_id}}")
def api_teacher_homework_update(homework_id: int, payload: dict = Body(default={}),
                                user: dict = Depends(require_teacher)):
    fields: dict[str, Any] = {}
    for key in ("title", "course", "class_name", "detail", "deadline", "status"):
        if key in payload:
            fields[key] = _str(payload, key)
    if "full_score" in payload:
        fields["full_score"] = float(_int(payload, "full_score", 100) or 100)
    return ok(homework.update_homework(int(user["id"]), homework_id, **fields),
              message="作业已更新")


@app.delete(f"{API}/teacher/homework/{{homework_id}}")
def api_teacher_homework_delete(homework_id: int, user: dict = Depends(require_teacher)):
    removed = homework.delete_homework(int(user["id"]), homework_id)
    return ok({"removed_submissions": removed}, message="作业已删除")


@app.get(f"{API}/teacher/homework/{{homework_id}}/roster")
def api_teacher_roster(homework_id: int, user: dict = Depends(require_teacher)):
    return ok(homework.roster(int(user["id"]), homework_id))


@app.get(f"{API}/teacher/homework/{{homework_id}}/stats")
def api_teacher_score_stats(homework_id: int, user: dict = Depends(require_teacher)):
    return ok(homework.score_stats(int(user["id"]), homework_id))


@app.post(f"{API}/teacher/homework/{{homework_id}}/suggest")
def api_teacher_suggest(homework_id: int, payload: dict = Body(default={}),
                        user: dict = Depends(require_teacher)):
    """AI 建议分。只给建议，**不写库** —— 最终分数必须由教师确认后提交。"""
    return ok(homework.suggest(
        int(user["id"]), homework_id, _int(payload, "student_id")
    ))


@app.post(f"{API}/teacher/homework/{{homework_id}}/grade")
def api_teacher_grade(homework_id: int, payload: dict = Body(default={}),
                      user: dict = Depends(require_teacher)):
    result = homework.grade(
        int(user["id"]), homework_id, _int(payload, "student_id"),
        score=payload.get("score", 0),
        comment=_str(payload, "comment"),
        level=_str(payload, "level"),
    )
    return ok(result, message="已保存成绩与评语")


@app.post(f"{API}/teacher/homework/{{homework_id}}/grade-missing")
def api_teacher_grade_missing(homework_id: int, user: dict = Depends(require_teacher)):
    count = homework.grade_missing_zero(int(user["id"]), homework_id)
    return ok({"count": count}, message=f"已把 {count} 名未提交学生记为 0 分")


@app.get(f"{API}/teacher/homework/{{homework_id}}/export")
def api_teacher_export(homework_id: int, only_missing: bool = False,
                       user: dict = Depends(require_teacher)):
    filename, text = homework.export_csv(int(user["id"]), homework_id, only_missing)
    return download(text, filename, "text/csv; charset=utf-8")


# 学生侧
@app.get(f"{API}/homework/mine")
def api_my_homework(user: dict = Depends(require_student)):
    return ok(homework.student_list(int(user["id"])))


@app.post(f"{API}/homework/{{homework_id}}/submit")
async def api_homework_submit(
    homework_id: int,
    content: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    user: dict = Depends(require_student),
):
    student_id = int(user["id"])
    saved: list[dict] = []
    for upload in files:
        if not (upload.filename or "").strip():
            continue
        data = await upload.read()
        saved.append(homework.save_file(student_id, homework_id, upload.filename, data))
    result = homework.submit(student_id, homework_id, content, saved)
    return ok(result, message="提交成功" if result.get("attempt", 1) <= 1 else "已重新提交（原分数已清空，教师需重批）")


@app.get(f"{API}/homework/file/{{submission_id}}/{{index}}")
def api_homework_file(submission_id: int, index: int, user: dict = Depends(current_user)):
    path, mime, name = homework.submission_file(user, submission_id, index)
    return FileResponse(path, media_type=mime, filename=name)


# ================================================================ 教师驾驶舱
@app.get(f"{API}/teacher/classes")
def api_teacher_classes(user: dict = Depends(require_teacher)):
    """该教师可查看的行政班列表（驾驶舱右上角切换班级用）。"""
    return ok({"classes": dashboard.classes_of(user),
               "current": dashboard.class_of(user)})


@app.get(f"{API}/teacher/overview")
def api_teacher_overview(level: str = "", track: str = "", keyword: str = "",
                         class_id: str = "", user: dict = Depends(require_teacher)):
    """班级学情总览。``class_id`` 传任教班级之一，或传 ``all`` 表示跨班汇总。"""
    return ok(dashboard.overview(user, level, track, keyword, class_id=class_id))


@app.get(f"{API}/teacher/students/{{student_id}}")
def api_teacher_student_detail(student_id: int, user: dict = Depends(require_teacher)):
    return ok(dashboard.student_detail(user, student_id))


@app.post(f"{API}/teacher/students/{{student_id}}/mastery")
def api_teacher_recompute_mastery(student_id: int, payload: dict = Body(default={}),
                                  user: dict = Depends(require_teacher)):
    count = dashboard.recompute_mastery(student_id, _str(payload, "course"))
    return ok({"count": count}, message=f"已由作业成绩重算 {count} 个知识点的掌握度")


# ================================================================ 教师辅助（能力④⑤）
def _folder_dir(user: dict, folder: str) -> Any:
    """备课文件夹在磁盘上的真实目录（教师之间互不干扰）。

    目录名 = ``用户id_文件夹名``：文件夹名是教师自己起的，两个教师完全可以叫同一个名字，
    不带上 user_id 就会互相覆盖。
    """
    name = re.sub(r"[\\/:*?\"<>|]", "_", (folder or "").strip())[:60]
    return config.EXPORT_DIR / f"{int(user['id'])}_{name}" if name else config.EXPORT_DIR


def _save_artifact(user: dict, kind: str, title: str, course: str,
                   blob: bytes | None, ext: str, content: dict,
                   folder: str = "") -> tuple[int, str]:
    """把生成的教案/PPT 落盘并登记，返回 ``(artifact_id, 可下载文件名)``。

    ``folder`` 非空时落进对应备课文件夹，同一课题的教案与 PPT 天然聚在一起。
    """
    user_id = int(user["id"])
    filename = office.safe_filename(title, ext)
    path = ""
    if blob is not None:
        directory = _folder_dir(user, folder)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{user_id}_{db.now().replace(':', '').replace(' ', '').replace('-', '')[:14]}_{filename}"
        target.write_bytes(blob)
        path = str(target)
    artifact_id = db.execute(
        "INSERT INTO artifacts (user_id, kind, title, course, file_path, content, created_at, folder) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (user_id, kind, title, course, path, db.jdump(content), db.now(), (folder or "").strip()),
    )
    return artifact_id, filename


def _artifact_folder_of(user: dict, artifact_id: int) -> str:
    row = db.query_one("SELECT folder FROM artifacts WHERE id = ? AND user_id = ?",
                       (artifact_id, int(user["id"]))) or {}
    return str(row.get("folder") or "")


def _default_folder(title: str) -> str:
    """自动生成备课文件夹名：课题 + 日期，方便一节课的产物自动聚成一堆。"""
    stamp = db.now()[:10]
    clean = re.sub(r"\s*(教案|PPT|PPT 大纲)\s*", "", (title or "").strip())
    return f"{clean or '未命名备课'} · {stamp}"[:60]


@app.post(f"{API}/teacher/lesson")
def api_teacher_lesson(payload: dict = Body(default={}), user: dict = Depends(require_teacher)):
    """生成教案：先检索教师上传的资料，再生成，最后同时产出 docx 文件。"""
    topic = _str(payload, "topic")
    if not topic:
        return fail("请输入课题（如：注意力机制）")
    course = _str(payload, "course")
    periods = max(1, min(6, _int(payload, "periods", 1) or 1))
    level = _str(payload, "level", "B") or "B"

    folder = _str(payload, "folder") or _default_folder(topic)
    result = teaching.lesson_plan(topic, course, periods, level,
                                  owner_id=int(user["id"]))
    plan, engine = result["plan"], result["engine"]
    title = f"{topic} 教案"
    docx = office.build_docx(title, office.lesson_to_blocks(plan))
    artifact_id, filename = _save_artifact(user, "lesson", title, course, docx, ".docx", plan,
                                           folder=folder)
    plan["folder"] = folder

    return ok(
        {"plan": plan, "engine": engine, "refs": result["refs"], "folder": folder,
         "artifact": {"id": artifact_id, "filename": filename, "size": len(docx)}},
        message="教案已生成（含 docx 文件）",
    )


@app.put(f"{API}/teacher/artifacts/{{artifact_id}}")
def api_teacher_artifact_update(artifact_id: int, payload: dict = Body(default={}),
                                user: dict = Depends(require_teacher)):
    """保存教师手工改过的教案 / PPT 大纲，并按改后内容重新出一份文件。

    只接受 ``content``（教案结构或大纲结构）与 ``title``；
    文件落在原文件夹里，不会另起一份，避免产物库越改越乱。
    """
    row = db.query_one("SELECT * FROM artifacts WHERE id = ? AND user_id = ?",
                       (artifact_id, int(user["id"])))
    if not row:
        return fail("产物不存在", 404)

    kind = str(row.get("kind") or "")
    content = payload.get("content")
    if not isinstance(content, dict) or not content:
        return fail("内容为空，未做任何修改")
    title = _str(payload, "title") or str(row.get("title") or "")
    course = _str(payload, "course") or str(row.get("course") or "")
    folder = str(row.get("folder") or "")

    if kind == "pptx":
        slides = content.get("slides") or []
        if not isinstance(slides, list) or not slides:
            return fail("大纲为空，无法保存")
        blob = office.build_pptx(title.replace(" PPT 大纲", ""), slides,
                                 subtitle=f"{course}　共 {len(slides)} 页" if course else "")
        ext = ".pptx"
    else:
        blob = office.build_docx(title, office.lesson_to_blocks(content))
        ext = ".docx"

    # 原地覆盖：旧文件删掉、新文件写回同一条记录，id 不变，前端不用重新定位。
    old_path = Path(str(row.get("file_path") or ""))
    if old_path.exists():
        try:
            old_path.unlink()
        except OSError:
            pass
    directory = _folder_dir(user, folder)
    directory.mkdir(parents=True, exist_ok=True)
    filename = office.safe_filename(title, ext)
    target = directory / f"{int(user['id'])}_{db.now().replace(':', '').replace(' ', '').replace('-', '')[:14]}_{filename}"
    target.write_bytes(blob)
    db.execute(
        "UPDATE artifacts SET title=?, course=?, file_path=?, content=? WHERE id=?",
        (title, course, str(target), db.jdump(content), artifact_id),
    )

    return ok({"artifact": {"id": artifact_id, "filename": filename, "size": len(blob)},
               "folder": folder},
              message="修改已保存，文件已按新内容重新生成")


def _save_slides(user: dict, topic: str, course: str, outline: dict,
                 folder: str = "") -> dict:
    """把大纲导出成 pptx 并登记（教案转 PPT / 资料转 PPT / 课题直出三条路共用）。"""
    slides = outline.get("slides") or []
    folder = folder or _default_folder(topic)
    title = f"{topic} PPT"
    subtitle = f"{course}　共 {len(slides)} 页" if course else f"共 {len(slides)} 页"
    pptx = office.build_pptx(topic, slides, subtitle=subtitle)
    artifact_id, filename = _save_artifact(user, "pptx", title, course, pptx, ".pptx",
                                           outline, folder=folder)
    return {"id": artifact_id, "filename": filename, "size": len(pptx)}, folder


@app.post(f"{API}/teacher/slides")
def api_teacher_slides(payload: dict = Body(default={}), user: dict = Depends(require_teacher)):
    """生成 PPT 大纲，并同时产出可打开的 .pptx 文件。"""
    topic = _str(payload, "topic")
    if not topic:
        return fail("请输入课题")
    course = _str(payload, "course")
    pages = max(4, min(20, _int(payload, "pages", 8) or 8))

    result = teaching.slide_outline(topic, pages, course, owner_id=int(user["id"]))
    outline, engine = result["outline"], result["engine"]
    outline.setdefault("source", "topic")
    artifact, folder = _save_slides(user, topic, course, outline, _str(payload, "folder"))

    return ok(
        {"outline": outline, "engine": engine, "folder": folder, "artifact": artifact},
        message="PPT 已生成（可直接下载打开）",
    )


@app.post(f"{API}/teacher/slides/from-lesson")
def api_teacher_slides_from_lesson(payload: dict = Body(default={}),
                                   user: dict = Depends(require_teacher)):
    """根据一份已生成的教案生成 PPT —— 教案本身就是最好的提纲。

    ``artifact_id`` 指定教案；也可以直接传 ``plan``（前端改过但还没保存时用这个）。
    产物自动归入教案所在的备课文件夹。
    """
    artifact_id = _int(payload, "artifact_id", 0) or 0
    plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else None
    course = _str(payload, "course")
    folder = _str(payload, "folder")

    if not plan:
        if not artifact_id:
            return fail("请先选择一份教案")
        row = db.query_one("SELECT * FROM artifacts WHERE id = ? AND user_id = ?",
                           (artifact_id, int(user["id"])))
        if not row:
            return fail("教案不存在", 404)
        plan = db.jload(row.get("content"), {})
        course = course or str(row.get("course") or "")
        folder = folder or str(row.get("folder") or "")
    if not plan:
        return fail("教案内容为空，请重新生成")

    pages = max(3, min(30, _int(payload, "pages", 0) or 0))
    result = teaching.slides_from_plan(plan, pages)
    outline, engine = result["outline"], result["engine"]
    topic = str(plan.get("title") or "").replace(" 教案", "").strip() or outline.get("title") or "教案"
    artifact, folder = _save_slides(user, topic, course, outline, folder)

    return ok(
        {"outline": outline, "engine": engine, "folder": folder, "artifact": artifact,
         "topic": topic},
        message="已按教案生成 PPT（可直接下载打开）",
    )


@app.post(f"{API}/teacher/slides/from-material")
async def api_teacher_slides_from_material(
    file: UploadFile = File(default=None),
    topic: str = Form(""),
    course: str = Form(""),
    pages: int = Form(8),
    folder: str = Form(""),
    user: dict = Depends(require_teacher),
):
    """上传一份资料（课件 / 讲义 / md / txt / docx / pptx / pdf）直接生成 PPT。

    与「按课题生成」的区别：内容完全来自这份资料，不靠主题推测，
    所以老师手上有现成讲义时用这条路最准。
    """
    if file is None or not file.filename:
        return fail("请先选择要上传的资料")
    name = extract.safe_name(file.filename)
    data = await file.read()
    if not data:
        return fail("文件内容为空")
    try:
        text = extract.read_text(name, data)
    except Exception as exc:  # noqa: BLE001
        return fail(f"资料读取失败：{exc}")
    if len(text.strip()) < 20:
        return fail("资料正文太短（不足 20 字），无法整理成 PPT")

    topic = (topic or "").strip() or re.sub(r"\.(md|txt|docx|pptx|pdf|ppt|doc)$", "", name,
                                            flags=re.I)[:30]
    result = teaching.slides_from_text(topic, text, max(3, min(20, int(pages or 8))))
    outline, engine = result["outline"], result["engine"]
    outline["source_material"] = name
    artifact, folder = _save_slides(user, topic, (course or "").strip(), outline, folder)

    return ok(
        {"outline": outline, "engine": engine, "folder": folder, "artifact": artifact,
         "topic": topic, "material": name, "chars": len(text)},
        message=f"已按《{name}》生成 PPT",
    )


@app.post(f"{API}/teacher/grade/suggest")
def api_teacher_grade_suggest(payload: dict = Body(default={}),
                              user: dict = Depends(require_teacher)):
    """试批：粘贴任意一段作答直接得到建议分。

    与 ``/{homework_id}/suggest`` 的区别是**不依赖已布置的作业、不落库** ——
    演示与自测时不必先走一遍"发布作业 → 学生提交"的流程。
    """
    return ok(homework.suggest_text(
        _str(payload, "text"),
        course=_str(payload, "course"),
        topic=_str(payload, "topic"),
        full_score=float(_int(payload, "full_score", 100) or 100),
    ))


@app.get(f"{API}/teacher/artifacts")
def api_teacher_artifacts(folder: str = "", user: dict = Depends(require_teacher)):
    """备课文稿列表。``folder`` 为空 = 全部；传 ``未归档`` 查没有归档的产物。"""
    clause, args = "", [int(user["id"])]
    if folder:
        clause = " AND folder = ?"
        args.append("" if folder == "未归档" else folder)
    rows = db.query(
        "SELECT id, kind, title, course, file_path, folder, created_at FROM artifacts "
        "WHERE user_id = ?" + clause + " ORDER BY id DESC LIMIT 200", tuple(args),
    )
    for row in rows:
        row["filename"] = Path(str(row.get("file_path") or "")).name
        row["exists"] = bool(row.get("file_path")) and Path(str(row["file_path"])).exists()
        row["folder"] = str(row.get("folder") or "")
        row.pop("file_path", None)
    return ok({"artifacts": rows})


@app.get(f"{API}/teacher/folders")
def api_teacher_folders(user: dict = Depends(require_teacher)):
    """备课文件夹列表（含每个文件夹里的产物数量）。

    两个来源合并：``artifacts.folder`` 的分组结果，加上教师**手工新建的空文件夹**
    （空文件夹里没有产物，光靠分组推不出来，所以单独登记在 prep_folders 里）。
    """
    uid = int(user["id"])
    counts: dict[str, int] = {}
    updated: dict[str, str] = {}
    for r in db.query(
        "SELECT folder, COUNT(*) AS count, MAX(created_at) AS updated_at "
        "FROM artifacts WHERE user_id = ? GROUP BY folder", (uid,)
    ):
        name = str(r.get("folder") or "")
        counts[name] = int(r.get("count") or 0)
        updated[name] = str(r.get("updated_at") or "")
    for r in db.query("SELECT name, created_at FROM prep_folders WHERE user_id = ?", (uid,)):
        name = str(r.get("name") or "")
        counts.setdefault(name, 0)
        updated.setdefault(name, str(r.get("created_at") or ""))
    folders = [{"name": n, "count": counts[n], "updated_at": updated.get(n, "")} for n in counts]
    folders.sort(key=lambda f: (f["name"] == "", f["updated_at"]), reverse=True)
    return ok({"folders": folders})


@app.post(f"{API}/teacher/folders")
def api_teacher_folder_create(payload: dict = Body(default={}),
                              user: dict = Depends(require_teacher)):
    """新建备课文件夹（只是个名字，产物移进来时才真正建立磁盘目录）。"""
    name = _str(payload, "name").strip()
    if not name:
        return fail("请输入文件夹名")
    if name == "未归档":
        return fail("「未归档」是系统保留名，换一个吧")
    uid = int(user["id"])
    if db.query_one("SELECT id FROM artifacts WHERE user_id = ? AND folder = ? LIMIT 1", (uid, name)):
        return fail("同名文件夹已存在")
    if db.query_one("SELECT id FROM prep_folders WHERE user_id = ? AND name = ?", (uid, name)):
        return fail("同名文件夹已存在")
    db.execute("INSERT INTO prep_folders (user_id, name, created_at) VALUES (?,?,?)",
               (uid, name, db.now()))
    _folder_dir(user, name).mkdir(parents=True, exist_ok=True)
    return ok({"folder": name}, message=f"已创建文件夹「{name}」")


@app.post(f"{API}/teacher/folders/rename")
def api_teacher_folder_rename(payload: dict = Body(default={}),
                              user: dict = Depends(require_teacher)):
    """重命名文件夹：库里的归属一并改，磁盘目录也跟着搬。"""
    old = _str(payload, "old").strip()
    new = _str(payload, "new").strip()
    if not old or not new:
        return fail("请输入原名称与新名称")
    if new == "未归档":
        return fail("「未归档」是系统保留名，换一个吧")
    if old == new:
        return ok({"folder": new}, message="名称未变")
    uid = int(user["id"])
    dup = db.query_one("SELECT id FROM artifacts WHERE user_id = ? AND folder = ? LIMIT 1", (uid, new))
    if dup or db.query_one("SELECT id FROM prep_folders WHERE user_id = ? AND name = ?", (uid, new)):
        return fail("已存在同名文件夹")

    db.execute("UPDATE artifacts SET folder = ? WHERE user_id = ? AND folder = ?", (new, uid, old))
    db.execute("UPDATE prep_folders SET name = ? WHERE user_id = ? AND name = ?", (new, uid, old))
    # 旧文件夹若是历史数据（只有产物、没登记过），改名后补一条，保证列表稳定
    db.execute("INSERT OR IGNORE INTO prep_folders (user_id, name, created_at) VALUES (?,?,?)",
               (uid, new, db.now()))
    src, dst = _folder_dir(user, old), _folder_dir(user, new)
    if src.exists() and src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for item in list(src.iterdir()):
            try:
                item.replace(dst / item.name)
            except OSError:
                pass
        try:
            src.rmdir()
        except OSError:
            pass
    return ok({"folder": new}, message=f"已重命名为「{new}」")


@app.delete(f"{API}/teacher/folders/{{name}}")
def api_teacher_folder_delete(name: str, keep_files: bool = True,
                              user: dict = Depends(require_teacher)):
    """删除文件夹。默认只取消归档（文件回到「未归档」保留下来），
    ``keep_files=false`` 时才连文件一起删除。
    """
    name = (name or "").strip()
    if not name or name == "未归档":
        return fail("该文件夹不可删除")
    uid = int(user["id"])
    rows = db.query("SELECT id, file_path FROM artifacts WHERE user_id = ? AND folder = ?",
                    (uid, name))
    registered = db.query_one("SELECT id FROM prep_folders WHERE user_id = ? AND name = ?", (uid, name))
    if not rows and not registered:
        return fail("文件夹不存在", 404)
    for row in rows:
        if keep_files:
            db.execute("UPDATE artifacts SET folder = '' WHERE id = ?", (row["id"],))
        else:
            path = Path(str(row.get("file_path") or ""))
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
            db.execute("DELETE FROM artifacts WHERE id = ?", (row["id"],))
    db.execute("DELETE FROM prep_folders WHERE user_id = ? AND name = ?", (uid, name))
    directory = _folder_dir(user, name)
    if directory.exists() and directory.is_dir():
        try:
            directory.rmdir()
        except OSError:
            pass
    return ok(message=("已取消归档，文件保留在「未归档」" if keep_files
                       else f"已删除文件夹「{name}」及其 {len(rows)} 份文件"))


@app.post(f"{API}/teacher/artifacts/move")
def api_teacher_artifacts_move(payload: dict = Body(default={}),
                               user: dict = Depends(require_teacher)):
    """把若干产物移动到目标文件夹（传空串 / ``未归档`` 表示移出到未归档）。"""
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return fail("请先选择要移动的文件")
    target = _str(payload, "folder").strip()
    if target == "未归档":
        target = ""
    if target:
        _folder_dir(user, target).mkdir(parents=True, exist_ok=True)
        # 目标文件夹登记一下：即便里面暂时没有产物，也会出现在文件夹列表里
        db.execute("INSERT OR IGNORE INTO prep_folders (user_id, name, created_at) VALUES (?,?,?)",
                   (int(user["id"]), target, db.now()))

    moved = 0
    for raw in ids[:100]:
        try:
            artifact_id = int(raw)
        except (TypeError, ValueError):
            continue
        row = db.query_one("SELECT file_path FROM artifacts WHERE id = ? AND user_id = ?",
                           (artifact_id, int(user["id"])))
        if not row:
            continue
        old_path = Path(str(row.get("file_path") or ""))
        new_path = old_path
        if old_path.exists():
            directory = _folder_dir(user, target)
            directory.mkdir(parents=True, exist_ok=True)
            new_path = directory / old_path.name
            try:
                old_path.replace(new_path)
            except OSError:
                new_path = old_path
        db.execute("UPDATE artifacts SET folder = ?, file_path = ? WHERE id = ?",
                   (target, str(new_path), artifact_id))
        moved += 1
    return ok({"moved": moved, "folder": target}, message=f"已移动 {moved} 份文件")


@app.get(f"{API}/teacher/artifacts/{{artifact_id}}")
def api_teacher_artifact_detail(artifact_id: int, user: dict = Depends(require_teacher)):
    row = db.query_one(
        "SELECT * FROM artifacts WHERE id = ? AND user_id = ?", (artifact_id, int(user["id"]))
    )
    if not row:
        return fail("产物不存在", 404)
    row["content"] = db.jload(row.get("content"), {})
    return ok(row)


@app.get(f"{API}/teacher/artifacts/{{artifact_id}}/download")
def api_teacher_artifact_download(artifact_id: int, user: dict = Depends(require_teacher)):
    row = db.query_one(
        "SELECT * FROM artifacts WHERE id = ? AND user_id = ?", (artifact_id, int(user["id"]))
    )
    if not row or not row.get("file_path"):
        return fail("产物文件不存在", 404)
    path = Path(str(row["file_path"]))
    if not path.exists():
        return fail("产物文件已被清理，请重新生成", 404)
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
        if row.get("kind") == "lesson" else \
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    return FileResponse(str(path), media_type=mime, filename=path.name)


@app.delete(f"{API}/teacher/artifacts/{{artifact_id}}")
def api_teacher_artifact_delete(artifact_id: int, user: dict = Depends(require_teacher)):
    row = db.query_one(
        "SELECT * FROM artifacts WHERE id = ? AND user_id = ?", (artifact_id, int(user["id"]))
    )
    if not row:
        return fail("产物不存在", 404)
    if row.get("file_path"):
        try:
            Path(str(row["file_path"])).unlink(missing_ok=True)
        except OSError:
            pass
    db.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
    return ok(message="已删除")


@app.post(f"{API}/teacher/slides/save")
def api_teacher_slides_save(payload: dict = Body(default={}), user: dict = Depends(require_teacher)):
    """保存（或重新导出）一份已有的 PPT 大纲 —— 用于教师手动改过大纲之后。"""
    outline = payload.get("outline") or {}
    slides = outline.get("slides") or []
    if not isinstance(slides, list) or not slides:
        return fail("大纲为空，无法导出")
    topic = _str(payload, "topic") or _str(outline, "title") or "PPT 大纲"
    course = _str(payload, "course")
    title = f"{topic} PPT 大纲"
    pptx = office.build_pptx(topic, slides, subtitle=f"{course}　共 {len(slides)} 页" if course else "")
    # 改完大纲重新导出时，默认留在原文件夹里，不另开一份，避免产物库越改越散。
    # 认原文件夹的方式：前端直接带 folder，或带 artifact_id 由后端查。
    folder = _str(payload, "folder") or _artifact_folder_of(user, _int(payload, "artifact_id", 0) or 0)
    artifact_id, filename = _save_artifact(user, "pptx", title, course, pptx, ".pptx", outline,
                                           folder=folder)
    return ok({"artifact": {"id": artifact_id, "filename": filename}, "folder": folder},
              message="已导出 PPT")


@app.post(f"{API}/teacher/grade/batch")
async def api_teacher_batch_grade(
    files: list[UploadFile] = File(default=[]),
    course: str = Form(""),
    topic: str = Form(""),
    full_score: float = Form(100.0),
    user: dict = Depends(require_teacher),
):
    """临时批量批改（不入库）：上传多份文本作业，一次性给出分数与评语。"""
    payload: list[tuple[str, str]] = []
    for upload in files:
        name = extract.safe_name(upload.filename or "未命名")
        data = await upload.read()
        try:
            payload.append((name, extract.read_text(name, data)))
        except Exception as exc:  # noqa: BLE001
            payload.append((name, f"（读取失败：{exc}）"))
    if not payload:
        return fail("请先选择要批改的文件")
    return ok(teaching.batch_grade(payload, course, topic, full_score))


# ================================================================ 教师 Copilot（能力⑥）
@app.post(f"{API}/teacher/copilot/ask")
def api_copilot_ask(payload: dict = Body(default={}), user: dict = Depends(require_teacher)):
    return ok(copilot.ask(user, _str(payload, "question"), _str(payload, "skill"),
                          session_id=_str(payload, "session_id"),
                          strategy=_str(payload, "strategy") or "auto"))


@app.get(f"{API}/teacher/copilot/sessions")
def api_copilot_sessions(limit: int = 30, user: dict = Depends(require_teacher)):
    return ok({"sessions": copilot.sessions(int(user["id"]), max(1, min(100, limit))),
               "new_session": copilot.new_session(),
               "strategies": ragroute.strategies_view()})


@app.post(f"{API}/teacher/copilot/new")
def api_copilot_new(user: dict = Depends(require_teacher)):
    return ok({"session_id": copilot.new_session()}, message="已新开一次对话")


@app.get(f"{API}/teacher/copilot/history")
def api_copilot_history(limit: int = 20, session_id: str = "",
                        user: dict = Depends(require_teacher)):
    return ok({"messages": copilot.history(int(user["id"]), max(1, min(100, limit)), session_id)})


@app.post(f"{API}/teacher/copilot/clear")
def api_copilot_clear(payload: dict = Body(default={}), user: dict = Depends(require_teacher)):
    copilot.clear_history(int(user["id"]), _str(payload, "session_id"))
    return ok(message="对话已清空")


# ================================================================ 师生匹配
@app.get(f"{API}/match/recommend")
def api_match_recommend(group_id: int = 0, user: dict = Depends(current_user)):
    user_id = int(user["id"])
    if user.get("role") == "teacher":
        return ok(matcher.recommend_for_teacher(user_id, group_id))
    return ok(matcher.recommend_for_student(user_id))


@app.post(f"{API}/match/decide")
def api_match_decide(payload: dict = Body(default={}), user: dict = Depends(current_user)):
    action = _str(payload, "action")
    student_id = _int(payload, "student_id") or int(user["id"])
    if user.get("role") == "student":
        actor = "student"
        if student_id != int(user["id"]):
            return fail("学生只能确认自己的匹配")
    else:
        actor = "teacher"
    return ok(matcher.decide(actor, student_id, _int(payload, "group_id"), action))


@app.get(f"{API}/match/mine")
def api_match_mine(user: dict = Depends(require_student)):
    return ok({"matches": matcher.my_matches(int(user["id"]))})


# ---------------------------------------------------------------- 团队维护
# 「团队」= 老师长期带的队伍，既包括科研课题组，也包括横向项目、竞赛团队、实习组。
# 表名仍是 research_groups（历史命名），语义已按类型放宽。
@app.get(f"{API}/teacher/groups")
def api_teacher_groups(user: dict = Depends(require_teacher)):
    return ok({"groups": matcher.my_groups(int(user["id"])), "kinds": matcher.GROUP_KINDS})


@app.post(f"{API}/teacher/groups")
def api_teacher_group_create(payload: dict = Body(default={}),
                             user: dict = Depends(require_teacher)):
    group_id = matcher.create_group(
        int(user["id"]), _str(payload, "name"), payload.get("directions"),
        _str(payload, "requirement"), _int(payload, "capacity"), _str(payload, "kind"),
    )
    return ok({"group_id": group_id, "message": "团队已创建"})


@app.post(f"{API}/teacher/groups/{{group_id}}")
def api_teacher_group_update(group_id: int, payload: dict = Body(default={}),
                             user: dict = Depends(require_teacher)):
    group = matcher.update_group(
        int(user["id"]), group_id,
        name=payload.get("name"), directions=payload.get("directions"),
        requirement=payload.get("requirement"), capacity=payload.get("capacity"),
        kind=payload.get("kind"),
    )
    return ok({"group": group, "message": "已保存"})


@app.delete(f"{API}/teacher/groups/{{group_id}}")
def api_teacher_group_delete(group_id: int, user: dict = Depends(require_teacher)):
    removed = matcher.delete_group(int(user["id"]), group_id)
    return ok({"removed_records": removed, "message": "团队已删除"})


# ================================================================ 自检
_SAMPLE_ANSWER = (
    "一、为什么需要注意力机制：循环网络必须按顺序传递信息，长距离依赖容易衰减，"
    "而注意力机制允许每个位置直接与任意位置交互，路径长度降为常数。\n"
    "二、缩放点积注意力：查询与键做点积得到相似度，除以根号 d_k 做缩放，"
    "再经 softmax 归一化为权重，最后对值加权求和。除以根号维度是因为"
    "维度越高点积方差越大，softmax 会被推到饱和区导致梯度极小。\n"
    "三、多头注意力：把表示切到多个子空间并行计算注意力，让不同头分别"
    "关注语法、指代、位置等不同关系，最后拼接再线性变换。\n"
    "四、位置编码：注意力本身不含顺序信息，需通过正弦位置编码或可学习"
    "位置编码显式注入次序。\n"
    "五、残差连接与层归一化：残差连接让梯度可直接回传，层归一化稳定每层"
    "输入分布，两者共同支撑起深层 Transformer 的可训练性。\n"
    "综上，注意力机制用可并行的加权聚合替代了循环结构，是 Transformer 的核心。"
)


@app.post(f"{API}/selfcheck")
def api_selfcheck(user: dict = Depends(current_user)):
    """双引擎全链路自检：逐项验证每条能力在**无 API Key** 时也能跑通。

    刻意逐条 try/except：某一环失败不影响其余项，前端能精确定位到坏点。
    """
    checks: list[dict] = []
    uid = int(user["id"])
    role = user.get("role")

    def run(name: str, fn):
        try:
            detail = fn()
            checks.append({"name": name, "ok": True, "detail": str(detail)})
        except Exception as exc:  # noqa: BLE001 - 自检要收集所有失败点
            checks.append({"name": name, "ok": False,
                           "detail": f"{type(exc).__name__}: {exc}"})

    # --- 基建 ---
    def _db_check() -> str:
        n = db.scalar("SELECT COUNT(*) FROM kb_fts", (), 0)
        return f"FTS5 {'可用' if db.FTS_OK else '不可用（已降级 LIKE）'}，kb_fts {n} 条，用户 {db.scalar('SELECT COUNT(*) FROM users', (), 0)} 人"

    def _llm_check() -> str:
        st = llm.status()
        mode = st.get("llm_mode") or "mock"
        model = st.get("model") or "未配置（走规则版）"
        return f"模式 {mode}｜模型 {model}｜当前出口 {st.get('label')}"

    run("数据库与 FTS", _db_check)
    run("模型网关", _llm_check)

    # --- 能力①分层 ---
    def _stratify() -> str:
        rows = db.query(
            "SELECT u.name, p.gpa FROM student_profiles p JOIN users u ON u.id = p.user_id LIMIT 3"
        )
        if not rows:
            return "无画像数据（可先跑 seeds.py）"
        parts = []
        for r in rows:
            res = stratify.rule_stratify(float(r["gpa"] or 60), 3.5, 3.5, [])
            parts.append(f"{r['name']}={res['track']}/{res['grade_level']}")
        return "、".join(parts)

    run("分层引擎", _stratify)

    # --- 能力②解析 ---
    def _parse() -> str:
        parsed = extract.rule_parse(
            "courseware", "机器学习-第5讲-注意力机制.md",
            "注意力机制是 Transformer 的核心。缩放点积注意力除以根号 d_k。",
        )
        return f"规则版解析得 {len(parsed.get('knowledge_points') or [])} 条知识点、" \
               f"{len(parsed.get('directions') or [])} 个学科方向"

    run("素材解析", _parse)

    # --- 检索 ---
    def _search() -> str:
        hits = retriever.hybrid_search("为什么注意力要除以 sqrt(d_k)", top_k=3)
        if not hits:
            return "未命中（知识库为空，可先上传材料）"
        head = hits[0]
        return f"命中 {len(hits)} 条，首位来源「{head.get('ref') or '—'}」，召回通道 {head.get('via')}"

    run("混合检索", _search)

    # --- 能力③答疑 ---
    def _tutor() -> str:
        res = tutor.ask(user, "什么是注意力机制", top_k=3)
        return f"engine={res.get('engine')}，层级={res.get('layer') or '未定'}，" \
               f"引用 {len(res.get('refs') or [])} 条"

    run("分层答疑", _tutor)

    # --- 能力④备课 ---
    def _lesson() -> str:
        res = teaching.lesson_plan("注意力机制", "机器学习", 1, "B")
        plan = res.get("plan") or {}
        return f"生成教案《{plan.get('title')}》，{len(plan.get('outline') or [])} 个教学环节，engine={res.get('engine')}"

    run("备课教案", _lesson)

    def _slides() -> str:
        res = teaching.slide_outline("注意力机制", 6, "机器学习")
        blob = office.build_pptx(
            res["outline"].get("title") or "自检", res["outline"].get("slides") or []
        )
        return f"生成 {len(blob)} 字节 pptx，{len(res['outline'].get('slides') or [])} 页，包自检通过"

    run("PPT 导出", _slides)

    # --- 能力⑤批改 ---
    def _grade() -> str:
        result, engine = teaching.grade_one(
            _SAMPLE_ANSWER, topic="注意力机制", full_score=100,
            terms=teaching.key_terms("机器学习"),
        )
        return f"建议分 {result.get('score')}/{result.get('full_score')}（{result.get('level_text')}），" \
               f"engine={engine}，亮点 {len(result.get('highlights') or [])} 条 / 待补 {len(result.get('missing') or [])} 条"

    run("规则批改", _grade)

    # --- 链路 D 资源 ---
    if role == "teacher":
        def _res_teacher() -> str:
            view = resources.teacher_view(uid)
            return f"教师侧管理 {view['stats']['total']} 条资源"
        run("资源闭环", _res_teacher)
    else:
        def _res_student() -> str:
            data = resources.board(uid)
            return f"学生侧可见 {len(data.get('teachers') or [])} 位教师的资源"
        run("资源闭环", _res_student)

    # --- 链路 E 作业 ---
    if role == "teacher":
        def _hw_teacher() -> str:
            data = homework.teacher_list(uid)
            return f"教师侧 {data['stats']['total']} 份作业"
        run("作业闭环", _hw_teacher)
    else:
        def _hw_student() -> str:
            data = homework.student_list(uid)
            return f"学生侧 {data['stats']['total']} 份作业"
        run("作业闭环", _hw_student)

    # --- 链路 B 匹配 ---
    if role == "teacher":
        def _match_teacher() -> str:
            try:
                data = matcher.recommend_for_teacher(uid)
            except matcher.MatchError as exc:
                return f"暂无可推荐（{exc}）"
            groups = data.get("groups") or []
            seats = sum(len(g.get("candidates") or []) for g in groups)
            return f"常设团队 {len(groups)} 个，候选学生 {seats} 人次"
        run("师生匹配", _match_teacher)

        def _group_crud() -> str:
            """团队增删改：建一个临时队，改完再删掉，不留痕迹（顺带验证类型字段）。"""
            gid = matcher.create_group(
                uid, "__自检临时团队__", "自检、临时",
                "由 /api/selfcheck 创建，正常情况下一瞬间就被删掉", 1, "竞赛团队",
            )
            try:
                matcher.update_group(uid, gid, capacity=2, requirement="自检已改",
                                     kind="横向项目")
                rows = [g for g in matcher.my_groups(uid) if int(g["id"]) == gid]
                if not rows:
                    raise ValueError("更新后查不到该团队")
                if int(rows[0].get("capacity") or 0) != 2:
                    raise ValueError("名额上限没改成功")
                if rows[0].get("kind") != "横向项目":
                    raise ValueError("团队类型没改成功")
            finally:
                matcher.delete_group(uid, gid)
            if db.query_one("SELECT id FROM research_groups WHERE id = ?", (gid,)):
                raise ValueError("团队没被删掉")
            return "创建（竞赛团队）→ 改名额、要求与类型 → 删除，三步都生效"

        run("团队维护", _group_crud)
    else:
        def _match_student() -> str:
            data = matcher.recommend_for_student(uid)
            out = data.get("matches") or []
            head = out[0] if out else None
            tail = f"，首选《{head['name']}》({head['score']})" if head else ""
            return f"推荐 {len(out)} 个团队{tail}"
        run("师生匹配", _match_student)

    # --- 能力⑥ Copilot ---
    def _copilot() -> str:
        skills = copilot.SKILLS
        intent = copilot.detect_intent("帮我备一节注意力机制的课")
        return f"识别意图 → {intent}，共 {len(skills)} 项技能"

    run("Copilot 路由", _copilot)

    passed = sum(1 for c in checks if c["ok"])
    return ok({
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "failed": [c["name"] for c in checks if not c["ok"]],
        "llm": llm.status(),
        "role": role,
        "verdict": "全部通过：当前环境不依赖任何 API Key 也能完整演示。" if passed == len(checks)
                   else f"存在 {len(checks) - passed} 项未通过，请按 detail 逐项排查。",
    })


# ================================================================ 入口
def main() -> None:  # pragma: no cover - 命令行入口
    import uvicorn

    if "--reload" in sys.argv:
        uvicorn.run("app:app", host=config.HOST, port=config.PORT, reload=True)
    else:
        uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":  # pragma: no cover
    main()
