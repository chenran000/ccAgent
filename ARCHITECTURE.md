# TestAssistant AI — 架构文档

## 项目概述

基于多平台大模型的**软件测试 AI Agent 平台**。核心是一个 LangGraph 状态机驱动的 Web 自动化测试 Agent(DOM 文本感知、确定性断言、检查点持久化、人工确认修复、探索产物沉淀),配合五类意图路由的统一对话入口、Instructor 结构化输出、分块/阈值/重排的 RAG 知识库,以及完整的 React 前端。

数据按用户隔离:业务库、向量集合、上传目录、登录态、测试任务均绑定 user_id。

## 目录结构

```
ccAgent-featureGli/
├── main.py                     # FastAPI 入口(uvicorn + CORS 白名单)
├── requirements.txt            # Python 依赖(含 langgraph/instructor/langfuse)
├── .env                        # 环境变量(密钥留空可自动生成)
├── ARCHITECTURE.md             # 本文档
│
├── app/                        # 后端
│   ├── config.py               # 配置:端口/JWT/CORS/路径/EMBEDDING_MODEL/RAG_*/TEST_AGENT_VISION
│   ├── database.py             # SQLAlchemy + SQLite(app.db)
│   ├── models.py               # ORM:User/Session/Conversation/ModelConfig/UserActiveModel/Document/ProjectFolder
│   ├── auth.py                 # JWT + bcrypt
│   ├── schemas.py              # Pydantic 请求/响应模型
│   ├── routes.py               # 全部 HTTP/SSE 接口 + SSE 事件编排
│   ├── llm.py                  # ★ 统一 LLM 客户端 + Instructor 结构化输出 + 9 个输出契约
│   ├── prompts.py              # 8 套提示词(与输出契约一一对应)
│   ├── intent_classifier.py    # 意图识别(本地关键词规则 + AI 结构化分类)
│   ├── test_agent_graph.py     # ★ LangGraph 测试状态机(init/test_step/analyze_issue/finalize/await_fix)
│   ├── test_engine.py          # 测试 Agent 的 AI 调用层(单步决策/错误定位)
│   ├── browser_capture.py      # Playwright 工具层:截图、错误收集、元素索引、页面摘要、storage_state
│   ├── code_analyzer.py        # AI 补丁生成 + 路径围栏写盘(.bak 备份)
│   ├── script_generator.py     # ★ 轨迹 → 可回放 Playwright 脚本 + 结构化测试报告
│   ├── analysis_service.py     # Bug枚举分析 / 测试用例生成 / 代码审查(含 RAG 知识检索)
│   ├── vector_db.py            # ChromaDB + 中文分块/阈值过滤/CrossEncoder重排
│   ├── file_parser.py          # PDF/TXT 文本提取
│   ├── file_storage.py         # 上传文件存储
│   └── file_viewer.py          # 文件预览(文本/图片/二进制识别)
│
├── frontend-react/             # React 18 + TypeScript + Vite + Tailwind
│   └── src/
│       ├── components/         # IDELayout/Sidebar/ChatPanel/TestRunCard/KnowledgePanel/ModelPanel
│       ├── lib/                # types.ts + api.ts(类型化 API + POST SSE 流解析)
│       ├── context/AuthContext.tsx
│       └── pages/LoginPage.tsx
│
├── data/
│   ├── app.db                  # 业务 SQLite
│   ├── checkpoints.db          # LangGraph 任务检查点
│   ├── .jwt_secret             # 自动生成的 JWT 密钥(未显式配置时)
│   └── storage_states/{uid}/   # 登录态档案(storage_state)
├── knowledge_base/             # ChromaDB 持久化(按用户分集合)
├── project_uploads/{uid}/      # 用户上传的被测项目
└── frontend/                   # 前端构建产物(npm run build 输出,后端服务首页)
```

## 分层架构

