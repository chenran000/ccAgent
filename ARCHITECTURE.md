# 保险AI助手 - 架构文档

## 项目概述

基于 DeepSeek 大模型的保险业务 AI 系统，提供用户认证、保单信息提取、投诉工单智能分类、知识库管理和基于知识库的 RAG 问答功能。支持统一对话入口（意图识别 + 智能路由）和多会话管理。数据按用户和会话隔离，每个用户拥有独立的知识库和对话记录。

## 目录结构

```
insuranceAiProject/
├── main.py                  # 主入口（启动服务）
├── requirements.txt         # Python 依赖清单
├── .env                     # 环境变量（API Key、JWT Secret）
├── ARCHITECTURE.md          # 架构文档（本文件）
├── README.md                # 使用说明
│
├── app/                     # 后端代码
│   ├── __init__.py          # 包初始化
│   ├── config.py            # 配置管理（API Key、模型、端口、JWT）
│   ├── database.py          # 数据库连接（SQLite + SQLAlchemy）
│   ├── models.py            # ORM 模型（User、Session、Conversation）
│   ├── auth.py              # 认证工具（JWT、bcrypt、用户校验）
│   ├── schemas.py           # 数据模型（请求/响应格式定义）
│   ├── prompts.py           # 提示词管理（分类规则、提取模板、知识库问答）
│   ├── vector_db.py         # 向量数据库（ChromaDB + sentence-transformers）
│   ├── intent_classifier.py     # 意图识别（本地规则 + AI 模型）
│   ├── complaint_classifier.py  # 投诉工单分类核心逻辑
│   ├── policy_extractor.py      # 保单信息提取核心逻辑
│   ├── knowledge_qa.py          # 知识库 RAG 问答
│   └── routes.py            # API 路由定义（HTTP 接口）
│
├── frontend-react/          # 前端代码（React + TypeScript）
│   ├── src/
│   │   ├── context/
│   │   │   └── AuthContext.tsx    # 全局认证状态管理（含会话持久化）
│   │   ├── pages/
│   │   │   ├── LoginPage.tsx      # 登录/注册页面
│   │   │   └── ChatPage.tsx       # 主应用页面（含多会话管理）
│   │   ├── App.tsx                # 应用根组件
│   │   ├── main.tsx               # React 入口
│   │   └── index.css              # 全局样式（Tailwind）
│   ├── index.html                 # HTML 模板
│   ├── package.json               # Node.js 依赖
│   ├── tsconfig.json              # TypeScript 配置
│   ├── vite.config.ts             # Vite 构建配置
│   ├── tailwind.config.js         # Tailwind CSS 配置
│   └── postcss.config.js          # PostCSS 配置
│
├── data/                    # 数据持久化（自动生成）
│   └── app.db               # SQLite 数据库（用户表、会话表、对话记录表）
│
└── knowledge_base/          # 向量数据存储（自动生成）
    └── chroma.sqlite3       # ChromaDB 元数据（按用户隔离的集合）
```

## 模块职责

### 后端模块 (app/)

| 模块 | 职责 | 依赖 |
|------|------|------|
| `config.py` | 集中管理所有配置项：API Key、模型名称、服务端口、JWT 密钥 | `.env` |
| `database.py` | SQLAlchemy 数据库连接和会话管理 | `config`, `sqlalchemy` |
| `models.py` | ORM 数据模型：User（用户表）、Session（会话表）、Conversation（对话记录表） | `database` |
| `auth.py` | 用户认证：密码加密（bcrypt）、JWT 签发/验证、用户校验中间件 | `config`, `database` |
| `schemas.py` | 定义所有接口的数据格式（含认证、会话、对话、知识库模型） | `pydantic` |
| `prompts.py` | 管理所有 AI 提示词模板和业务枚举值（分类、原因、知识库问答模板） | 无 |
| `vector_db.py` | ChromaDB 向量数据库 + sentence-transformers 本地 Embedding | `config`, `chromadb` |
| `intent_classifier.py` | 意图识别：本地规则分类（关键词匹配）+ AI 模型分类 | `prompts`, `config` |
| `complaint_classifier.py` | 投诉分类核心逻辑：调用 AI 分类、结果校验、容错处理 | `prompts`, `config` |
| `policy_extractor.py` | 保单提取核心逻辑：普通模式和 RAG 模式（按用户检索知识） | `prompts`, `config`, `vector_db` |
| `knowledge_qa.py` | 知识库 RAG 问答：向量检索 + 上下文拼接 + AI 生成回答 | `prompts`, `config`, `vector_db` |
| `routes.py` | 所有 HTTP 接口路由：认证、会话管理、业务接口、对话历史管理 | `schemas`, `auth`, 功能模块 |

