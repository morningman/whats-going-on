# Email Watcher — 项目分析报告

> 分析日期：2026-02-28（已更新）

## 1. 项目概述

**Email Watcher** 是一个邮件组监控与每日摘要系统。核心功能是监控 Apache 等公开邮件组，自动抓取邮件并通过 Claude AI 生成结构化的每日摘要（Digest）。

**项目名称**：`whats-going-on`（仓库名） / `Email Watcher`（应用名）

---

## 2. 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端框架 | Python + Flask (≥3.0) | 轻量级 Web 框架 |
| AI 能力 | Anthropic / OpenAI / Google | 多供应商支持，可配置 base_url |
| HTTP 请求 | Requests (≥2.31) | 用于抓取外部邮件归档 |
| 前端 | 原生 HTML / CSS / JavaScript | 无框架依赖 |
| 数据存储 | 本地 JSON 文件 | 邮件缓存 + 摘要缓存 |
| 配置管理 | JSON 文件 (`config.json`) | 邮件列表 + 多供应商 LLM 配置 |
| 日志 | Python logging + TimedRotatingFileHandler | 按日轮转，保留 30 天 |
| 构建/部署 | build.sh + run.sh | macOS/Linux 兼容 |

---

## 3. 项目结构

```
whats-going-on/
├── app.py                  # Flask 主应用 — 路由 & API & 日志配置
├── summarizer.py           # AI 摘要模块 — 多供应商 LLM 调用
├── requirements.txt        # Python 依赖 (5 个依赖)
├── config.example.json     # 配置模板（多供应商格式）
├── build.sh                # 构建脚本 — 打包到 output/
├── run.sh                  # 服务管理脚本 — start/stop/restart/status/logs
├── .gitignore
├── README.md
│
├── fetchers/               # 邮件获取模块（插件化架构）
│   ├── __init__.py         # 基类 BaseFetcher + 工厂函数
│   ├── ponymail.py         # Apache Pony Mail 适配器
│   └── pipermail.py        # Mailman 2 Pipermail 适配器
│
├── static/                 # 前端静态资源
│   ├── style.css           # 全局 CSS 样式
│   ├── app.js              # 主页前端逻辑
│   └── settings.js         # 设置页前端逻辑
│
├── templates/              # Jinja2 HTML 模板
│   ├── index.html          # 主页 — 邮件浏览 & 摘要生成
│   └── settings.html       # 设置页 — 多供应商管理 & 邮件列表配置
│
├── data/                   # 运行时缓存数据（.gitignore 排除）
│   ├── emails/             # 邮件缓存（按月存储）
│   └── digests/            # AI 摘要缓存
│
├── log/                    # 运行日志目录（.gitignore 排除）
│   ├── app.log             # 应用详细日志（按日轮转）
│   └── console.log         # 控制台输出
│
├── output/                 # 构建输出目录（.gitignore 排除）
│
└── progress-docs/          # 项目文档
    ├── design.md           # 设计文档
    └── project-analysis.md # 项目分析报告
```

---

## 4. 架构设计

### 4.1 整体架构

```
┌─────────────────────────────────────────────────┐
│                   浏览器 (前端)                    │
│   index.html + app.js  |  settings.html + settings.js │
└──────────────┬──────────────────┬────────────────┘
               │ HTTP API         │
┌──────────────▼──────────────────▼────────────────┐
│                Flask 应用 (app.py)                 │
│  /api/lists  /api/emails  /api/digest  /api/config │
│              logging → log/app.log                 │
└──────┬────────────┬────────────┬─────────────────┘
       │            │            │
       ▼            ▼            ▼
  ┌─────────┐ ┌──────────┐ ┌────────────────────┐
  │ config  │ │ fetchers │ │    summarizer      │
  │  .json  │ │ (插件化)  │ │ (多供应商 LLM)     │
  └─────────┘ └─────┬────┘ └─────┬──────────────┘
                    │            │
              ┌─────▼────┐  ┌───▼─────────────┐
              │ 外部邮件  │  │ Anthropic/OpenAI │
              │   归档    │  │  /Google API     │
              └──────────┘  └─────────────────┘
```

### 4.2 核心模块分析

#### `app.py` — Flask 主应用

