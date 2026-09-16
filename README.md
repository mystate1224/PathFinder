# 寻径教育 PathFinder · LearnBuddy

> 面向高校的**学业—就业双轨智能导航平台**。
> 依据手写技术文档与实现流程逐步构建，可优化处已做补强。
> **无网络、无 API Key 也能完整演示全部链路。**

---

## 一、这个项目在解决什么

高校里「一个学生该往哪走」这件事，信息散落在四个地方：成绩单、兴趣自述、科研/就业倾向、企业侧的岗位与项目资源。辅导员和教师靠经验拼接，学生自己看不到全局。

PathFinder 把这些拼起来，做成一条能跑通的闭环：

```
画像（你是谁） → 匹配（去哪） → 答疑（卡住时问谁） → 资源（拿到什么练） → 作业（练得怎么样）
   ↑                                                                        │
   └──────────────────────── 结果回写进画像 ─────────────────────────────────┘
```

需要注意的一点：平台产出的**分层结论只用来决定「推荐内容的深度」与「任务难度」**，不用于分班、不构成准入门槛。这条口径写在代码里，也写在每一个展示分层的界面上（界面统一附带 `PF.caveat` 提示）。

---

## 二、三分钟跑起来

```bash
# 1. 依赖（Python 3.10+，开发环境实测 3.13 / 3.14）
pip install -r requirements.txt

# 2. 配置（可选。不配任何东西也能跑 —— 默认就是规则版）
cp .env.example .env

# 3. 启动
python backend/app.py
#   → http://127.0.0.1:8000
```

> **开发时建议加 `--reload`**：`python backend/app.py --reload`。
> 默认不带热重载，改了后端 `.py` 而不重启，页面会一直在跑旧逻辑——而且**一切看起来都正常**，
> 最难排查。一个直观的确认信号：`POST /api/selfcheck` 返回的项数会随代码变化（当前教师 14 项 / 学生 13 项）。

首次启动会自动建库、建表、灌入种子数据（3 位教师 / 15 名学生 / 4 门课 25 个知识点 / 4 个课题组 / 8 条企业资源）。

**浏览器要求**：无。原生 HTML/CSS/JS，零构建、零前端框架、零 npm。

### 切换到真实模型

只改 `.env`，**代码一行不动**：

```ini
LLM_MODE=api
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

改完重启即可。任何一个模型调用失败，都会自动回落到规则版，界面上的徽标从「AI 生成」变成「规则生成」——功能不会中断。

### 部署到 Vercel（线上演示）

仓库里已经带好了部署适配层（`api/index.py` + `vercel.json`），把仓库导入 Vercel 即可：

1. 仓库推到 GitHub（`api/index.py` 是 Serverless 入口，`vercel.json` 把全部路由交给 FastAPI）；
2. Vercel 控制台 **Add New → Project**，导入该 GitHub 仓库，**不需要改任何设置**，直接 Deploy；
3. 部署完成后拿到 `https://xxx.vercel.app` 链接，账号与本地一致（`teacher` / `stu01`，密码 `123456`）。

**平台差异（无服务器架构决定的，提前说明）**：

* Vercel 函数的代码目录只读，SQLite 自动落到 `/tmp`（`api/index.py` 里通过 `DATA_DIR` 环境变量切换，后端代码零改动）；
* **登录会话是自己签名的 token**（`v2.<用户id>.<过期时间>.<HMAC 签名>`，见 `db.make_session_token`），
  不依赖数据库，因此**跨实例、跨冷启动都不会掉线**；正式部署可在环境变量里换一个自己的 `SECRET_KEY`；
* 实例回收后 `/tmp` 清空，下次冷启动由 lifespan 自动重建种子数据——**线上永远是干净的初始演示数据**；
* 上传的素材、聊天记录、作业提交在实例回收后不保留（演示口径，不是数据丢失 bug）；
* 从旧版本升级上来时，浏览器里的旧格式 cookie 会失效，**重新登录一次**即可；
* 若在 Vercel 环境变量里配置了 `LLM_*`，线上同样切真实模型；不配就是规则版，**零 Key 也能跑**。

