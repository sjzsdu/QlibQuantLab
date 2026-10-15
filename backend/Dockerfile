# syntax=docker/dockerfile:1
# 多阶段：
#   base    —— 基础镜像与 uv
#   builder —— 依赖已安装（开发 compose 用 target: builder + bind mount + venv 卷）
#   runtime —— 生产运行镜像（非 root）
# Qlib 只装进 worker（阶段 3 通过 --extra qlib 区分），API 进程永远不 import qlib。

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