```
┌────────────────────────────────────────────────────────────────┐
│ 前端   React 三视图(对话/知识库/模型),聊天视图常驻保留状态      │
├────────────────────────────────────────────────────────────────┤
│ 接入层  routes.py — REST + SSE,全部鉴权、按用户隔离            │
├────────────────────────────────────────────────────────────────┤
│ 编排层  test_agent_graph.py — LangGraph 状态机(每步 checkpoint)│
│         routes /chat/stream — 五类意图路由 + 流式对话           │
├────────────────────────────────────────────────────────────────┤
│ AI层   llm.py — Instructor 结构化输出(TOOLS→JSON→纯文本回退)   │
│         test_engine.py — 决策/定位提示词组装                    │
│         analysis_service.py — Bug分析/用例生成/代码审查          │
├────────────────────────────────────────────────────────────────┤
│ 工具层  browser_capture.py — Playwright(元素索引/摘要/登录态)   │
│         code_analyzer.py — 补丁生成 + 路径围栏写盘              │
├────────────────────────────────────────────────────────────────┤
│ 存储层  app.db + checkpoints.db + ChromaDB + storage_states    │
├────────────────────────────────────────────────────────────────┤
│ 安全    JWT自动密钥/路径围栏/Key掩码/zip-slip防护/项目路径白名单 │
│ 观测    Langfuse 可选全链路追踪(LANGFUSE_* 三项配置即启用)     │
└────────────────────────────────────────────────────────────────┘
```

## AI 调用规范(全项目唯一通道 `app/llm.py`)

- 多平台:DeepSeek/OpenAI/通义千问/Kimi/智谱/自定义,均走 OpenAI 兼容协议,`base_url` 可覆盖;模型按用户配置于 `model_configs` 表
- 自由文本/流式 → `build_plain_client`;结构化输出 → `create_structured`(Instructor,格式错误自动重试,端点不支持函数调用时 TOOLS→JSON→纯文本三级回退)
- 输出契约与提示词一一对应:

| 契约 | 提示词 | 用途 |
|---|---|---|
| TestStepDecision | TEST_AGENT_PROMPT | 测试单步决策(11 种动作) |
| CodeIssueAnalysis | CODE_ANALYSIS_WEB_PROMPT | 错误定位到文件/行号 |
| CodeFixResult | CODE_FIX_PROMPT | 修复补丁 |
| BugAnalysis | BUG_ANALYSIS_PROMPT | Bug 三维度枚举分析 |
| TestCaseSet | TEST_CASE_PROMPT | 测试用例生成 |
| CodeReview | CODE_ANALYSIS_PROMPT | 代码审查 |
| (内联) | KNOWLEDGE_QA_PROMPT | RAG 问答 |

## Web 测试 Agent(LangGraph 状态机)

```
init(校验配置,RAG 检索业务知识增强测试目标,记录 started_at)
  ↓
test_step ⟲ 每步一次 checkpoint:
  截图(仅视觉模式)+ 页面结构摘要 + 可交互元素列表(≤60,视口优先,编号定位)
  → AI 决策 → 重复动作防护(与上一步相同则跳过)→ 执行
  → Console/Network 错误收集 → astream(updates) → SSE "step" 事件
  视觉模式下截图落盘归档;成功操作采集稳定定位(data-testid>id>name>placeholder>aria-label>text)
  ↓ 出错分支
analyze_issue:AI 定位代码文件+行号 → code_issues
  ↓
finalize:保存登录态(storage_state 档案)→ 关浏览器 → 沉淀产物:
  test_recordings/test_{id}.py   可回放 Playwright 脚本(回归零 token)
  test_recordings/report_{id}.md 结构化报告(断言通过率/步骤/问题/耗时)
  ↓ 有 code_issues
await_fix:interrupt() 暂停 → /test/code/fix 逐个确认 → AI 补丁自动写盘(.bak 备份,路径围栏内)→ END
```

**动作集(11)**:`click / fill / navigate / wait / press / assert(可见性) / assert_text / assert_url / extract_value / scroll / done`。
确定性断言(assert_text/assert_url)由 Playwright 代码判定,是测试结论的事实依据;`done.success` 仅为 LLM 总结。

**感知模式**:默认 DOM 文本感知(结构摘要+元素列表,兼容纯文本模型,成本约视觉模式 1/3~1/5);`use_vision` 开启后携带截图(视觉类问题),API 不支持图片时自动回退文本。

**状态与生命周期**:`running → completed / awaiting_fix / cancelled / failed`;服务重启后未结束任务标记 `interrupted`,`POST /test/resume/{id}` 从最后检查点恢复(浏览器重建,状态不丢)。停止为协作式(下一步骤边界生效)。

