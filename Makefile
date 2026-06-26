.PHONY: up down restart rebuild logs status clean purge test-integration-real health qlib-update qlib-status bridge-start bridge-stop bridge-status demo help

PYTHON ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

# ============================================================
# Docker Compose 管理脚本
# ============================================================

# --- 可覆盖变量 ---
export PORT          ?= 80
export REDIS_PORT    ?= 6379
HEALTH_RETRIES       ?= 60
HEALTH_INTERVAL      ?= 2
COMPOSE              := docker-compose

# ============================================================
# 内部 Helpers（不直接调用）
# ============================================================

_stop:
	@echo "==> 停止旧容器 (等待 Celery 优雅退出, 最长 30s)..."
	$(COMPOSE) down --remove-orphans -t 30 2>/dev/null || true
	@sleep 3

_clean-volumes:
	@echo "==> 清空前端 dist 卷..."
	docker volume rm marketing_frontend-dist 2>/dev/null || true

_flush-celery:
	@echo "==> 清理 Celery 队列..."
	@sleep 2
	$(COMPOSE) exec -T redis sh -c "redis-cli KEYS 'celery*' | xargs -r redis-cli DEL" 2>/dev/null || true

_wait-healthy:
	@echo "==> 等待 API 健康检查通过 (最长 $(shell echo $$(($(HEALTH_RETRIES) * $(HEALTH_INTERVAL))))s)..."
	@n=0; while [ $$n -lt $(HEALTH_RETRIES) ]; do \
		state=$$($(COMPOSE) ps --format json 2>/dev/null \
			| python3 -c "import sys,json; \
data=sys.stdin.read().strip(); \
objs=json.loads(data) if data.startswith('[') else [json.loads(l) for l in data.splitlines() if l.strip()]; \
matches=[o for o in objs if o.get('Service')=='api']; \
print(matches[0].get('Health','') if matches else '')" 2>/dev/null); \
		if [ "$$state" = "healthy" ]; then \
			echo "==> API 健康检查通过"; \
			exit 0; \
		fi; \
		n=$$((n + 1)); \
		sleep $(HEALTH_INTERVAL); \
	done; \
	echo "⚠️  API 健康检查超时 — 请检查: $(COMPOSE) logs api"; \
	exit 1

_check-ports:
	@echo "==> 检查端口占用 (PORT=$(PORT), REDIS_PORT=$(REDIS_PORT))..."
	@conflict=0; \
	for p in $(PORT) $(REDIS_PORT); do \
		pids=$$(lsof -ti :$$p -sTCP:LISTEN 2>/dev/null || true); \
		if [ -n "$$pids" ]; then \
			echo "❌ 端口 $$p 被占用:"; \
			for pid in $$pids; do \
				name=$$(ps -p $$pid -o comm= 2>/dev/null || echo "unknown"); \
				echo "   PID $$pid ($$name)"; \
			done; \
			conflict=1; \
		fi; \
	done; \
	if [ $$conflict -eq 1 ]; then \
		echo ""; \
		echo "提示: 使用自定义端口启动: PORT=8080 REDIS_PORT=16379 make up"; \
		exit 1; \
	fi; \
	echo "==> 端口可用"

# ============================================================
# 用户命令
# ============================================================

# 启动 (完整流程: 停止 → 端口检测 → 构建 → 启动 → 清理 → 健康检查)
up: _stop _check-ports _clean-volumes
	@echo "==> 构建并启动 (PORT=$(PORT), REDIS_PORT=$(REDIS_PORT))..."
	$(COMPOSE) build
	$(COMPOSE) up -d
	@$(MAKE) --no-print-directory _flush-celery
	@$(MAKE) --no-print-directory _wait-healthy
	@$(MAKE) --no-print-directory _bridge-auto-start
	@echo "✅ 启动完成"
	@$(MAKE) --no-print-directory status

# 停止并清理 (优雅等待 30s, 含桥接服务)
down:
	$(COMPOSE) down --remove-orphans -t 30
	@lsof -ti :19821 | xargs kill 2>/dev/null || true
	@echo "✅ 已停止"

# 重启 (保留镜像，清理 Celery 队列)
restart: _stop _check-ports _clean-volumes
	@echo "==> 启动 (PORT=$(PORT), REDIS_PORT=$(REDIS_PORT))..."
	$(COMPOSE) up -d
	@$(MAKE) --no-print-directory _flush-celery
	@$(MAKE) --no-print-directory _wait-healthy
	@echo "✅ 重启完成"
	@$(MAKE) --no-print-directory status

# 全量重建 (no-cache + 清理 Celery 队列)
rebuild: _stop _check-ports _clean-volumes
	@echo "==> 全量重建 (no-cache, PORT=$(PORT), REDIS_PORT=$(REDIS_PORT))..."
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d
	@$(MAKE) --no-print-directory _flush-celery
	@$(MAKE) --no-print-directory _wait-healthy
	@echo "✅ 重建完成"
	@$(MAKE) --no-print-directory status

# 查看日志
logs:
	$(COMPOSE) logs -f --tail=50

# 查看状态
status:
	@$(COMPOSE) ps

# 独立健康检查 (可单独调用)
health: _wait-healthy

# 清理 (容器 + 无状态卷 + 镜像 + 本地缓存, 保留 redis-data)
clean:
	@echo "==> 停止并删除容器、网络..."
	$(COMPOSE) down --remove-orphans -t 30
	@echo "==> 删除无状态卷 (保留 redis-data)..."
	docker volume rm marketing_frontend-dist 2>/dev/null || true
	@echo "==> 删除构建镜像..."
	docker rmi marketing-api marketing-frontend marketing-celery-worker marketing-celery-beat 2>/dev/null || true
	@echo "==> 清理本地 Python 缓存..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ 清理完成 (redis-data 已保留)"