- **页面路由**：`/`（主页）、`/settings`（设置页）
- **REST API**：
  - `GET /api/config` — 获取配置（API Key 脱敏处理）
  - `POST /api/config` — 保存配置
  - `GET /api/lists` — 获取邮件列表
  - `GET /api/emails` — 按日期获取邮件
  - `GET /api/digest` — 获取缓存的摘要
  - `POST /api/digest` — 生成新摘要
  - `POST /api/test-connection` — 测试邮件源连接

#### `fetchers/` — 邮件获取模块（插件化）

采用 **策略模式 + 工厂模式**：

- `BaseFetcher` (ABC) — 抽象基类，定义 `fetch_emails()` 和 `test_connection()` 接口
- `get_fetcher(type)` — 工厂函数，根据类型返回对应 Fetcher 实例
- `PonyMailFetcher` — 通过 mbox API (`/api/mbox.lua`) 获取 Apache 邮件
- `PipermailFetcher` — 通过下载 `.txt.gz` / `.txt` 归档获取 Mailman 2 邮件

两个 Fetcher 共同特点：
- 都使用 Python `mailbox.mbox` 解析 mbox 格式
- 都有**按月缓存机制**（`data/emails/` 目录下存 JSON）
- 都支持邮件头解码（`_decode_header`）
- 统一输出格式：`{id, subject, from, body, date, epoch, in_reply_to, thread_id}`

#### `summarizer.py` — AI 摘要模块

- 支持多供应商 LLM 调用：Anthropic Claude、OpenAI、Google Gemini
- 每个供应商支持自定义 `base_url` 和 `auth_token`
- SDK 懒加载（运行时才 import，未安装不影响其他供应商）
- 将邮件按 Thread 组织后构建 Prompt
- Prompt 要求生成：Overview / Key Discussions / Action Items / Notable
- 摘要会缓存到 `data/digests/` 目录
- 支持自动语言检测（跟随邮件语言）
- 详细的日志记录（API 调用耗时、token 用量等）

#### 前端

- 纯原生 JS，无框架依赖
- 主页：选择邮件列表 + 日期 → 加载邮件 → 生成摘要
- 设置页：多供应商管理（增删、选择活跃供应商）+ 邮件列表管理
- 简易 Markdown 渲染（正则替换实现）

#### 日志系统

- `app.py` 中配置 `setup_logging()` 统一初始化
- `TimedRotatingFileHandler` 按日轮转，保留 30 天
- 日志文件：`log/app.log`（详细日志）+ `log/console.log`（控制台输出）
- 所有模块（app、summarizer、fetchers）均有详细日志
- 记录内容：HTTP 请求、邮件获取、LLM 调用耗时、缓存命中、错误堆栈等

---

## 5. 数据流

```
用户选择邮件列表和日期
        │
        ▼
  app.py /api/emails
        │
        ▼
  fetcher.fetch_emails(config, date)
        │
        ├── 检查本地缓存 (data/emails/xxx.json)
        │   ├── 命中 → 直接按日期过滤返回
        │   └── 未命中 ↓
        │
        ▼
  请求外部邮件归档 (Pony Mail API / Pipermail mbox)
        │
        ▼
  解析 mbox 格式 → 统一邮件数据结构
        │
        ▼
  缓存整月数据 → 按日期过滤返回
        │
        ▼
  用户点击 "Generate Digest"
        │
        ▼
  app.py POST /api/digest
        │
        ▼
  summarizer.generate_digest()
        │
        ├── 检查摘要缓存 (data/digests/xxx.json)
        │   ├── 命中 → 直接返回
        │   └── 未命中 ↓
        │
        ▼
  构建 Prompt（按 Thread 组织邮件内容）
        │
        ▼
  调用 Claude API → 获取结构化摘要
        │
        ▼
  保存到缓存 → 返回给前端
```

---

## 6. 配置结构

```json
{
  "mailing_lists": [
    {
      "id": "doris-dev",
      "name": "Apache Doris Dev",
      "type": "ponymail",
      "config": {
        "base_url": "https://lists.apache.org",
        "list": "dev",
        "domain": "doris.apache.org"
      }
    }
  ],
  "llm": {
    "active_provider": "anthropic",
    "providers": [
      {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "type": "anthropic",
        "base_url": "",
        "auth_token": "sk-xxx",
        "model": "claude-sonnet-4-20250514"
      },
      {
        "id": "openai",
        "name": "OpenAI GPT",
        "type": "openai",
        "base_url": "",
        "auth_token": "sk-xxx",
        "model": "gpt-4o"
      }
    ]
  },
  "fetch_days": 7
}
```

