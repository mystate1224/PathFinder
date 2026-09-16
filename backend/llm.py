# -*- coding: utf-8 -*-
"""llm.py —— ★ 全局唯一模型调用出口（双引擎骨架）。

## 为什么要有这一层

本项目所有"模型能力"都必须是**可选增强**而不是**必要依赖**。做法是把每个能力写成
「规则版兜底 + 模型版增强」，两者**返回结构完全一致**，调用方拿到的永远是同一种数据。

    data, engine = llm.chat_json(messages, schema_hint=..., mock=rule_result)
    # engine == "llm"  -> 界面显示「AI 生成」
    # engine == "rule" -> 界面显示「规则生成」

## 自研同构（替代 LangChain）

| LangChain 概念            | 本项目实现                          |
|---------------------------|-------------------------------------|
| `ChatOpenAI`              | 本文件（统一 HTTP 出口）            |
| `with_fallbacks`          | `mock=` 参数 + 逐级降级             |
| `ChatPromptTemplate`      | `tutor._system_prompt()` 按画像拼装 |
| `JsonOutputParser`        | `_extract_json()`                   |
| `EnsembleRetriever`       | `retriever.hybrid_search()`         |
| `RunnableWithMessageHistory` | `db.recent_chat()` 取最近 4 轮   |

## 容错纪律

1. 统一 2 次尝试（间隔 1s），超时可配；
2. 任何异常统一收敛为 `LLMError`，**绝不向上抛网络细节**；
3. JSON 解析不出来 == 调用失败，同样回落规则版；
4. 模型结果缺字段时用规则版补齐（合并策略），不让半成品流进业务层。
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterable, Sequence

import config

try:
    import httpx
except Exception:  # pragma: no cover - httpx 在 requirements 中
    httpx = None


class LLMError(RuntimeError):
    """统一的模型调用异常。业务层只需认这一个类型。"""


# 最近一次调用的诊断信息（供 /api/health 与"模型连通性自检"使用）
_LAST_ERROR: str = ""
_LAST_OK_AT: float = 0.0


# ================================================================ 状态
def current_mode() -> str:
    """当前引擎模式：``api`` 或 ``mock``。"""
    return "api" if config.LLM_MODE == "api" else "mock"


def api_ready() -> bool:
    """真实模型是否可用（模式 + 地址 + 密钥三者齐备）。"""
    return current_mode() == "api" and bool(config.LLM_BASE_URL and config.LLM_API_KEY)


def engine_label(engine: str) -> str:
    return "AI 生成" if engine == "llm" else "规则生成"


def status() -> dict:
    """给前端上报当前引擎状态（不含密钥）。"""
    return {
        "llm_mode": current_mode(),
        "api_ready": api_ready(),
        "model": config.LLM_MODEL if api_ready() else "",
        "vision_model": config.LLM_VISION_MODEL if api_ready() else "",
        "vision_ready": bool(api_ready()),
        "embed_ready": bool(api_ready()),
        "last_error": _LAST_ERROR,
        "last_ok_at": _LAST_OK_AT,
        "label": engine_label("llm" if api_ready() else "rule"),
    }


def probe() -> dict:
    """连通性自检：启动时或页面手动触发一次，避免"配错了却静默降级"。"""
    if not api_ready():
        return {"ok": False, "engine": "rule",
                "message": "未配置真实模型（LLM_MODE=mock 或缺少地址/密钥），全程使用规则版。"}
    text, engine = chat(
        [{"role": "user", "content": "请只回复两个字：正常"}],
        mock=lambda: "规则版",
        temperature=0.0,
        max_tokens=8,
    )
    return {"ok": engine == "llm", "engine": engine,
            "message": text[:120] if engine == "llm" else f"网关不可达，已降级：{_LAST_ERROR}"}


# ================================================================ 底层 HTTP
def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.LLM_API_KEY}",
        "Content-Type": "application/json",
    }


def _post(path: str, payload: dict) -> dict:
    """带重试的 POST。任何失败都抛 LLMError。"""
    global _LAST_ERROR, _LAST_OK_AT
    if httpx is None:
        _LAST_ERROR = "httpx 未安装"
        raise LLMError(_LAST_ERROR)

    url = f"{config.LLM_BASE_URL}{path}"
    last_exc: Exception | None = None
    attempts = max(1, config.LLM_RETRY)
    for i in range(attempts):
        try:
            with httpx.Client(timeout=config.LLM_TIMEOUT) as client:
                resp = client.post(url, headers=_headers(), json=payload)
            if resp.status_code >= 400:
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            _LAST_ERROR = ""
            _LAST_OK_AT = time.time()
            return resp.json()
        except Exception as exc:            # 网络/超时/状态码/解析，全部收敛
            last_exc = exc
            if i < attempts - 1:
                time.sleep(config.LLM_RETRY_WAIT)
    _LAST_ERROR = f"{type(last_exc).__name__}: {str(last_exc)[:200]}"
    raise LLMError(_LAST_ERROR)


def _extract_json(text: str) -> dict | None:
    """JsonOutputParser 的等价物：三级兜底清洗。

    1. 直接 ``json.loads``；
    2. 去掉 ```json 代码围栏再解析；
    3. 截取首个 ``{`` 到末个 ``}`` 之间的片段再解析。
    """
    if not text:
        return None
    raw = text.strip()

    candidates = [raw]
    if "```" in raw:
        # 去掉代码围栏，逐段再试
        body = raw.replace("```json", "```").replace("```JSON", "```").replace("```Json", "```")
        candidates.extend(p.strip() for p in body.split("```") if p.strip())
    if "{" in raw and "}" in raw:
        candidates.append(raw[raw.find("{"): raw.rfind("}") + 1])

    for cand in candidates:
        cand = (cand or "").strip().rstrip(",")
        if not cand or not cand.startswith("{"):
            continue
        try:
            parsed = json.loads(cand)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# ================================================================ mock 解析
