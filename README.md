# What's Going On

> 🔭 信息聚合中心 — 支持邮件列表、GitHub、Slack 的自动摘要与推送

**What's Going On** 是一个信息聚合与 AI 摘要系统。支持监控 Apache 邮件组、GitHub 仓库活动、Slack 频道消息，通过 AI 自动生成结构化摘要，并可推送至飞书、Slack 等平台。

---

## 功能特性

- 📧 **邮件列表监控** — 支持 Pony Mail（Apache）和 Pipermail（Mailman 2）
- 🐙 **GitHub 追踪** — 追踪多仓库 PR / Issue 活动
- 💬 **Slack 监控** — 抓取 Workspace 频道消息
- 🤖 **AI 摘要生成** — 支持 Anthropic Claude / OpenAI / Google Gemini / 智谱 GLM 等多供应商
- 📤 **推送集成** — 飞书文档创建 + 群通知、Slack Webhook 推送
- 🔐 **ASF 私有邮件列表** — 支持 Apache LDAP 认证
- 📊 **Dashboard 仪表盘** — 一站式查看所有信息源，一键生成每日摘要

---

## 快速开始

### 1. 环境要求

- Python 3.10+
- macOS 或 Linux

### 2. 启动服务（推荐方式）

使用 `dev.sh` 脚本，它会**自动创建虚拟环境并安装依赖**：

```bash
# 首次启动（自动初始化环境 + 安装依赖 + 启动服务）
./dev.sh start

# 指定端口和绑定地址
./dev.sh start --port 8080 --host 127.0.0.1
```

启动成功后访问：

| 页面 | 地址 |
|------|------|
| 🌐 首页（Dashboard） | http://localhost:5000 |
| ⚙️ 设置页 | http://localhost:5000/settings |

### 3. 停止 / 重启 / 查看状态

```bash
./dev.sh stop        # 停止服务（优雅关闭，10 秒超时后强制终止）
./dev.sh restart     # 重启服务
./dev.sh status      # 查看运行状态（PID、CPU/内存等）
./dev.sh logs        # 查看最近 50 行日志
./dev.sh logs -f     # 实时追踪日志（Ctrl+C 退出）
./dev.sh setup       # 仅初始化/更新虚拟环境，不启动服务
```

### 4. 手动方式（可选）

```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 复制配置模板
cp config.example.json config.json

# 启动服务
python app.py
```

---

## 配置说明

所有配置存储在 `config.json` 中（已在 `.gitignore` 中排除）。首次使用请从模板创建：

```bash
cp config.example.json config.json
```

