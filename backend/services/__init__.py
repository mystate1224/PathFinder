# -*- coding: utf-8 -*-
"""services —— 业务服务层。

分层纪律：
* ``app.py`` 只做「注册路由 / 托管静态页 / 管理生命周期」三件事；
* 所有业务规则在 ``services/``；
* 所有 SQL 语句在 ``db.py``（此处只调用它提供的通用读写函数）。

导入约定：``app.py`` 会把 ``backend/`` 加入 ``sys.path``，因此包内模块统一写成
``import db`` / ``import llm`` / ``from services import xxx``。
"""