**RAG 增强**:init 时检索用户知识库,业务知识(超时规则/预期文案)拼入每个测试目标作为断言依据;检索失败不阻断任务。

## 统一对话入口(/chat/stream,SSE)

```
输入(+可选文件引用) → RAG 检索注入(use_rag 开关)
→ classify_intent_local 本地关键词意图识别 → 五路分发:
  web_test  → 测试状态机(SSE 实时步骤/代码问题/确认修复)
  code      → Bug 枚举分析(原始输入,结果单事件返回)
  case      → 测试用例生成(检索知识库业务知识,注入参考)
  knowledge → 提取"记住:xxx"正文 → 分块入库
  chat      → LLM 流式(10 轮上下文)
→ 对话落库 conversations 表(module 区分)
```

## RAG 管线(vector_db.py)

- **入库**:中文友好分块(段落/句子边界,目标 500 字符,超长硬切留 100 重叠)→ `BAAI/bge-small-zh-v1.5` 向量 → ChromaDB 用户分集合(cosine);同一文档全部分块共享 `doc_id` 元数据,删除/列表按父文档聚合
- **检索**:4 倍超量召回 → cosine 相似度 ≥0.3 过滤 → `BAAI/bge-reranker-base` CrossEncoder 重排(模型缺失自动降级)→ top_k
- **兼容校验**:集合元数据记录 embedding 模型,换模型后维度不匹配给出明确重建提示
- **接入点**:chat 增强(开关)、用例生成、测试目标增强、"记住"入库;文件上传自动入库

## 数据存储

| 存储 | 内容 |
|---|---|
| app.db | users / sessions / conversations / model_configs / user_active_models / documents / project_folders |
| checkpoints.db | LangGraph 任务全量状态(steps/code_issues/fix_results/ai_config/extracted/started_at 等),thread_id=task_id |
| knowledge_base/ | ChromaDB,集合 `knowledge_user_{uid}`,元数据含 embedding_model 标记 |
| data/storage_states/{uid}/ | 登录态档案(档案名白名单清洗,防遍历) |
| project_uploads/{uid}/ + uploads/{uid}/ | 被测项目(测试产物写入其 test_recordings/)与文档 |

## API 接口清单

| 分组 | 接口 |
|---|---|
| 认证 | POST /auth/register · POST /auth/login · GET /auth/me |
| 会话 | GET/POST /sessions · PUT/DELETE /sessions/{id} |
| 模型 | GET /settings/models · GET /settings/platforms · POST /settings/models · GET/PUT/DELETE /settings/models/{id} · GET /settings/active · POST /settings/active/{id} · DELETE /settings/active · POST /settings/ai/test(需鉴权) |
| 历史 | GET /conversations(分页/按会话) · DELETE /conversations/{id} |
| 智能分析 | POST /analysis/bug · POST /analysis/cases · POST /analysis/code |
| 文件 | POST /files/upload · GET /files · GET/DELETE /files/{id} |
| 项目 | GET/POST /projects · POST /projects/upload(ZIP,防 zip-slip) · DELETE /projects/{id} · GET /projects/{id}/files · GET /projects/{id}/file/{path} |
| 知识库 | GET /knowledge/stats · GET /knowledge/list · POST /knowledge/add · PUT/DELETE /knowledge/{doc_id} |
| 对话 | POST /chat/stream(SSE,五类意图路由) |
| 测试 Agent | POST /test/run · POST /test/stream(SSE) · POST /test/resume/{id}(SSE) · GET /test/tasks/{id} · POST /test/stop/{id} · POST /test/code/fix · GET /test/project/files |

测试入口公共参数:`use_vision`(None 跟随全局)、`storage_state`(登录态档案名)、`max_steps`(run)、`project_id`(托管项目ID,/chat/stream 与 /test/stream 可选;指定时代码定位与修复写入该项目,缺省回落自动创建的 test_project 目录)。

## 技术栈

