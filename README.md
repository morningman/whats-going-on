# Email Watcher

邮件组监控与每日摘要系统。监控 Apache 等公开邮件组，自动抓取邮件并通过 AI 生成每日摘要。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置模板
cp config.example.json config.json

# 启动服务
python app.py
```

访问 http://localhost:5000

## 使用流程

1. 打开 Settings 页面，填入 Claude API Key
2. 添加要监控的邮件列表（支持 Pony Mail 和 Pipermail）
3. 回到主页，选择邮件列表和日期，点击 Load Emails
4. 点击 Generate Digest 生成 AI 摘要

## 支持的邮件组类型

| 类型 | 说明 | 示例 |
|------|------|------|
| Pony Mail | Apache 邮件归档 | lists.apache.org |
| Pipermail | Mailman 2 归档 | mail.python.org/pipermail/ |

## 项目结构

```
app.py              # Flask 主应用
fetchers/           # 邮件获取模块（插件化）
  ponymail.py       # Apache Pony Mail
  pipermail.py      # Mailman 2 Pipermail
summarizer.py       # AI 摘要模块
static/             # 前端静态文件
templates/          # HTML 模板
data/               # 缓存数据（自动创建）
```

## 配置说明

编辑 `config.json`：

- `mailing_lists`: 邮件列表配置数组
- `llm.api_key`: Claude API Key
- `llm.model`: 使用的模型（默认 claude-sonnet-4-20250514）
- `fetch_days`: 默认获取天数
