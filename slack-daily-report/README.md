# Slack Daily Report

独立的 Slack 全频道日报工具。自动抓取 Slack 工作区所有公开频道的消息，按日期/频道分目录保存结构化 Markdown，并推送到指定 GitHub 仓库。

## 快速开始

### 1. 安装依赖

```bash
cd slack-daily-report
pip install -r requirements.txt
```

### 2. 配置

复制配置模板并填入你的值：

```bash
cp config.example.json config.json
```

编辑 `config.json`：

```json
{
  "slack": {
    "token": "xoxp-your-slack-user-token",
    "workspace_name": "ApacheDoris"
  },
  "github": {
    "repo_url": "git@github.com:user/slack-archive.git",
    "local_dir": "/path/to/local/clone",
    "branch": "main"
  }
}
```

**配置说明：**

| 字段 | 说明 |
|------|------|
| `slack.token` | Slack User Token（`xoxp-...`），需要有读取频道和消息的权限 |
| `slack.workspace_name` | 工作区显示名称，用于 README 标题 |
| `github.repo_url` | GitHub 仓库 SSH/HTTPS 地址，首次运行自动 clone |
| `github.local_dir` | 本地仓库路径 |
| `github.branch` | 目标分支（默认 `main`） |

### 3. 运行

```bash
# 抓取昨天的数据并推送到 GitHub
python3 slack_daily_report.py

# 指定日期
python3 slack_daily_report.py --date 2026-03-26

# 只抓取保存，不推送（调试用）
python3 slack_daily_report.py --dry-run

# 指定配置文件
python3 slack_daily_report.py --config /path/to/config.json
```

### 4. Crontab 定时运行

```bash
# 每天早上 8:00 自动运行
0 8 * * * cd /path/to/slack-daily-report && /usr/bin/python3 slack_daily_report.py >> /var/log/slack-daily-report.log 2>&1
```

## 输出目录结构

数据保存在 `github.local_dir` 指定的仓库中：

```
{local_dir}/
├── 2026-03-26/
│   ├── README.md              # 当天汇总索引（频道列表 + 消息统计）
│   ├── general/
│   │   └── messages.md        # #general 频道完整原始消息
│   ├── dev-discussion/
│   │   └── messages.md
│   └── ...
├── 2026-03-27/
│   ├── README.md
│   └── ...
└── ...
```

每个频道的 `messages.md` 包含：
- 按时间排序的全部消息
- 用户名、时间戳、完整消息文本
- Reactions
- Thread 回复（完整展示在对应消息下方）

## Slack Token 权限

需要的 Slack User Token Scopes：
- `channels:history` — 读取公开频道消息
- `channels:read` — 列出公开频道
- `groups:history` — 读取私有频道消息（可选）
- `groups:read` — 列出私有频道（可选）
- `users:read` — 解析用户名