| 类别 | 技术 |
|---|---|
| 后端 | FastAPI + Uvicorn + SQLAlchemy(SQLite) + Pydantic v2 |
| Agent | LangGraph(状态机 + AsyncSqliteSaver 检查点 + interrupt 人工介入) |
| LLM | OpenAI 兼容协议多平台;Instructor 结构化输出 |
| 感知/执行 | Playwright(Chromium):元素索引、页面摘要、确定性断言、storage_state |
| RAG | ChromaDB + sentence-transformers(bge-small-zh-v1.5 / bge-reranker-base) |
| 前端 | React 18 + TypeScript(strict) + Vite 6 + Tailwind CSS + lucide-react |
| 安全 | PyJWT + bcrypt;路径围栏;CORS 白名单;zip-slip 防护 |
| 观测 | Langfuse(可选,openai 客户端自动埋点) |

## 关键设计决策

1. **LangGraph 而非手写循环**:每步 checkpoint 落盘(重启可查可恢复)、`interrupt()` 人工确认、`astream(updates)` 原生流式——替代原型的内存任务表与 Queue 拼接
2. **Instructor 结构化输出**:Pydantic 契约 + 自动重试 + 三级回退,消灭"提示词格式与解析端错配"类 bug
3. **DOM 文本感知优先**:结构摘要+元素编号定位为主,截图可选(视觉类问题才开启),纯文本模型零浪费
4. **确定性断言优先**:结论由代码判定(assert_text/assert_url),LLM 的 done.success 仅作总结
5. **探索产物沉淀**:脚本+报告+截图落盘,回归回放零 token——Agent 定位是"探索一次、沉淀资产"的测试生成器
6. **RAG 只接高价值点位**:用例生成/测试目标/chat,"记住"作轻量长期记忆;分析类功能(Bug分析/代码审查)用原始输入避免知识污染
7. **路径围栏**:AI 给出的文件路径强制限制在项目目录内(abspath+分隔符后缀比对,防 ../ 与前缀绕过)

## 运行方式

### 后端

```bash
# 1. Python 3.12 + 虚拟环境
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
# 2. Playwright 浏览器
python -m playwright install chromium
# 3. 预下载模型(HF 镜像已内置配置)
python -c "import os; os.environ['HF_ENDPOINT']='https://hf-mirror.com'; from sentence_transformers import SentenceTransformer, CrossEncoder; SentenceTransformer('BAAI/bge-small-zh-v1.5'); CrossEncoder('BAAI/bge-reranker-base')"
# 4. 启动(首次自动建表/生成 JWT 密钥)
python main.py
```

服务 `http://localhost:2222`,API 文档 `/docs`。旧版 knowledge_base/(英文模型 384 维向量)不兼容,启动前删除即可,运行时亦有明确报错提示。

### 前端

```bash
cd frontend-react
npm install
npm run dev     # 开发:http://localhost:5173(CORS 已放行)
npm run build   # 产物输出 ../frontend/,由后端 / 直接服务
```

## 配置项(.env)

| 变量 | 默认 | 说明 |
|---|---|---|
| JWT_SECRET_KEY | 自动生成 | 留空/占位符时首启生成随机密钥存 data/.jwt_secret |
| CORS_ORIGINS | localhost:5173 | 逗号分隔白名单,"*" 显式放开 |
| EMBEDDING_MODEL | BAAI/bge-small-zh-v1.5 | 更换后需清空知识库重建 |
| RAG_CHUNK_SIZE / RAG_CHUNK_OVERLAP | 500 / 100 | 分块参数 |
| RAG_MIN_SIMILARITY | 0.3 | 检索相关度阈值(cosine) |
| RAG_RERANK_ENABLED / RAG_RERANK_MODEL | true / BAAI/bge-reranker-base | 重排(缺失自动跳过) |
| TEST_AGENT_VISION | false | 测试 Agent 视觉感知全局默认 |
| LANGFUSE_PUBLIC_KEY / SECRET_KEY / HOST | 空 | 三项齐备启用 LLM 调用追踪 |

## 已知限制

- API Key 在数据库中明文存储(传输/展示层已掩码,存储加密未做)
- 前端未做移动端适配;登录态(storage_state)暂仅 API 支持,无管理界面
- web_test 的浏览器操作过程不落 conversations 表(产物在 test_recordings/)
- 测试用例生成结果为文本格式,非结构化用例表
- 浏览器 headless=False,服务器无显示器环境不可直接运行
