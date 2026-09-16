# -*- coding: utf-8 -*-
"""errors.py —— 业务异常的共同父类。

为什么需要它：路由层要能把 services 抛出的异常翻译成合适的 HTTP 状态码。
"资源不存在" 该是 404，"该学生尚未提交，无法给出建议分" 该是 400 —— 如果都
当成 400，前端就没法区分"你参数错了"和"这东西真的没有"。

约定：``status`` 就是期望的 HTTP 状态码，缺省 400。
"""
from __future__ import annotations


class ServiceError(ValueError):
    """所有业务异常的共同父类（继承 ValueError，兼容旧的捕获写法）。

    * 默认 ``status = 400``：入参不合法、业务规则不允许。
    * 目标对象不存在时传 ``status=404``，前端据此展示"没有找到"的空态。
    """

    status = 400

    def __init__(self, message: str = "", status: int | None = None) -> None:
        super().__init__(message or "请求失败")
        if status is not None:
            self.status = int(status)