# 彻底清理 (包括 redis-data, 慎用)
purge: clean
	@echo "==> 删除 redis-data 卷..."
	docker volume rm marketing_redis-data 2>/dev/null || true
	@echo "✅ 全部清理完成 (含 Redis 数据)"

# Real integration tests (no mocks, real API calls)
test-integration-real:
	.venv/bin/pytest tests/integration_real/ -v -m integration_real --timeout=600
	python tests/integration_real/report_generator.py
	@echo "✅ Report: reports/integration-real-report.md"

# Qlib 数据更新 — 调试用逃生出口 (正常由 Celery task_qlib_data_update 16:15 自动执行)
# 用法: make qlib-update                              从 parquet 缓存更新
#        make qlib-update MODE=akshare SYMBOLS=600519  从 AKShare 拉取
qlib-update:
	@if [ "$(MODE)" = "akshare" ]; then \
		echo "==> 从 AKShare 更新 Qlib 数据..."; \
		.venv/bin/python scripts/qlib_data_updater.py --from-akshare --symbols $(SYMBOLS); \
	else \
		echo "==> 从 parquet 缓存更新 Qlib 数据..."; \
		.venv/bin/python scripts/qlib_data_updater.py --from-cache; \
	fi
	@.venv/bin/python scripts/qlib_data_updater.py --status

qlib-status:
	@.venv/bin/python scripts/qlib_data_updater.py --status

# ============================================================
# Claude Code 桥接服务 (宿主机后台运行)
# ============================================================

# Auto-start bridge if claude CLI is available (called from `make up`)
_bridge-auto-start:
	@if command -v claude >/dev/null 2>&1; then \
		if ! lsof -ti :19821 >/dev/null 2>&1; then \
			mkdir -p logs; \
			echo "==> 启动 Claude Code 桥接服务 (port 19821)..."; \
			nohup .venv/bin/python scripts/claude_code_bridge.py > logs/bridge.log 2>&1 & \
			sleep 1; \
			echo "✅ Bridge PID: $$(lsof -ti :19821 2>/dev/null || echo 'starting...')"; \
		else \
			echo "==> Claude Code 桥接服务已在运行"; \
		fi; \
	else \
		echo "==> 跳过 Claude Code 桥接 (claude CLI 未安装)"; \
	fi

bridge-start:
	@mkdir -p logs
	@echo "==> 启动 Claude Code 桥接服务 (port 19821)..."
	@nohup .venv/bin/python scripts/claude_code_bridge.py > logs/bridge.log 2>&1 &
	@sleep 1
	@echo "✅ Bridge PID: $$(lsof -ti :19821 2>/dev/null || echo 'starting...')"

bridge-stop:
	@echo "==> 停止 Claude Code 桥接服务..."
	@lsof -ti :19821 | xargs kill 2>/dev/null || echo "Bridge not running"
	@echo "✅ Bridge stopped"

bridge-status:
	@curl -s http://localhost:19821/health 2>/dev/null | python3 -m json.tool \
		|| echo "Bridge not running"

# ============================================================
# 离线演示 / Offline demo (no Docker, no API keys, no network)
# ============================================================

demo:
	@echo "▶ v2 回测离线演示（无需 Docker / API Key / 网络）"
	@echo "  v2 backtest on bundled sample data — no Docker, API keys, or network."
	@echo ""
	@$(PYTHON) -m scripts.backtest_v2 --csv scripts/sample/demo_ohlcv.csv --no-regime
	@echo ""
	@echo "下一步 / Next: 用真实数据跑 universe 回测："
	@echo "  $(PYTHON) -m scripts.backtest_v2_universe --start 20190101 --end 20241231"
	@echo "完整启动 / Full stack:  make up   ·   文档/docs: docs/how-it-works.md"

# 帮助信息
help:
	@echo ""
	@echo "Docker Compose 管理命令"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  make demo      一键离线演示 (无需 Docker/API Key/网络)"
	@echo "  make up        构建并启动所有服务 (默认)"
	@echo "  make down      停止所有服务 (优雅等待 30s)"
	@echo "  make restart   重启 (保留镜像)"
	@echo "  make rebuild   全量重建 (no-cache)"
	@echo "  make logs      查看日志 (实时, 最近 50 行)"
	@echo "  make status    查看容器状态"
	@echo "  make health    等待 API 健康检查通过"
	@echo "  make clean     清理容器+镜像+缓存 (保留 Redis)"
	@echo "  make purge     彻底清理 (含 Redis 数据)"
	@echo "  make help      显示此帮助"
	@echo ""
	@echo "端口配置 (默认值)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  PORT=80          Nginx 端口"
	@echo "  REDIS_PORT=6379  Redis 端口"
	@echo ""
	@echo "  示例: PORT=8080 make up"
	@echo "  示例: PORT=8080 REDIS_PORT=16379 make up"
	@echo ""
	@echo "Claude Code 桥接服务"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  make bridge-start   启动桥接服务 (后台, port 19821)"
	@echo "  make bridge-stop    停止桥接服务"
	@echo "  make bridge-status  查看桥接服务状态"
	@echo ""
	@echo "Qlib 调试 (正常由 Celery 自动执行)"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "  make qlib-status                              查看数据状态"
	@echo "  make qlib-update                              从 parquet 缓存更新"
	@echo "  make qlib-update MODE=akshare SYMBOLS=600519  从 AKShare 拉取"
	@echo ""
