# TestAssistant AI — 架构文档(testAExe 分支)

## 项目概述

**本地桌面代码检查智能体**(对齐 ZCode 的产品形态):打开本地项目工作区后,通过工具调用型 Agent 完成代码分析、Bug 定位、规范检查(规则引擎 + AI 语义审查)、自由问答;知识库(规范文档 RAG)作为检查标准与问答参考;智能体具备跨会话记忆。

**单用户本地版**:无注册/登录/用户系统(参考 ZCode 的本地单用户实践),所有数据归属内置 "local" 用户(启动时自动归并历史多用户数据);服务默认只绑 127.0.0.1;API Key 落盘前用 AES-256-GCM 加密(`enc:v1:` 前缀,密钥由机器信息派生,借鉴 ZCode credential-cipher);知识库 Embedding 走 OpenAI 兼容 API(无本地 torch/bge 模型依赖)。

多用户 Web 版与 Web 自动化测试 Agent 保留在 featureGli 分支(testAExe 分支已移除测试 Agent 全链路)。

## 目录结构

```
ccAgent/
├── main.py                     # FastAPI 入口(uvicorn + CORS 白名单)
├── shell_app.py                # 桌面壳(pywebview/WebView2):拉起后端 + 独立窗口 + 生命周期
├── requirements.txt
├── ARCHITECTURE.md             # 本文档
│
├── app/                        # 后端
│   ├── config.py               # ★ 路径解析(frozen 感知,代码与 ~/.testassistant 数据分离)
│   ├── database.py             # SQLAlchemy 引擎/会话
│   ├── models.py               # ORM:users/sessions/conversations/model_configs/user_active_models/documents
│   ├── credential_cipher.py    # API Key 加密(AES-256-GCM,机器派生密钥)
│   ├── auth.py                 # 本地用户依赖(固定返回内置 "local" 用户)
│   ├── schemas.py              # Pydantic 请求/响应模型
│   ├── routes.py               # 全部 HTTP/SSE 接口 + SSE 事件编排
│   ├── llm.py                  # ★ 统一 LLM 客户端 + Instructor 结构化输出(CodeReview 契约)
│   ├── agent_loop.py           # ★ 工具调用型 Agent 循环(OpenAI function calling,SSE 步骤事件)
│   ├── agent_tools.py          # Agent 工具集(list_tree/read_file/search_code/edit_file/run_command 等)
│   ├── workspace.py            # 工作区状态(当前项目路径 + 路径围栏 + 文件树)
│   ├── memory.py               # 智能体记忆(读写 DATA_DIR/memory/,跨会话注入)
│   ├── inspector.py            # ★ 规范检查管线:规则引擎(零 token) + AI 语义审查 → 分级报告
│   ├── vector_db.py            # ChromaDB + 中文分块/阈值过滤(Embedding 走 API)
│   ├── file_parser.py          # PDF/TXT 文本提取(知识库文档)
│   ├── file_storage.py         # 上传文件存储
│   ├── file_viewer.py          # 文件预览(文本/图片/二进制识别,/workspace/file 使用)
│   └── native_dialog.py        # 系统目录选择框(tkinter,线程内运行)
│
├── frontend-react/             # React 18 + TypeScript + Vite + Tailwind
│   └── src/
│       ├── components/         # IDELayout/Sidebar/ChatPanel/WorkspacePane/KnowledgePanel/ModelPanel
│       └── lib/                # types.ts + api.ts(类型化 API + POST SSE 流解析)
│
├── data/                       # (storage_root 下)业务 SQLite + memory/ + reports/
├── knowledge_base/             # ChromaDB 持久化
├── uploads/                    # 上传的规范/知识文档
└── frontend/                   # 前端构建产物(vite outDir,后端同源服务)
```

## 分层架构

