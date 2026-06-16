# Runbook (本地运行手册)

> A股智能分析与预测系统 — 本地开发环境启动指南

## 前置依赖

| 依赖 | 最低版本 | 确认命令 |
|------|---------|---------|
| Python | 3.10+ | `python --version` |
| Node.js | 20+ | `node --version` |
| npm | 9+ | `npm --version` |
| Redis | 7+ (仅 Docker 模式需要) | `redis-server --version` |
| Docker + Compose | 24+ (仅 Docker 模式) | `docker --version` |

## 环境变量

复制 `.env.example` 为 `.env`，填入实际 API Key：

```bash
cp .env.example .env
# 编辑 .env，填入 GOOGLE_API_KEY（必须）和 DISCORD_WEBHOOK_URL（可选）
```

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `GOOGLE_API_KEY` | 是 | Google Gemini API Key，用于 AI 分析（主要 LLM provider） |
| `ANTHROPIC_API_KEY` | 否 | Anthropic Claude API Key（备选 LLM） |
| `DISCORD_WEBHOOK_URL` | 否 | Discord 通知推送 |
| `CELERY_BROKER_URL` | 否 | Redis 连接地址（默认 `redis://redis:6379/0`） |

## 方式 A：本地开发（推荐，快速迭代）

### 1. 安装 Python 依赖

```bash
cd ashare-ai-analyst
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 启动后端（FastAPI）

```bash
# 从项目根目录
.venv/bin/uvicorn src.web.app:app --host 127.0.0.1 --port 8000 --reload
```

- API 地址：`http://127.0.0.1:8000`
- Swagger 文档：`http://127.0.0.1:8000/docs`（需 config/web.yaml 中 `debug: true`）
- 健康检查：`curl http://127.0.0.1:8000/api/v1/watchlist`

### 4. 启动前端（Vite Dev Server）

```bash
cd frontend
npm run dev
```

- 前端地址：`http://127.0.0.1:5173`
- API 代理：Vite 自动将 `/api/v1` 代理到 `http://127.0.0.1:8000`

### 5. 验证

```bash
# 后端 API
curl http://127.0.0.1:8000/api/v1/watchlist
# 应返回 JSON 数组（自选股列表）

# 前端
open http://127.0.0.1:5173
# 应看到 A股智能投顾 Dashboard
```

> **注意**：本地开发模式不启动 Redis/Celery，部分功能（定时任务、通知推送）不可用。核心功能（行情、分析、AI 投顾）正常运作。

## 方式 B：Docker Compose（完整环境）

```bash
# 一键启动全部服务（nginx + api + frontend + redis + celery）
make up

# 查看状态
make status

# 查看日志
make logs

# 停止
make down

# 全量重建（清除缓存）
make rebuild
```

Docker 模式下的访问地址：

| 服务 | 地址 |
|------|------|
| 前端（nginx） | `http://localhost:80` |
| API（经 nginx 代理） | `http://localhost:80/api/v1/` |
| API（直连） | 容器内部 `api:8000`，不对外暴露 |
| Redis | `localhost:6379` |

## 运行测试

```bash
# Python 后端测试（875+ 测试用例）
.venv/bin/pytest tests/ -v

# 仅运行快速测试
.venv/bin/pytest tests/ -v -m "not slow"

# 代码风格检查
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/

# 前端类型检查 + 构建验证
cd frontend && npx tsc --noEmit && npm run build
```

## 已知问题

| 问题 | 影响 | 状态 |
|------|------|------|
| `test_admin_routes.py` 8 个 ERROR | `src.web.routes.admin` 模块不存在 | 历史遗留，不影响功能 |
| `test_web_routes.py` 22 个 FAIL | 旧 HTML 路由已被 React SPA 替代 | 历史遗留 |
| `test_news_routes.py` 7 个 FAIL | Mock 不匹配 | 历史遗留 |
| VPN 下 push2.eastmoney.com 不稳定 | 概念板块实时数据可能不可用 | 前端已做零值降级 |
| Redis 不可用时 | Celery 定时任务、通知推送不工作 | 核心分析功能不受影响 |

## 端口占用排查

```bash
# 检查端口占用
lsof -i :8000  # 后端
lsof -i :5173  # 前端
lsof -i :6379  # Redis
lsof -i :80    # nginx

# 强制释放端口
kill -9 $(lsof -ti :8000)
```