### 前端模块 (frontend-react/)

| 文件 | 职责 |
|------|------|
| `src/App.tsx` | 应用根组件，根据登录状态切换登录页或主页面 |
| `src/main.tsx` | React 应用入口，挂载根组件 |
| `src/index.css` | 全局样式（Tailwind CSS + 自定义动画） |
| `src/context/AuthContext.tsx` | 全局认证状态管理（登录/注册/登出、Token 维护、API 请求拦截、会话持久化） |
| `src/pages/LoginPage.tsx` | 登录/注册页面，深色玻璃拟态风格 UI |
| `src/pages/ChatPage.tsx` | 主应用页面，包含多会话管理侧边栏、知识库管理和聊天交互 |

### 前端功能模块

| 模块 | 功能 |
|------|------|
| 多会话管理 | 创建/切换/删除/重命名会话，按最新使用时间排序，自动恢复上次会话 |
| 统一对话入口 | 输入任意内容，AI 自动识别意图（提取/投诉/知识库/问答）并路由 |
| 知识库 RAG 问答 | 基于用户知识库的语义检索 + AI 生成回答，显示引用知识 |
| 投诉工单分类 | 智能分类业务类型和投诉原因，显示置信度徽章 |
| 保单信息提取 | 从保险文本中提取投保人姓名和保单号（支持 RAG 增强模式） |
| 知识库管理 | 添加、搜索、编辑、删除和管理保险知识文档 |
| 对话历史 | 按会话加载和展示历史对话记录，支持清空操作 |
| 用户认证 | 登录/注册/退出，Token 自动续期，401 自动登出 |

## 数据流向

```
用户登录/注册 → 获取 JWT Token → Token 存 localStorage
       ↓
前端发送 HTTP 请求（携带 Authorization: Bearer token + session_id）
       ↓
routes.py 验证 Token → 获取当前用户
       ↓
意图识别（本地规则匹配） → 路由到对应模块
       ↓
   ┌──────────────┬──────────────┬──────────────┬──────────────┐
   ↓              ↓              ↓              ↓              ↓
policy_extractor  complaint_classifier  knowledge_qa   对话记录保存
   ↓              ↓              ↓              ↓
调用 DeepSeek AI  调用 DeepSeek AI  RAG检索+生成  SQLite 持久化
   ↓              ↓              ↓              ↓
返回 JSON 结果 → 前端展示结果 + 更新会话列表
```

## API 接口清单

### 用户认证
| 方法 | 路径 | 认证 | 功能 |
|------|------|------|------|
| POST | `/auth/register` | 否 | 用户注册 |
| POST | `/auth/login` | 否 | 用户登录 |
| GET | `/auth/me` | 是 | 获取当前用户信息 |

### 会话管理
| 方法 | 路径 | 认证 | 功能 |
|------|------|------|------|
| GET | `/sessions` | 是 | 获取当前用户的会话列表（按 updated_at 倒序） |
| POST | `/sessions` | 是 | 创建新会话 |
| PUT | `/sessions/{id}` | 是 | 更新会话名称 |
| DELETE | `/sessions/{id}` | 是 | 删除会话及所有对话记录 |

### 对话历史
| 方法 | 路径 | 认证 | 功能 |
|------|------|------|------|
| GET | `/conversations` | 是 | 获取对话历史（支持分页、按会话/模块筛选） |
| DELETE | `/conversations/{id}` | 是 | 删除指定对话记录 |

