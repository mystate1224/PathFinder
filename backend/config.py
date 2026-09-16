# -*- coding: utf-8 -*-
"""config.py —— 全项目唯一读取环境变量的地方。

纪律：任何其它模块都不得直接 ``os.getenv``，一律 ``import config`` 后取属性。
这样「切到真实模型」只需要改 .env 一个文件，代码一行不动。
"""
from __future__ import annotations

import os
from pathlib import Path

try:  # .env 是可选依赖，缺失时仍能启动
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv 已在 requirements 中
    load_dotenv = None


# ---------------------------------------------------------------- 路径
def _env_path(name: str) -> Path | None:
    """读一个「目录/文件」环境变量；空值视为未设置。

    允许用相对路径，但一律相对项目根解析，避免受 cwd 影响。
    """
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return None
    p = Path(str(raw).strip()).expanduser()
    return p if p.is_absolute() else (BASE_DIR / p)


BASE_DIR = Path(__file__).resolve().parent.parent          # 项目根 D:/edu
BACKEND_DIR = BASE_DIR / "backend"
FRONTEND_DIR = BASE_DIR / "frontend"

# DATA_DIR / DB_PATH 可被环境变量覆盖 —— 冒烟测试（backend/smoke.py）靠这个
# 把数据指向临时目录，从而绝不污染开发库。
DATA_DIR = _env_path("DATA_DIR") or (BASE_DIR / "data")
UPLOAD_DIR = DATA_DIR / "uploads"
HOMEWORK_UPLOAD_DIR = UPLOAD_DIR / "homework"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = _env_path("DB_PATH") or (DATA_DIR / "pathfinder.db")

for _d in (DATA_DIR, UPLOAD_DIR, HOMEWORK_UPLOAD_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

if load_dotenv is not None:
    # 不覆盖已存在的真实环境变量，方便用 shell 临时切换
    load_dotenv(BASE_DIR / ".env", override=False)


# ---------------------------------------------------------------- 工具
def _s(name: str, default: str = "") -> str:
    """读字符串环境变量，去空白。"""
    value = os.getenv(name)
    return default if value is None or not str(value).strip() else str(value).strip()


def _f(name: str, default: float) -> float:
    try:
        return float(_s(name, str(default)))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(float(_s(name, str(default))))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 模型网关
LLM_MODE = _s("LLM_MODE", "mock").lower()
LLM_BASE_URL = _s("LLM_BASE_URL").rstrip("/")
LLM_API_KEY = _s("LLM_API_KEY")
LLM_MODEL = _s("LLM_MODEL", "gpt-4o-mini")
LLM_VISION_MODEL = _s("LLM_VISION_MODEL", "") or LLM_MODEL
EMBED_MODEL = _s("EMBED_MODEL", "text-embedding-3-small")
LLM_TIMEOUT = _f("LLM_TIMEOUT", 60.0)
LLM_RETRY = _i("LLM_RETRY", 2)          # 总尝试次数（含首次）
LLM_RETRY_WAIT = _f("LLM_RETRY_WAIT", 1.0)


# ---------------------------------------------------------------- 业务阈值
MAX_UPLOAD_MB = _i("MAX_UPLOAD_MB", 8)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
SESSION_DAYS = _i("SESSION_DAYS", 7)

# 会话签名密钥 —— 无服务器平台（Vercel）上函数实例之间不共享 /tmp，
# 存在 SQLite 里的会话会「换一个实例就掉线」。因此会话 token 改成
# 自包含签名串（见 db.make_session_token），靠这个密钥跨实例保持一致。
# 正式部署时建议在平台环境变量里换一个自己的随机串。
SECRET_KEY = _s("SECRET_KEY", "pathfinder-demo-secret-key")

# 检索相关（调参集中在此，便于统一口径）
CHUNK_SIZE = _i("CHUNK_SIZE", 400)
CHUNK_OVERLAP = _i("CHUNK_OVERLAP", 80)
PARSE_CHUNK_SIZE = _i("PARSE_CHUNK_SIZE", 800)
PARSE_CHUNK_OVERLAP = _i("PARSE_CHUNK_OVERLAP", 200)
RRF_K = _i("RRF_K", 60)

# 服务监听
HOST = _s("HOST", "127.0.0.1")
PORT = _i("PORT", 8000)


# ---------------------------------------------------------------- 自检
def snapshot() -> dict:
    """给启动日志与 /api/health 用的安全快照（**绝不包含 Key 本身**）。"""
    return {
        "llm_mode": LLM_MODE,
        "base_url": LLM_BASE_URL or "(未配置)",
        "model": LLM_MODEL,
        "vision_model": LLM_VISION_MODEL,
        "embed_model": EMBED_MODEL,
        "key_set": bool(LLM_API_KEY),
        "timeout": LLM_TIMEOUT,
        "db": str(DB_PATH),
    }
