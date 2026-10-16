# 注：不写 `# syntax=` 指令 —— 该指令需联网拉取 docker/dockerfile:1 前端镜像，
# 构建机访问 registry-1.docker.io 失败（EOF）时整个构建不可用；本文件只用基础语法，
# 内置前端即可。若将来用到 heredoc/--mount 再恢复该指令。
# 多阶段：
#   base    —— 基础镜像与 uv（API 侧，Python 3.12）
#   builder —— 依赖已安装（开发 compose 用 target: dev + bind mount + venv 卷）
#   runtime —— 生产运行镜像（非 root）
#   worker-base / worker-builder / dev-worker / worker-runtime
#             —— worker 侧（Python 3.11，阶段 3 决策 #5：pyqlib 0.9.7 的
#                tables/lightgbm 在 cp311 wheel 齐全，3.12 不保证），
#                唯一安装 qlib 的镜像 —— API 镜像物理上不含 qlib。

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0
RUN pip install --no-cache-dir uv==0.12.5 \
    && useradd --create-home --uid 10001 qqlab
WORKDIR /app

FROM base AS builder
# 先只拷清单，命中层缓存
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

FROM builder AS dev
# 开发：bind mount 覆盖 src/，venv 走命名卷保持依赖
CMD ["uvicorn", "qqlab.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app/src"]

FROM base AS runtime
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/alembic /app/alembic
COPY --from=builder /app/alembic.ini /app/alembic.ini
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
RUN chown -R qqlab:qqlab /app
USER qqlab
EXPOSE 8000
CMD ["uvicorn", "qqlab.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ============================================================================
# worker 侧（Python 3.11 + qlib extra）—— 唯一安装 qlib 的镜像
# ============================================================================
FROM python:3.11-slim AS worker-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0
# .python-version 钉的是 3.12（API 侧），worker 用 UV_PYTHON 覆盖为 3.11
ENV UV_PYTHON=3.11
# libgomp1：lightgbm 训练的 OpenMP 运行时（阶段 5 实机踩坑：缺库 → libgomp.so.1 not found）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.5 \
    && useradd --create-home --uid 10001 qqlab
WORKDIR /app

FROM worker-base AS worker-builder
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --extra qlib --no-install-project
COPY . .
RUN uv sync --frozen --no-dev --extra qlib
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

FROM worker-builder AS dev-worker
# 开发：bind mount 覆盖 src/，worker 专用 venv 卷（与 API 的 backend_venv 分开）
CMD ["qqlab-worker"]

FROM worker-base AS worker-runtime
WORKDIR /app
COPY --from=worker-builder /app/.venv /app/.venv
COPY --from=worker-builder /app/src /app/src
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
RUN chown -R qqlab:qqlab /app
USER qqlab
CMD ["qqlab-worker"]