### 支持的 LLM 供应商

| Type | 说明 | 默认模型 | SDK |
|------|------|---------|-----|
| `anthropic` | Anthropic Claude API | `claude-sonnet-4-20250514` | `anthropic` |
| `openai` | OpenAI / 兼容 API | `gpt-4o` | `openai` |
| `google` | Google Gemini API | `gemini-2.0-flash` | `google-generativeai` |

---

## 7. 支持的邮件源

| 类型 | 实现文件 | 数据获取方式 | 典型场景 |
|------|----------|------------|---------|
| Pony Mail | `fetchers/ponymail.py` | HTTP API (`/api/mbox.lua`) | Apache 项目邮件组 (lists.apache.org) |
| Pipermail | `fetchers/pipermail.py` | 下载 mbox 归档 (`.txt.gz` / `.txt`) | Python, GNU 等使用 Mailman 2 的项目 |

---

## 8. 设计亮点

1. **插件化 Fetcher 架构**：通过抽象基类 + 工厂模式，新增邮件源只需新建一个 Fetcher 类即可
2. **两级缓存**：邮件按月缓存 + 摘要独立缓存，避免重复请求和 API 调用
3. **统一邮件格式**：不同源的邮件被标准化为统一的 dict 格式，解耦数据获取与展示/摘要
4. **Thread 组织**：摘要生成前会将邮件按讨论线程分组，提供更好的上下文
5. **Auth Token 安全**：配置 API 返回时对 Token 做脱敏处理，保存时自动还原
6. **多供应商 LLM 支持**：Anthropic / OpenAI / Google，可配置自定义 base_url
7. **完整日志系统**：按日轮转、保留 30 天、记录所有业务操作
8. **一键构建部署**：`build.sh` 打包 + `run.sh` 管理生命周期
9. **旧配置自动迁移**：老格式 config.json 自动升级为新多供应商格式

---

## 9. 潜在改进方向

### 功能层面
- [ ] 支持更多邮件源（如 Google Groups、Discourse、HyperKitty/Mailman 3）
- [ ] 添加定时任务自动抓取和生成摘要
- [ ] 支持多日/多列表的聚合摘要
- [ ] 邮件搜索功能
- [ ] 邮件统计分析（活跃度图表等）

### 技术层面
- [ ] Fetcher 中的 `_parse_message` 和 `_decode_header` 存在大量重复代码，建议提取到基类
- [ ] 缓存策略可优化（当前缓存无过期机制，当月数据可能不完整）
- [ ] 前端 Markdown 渲染较简陋，可引入 `marked.js` 等库
- [x] ~~无错误日志记录机制~~ ✅ 已实现完整日志系统
- [ ] 无单元测试
- [ ] `config.json` 中 `fetch_days` 字段在代码中未被使用
- [ ] 前端可考虑引入简单的状态管理
- [ ] 设置页中已有供应商的 Token 更新需要删除后重新添加

### 安全层面
- [ ] API 无认证机制（任何人可访问和修改配置）
- [ ] 配置直接存文件，多实例部署有冲突风险
- [ ] `POST /api/config` 无输入校验

---

## 10. 文件行数统计

| 文件 | 行数 | 说明 |
|------|------|------|
| `app.py` | ~230 | Flask 主应用 + 日志配置 + 配置迁移 |
| `summarizer.py` | ~240 | 多供应商 AI 摘要模块 |
| `fetchers/__init__.py` | 35 | Fetcher 基类 & 工厂 |
| `fetchers/ponymail.py` | ~185 | Pony Mail 适配器 |
| `fetchers/pipermail.py` | ~200 | Pipermail 适配器 |
| `static/app.js` | 178 | 主页前端逻辑 |
| `static/settings.js` | ~260 | 设置页前端逻辑（含供应商管理） |
| `static/style.css` | ~270 | 全局 CSS 样式 |
| `templates/index.html` | 46 | 主页模板 |
| `templates/settings.html` | ~115 | 设置页模板 |
| `build.sh` | ~130 | 构建脚本 |
| `run.sh` | ~290 | 服务管理脚本 |
| **合计** | **~2,180** | |
