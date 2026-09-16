# -*- coding: utf-8 -*-
"""Vercel Serverless 入口。

Vercel 的 Python 运行时把 ``api/*.py`` 视为函数文件：导出的 ASGI 对象
``app`` 会被运行时接管，配合 vercel.json 的 catch-all 路由，
所有请求（页面 + /api/*）都由 backend/app.py 里的 FastAPI 处理。

与本地开发的两个关键差异，都在这里兜住：

1. **代码目录只读** —— Vercel 函数的部署目录是只读文件系统，
   SQLite / 上传文件必须落到可写层 ``/tmp``。通过环境变量
   ``DATA_DIR=/tmp/pf-data`` 切换（config.py 原生支持该变量，
   后端代码一行不用改）。注意必须在 import app **之前**设置，
   因为 config 在导入期就解析并创建目录。

2. **冷启动即建库播种** —— 实例回收后 /tmp 数据清空，下次冷启动
   由 lifespan 自动重建种子数据（3 位教师 / 15 名学生等）。
   演示口径：大家点开链接看到的永远是干净初始数据；
   上传的素材、聊天记录、作业提交在实例回收后不保留。
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 只读文件系统兜底：Vercel Serverless 部署目录是只读文件系统，
# SQLite / 上传文件必须落到可写层 /tmp。用强制赋值而非 setdefault，
# 避免平台已存在空值/默认值导致兜底失效。
os.environ["DATA_DIR"] = "/tmp/pf-data"

from app import app  # noqa: E402,F401  backend/app.py 的 FastAPI 实例