### 统一对话入口
| 方法 | 路径 | 认证 | 功能 |
|------|------|------|------|
| POST | `/chat` | 是 | 统一对话入口（意图识别 + 智能路由，支持 RAG） |

### 保单信息提取（独立接口，可选）
| 方法 | 路径 | 认证 | 功能 |
|------|------|------|------|
| POST | `/extractPolicyInfo` | 是 | 提取投保人姓名和保单号（支持 RAG） |

### 投诉工单分类（独立接口，可选）
| 方法 | 路径 | 认证 | 功能 |
|------|------|------|------|
| POST | `/classifyComplaint` | 是 | 智能分类业务类型和投诉原因 |
| GET | `/complaint/categories` | 否 | 获取业务分类枚举列表 |
| GET | `/complaint/reasons` | 否 | 获取投诉原因枚举列表 |

### 知识库管理
| 方法 | 路径 | 认证 | 功能 |
|------|------|------|------|
| POST | `/knowledge/add` | 是 | 添加知识文档（用户隔离） |
| POST | `/knowledge/search` | 是 | 语义搜索知识（用户隔离） |
| GET | `/knowledge/stats` | 是 | 查看当前用户知识库统计 |
| GET | `/knowledge/list` | 是 | 获取知识库文档列表 |
| PUT | `/knowledge/{doc_id}` | 是 | 编辑指定知识文档 |
| DELETE | `/knowledge/{doc_id}` | 是 | 删除指定知识文档 |
| DELETE | `/knowledge/clear` | 是 | 清空当前用户知识库 |

## 启动方式

### 后端服务

```bash
py main.py
```

服务地址：`http://localhost:2222`

API 文档：`http://localhost:2222/docs`

### 前端开发

```bash
cd frontend-react
npm install
npm run dev
```

前端开发地址：`http://localhost:5173`

## 技术栈

### 后端
| 类别 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| AI 模型 | DeepSeek (deepseek-v4-flash) |
| Embedding 模型 | **sentence-transformers (all-MiniLM-L6-v2)** |
| 向量数据库 | ChromaDB (HNSW 索引 + 余弦相似度) |
| 关系数据库 | SQLite + SQLAlchemy ORM |
| 认证方案 | JWT (JSON Web Token) |
| 密码加密 | bcrypt |
| 服务部署 | Uvicorn ASGI 服务器 |
| 数据校验 | Pydantic |

### 前端
| 类别 | 技术 |
|------|------|
| UI 框架 | React 18 |
| 语言 | TypeScript |
| 构建工具 | Vite 6 |
| CSS 框架 | Tailwind CSS 3 |
| 图标库 | Lucide React |
| 样式工具 | class-variance-authority + tailwind-merge |

## 关键设计决策

### 为什么不使用 LangChain？

项目选择**从零手写** RAG 实现，而非使用 LangChain 框架：

| 考量 | 当前方式 | LangChain |
|------|----------|-----------|
| 依赖数量 | 少（10 个核心包） | 多（几十个包） |
| 学习成本 | 低，代码透明 | 高，概念多 |
| 调试难度 | 简单 | 复杂 |
| 适用场景 | 学习和演示 | 生产级应用 |

### 为什么使用 ChromaDB？

从 Pickle 轻量实现升级到 ChromaDB：

| 特性 | Pickle 实现 | ChromaDB |
|------|------------|----------|
| 向量计算 | 手动计算余弦相似度 | HNSW 近似最近邻 |
| 搜索性能 | 全量遍历 O(n) | 近似搜索 O(log n) |
| 扩展性 | 适合万级以下 | 支持百万级文档 |
| 元数据过滤 | 不支持 | 支持 |
| 用户隔离 | 单集合共享 | 按用户分集合 |

### 为什么使用 sentence-transformers？

从 DeepSeek Embedding API 切换到本地 sentence-transformers 模型：

| 特性 | DeepSeek API | sentence-transformers |
|------|-------------|----------------------|
| 可用性 | 模型不存在（404） | 本地运行，100% 可用 |
| 语义理解 | 无 | 深度学习模型，真语义匹配 |
| 网络依赖 | 需要 API 调用 | 完全离线 |
| 响应速度 | 网络延迟 | 本地计算，毫秒级 |
| 额外成本 | 按调用计费 | 零成本 |

