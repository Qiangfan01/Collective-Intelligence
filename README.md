# Collective-Intelligence

运维机器人项目。基于 DeerFlow 2.0 构建的单人多 Agent 运维助手，部署在本地，通过飞书群接收任务。

## 这是什么

一个在飞书群里 @ 一下就能用的运维助手。它能查服务状态、读日志、分析报错，遇到需要动手的事会先出方案发到你私聊，你点了批准才执行。

当前接入的第一个对象是 ELN（电子实验记录本）项目。

## 目录

```
docs/                      设计文档
deploy/deer-flow/          DeerFlow 配置（config.yaml / compose / env）
deploy/skills/             作业规程（SKILL.md）
ops-bot-eln/               运维能力层（MCP Server，Python）
```

## 快速开始

见 `docs/DeerFlow实施方案.md`。

## 设计原则

1. **能力收窄**：不给 Agent 自由 shell，所有运维操作走固定模板的 MCP 工具。
2. **两段式写操作**：先出方案落库，再由人点批准，方案不可变。
3. **规程显式化**：什么能直接做、什么必须审批，写在 SKILL.md 里，可审查。
4. **业务与框架解耦**：所有业务逻辑在 `ops-bot-eln`，换编排框架不用重写。

## 许可证

内部项目。