```
┌────────────────────────────────────────────────────────────────┐
│ 桌面壳  shell_app.py — pywebview 窗口 + 后端子进程生命周期       │
├────────────────────────────────────────────────────────────────┤
│ 前端   React IDE 布局(工作区文件树 / 对话 / 知识库 / 模型)      │
├────────────────────────────────────────────────────────────────┤
│ 接入层  routes.py — REST + SSE,单用户本地回环                  │
├────────────────────────────────────────────────────────────────┤
│ 编排层  routes /chat/stream — 工作区打开→Agent;未开→纯 LLM 对话 │
│         inspector.py — 规范检查任务编排(SSE 进度)               │
├────────────────────────────────────────────────────────────────┤
│ Agent层 agent_loop.py — function calling 循环(步数上限+上下文压缩)│
│         agent_tools.py — 工作区围栏内的文件/搜索/命令工具        │
│         memory.py — 长期记忆读写与提示词注入                     │
├────────────────────────────────────────────────────────────────┤
│ AI层   llm.py — build_plain_client / create_structured(Instructor)│
├────────────────────────────────────────────────────────────────┤
│ 存储层  app.db + ChromaDB + memory/ + reports/ + uploads/       │
├────────────────────────────────────────────────────────────────┤
│ 安全    凭据加密(AES-GCM)/工作区路径围栏/回环绑定/Key 掩码      │
│ 观测    结构化 logging(stderr;stdout 保持干净)(凭据不落日志)   │
└────────────────────────────────────────────────────────────────┘
```

## AI 调用规范(全项目唯一通道 `app/llm.py`)

- 多平台:DeepSeek/OpenAI/通义千问/Kimi/智谱/自定义,均走 OpenAI 兼容协议,`base_url` 可覆盖;模型配置存 `model_configs` 表
- 自由文本/流式 → `build_plain_client`;结构化输出 → `create_structured`(Instructor,格式错误自动重试,端点不支持函数调用时 TOOLS→JSON→纯文本三级回退)
- 输出契约:目前仅 `CodeReview`(规范检查的 AI 语义审查);Agent 循环与对话直接使用自由文本/函数调用

## 智能体(agent_loop + agent_tools)

- **触发**:`POST /chat/stream` 且工作区已打开 → 全部消息走 Agent(无意图分类,对齐 ZCode 的自由提问形态);未打开工作区回落纯 LLM 流式对话
- **循环**:OpenAI function calling;system 提示注入工作区路径、跨会话记忆(memory/)、知识库规范文档摘要;每轮携带最近 10 轮历史
- **工具**(路径强制围栏在工作区内):`list_tree` / `read_file` / `search_code`(正则) / `edit_file`(写盘前强制先读) / `run_command`(子进程,cwd=工作区) / `remember`(写长期记忆)
- **护栏**:最大轮数上限;工具结果条数超限时上下文压缩(保留 system/首问/最近若干条,其余替换占位符);过程以 `step` SSE 事件实时推送前端内联渲染

## 规范检查管线(inspector.py)

两层检查(确定性 + 语义):
1. **规则引擎**(零 token,零误报):硬编码密钥 / 危险函数 / 调试残留 / TODO 标记,正则全项目扫描
2. **AI 语义审查**:分文件调用大模型(带行号上下文),知识库 `standards` 分类的规范文档作为评审标准注入,复用 `CodeReview` 契约
产出:分级问题清单 + 健康分,持久化到 `data/reports/`;`POST /inspect/stream` SSE 实时进度,报告列表/详情可回看。

## 统一对话入口(/chat/stream,SSE)

```
输入(+可选文件引用 file_id) → 工作区已打开?
  是 → stream_agent(工具调用循环,SSE: meta/step/chunk/done)
  否 → (use_rag 开启时检索知识库注入) → LLM 流式(chunk)
→ 对话落库 conversations 表(module 区分 agent/chat)
```

## RAG 管线(vector_db.py)

- **入库**:中文友好分块(段落/句子边界,目标 500 字符,超长硬切留 100 重叠)→ OpenAI 兼容 Embedding API → ChromaDB(cosine);同一文档全部分块共享 `doc_id` 元数据,删除/列表按父文档聚合
- **检索**:超量召回 → 相似度阈值过滤(≥0.3)→ top_k(CrossEncoder 重排已随本地模型依赖移除)
- **兼容校验**:集合元数据记录 embedding 模型,换模型后维度不匹配给出明确重建提示
- **接入点**:规范检查评审标准(standards 分类)、chat 的 RAG 问答开关、文件上传自动入库

## 数据存储(storage_root = `~/.testassistant`,TESTASSISTANT_STORAGE_DIR 可重定向)

