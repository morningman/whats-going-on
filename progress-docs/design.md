# Email Watcher - 设计文档

## 概述

邮件组监控与每日摘要系统，监控 Apache 等公开邮件组，自动抓取邮件并通过 AI 生成每日摘要。

## 技术栈

- 后端：Python + Flask
- 前端：原生 HTML/CSS/JS
- AI：Claude API（anthropic SDK）
- 存储：本地 JSON 文件

## 数据源

- Apache Pony Mail API（lists.apache.org）
- Mailman 2 Pipermail 归档

## 核心流程

1. 用户配置邮件列表和 LLM API Key
2. 选择日期 → 后端拉取邮件 → 按日期过滤
3. 点击生成摘要 → Claude API 生成结构化摘要
4. 摘要缓存到本地，下次直接读取
