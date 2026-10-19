# 02 · CI 门禁与一键复种（A 项 + F 项）

## 1. `ci.yml` —— 主门禁（push / PR 触发）

三 job 并行，分工与本地等效复现方式：

### 1.1 `backend` · ruff + pytest + alembic（stub compute）

- **services**：`postgres:16-alpine` + `redis:7-alpine` + `rabbitmq:3.13-management-alpine`（自带 vhost `/qqlab`）——
  pytest 主体由 `tests/conftest.py` 覆盖成 sqlite/memory，services 服务两件事：
  1. **契约真源**：`TEST_REDIS_URL` / `TEST_MQ_URL` 指过去 → cache/MQ 契约测试对**真实实现**跑（未设置时只跑 memory 实现，这就是 fixture 工厂化的动机——两类环境同一套用例）；
  2. **alembic 步骤**：`DATABASE_BACKEND=postgres` 下 `alembic upgrade head` 对真实 PG 跑迁移链。
- 步骤：`uv sync --frozen --extra dev` → `ruff check .` → `pytest -q` → `alembic upgrade head`。
- **钉版**（D8-11）：`astral-sh/setup-uv@v10` + `version: 0.12.5`（`UV_VERSION` env 单点定义）；
  **禁 `--all-extras`** —— qlib extra 在 CI 里会挂死，只装 `--extra dev`（API 进程本就不该有 qlib）。

### 1.2 `frontend` · lint + typecheck + build

- pnpm 版本与 `frontend/Dockerfile` 钉的版本一致（12.9.1）；
- `pnpm install --frozen-lockfile` → `pnpm lint` → `tsc --noEmit` → `pnpm build`。

### 1.3 `e2e` · 干净 compose 栈 + seed + Playwright（串行）

完全复刻本机验证过的顺序（`E2E_BASE_URL=http://localhost:3000`）：

```
cp .env.example .env
docker compose up -d --build          # 模式 A 全栈，stub compute，不起 qlib profile
轮询 /api/v1/health/ready（90×2s）
scripts/seed_dev.sh --ci              # 伪造最小数据目录 + 导入 + e2e 锚点
cd frontend && pnpm install --frozen-lockfile
pnpm exec playwright test --workers=1 # setup 登录一次存 storageState，其余复用
失败时 docker compose ps + logs → artifact
```

> 本地等效复现注意：compose 文件 `name: qqlab` 会撞 dev 栈项目名，**必须** `-p <隔离名>`（D8-11，05 §4 有一次实翻车记录）。

## 2. `stage-smoke.yml` —— 重冒烟手动门禁

`workflow_dispatch` 手动触发（真 qlib 真 Casdoor 的冒烟在 PR 合并前按需手动点，不进 push 门禁——
镜像拉取与 65s×3 错峰会把每次 push 拖到 20+ 分钟）：

```
docker compose --profile qlib up -d --build   # 含 qlib-server
scripts/seed_dev.sh                            # 完整种子（真实 qlib 数据链路）
sleep 65 → stage6_smoke.py                     # 34 项
sleep 65 → 切 casdoor 覆盖 → stage7_smoke.py   # 17 项（三轮错峰，脚本自带 60s 等待）
还原 mock 态；失败时 logs artifact
```

入口与 dev 完全一致（`-f docker-compose.casdoor-smoke.yml` 临时覆盖，不改 `.env`）。

## 3. F 项：`scripts/seed_dev.sh` 一键复种

| 分档 | 作用 |
|------|------|
| （默认） | 等 ready → 导入数据 → 复种 e2e 锚点（项目/因子/模型/回测） |
| `--ci` | = `--skip-qlib-data`：`fabricate_ci_data.py` 伪造最小数据目录（calendars + instruments），**缺才写、不覆盖真实数据**，随后走正常导入+锚点 |
| `--skip-qlib-data` | 只跳过数据目录伪造/导入前置 |
| `--skip-import` | 不入队 dataset 导入 |
| `--skip-anchors` | 只做导入，不复种锚点 |

- **幂等**：锚点已存在即跳过（「项目 smoke 已存在 / 已有 succeeded 回测 2 条，跳过提交」）；
- **登录节流意识**：整脚本仅 ③ 处一次 auth 命中（限流 5/min/IP）；
- CI 侧 `SEED_API_BASE=http://localhost:8100/api/v1`（端口错开时）由环境变量注入。

## 4. D8-12：dataset probe 直走文件系统

`worker/handlers/dataset_import.py` 的数据集校验在 `COMPUTE_BACKEND != qlib` 时不再 import qlib，
直接读 `calendars/` / `instruments/` 目录结构判定 —— 延续「API 进程零 qlib import」硬约束，
也是 `--ci` 伪造目录能被导入链路消费的前提。单测 `test_dataset_probe.py` 覆盖 qlib / 非 qlib 两分支。

## 5. 干净 clone 才暴露的真缺陷：`.env.example` 行内注释

`QLIB_DATA_SYMBOLS=` 空值后面跟着行内注释 —— **compose 不剥 dotenv 行内注释**，把整段注释文本当成
变量值传进容器 → migrate 启动即崩。任何 `cp .env.example .env` 的新环境（CI 正是这么干的）都会踩。

修复：`QLIB_DATA_SYMBOLS=0` + 注释独立成行（已回归：clean clone 中 migrate 0001→0005 正常）。
教训：**`.env.example` 的行内注释只允许出现在非空值行**，且新环境必须以 `cp .env.example .env` 实跑验证。