def _resolve_mock(mock: Any) -> Any:
    """``mock`` 可以是字面值，也可以是 callable（推迟到真正需要时才计算）。"""
    if callable(mock):
        try:
            return mock()
        except Exception as exc:  # 规则版自身出错也要能兜住，绝不 500
            print(f"[llm] 规则版生成失败：{type(exc).__name__}: {exc}")
            return {}
    return {} if mock is None else mock


def _merge(rule: Any, result: Any) -> Any:
    """合并策略：以规则版为骨架，模型结果只覆盖"有值"的字段。"""
    if not isinstance(rule, dict) or not isinstance(result, dict):
        return result if result not in (None, "", [], {}) else rule
    merged = dict(rule)
    for key, value in result.items():
        if key.startswith("_"):
            continue
        if value not in (None, "", [], {}):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    return merged


def _messages_with_system(
    messages: Sequence[dict],
    schema_hint: str = "",
    json_mode: bool = False,
) -> list[dict]:
    msgs = [dict(m) for m in messages]
    hints: list[str] = []
    if json_mode:
        hints.append("只输出一个合法 JSON 对象，不要任何解释文字、不要 Markdown 代码围栏。")
    if schema_hint:
        hints.append(f"JSON 结构要求：{schema_hint}")
    if hints:
        # 已有 system 就追加约束，没有就插到最前
        if msgs and msgs[0].get("role") == "system":
            msgs[0]["content"] = f"{msgs[0]['content']}\n\n{chr(10).join(hints)}"
        else:
            msgs.insert(0, {"role": "system", "content": chr(10).join(hints)})
    return msgs