> **💡 大部分配置项均可在 Web 界面的 [Settings](http://localhost:5000/settings) 页面中完成配置，无需手动编辑 JSON 文件。**

### 配置文件结构总览

```json
{
  "llm": { ... },              // LLM 供应商配置（必填）
  "mailing_lists": [ ... ],    // 邮件列表配置
  "github": { ... },           // GitHub 仓库与 Token
  "slack": { ... },            // Slack Workspace 与推送
  "feishu": { ... },           // 飞书推送配置
  "asf_auth": { ... },         // ASF 私有列表认证
  "fetch_days": 7              // 默认获取天数
}
```

### LLM 供应商配置（必填）

系统需要至少一个 LLM 供应商来生成 AI 摘要。支持多供应商配置，通过 `active_provider` 指定当前使用的供应商。

```json
{
  "llm": {
    "active_provider": "anthropic",
    "providers": [
      {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "type": "anthropic",
        "base_url": "",
        "auth_token": "sk-ant-xxx",
        "model": "claude-sonnet-4-20250514"
      },
      {
        "id": "openai",
        "name": "OpenAI GPT",
        "type": "openai",
        "base_url": "",
        "auth_token": "sk-xxx",
        "model": "gpt-4o"
      },
      {
        "id": "google",
        "name": "Google Gemini",
        "type": "google",
        "base_url": "",
        "auth_token": "",
        "model": "gemini-2.0-flash"
      },
      {
        "id": "zhipu",
        "name": "ZhiPu GLM",
        "type": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "auth_token": "your-zhipu-token",
        "model": "glm-5"
      }
    ]
  }
}
```

| 字段 | 说明 |
|------|------|
| `id` | 供应商唯一标识（自定义） |
| `name` | 显示名称 |
| `type` | SDK 类型：`anthropic` / `openai` / `google`。兼容 OpenAI 接口的第三方供应商使用 `openai` |
| `base_url` | API 基础 URL。留空则使用各 SDK 默认地址。第三方兼容 API 需要填写 |
| `auth_token` | API 密钥 |
| `model` | 使用的模型名称 |

> **提示**：智谱 GLM、DeepSeek 等兼容 OpenAI 接口的供应商，`type` 设为 `openai`，并填入对应的 `base_url` 即可。

### 邮件列表配置

```json
{
  "mailing_lists": [
    {
      "id": "doris-dev",
      "name": "Apache Doris Dev",
      "type": "ponymail",
      "private": false,
      "config": {
        "base_url": "https://lists.apache.org",
        "list": "dev",
        "domain": "doris.apache.org"
      }
    },
    {
      "id": "apachecon-planners",
      "name": "ApacheCon Planners",
      "type": "ponymail",
      "private": true,
      "config": {
        "base_url": "https://lists.apache.org",
        "list": "planners",
        "domain": "apachecon.com"
      }
    }
  ]
}
```

支持两种邮件源类型：

| 类型 | 说明 | 配置字段 | 示例 |
|------|------|----------|------|
| `ponymail` | Apache Pony Mail 归档 | `base_url`, `list`, `domain` | lists.apache.org |
| `pipermail` | Mailman 2 Pipermail 归档 | `base_url`（归档 URL） | mail.python.org/pipermail/ |

- `private: true` 的列表需要配置 ASF 认证（见下文）

### GitHub 配置

```json
{
  "github": {
    "token": "ghp_xxxx",
    "repos": [
      {
        "id": "apache-doris",
        "name": "Apache Doris",
        "owner": "apache",
        "repo": "doris"
      }
    ]
  }
}
```

| 字段 | 说明 |
|------|------|
| `token` | GitHub Personal Access Token（可选，提升 API 速率限制） |
| `repos[].owner` | 仓库所有者（用户名或组织名） |
| `repos[].repo` | 仓库名称 |
| `repos[].name` | 显示名称 |
| `repos[].id` | 唯一标识（`owner-repo` 格式） |

### Slack 配置

```json
{
  "slack": {
    "push_webhook_url": "https://hooks.slack.com/services/T.../B.../...",
    "workspaces": [
      {
        "id": "my-team",
        "name": "My Team",
        "token": "xoxp-xxx",
        "channels": [
          { "id": "C08375R60EB", "name": "general" }
        ]
      }
    ]
  }
}
```

| 字段 | 说明 |
|------|------|
| `push_webhook_url` | Slack Incoming Webhook URL（用于推送摘要到频道） |
| `workspaces[].token` | Slack User Token（`xoxp-...`），需要 `channels:history`, `channels:read` 权限 |
| `workspaces[].channels` | 要监控的频道列表（可通过 Settings 页面自动获取） |

### 飞书推送配置

飞书推送使用两个机器人协作：

```json
{
  "feishu": {
    "bot_a": {
      "app_id": "cli_xxx",
      "app_secret": "xxx",
      "folder_token": "fldcnXXX",
      "owner_email": "13800000000"
    },
    "bot_b": {
      "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
    },
    "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
  }
}
```

| 机器人 | 用途 | 配置 |
|--------|------|------|
| **Bot A**（自建应用） | 创建飞书文档 | `app_id` + `app_secret` + 可选 `folder_token`、`owner_email` |
| **Bot B**（自定义机器人） | 推送文档链接到群 | `webhook_url` |
| **兼容模式** | 直接发送富文本消息到群 | `feishu.webhook_url` |

### ASF 认证配置

访问 Apache 私有邮件列表需要 ASF LDAP 账号：

```json
{
  "asf_auth": {
    "username": "your-asf-id",
    "password": "your-password",
    "cookie": ""
  }
}
```

> **推荐在 Settings 页面使用「Login with ASF Account」功能登录**，系统会自动获取并保存 session cookie。

### 全局配置

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `fetch_days` | `7` | 默认获取的邮件天数 |

---

## 使用流程

1. 启动服务后，打开 **Settings** 页面（`http://localhost:5000/settings`）
2. **配置 LLM** — 至少添加一个 AI 供应商并填入 API Key
3. **添加数据源** — 按需添加邮件列表、GitHub 仓库、Slack Workspace
4. 回到 **Dashboard** 页面，选择数据源和日期范围
5. 点击 **Generate Digest** 即可生成 AI 摘要
6. 可选：将摘要推送至飞书或 Slack

---

## 项目结构

```
whats-going-on/
├── app.py                  # Flask 主应用 — 路由、API、日志配置
├── summarizer.py           # AI 摘要模块 — 多供应商 LLM 调用
├── asf_auth.py             # ASF LDAP 认证模块
├── cache.py                # 缓存管理
├── requirements.txt        # Python 依赖
├── config.example.json     # 配置模板
├── dev.sh                  # 开发/运行脚本（推荐使用）
├── run.sh                  # 服务管理脚本（需预先初始化 venv）
│
├── fetchers/               # 邮件获取模块（插件化）
│   ├── __init__.py         # 基类 BaseFetcher + 工厂函数
│   ├── ponymail.py         # Apache Pony Mail 适配器
│   └── pipermail.py        # Mailman 2 Pipermail 适配器
│
├── sources/                # 数据源模块
│   ├── github.py           # GitHub API 交互
│   ├── slack.py            # Slack API 交互
│   └── feishu.py           # 飞书 API 交互
│
├── static/                 # 前端静态资源
│   ├── style.css           # 全局 CSS
│   ├── app.js              # 邮件页前端逻辑
│   ├── dashboard.js        # Dashboard 前端逻辑
│   ├── github.js           # GitHub 页前端逻辑
│   ├── slack.js            # Slack 页前端逻辑
│   └── settings.js         # 设置页前端逻辑
│
├── templates/              # Jinja2 HTML 模板
│   ├── base.html           # 基础布局
│   ├── dashboard.html      # Dashboard 仪表盘
│   ├── email.html          # 邮件列表页
│   ├── github.html         # GitHub 追踪页
│   ├── slack.html          # Slack 监控页
│   └── settings.html       # 设置页
│
├── data/                   # 运行时缓存（.gitignore 排除）
│   ├── emails/             # 邮件缓存（按月存储）
│   ├── cache/              # GitHub / 邮件缓存
│   ├── digests/            # AI 摘要缓存
│   └── summaries/          # 保存的摘要文件
│
├── summaries/              # 生成的摘要 Markdown 文件
├── log/                    # 运行日志（.gitignore 排除）
└── progress-docs/          # 项目文档
```

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端框架 | Python + Flask (≥3.0) | 轻量级 Web 框架 |
| AI 能力 | Anthropic / OpenAI / Google / 智谱 | 多供应商支持，可配置 base_url |
| HTTP 请求 | Requests (≥2.31) | 外部 API 调用 |
| 前端 | 原生 HTML / CSS / JavaScript | 无框架依赖 |
| 数据存储 | 本地 JSON 文件 | 邮件缓存 + 摘要缓存 |
| 日志 | Python logging + TimedRotatingFileHandler | 按日轮转，保留 30 天 |

---

## License

MIT