需要数据持久化的正式部署，建议换长驻进程平台（Render / Railway / Fly.io，`python backend/app.py` 直接跑），或把 SQLite 换成 Turso / Postgres。

---

## 三、账号

密码统一 `123456`。

| 用户名 | 姓名 | 角色 | 行政班 | 说明 |
|---|---|---|---|---|
| `teacher` | 张明远 | 教师 | CS2301 | 主演示账号，课题组与资源最全 |
| `teacher2` | 李文静 | 教师 | CS2302 | |
| `teacher3` | 王海涛 | 教师 | AI2301 | |
| `stu01` | 陈嘉禾 | 学生 | CS2301 | 学业型 · A 级，推荐链路主演示 |
| `stu02` | 林思远 | 学生 | CS2301 | 学业型 · A 级 |
| `stu04` | 周雨桐 | 学生 | CS2301 | 事业型 · B 级，对比用 |
| `stu09` ~ `stu15` | — | 学生 | CS2302 / AI2301 | 跨班对照 |

> 两个班级口径不要混淆：
> `users.class_id` 是**行政班**（班级总览、匹配打分范围用它）；
> `users.class_name` 是**教学班**（作业分发用它）。

---

## 四、核心设计一：双引擎 + 规则兜底

这是整个项目的地基，也是唯一一条「不许破例」的纪律：

```python
data, engine = llm.chat_json(messages, schema_hint=..., mock=rule_result)
# engine == "llm"  → 界面徽标「AI 生成」
# engine == "rule" → 界面徽标「规则生成」
```

要点：

1. **规则版不是占位符**。它用真实算法（分层规则、BM25 检索、要点匹配计分）算出**结构完全一致**的结果，所以断网演示时界面不会空着。
2. **`mock=` 是必填参数**。任何一个模型调用都必须给出规则兜底，否则代码层面就过不去。
3. **失败即降级，不抛网络细节**。统一 2 次重试 → 收敛为 `LLMError` → 回落规则版。JSON 解析不出来等同于调用失败。
4. **合并补齐**。模型返回缺字段时，用规则版对应字段补上，不让半成品流进业务层。
5. **engine 一路透传到前端**。所有模型能力的结果里都带 `engine`，前端 `PF.engineBadge()` 常显，用户永远知道这条结论是怎么来的。

---

## 五、核心设计二：自研同构，不用 LangChain

技术上刻意**不引入 LangChain**——它的抽象层会掩盖掉「模型失败时怎么办」这个本项目的核心命题。但保留它的分层思想，用约 400 行自研代码同构等价：

| LangChain 概念 | 本项目实现 | 位置 |
|---|---|---|
| `ChatOpenAI` | 统一 HTTP 出口（含超时/重试/JSON 抽取） | `backend/llm.py` |
| `with_fallbacks` | `mock=` 参数 + 逐级降级 | `backend/llm.py` |
| `ChatPromptTemplate` | `tutor.system_prompt()` 按画像拼装 | `services/tutor.py` |
| `JsonOutputParser` | `llm._extract_json()`（容忍 ```json 包裹与前后噪声） | `backend/llm.py` |
| `EnsembleRetriever` | `retriever.hybrid_search()` | `services/retriever.py` |
| `RunnableWithMessageHistory` | `db.recent_chat()` 取最近 4 轮 | `backend/db.py` |

自研反而换来了两个 LangChain 给不了的东西：**降级路径是类型系统逼出来的**（不给 `mock` 就调用不了），以及**零框架依赖**（`requirements.txt` 只有 7 个包）。

### 检索是怎么做的

```
                ┌── BM25（SQLite FTS5 + trigram 分词器）──┐
query ──────────┤                                          ├── RRF 融合(k=60) ── 重排 ── top-N
                └── 向量余弦（本地 3-gram md5 哈希 1024 维）─┘