**模型选择 `all-MiniLM-L6-v2`**：
- 轻量高效（约 80MB）
- 384 维向量输出
- 在数百万句子对上训练过
- 支持中英文语义理解

### 用户认证方案

| 方案 | 选择 | 原因 |
|------|------|------|
| 认证方式 | JWT Token | 无状态，适合 API 服务 |
| 密码存储 | bcrypt 哈希 | 抗彩虹表攻击 |
| Token 存储 | localStorage | 前端方便存取 |
| Token 过期 | 24 小时 | 安全与便利平衡 |
| 用户隔离 | Chroma 分集合 + DB 关联 | 数据互不干扰 |

### 统一对话入口设计

系统采用**意图识别 + 智能路由**模式，用户只需一个聊天框即可使用所有功能：

| 意图类型 | 识别方式 | 关键词示例 | 路由模块 |
|----------|----------|-----------|----------|
| 保单提取 | 本地规则 | 保单、保单号、投保人 | `policy_extractor` |
| 投诉分类 | 本地规则 | 投诉、举报、不满、慢 | `complaint_classifier` |
| 知识管理 | 本地规则 | 知识库、添加知识、记住 | `vector_db` |
| 智能问答 | 默认路由 | 其他任意内容 | `knowledge_qa`（RAG） |

**优势**：
- 本地关键词匹配，毫秒级响应，无需调用 AI API
- 前端只需调用一个 `/chat` 接口，后端自动路由
- 可扩展为 AI 意图识别（已预留 `classify_intent` 函数）

## 核心流程

### 用户注册/登录流程

```
用户输入用户名密码 → POST /auth/register 或 /auth/login
→ 密码 bcrypt 加密存储 / 验证
→ 签发 JWT Token（含 user_id、username、exp）
→ Token 存 localStorage → 后续请求携带
→ 前端 AuthContext 自动维护登录状态
```

### 会话管理流程

```
用户登录 → 从 localStorage 恢复 lastSessionId → 加载会话列表
→ 若无会话，自动创建"新会话" → 选择最新/上次会话
→ 发送消息 → 后端自动关联 session_id → 更新 session.updated_at
→ 会话列表按 updated_at 倒序排列
→ 刷新页面 → 恢复上次会话
```

### 统一对话入口流程

```
用户输入内容 → POST /chat（携带 session_id）
→ 本地规则意图识别 → classify_intent_local()
→ 根据意图路由到对应模块：
    extract → _handle_extract() → extract_with_llm()
    complaint → _handle_complaint() → classify_complaint()
    knowledge → _handle_knowledge() → vector_db.add_document()
    chat → _handle_chat() → answer_with_knowledge() (RAG)
→ 保存对话记录到 SQLite（关联 session_id）
→ 更新会话名称和时间戳
→ 返回结果
```

### RAG 问答流程

```
用户提问 → 意图识别为 chat → answer_with_knowledge()
→ sentence-transformers 生成查询向量
→ ChromaDB 检索该用户知识库 (top_k=3)
→ 拼接知识上下文到 KNOWLEDGE_QA_PROMPT
→ 调用 DeepSeek AI 生成回答
→ 返回回答内容 + 引用知识列表
→ 前端展示回答 + 知识标签
```

### RAG 提取流程（用户隔离）

```
用户输入文本 → 从 Token 获取 user_id
→ ChromaDB 检索该用户的知识库 (top_k=3)
→ sentence-transformers 本地生成查询向量
→ 拼接参考资料到提示词
→ 调用 DeepSeek AI → 解析 JSON 结果
→ 保存对话记录到 SQLite → 返回结果
```

### 投诉分类流程

```
用户输入投诉内容 → 从 Token 获取 user_id
→ 调用 DeepSeek AI (带分类规则提示词)
→ 解析 JSON 结果 → 校验枚举值
→ 保存对话记录到 SQLite → 返回分类及置信度
```