# ================================================================ 对外能力
def chat(
    messages: Sequence[dict],
    mock: Any = None,
    temperature: float = 0.3,
    model: str | None = None,
    max_tokens: int | None = None,
) -> tuple[str, str]:
    """纯文本生成。返回 ``(文本, engine)``。"""
    if not api_ready():
        text = _resolve_mock(mock)
        return (text if isinstance(text, str) else str(text or "")), "rule"

    payload: dict[str, Any] = {
        "model": model or config.LLM_MODEL,
        "messages": _messages_with_system(messages),
        "temperature": temperature,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens

    try:
        data = _post("/chat/completions", payload)
        text = (
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
        ) or ""
        if not text.strip():
            raise LLMError("模型返回空内容")
        return text.strip(), "llm"
    except Exception as exc:
        print(f"[llm] chat 降级为规则版：{exc}")
        text = _resolve_mock(mock)
        return (text if isinstance(text, str) else str(text or "")), "rule"


def chat_json(
    messages: Sequence[dict],
    schema_hint: str = "",
    mock: Any = None,
    temperature: float = 0.2,
    model: str | None = None,
) -> tuple[dict, str]:
    """结构化生成。返回 ``(dict, engine)``。

    ``mock`` 传入业务方自己的规则版结果（dict 或可调用对象）。
    模型可用且能解析出 JSON 时，用规则版补齐缺失字段后返回。
    """
    if not api_ready():
        rule = _resolve_mock(mock)
        return (rule if isinstance(rule, dict) else {}), "rule"

    payload: dict[str, Any] = {
        "model": model or config.LLM_MODEL,
        "messages": _messages_with_system(messages, schema_hint, json_mode=True),
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    try:
        data = _post("/chat/completions", payload)
        text = ((data.get("choices") or [{}])[0].get("message", {}) or {}).get("content", "")
        parsed = _extract_json(text or "")
        if parsed is None:
            raise LLMError("模型输出无法解析为 JSON")
        return _merge(_resolve_mock(mock), parsed), "llm"
    except Exception as exc:
        print(f"[llm] chat_json 降级为规则版：{exc}")
        rule = _resolve_mock(mock)
        return (rule if isinstance(rule, dict) else {}), "rule"


def vision(
    image_b64: str,
    prompt: str,
    schema_hint: str = "",
    mock: Any = None,
    temperature: float = 0.2,
) -> tuple[dict, str]:
    """图片 + 文本。图片走 ``image_url`` 的 base64 data URI。

    未配视觉模型时**如实返回规则版**（含 ``note`` 说明），不假装解析成功。
    """
    if not api_ready() or not image_b64:
        rule = _resolve_mock(mock)
        if isinstance(rule, dict) and "note" not in rule:
            rule["note"] = "未配置视觉模型，本次未真正读图。"
        return (rule if isinstance(rule, dict) else {}), "rule"

    data_uri = image_b64 if image_b64.startswith("data:") else f"data:image/png;base64,{image_b64}"
    content = [
        {"type": "text", "text": prompt + (f"\n\nJSON 结构要求：{schema_hint}" if schema_hint else "")},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]
    payload: dict[str, Any] = {
        "model": config.LLM_VISION_MODEL,
        "messages": _messages_with_system([{"role": "user", "content": content}], json_mode=True),
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    try:
        data = _post("/chat/completions", payload)
        text = ((data.get("choices") or [{}])[0].get("message", {}) or {}).get("content", "")
        parsed = _extract_json(text or "")
        if parsed is None:
            raise LLMError("视觉模型输出无法解析为 JSON")
        return _merge(_resolve_mock(mock), parsed), "llm"
    except Exception as exc:
        print(f"[llm] vision 降级为规则版：{exc}")
        rule = _resolve_mock(mock)
        if isinstance(rule, dict) and "note" not in rule:
            rule["note"] = "视觉模型调用失败，本次未真正读图。"
        return (rule if isinstance(rule, dict) else {}), "rule"


def embed(texts: Iterable[str]) -> tuple[list[list[float]] | None, str]:
    """向量化。返回 ``(向量列表 或 None, engine)``。

    返回 ``None`` 时调用方（``services/embedding.py``）自动切换到本地哈希向量。
    """
    items = [str(t) for t in texts]
    if not items or not api_ready():
        return None, "rule"
    payload = {"model": config.EMBED_MODEL, "input": items}
    try:
        data = _post("/embeddings", payload)
        rows = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        vectors = [list(map(float, r.get("embedding", []))) for r in rows]
        if len(vectors) != len(items) or not vectors or not vectors[0]:
            raise LLMError("embeddings 返回结构异常")
        return vectors, "llm"
    except Exception as exc:
        print(f"[llm] embed 降级为本地哈希向量：{exc}")
        return None, "rule"


def describe() -> str:
    """一行人类可读的引擎描述，用于启动日志。"""
    if api_ready():
        return f"真实模型已启用（model={config.LLM_MODEL}, vision={config.LLM_VISION_MODEL}）"
    if current_mode() == "api":
        return "LLM_MODE=api 但地址/密钥不完整 → 已自动回落规则版"
    return "规则版（mock）：不联网即可完整演示，配 .env 后一行代码不用改即可切换真实模型"
