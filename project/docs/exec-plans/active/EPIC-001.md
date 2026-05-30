# EPIC-001 — 项目基础设施

## Goal

搭建 Docker Compose 开发环境 + PostgreSQL 初始化 + FastAPI 骨架 + 基础鉴权。这是所有后续 EPIC 的底座。

## Scope

- Docker Compose 编排（FastAPI + PostgreSQL + Redis）
- PostgreSQL 初始化脚本（按 CLAUDE.md 数据模型建表）
- FastAPI 项目骨架与路由结构
- 基础鉴权（JWT + 简单的用户管理）
- 健康检查端点
- 项目的 pyproject.toml / 依赖管理

## Acceptance Criteria

- `docker compose up` 一键启动全部服务
- FastAPI `/health` 返回 200
- PostgreSQL 数据持久化、表结构正确
- JWT 登录/验证流程可用
- API 文档（Swagger）可通过浏览器访问

## Branch

`feature/epic-001-infra`