### 知识添加流程（用户隔离）

```
用户输入知识文本 → 从 Token 获取 user_id
→ sentence-transformers 本地生成向量
→ 存入 ChromaDB（该用户的独立集合）
→ 返回文档 ID
```

### 对话历史流程

```
用户切换会话 → GET /conversations?session_id=xxx&limit=100
→ SQLite 查询该会话的对话记录（按时间正序）
→ 前端按日期分组展示卡片列表（输入内容 + 输出结果 + 时间）
```

## 数据库设计

### users 表（用户）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| username | VARCHAR(50) | 用户名，唯一索引 |
| password_hash | VARCHAR(255) | bcrypt 加密后的密码 |
| created_at | DATETIME | 注册时间 |

### sessions 表（会话）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| user_id | INTEGER | 外键 → users.id |
| session_id | VARCHAR(36) | 会话标识（UUID），唯一索引 |
| name | VARCHAR(100) | 会话名称（默认"新会话"，首条消息自动命名） |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 最后使用时间（对话列表排序依据） |

### conversations 表（对话记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| user_id | INTEGER | 外键 → users.id |
| session_id | VARCHAR(36) | 外键 → sessions.session_id（允许 NULL，兼容旧数据） |
| module | VARCHAR(50) | 模块：extract / complaint / knowledge / chat |
| intent | VARCHAR(50) | 识别的意图（可选） |
| input_text | TEXT | 用户输入内容 |
| output_data | TEXT | AI 输出结果（JSON 字符串） |
| created_at | DATETIME | 创建时间，索引 |

## 前端架构

### 组件结构

```
App (根组件)
├── AuthProvider (全局认证状态)
│   ├── LoginPage (登录/注册)
│   └── ChatPage (主应用)
│       ├── Sidebar (侧边栏)
│       │   ├── Logo & 用户信息
│       │   ├── 新建会话按钮
│       │   ├── 会话列表（可切换/删除/重命名）
│       │   │   └── 悬停显示编辑/删除按钮
│       │   ├── 知识库统计
│       │   └── 清空当前会话按钮
│       ├── Main Content (主内容区)
│       │   ├── 对话页面 (default)
│       │   │   ├── Header (会话标题)
│       │   │   ├── MessageList (消息列表)
│       │   │   │   ├── EmptyState (空状态 + 示例)
│       │   │   │   ├── UserMessage (用户输入气泡)
│       │   │   │   ├── BotMessage (AI 响应气泡)
│       │   │   │   │   ├── 提取结果卡片
│       │   │   │   │   ├── 分类结果卡片（含置信度徽章）
│       │   │   │   │   ├── 知识添加成功提示
│       │   │   │   │   └── RAG 问答结果（含引用知识）
│       │   │   │   ├── TypingIndicator (AI 思考动画)
│       │   │   │   └── 日期分组
│       │   │   └── InputArea (输入区域)
│       │   │       ├── Textarea (多行输入)
│       │   │       ├── Send Button
│       │   │       └── RAG Toggle
│       │   └── 知识库管理页面
│       │       ├── Header (知识库标题 + 添加按钮)
│       │       ├── 知识文档列表
│       │       └── 添加知识弹窗
│       └── 弹窗组件
│           ├── 删除会话确认弹窗
│           ├── 清空对话确认弹窗
│           ── 添加知识弹窗
```

### 状态管理

- **AuthContext**: 全局认证状态（user、token、isLoading）
- **ChatPage 本地状态**:
  - 会话管理：sessions 列表、currentSessionId、editingSessionId
  - 对话管理：messages 列表、loading 状态
  - 知识库管理：knowledgeList、stats、knowledgeView
  - 持久化：localStorage 存储 lastSessionId，刷新页面自动恢复
- **数据加载**: 会话切换时加载对应历史，页面初始化时加载知识库统计

### UI 设计风格

- 深色玻璃拟态风格（Glassmorphism）
- Tailwind CSS 工具类
- 渐变色背景 + 圆角卡片 + 微光效果
- 响应式侧边栏 + 聊天式交互布局
- 悬停显示操作按钮（编辑/删除）
