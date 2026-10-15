# QlibQuantLab 常用命令入口
# 用法：make help

.PHONY: help env install dev dev-logs dev-down ps build migrate test test-backend test-frontend lint format smoke clean \
        qlib-up qlib-data qlib-smoke backtest-smoke dataset-import-smoke

help: ## 列出所有命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

env: ## 生成 .env（已存在则不覆盖）
	@test -f .env || cp .env.example .env
	@echo ".env ready"

install: ## 安装后端(uv)与前端(pnpm)依赖
	cd backend && uv sync --all-extras
	cd frontend && pnpm install

dev: env ## 模式 A：一键启动全套依赖与应用
	docker compose up -d --build

dev-logs: ## 跟随应用日志
	docker compose logs -f backend frontend

dev-down: ## 停止（保留数据卷）
	docker compose down

ps: ## 查看容器状态
	docker compose ps

build: env ## 只构建镜像
	docker compose build

migrate: env ## 本地跑数据库迁移（不走容器）
	cd backend && uv run alembic upgrade head

test: test-backend test-frontend ## 全部测试与静态检查

test-backend: ## 后端：pytest + ruff
	cd backend && uv run ruff check . && uv run pytest -q

test-frontend: ## 前端：lint + typecheck + build
	cd frontend && pnpm lint && pnpm typecheck && pnpm build

lint: ## 静态检查（不跑测试）
	cd backend && uv run ruff check .
	cd frontend && pnpm lint

format: ## 自动格式化 + 自动修 lint
	cd backend && uv run ruff format . && uv run ruff check . --fix

smoke: ## 打健康检查（需先 make dev）
	curl -s localhost:8000/api/v1/health/ready
	curl -s localhost:3000/api/v1/health/live
	curl -s localhost:3000/api/v1/me

# ---------------------------------------------------------------- 阶段 3 · Qlib 链路（opt-in）
qlib-up: env ## 起 Qlib-Server + rabbitmq-init（vhost 授权）+ 应用栈
	docker compose --profile qlib up -d --build

qlib-data: ## 导入 qlib 数据（官方 zip 两段式；幂等，已存在则跳过）
	docker compose --profile qlib run --rm qlib-bootstrap

qlib-smoke: ## Qlib-Server 连通性 smoke（L1 WS → L2 instruments → L3 features）
	docker compose --profile qlib run --rm worker python /scripts/qlib_connectivity_smoke.py

backtest-smoke: ## 入队最小回测（先跑 qlib-data；worker 消费后 logs -f worker 观测）
	docker compose exec backend python /scripts/enqueue_backtest_smoke.py backtest

dataset-import-smoke: ## 入队数据导入任务（校验目录 + 登记台账；worker 消费）
	docker compose exec backend python /scripts/enqueue_backtest_smoke.py dataset_import

clean: ## 清理缓存与构建产物
	find backend -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/.pytest_cache backend/.ruff_cache frontend/.next