```

- **FTS5 不可用时自动降级为 LIKE**（`db.FTS_OK` 标记），启动日志会明确打印。
- **没有 embedding API 时的向量兜底**：本地字符 3-gram + md5 哈希 → 1024 维 → L2 归一化。它不是语义向量，但足够在演示中体现「双路召回 + RRF 融合」的完整链路。
- 检索到的切片带 `via` 字段（`bm25` / `vec` / `bm25+vec`），界面上能看到每条命中是被哪一路召回的。

---

## 六、五条业务链路 × 六大能力

### 五条链路与页面对照

| 链路 | 干什么 | 页面 | 主要接口 |
|---|---|---|---|
| **A · 画像** | 学业/事业倾向判定、等级评定、能力雷达、成长路线 | `/student`、`/teacher` | `/api/student/profile`、`/api/teacher/overview` |
| **B · 匹配** | 课题组双向推荐与确认 | `/match` | `/api/match/recommend`、`/api/match/decide` |
| **C · 答疑** | 按画像分层回答，带引用来源 | `/ask`、`/tutor` | `/api/tutor/ask`、`/api/teacher/copilot/ask` |
| **D · 资源** | 素材解析入库 + 企业资源广场与申请 | `/library`、`/resources`、`/hub` | `/api/materials/*`、`/api/resources/*` |
| **E · 作业** | 发布 → 提交 → AI 建议分 → 教师定分 → 导出 | `/homework`、`/grade` | `/api/teacher/homework/*`、`/api/homework/*` |

### 六大能力落地位置

| # | 能力 | 页面 | 说明 |
|---|---|---|---|
| ① | 图文素材智能解析 | `/library` | 支持 md/txt/pdf/png/jpg；无视觉模型时图片降级为「需人工批改」 |
| ② | 知识点结构化抽取 | `/library` | 解析结果落 `knowledge_points` 表，按课程聚合视图 |
| ③ | 交互式分层答疑 | `/ask` | 同一问题，A 级 / B 级 / C 级拿到的回答深度不同；必带检索引用 |
| ④ | 教师备课（教案 / PPT） | `/teach` | 纯标准库 `zipfile` + 手写 OOXML 生成**真实可打开**的 `.docx` / `.pptx` |
| ⑤ | 作业智能批改 | `/grade` | 试批（自由文本）+ 批量批改 + 缺交记零 + CSV 导出 |
| ⑥ | 教师 Copilot | `/tutor` | 意图路由：`lesson` / `explain` / `student` 三类，分别走不同服务 |

### 六格矩阵

主标签（学业型 / 事业型）× 等级（A / B / C）= 6 格，每格对应一套答疑风格与教案取向：

| | A 级 | B 级 | C 级 |
|---|---|---|---|
| **学业型** | 科研拔高 | 学业强化 | 基础夯实 |
| **事业型** | 工程进阶 | 实践导向 | 技能起步 |

---

## 七、目录结构

```
D:/edu
├── backend/
│   ├── app.py            FastAPI 路由层（只做 鉴权→取参→调services→包装响应）
│   ├── config.py         ★ 全项目唯一读环境变量的地方，其它模块禁止 os.getenv
│   ├── db.py             SQLite(WAL) + FTS5 + 连接管理 + 会话
│   ├── llm.py            ★ 全局唯一模型出口（双引擎骨架）
│   ├── seeds.py          种子数据
│   ├── smoke.py          全链路冒烟测试（用临时数据目录，不污染开发库）
│   └── services/         业务规则全在这里（19 个模块）
│       ├── stratify.py     分层引擎（六格矩阵）
│       ├── retriever.py    混合检索 BM25 + 向量 + RRF
│       ├── embedding.py    向量兜底（3-gram md5 哈希）
│       ├── extract.py      素材解析 + 知识点抽取
│       ├── tutor.py        分层答疑
│       ├── teaching.py     备课（教案/PPT）
│       ├── office.py       OOXML 生成（手写 docx/pptx）
│       ├── homework.py     作业闭环
│       ├── resources.py    资源广场
│       ├── matcher.py      课题组匹配 + 增删改
│       ├── copilot.py      教师 Copilot
│       ├── dashboard.py    班级学情
│       ├── mylibrary.py    我的素材
│       ├── planner.py      成长路线
│       ├── taxonomy.py     方向/课程/资源类型字典
│       └── tasks.py        成长任务
├── frontend/
│   ├── css/style.css     单一设计系统（288 个 class，无框架）
│   ├── js/common.js      唯一全局 window.PF（45 个成员 / 45 个图标）
│   ├── js/tabs.js        页签容器
│   └── *.html            12 个页面（登录 + 11 个业务页）
├── samples/              演示素材 + 说明（手工演示上传解析用）
├── tools/check_frontend.py  前端静态体检（见下节）
├── tools/browser_sweep.sh   浏览器级巡检（见下节）
├── data/                 运行期数据（SQLite / 上传文件 / 导出，已 gitignore）
├── .env.example
└── requirements.txt      只有 7 个依赖
```

**分层纪律**：路由层不写业务规则，业务层不碰 HTTP，模型调用只发生在 `llm.py` 与 `services/` 内。

---

## 八、验证：四道关卡

> 从「接口能不能通」到「页面能不能用」，逐层加严。每一道都抓到过前一道看不见的问题。

### 1. 全链路冒烟测试

```bash
python backend/smoke.py
```

会拉起一个临时服务（随机端口）+ **临时数据目录**，跑完自动清理，绝不碰开发库。当前结果：

```
结果：41/41 全部通过 —— 无 API Key 也能完整演示。
```

覆盖：教师端 18 项、学生端 16 项、权限边界 6 项。包括完整的
「发布作业 → 学生提交带附件 → AI 建议分 → 教师定分 → 缺交记零 → CSV 导出 → 删除」
和「新建课题组 → 改名/改方向/改名额 → 重名与空名被拒 → 删除」。

### 2. 运行时自检

登录后调用 `POST /api/selfcheck`（教师 14 项 / 学生 13 项），逐项返回 `detail`。任一项失败会告诉你具体原因。

```bash
# 先登录拿 Cookie（-c 写出），再复用（-b 读出）
curl -s -c cookies.txt -X POST -H "Content-Type: application/json" \
     -d '{"username":"teacher","password":"123456"}' http://127.0.0.1:8000/api/auth/login
curl -s -b cookies.txt -X POST http://127.0.0.1:8000/api/selfcheck
```

> 刻意写成 POST：它会在服务端现场跑一遍完整链路（含建一个临时课题组再删掉），**不是幂等的读操作**。

### 3. 前端静态体检（无需浏览器）

```bash
python tools/check_frontend.py
```

对 12 个页面做三件事：
- 抽出每个内联 `<script>` 用 `node --check` 校验语法
- 扫描 `PF.xxx` 调用，比对 `common.js` / `tabs.js` 真实导出的成员（45 个）
- 扫描 `class="..."`，比对 `style.css`（288 个）+ 页面自带 `<style>` 的定义

当前结果：**全部通过**。

### 4. 浏览器级实测（真实点击）

```bash
bash tools/browser_sweep.sh 8123
```

脚本会临时拉起一个独立服务（默认 `:8123`，用完即关，不碰开发库）、真实登录、
逐页读取真实 DOM，最后打印每页一行：

```
/teacher -> "/teacher | len=1101 cards=6 tabs=3 bad=0"
/ask     -> "/ask | len=1519 cards=4 tabs=0 bad=0"
...
全部页面通过：路径正确、内容已渲染、无异常字样
```

每页看四件事：**落在哪个路径**（登录后是否落到预期首页、有没有被意外重定向）、
`innerText` 长度（0 或极短 = 白屏）、`.card`/`.tab`/`.empty` 容器数量、
以及正文里有没有 `读取失败` / `undefined` / `NaN` / `[object Object]` 这类泄漏。

需要 `agent-browser`（见 `tools/browser_sweep.sh` 顶部注释）；没装时脚本会自行跳过，不阻断流程。
当前结果：**教师 8 页 + 学生 6 页，全部 bad=0**。

再手工走一遍交互链路（脚本只做页面级探针，不做点击）：
教师登录跳转 `/teacher` → `/match` 渲染候选人卡片（含引擎徽标「规则生成」与「不用于分班」声明）
→ 切「课题组管理」页签 → 点「新建课题组」弹窗正常打开。

> **为什么需要这道关卡。** 前三道关卡都是「HTTP 层面的绿灯」——只验证返回码和 JSON 结构，
> 对**跑在浏览器里的 JS 是否真的执行成功一无所知**。这道关卡一共抓到 4 个前三道必然漏掉的真实缺陷：
>
> | 缺陷 | 症状 | 根因 |
> |---|---|---|
> | `grade.html` 两处引号不闭合 | 整个 `<script>` 块解析失败，批改区空白 | 字符串单引号开头、双引号结尾 |
> | 登录页无限自我重定向 | 每 700ms 重载一次，账号密码永远填不进去（日志 252 次 `/api/auth/me` 401） | `PF.api` 收到 401 就无条件跳 `/login`，而登录页自己正是靠这个 401 判断「当前未登录」 |
> | `match.html` 头部按钮点了没反应 | 「新建课题组」弹窗不弹 | 页面头部 `actions` 渲染在 `#view` **之外**，`PF.$(sel, view)` 取不到 |
> | `match.html` 姓名读成「林林思远」 | 头像首字与姓名无分隔 | 头像缺 `aria-hidden` |
>
> 结论：**页面返回 200 ≠ 页面能用。** 前端至少要有一道能看到真实 DOM 的关卡。

---

## 九、配置项（`.env`）

| 键 | 默认 | 说明 |
|---|---|---|
| `LLM_MODE` | `mock` | `mock` 规则版 / `api` 真实模型 |
| `LLM_BASE_URL` / `LLM_API_KEY` | 空 | 两项都非空且模式为 `api` 才走真实模型 |
| `LLM_MODEL` | `gpt-4o-mini` | |
| `LLM_VISION_MODEL` | 同 `LLM_MODEL` | 留空则图片走降级 |
| `EMBED_MODEL` | `text-embedding-3-small` | |
| `LLM_TIMEOUT` / `LLM_RETRY` / `LLM_RETRY_WAIT` | `60` / `2` / `1.0` | |
| `MAX_UPLOAD_MB` | `8` | |
| `SESSION_DAYS` | `7` | |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `400` / `80` | 检索切片 |
| `PARSE_CHUNK_SIZE` / `PARSE_CHUNK_OVERLAP` | `800` / `200` | 解析切片 |
| `RRF_K` | `60` | RRF 融合常数 |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | |
| `DATA_DIR` / `DB_PATH` | 空 | 留空用 `data/`；冒烟测试靠它指向临时目录 |

---

## 十、诚实的局限

写出来比藏起来好。

1. **等级评定是规则算出来的，不是模型评的**。`stratify.py` 按成绩 + 科研/就业倾向得分落格。它可解释、可复现，但不要当成教育学意义上的科学测评。
2. **向量检索默认不是语义向量**。没有 `EMBED_MODEL` 可用时，走的是字符 3-gram 哈希。想看真正的语义召回，请配 `LLM_MODE=api`。
3. **图片解析依赖视觉模型**。未配置 `LLM_VISION_MODEL` 时，图片素材会被标记为「需人工批改」，并且**不生成**知识点——这是有意的降级，不是 bug。
4. **批改建议分不是评分权威**。它对的是「评分要点命中度」，教师定分才是最终结果。界面上一贯以「建议分」措辞。
5. **鉴权是演示级的**。`pwd_hash` 用的是项目内实现的哈希，会话是 SQLite 里的一行记录。上生产要换成成熟的认证方案。
6. **PPT 是内容大纲，不是设计稿**。纯标准库生成 OOXML，样式朴素，胜在**真能打开、真能编辑**，不依赖任何 Office 组件。

---

## 十一、界面设计系统（UI/UX v2）

界面经过一次完整的 UI/UX 重构，目标是「成熟 SaaS 产品的观感」，约束是**不碰任何业务逻辑**。

### 设计令牌（`frontend/css/style.css` 顶部 `:root`）

| 类别 | 说明 |
|---|---|
| 品牌色 | 晴空蓝 `--brand-500:#3a72c4`（HSL 215,54%,50%），10 级色阶 50→800；v2.2 从 196° 雾青蓝整体提亮转蓝，更明亮但仍克制 |
| 副强调 | 淡靛 `--accent-500:#6b78c9`，只用于第二层级信息与「学业型」轨道 |
| 语义色 | `--ok-500 / --warn-500 / --danger-500 / --info-500`，统一降饱和 |
| 中性色 | 中性雾灰 12 级 `--ink-950 … --ink-50`，无蓝紫偏色 |
| 表面 | `--bg / --surface / --surface-2 / --surface-3 / --surface-glass` |
| 圆角 | `--r-xs:6 → --r-xl:22 → --r-pill:999`，6 级 |
| 阴影 | `--sh-1 → --sh-4`，不透明度压在 3%~12%，靠扩散半径拉层次 |
| 字号 | 收敛到 6 级：`--fs-display:30 / --fs-h1:22 / --fs-h2:17 / --fs-h3:15 / --fs-body:14 / --fs-sm:13 / --fs-xs:12` |
| 间距 | `--s-1:4 → --s-9:56`，8px 基准栅格 |
| 动效 | `--dur-1:120 / --dur-2:180 / --dur-3:240 / --dur-4:380`（ms）+ `--ease-out / --ease-in-out / --ease-soft` |

**关键约定**：所有变量名与 class 名**保持向后兼容**，12 个页面零改动即可受益。历史上 `match / resources / hub / homework` 各写一套的卡片（`.mk-card / .res-card / .hub-card / .hw-card`）已合并进全局样式表，类名一个没删。

### 动效层（`frontend/js/common.js`）

四条自我约束（改之前先读）：

1. **只动 `opacity` 与 `transform`**，不碰 `width/height/margin` 等布局属性；
2. 时长封顶 400ms，缓动一律快起慢收；
3. 命中 `prefers-reduced-motion: reduce` 时**整个 `MutationObserver` 根本不安装**；
4. 元素**默认可见**，动画只是 JS 参与时额外加的入场效果 —— JS 挂掉、浏览器不支持、用户开了减少动效，三种情况页面都完整可用。

对外只有两个入口：`PF.reveal(scope)`（手动触发）与自动观察 `document.body` 的子树变化。数字滚动只改文本节点、进度条/分数环走两次 `requestAnimationFrame`（不用 `void el.offsetWidth` 强制同步布局），可见性判定「先读后写」，避免 N 次同步布局。

### 无障碍

- `PF.shell()` 顶部注入 `.skip-link`「跳到主要内容」，`<main id="pf-main" tabindex="-1">` 可聚焦
- 导航当前项带 `aria-current="page"`；移动端抽屉按钮带 `aria-expanded` / `aria-controls`
- 标签条按 ARIA tabs 模式实现：`←/→/Home/End` 移动并激活，roving `tabindex`
- `PF.modal()` 有焦点陷阱与焦点归还（关闭后焦点回到触发元素），带 `role="dialog"` / `aria-modal` / `aria-label`
- 移动端触控目标一律补到 32px 以上（`.btn` 38px / `.input` 40px / `.nav-item` 11px 内边距）

### 零新增依赖

仍然是原来 7 个 Python 依赖，**零 npm、零前端构建、零网络字体**。所有动效都是原生 CSS + 原生 JS；无法访问外网时视觉表现完全一致。

### UI/UX v2.1：暗色主题、主题切换与移动端贴底操作条

在 v2 令牌化基础上新增的一轮纯前端打磨，**零业务代码改动、零 class 删除**。

#### 暗色主题

- 使用单一开关 `html[data-theme="dark"]`，而不是 `@media (prefers-color-scheme: dark)`，避免手动切换与系统偏好打架。
- 所有页面 `<head>` 里插入了一段不依赖外部文件的引导脚本，抢在首帧渲染前写入 `data-theme`，防止暗色偏好下先闪一帧浅色。
- 新增专用「反相块」令牌 `--code-bg/--code-fg`、`--solid-bg/--solid-fg`，把代码块、`.skip-link` 等「浅色下深底、暗色下浅底」的元素从墨阶倒转中解耦，避免暗色下变白底白字。
- 组件级覆盖集中在 `style.css` 第 20 节，覆盖侧边栏、顶栏、Toast、统计图标、空状态、登录页品牌区等 30 余处细节。

#### 主题切换

- `PF.theme` 模块（`common.js`）管理 `localStorage` 记忆、系统偏好监听、顶栏按钮状态同步。
- 顶栏右侧出现太阳/月亮图标按钮；登录页单独放了一个浮动主题按钮（登录页没有顶栏）。
- `window.PF` 成员从 47 个增至 48 个；`tools/check_frontend.py` 的交叉校验同步更新。

#### 移动端贴底操作条

- 原来的 `.fab-bar` 在 v2 中是全站未引用的死代码；v2.1 改为 `PF.shell({ dock: true })` 的 opt-in 能力。
- 命中 `max-width: 620px` 时，`.page-head__actions` 被动态加上 `.fab-bar`，贴底悬浮并留出安全区 `env(safe-area-inset-bottom)`。
- 为避免 `.page-head` 的入场位移动画把 fixed 子元素钉在错误位置，手机端 `.page-head.anim-in` 改为仅淡入。
- 当前只在**资源管理页**启用（该页列表很长，发布按钮贴底可提升拇指可达性）。其余页面的主操作仍在卡片体内，暂未迁移。

#### v2.1 验证结果

| 检查项 | 结果 |
|---|---|
| `tools/check_frontend.py` | 12/12 通过（390 个 class、48 个 `PF` 成员交叉校验） |
| `backend/smoke.py` | 41/41 通过 |
| `bash tools/browser_sweep.sh` | 教师 8 页 + 学生 6 页，全部 `bad=0` |
| `POST /api/selfcheck` | 教师 14/14、学生 13/13 |
| 真实浏览器明暗双主题抽查 | 登录页、教师驾驶舱、资源、备课、匹配 明暗均正常；移动端 390px 无横向溢出；贴底条距底 12px 生效 |

### UI/UX v2.2：浅色提亮转蓝 + 导航滑动指示器

在 v2.1 基础上的又一次纯视觉打磨，**零业务代码改动、零 class 删除**。

#### 浅色主题提亮、更蓝

- 品牌色从 196°「雾青蓝」`#3b82a0`（S 46%）转到 215°「晴空蓝」`#3a72c4`（S 54%），幅度克制但视觉明显更亮、更蓝。
- `--bg` 从 `#f4f7fa` 提亮到 `#f6f9fd`，`--surface-2/3` 与 `--border` 同步带一点蓝调；浅色端墨阶（`--ink-50 … --ink-300`）也做了微蓝偏移。
- 暗色主题同步把品牌色阶提到同源蓝色，保持亮/暗同源，而非暗色继续留在旧青色。
- 全站 16 处 `rgba(59, 130, 160, …)` 字面量已随新品牌色全部更新为 `rgba(58, 114, 196, …)`。

#### 导航滑动选中效果

- 多页应用没有单页路由的「滑动指示器」，于是做了一层跨页等价物：切换页面时，`.nav-glider` 底光从**上一页选中项的位置**滑动到当前选中项。
- 实现依赖 `sessionStorage` 记住上一页 `.nav-item.is-active` 的 `offsetTop`，落地后由 JS 移除，落点样式与 `.is-active` 常态逐像素一致。
- 滑块存在期间，当前项的自身底光让位给滑块，左侧「路标」光条同步生长动画；结束后再恢复常态，避免二次跳变。
- 尊重 `prefers-reduced-motion: reduce`：JS 根本不创建滑块，CSS 也已被 reduced-motion 媒体查询压缩为瞬间完成。

#### v2.2 验证结果

| 检查项 | 结果 |
|---|---|
| `tools/check_frontend.py` | 12/12 通过（392 个 class、48 个 `PF` 成员交叉校验） |
| `backend/smoke.py` | 41/41 通过 |
| `bash tools/browser_sweep.sh` | 教师 8 页 + 学生 6 页，全部 `bad=0` |
| `POST /api/selfcheck` | 教师 14/14、学生 13/13 |
| 浅色新配色抽查 | 教师驾驶舱、资源管理页均更亮更蓝，无旧青色残留 |
| 滑块效果验证 | 真实页面导航中 `sessionStorage` 记录到 `created 78->278`，慢速版测试截图抓到滑块中飞状态 |

---

## 十二、相关文档

- `samples/README.md` —— 每份演示素材对应哪个页面、哪个能力，以及手工演示的推荐路径
- `data/smoke.log` —— 最近一次冒烟测试的完整输出
- `.env.example` —— 与 `backend/config.py` 全字段一致的配置模板

---

_本项目为「寻径教育 PathFinder」的技术复现实现，用于教学演示与技术验证。_