| 存储 | 内容 |
|---|---|
| data/app.db | users / sessions / conversations / model_configs / user_active_models / documents |
| data/memory/ | 智能体长期记忆(Markdown,跨会话) |
| data/reports/ | 规范检查报告(JSON) |
| knowledge_base/ | ChromaDB,集合按用户,元数据含 embedding_model 标记 |
| uploads/ | 上传的规范/知识文档 |

源码模式 storage_root=仓库根;打包模式固定到用户目录,升级替换 exe 不动数据。

## API 接口清单

| 分组 | 接口 |
|---|---|
| 工作区 | GET/POST /workspace · POST /workspace/dialog(系统目录框) · DELETE /workspace · GET /workspace/files · GET /workspace/file |
| 会话 | GET/POST /sessions · PUT/DELETE /sessions/{id} |
| 模型 | GET /settings/models · GET /settings/platforms · POST /settings/models · GET/PUT/DELETE /settings/models/{id} · GET /settings/active · POST /settings/active/{id} · DELETE /settings/active · POST /settings/ai/test |
| 历史 | GET /conversations(分页/按会话) · DELETE /conversations/{id} |
| 文件 | POST /files/upload(知识库文档) · GET /files · GET/DELETE /files/{id} |
| 知识库 | GET /knowledge/stats · GET /knowledge/list · POST /knowledge/add · PUT/DELETE /knowledge/{doc_id} |
| 规范检查 | POST /inspect/stream(SSE) · GET /inspect/reports · GET /inspect/report |
| 对话 | POST /chat/stream(SSE,Agent / 纯对话) |

## 技术栈

| 类别 | 技术 |
|---|---|
| 后端 | FastAPI + Uvicorn + SQLAlchemy(SQLite) + Pydantic v2 |
| Agent | OpenAI function calling 循环 + 工作区围栏工具集 |
| LLM | OpenAI 兼容协议多平台;Instructor 结构化输出 |
| 检查 | 规则引擎(正则,零 token)+ AI 分文件语义审查 |
| RAG | ChromaDB + OpenAI 兼容 Embedding API |
| 前端 | React 18 + TypeScript(strict) + Vite 6 + Tailwind CSS + lucide-react |
| 桌面 | pywebview(WebView2)壳 + PyInstaller onedir 后端 |
| 安全 | AES-GCM 凭据加密;工作区路径围栏;回环绑定 |
| 观测 | 结构化 logging(stderr;凭据不落日志) |

## 运行方式

### 后端

```bash
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

服务 `http://127.0.0.1:2222`,API 文档 `/docs`。知识库需在 .env 配置 EMBEDDING_API_KEY/EMBEDDING_API_BASE/EMBEDDING_MODEL 后启用。

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
| HOST / PORT | 127.0.0.1 / 2222 | 服务绑定地址(默认仅回环) |
| CORS_ORIGINS | localhost:5173 | 逗号分隔白名单,"*" 显式放开 |
| TESTASSISTANT_STORAGE_DIR | ~/.testassistant | 用户数据根目录(打包模式) |
| TESTASSISTANT_CREDENTIAL_SECRET | 空 | 凭据加密密钥材料;缺省由机器信息派生(数据文件拷到其他机器密文自动失效) |
| EMBEDDING_API_KEY / EMBEDDING_API_BASE / EMBEDDING_MODEL | 空 | OpenAI 兼容 embeddings 接口;不配则知识库向量能力禁用(其余功能正常) |
| RAG_CHUNK_SIZE / RAG_CHUNK_OVERLAP | 500 / 100 | 分块参数 |
| RAG_MIN_SIMILARITY | 0.3 | 检索相关度阈值(cosine) |

## 打包(exe 桌面版)

- 构建: `build_exe.bat`(前端构建 → 后端 PyInstaller onedir → 桌面壳 onefile → 组装);产物 `dist/testassistant/`
- **桌面形态**: `TestAssistantApp.exe`(pywebview/WebView2 独立窗口)双击启动 → 拉起同目录 `TestAssistant.exe` 后端(隐藏控制台) → 就绪后窗口加载 UI → **关窗自动结束后端**
- 代码/数据分层(对齐 ZCode): 后端 onedir 为代码,`frontend/` 在 exe 旁,**用户数据固定 `~/.testassistant/`**,升级替换文件不动数据
- 已知坑: 凭据加密的机器绑定含 hostname,跨机器迁移会使已存 API Key 失效,需重新配置或固定 `TESTASSISTANT_CREDENTIAL_SECRET`
