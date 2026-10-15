# syntax=docker/dockerfile:1
# ============================================================================
# Qlib-Server 自建镜像（阶段 3）
#
# 与官方 docker_support/Dockerfile 的差异（见 qlib-server/README.md）：
#   1. 基座默认 python:3.10-slim —— 官方 continuumio/miniconda3:4.8.2 (2020, amd64)
#      在当前环境拉不到，且其 pip install git+qlib（当日 main）已无法解析；
#      选 3.10 而非 3.11：gevent<23（官方 setup.py 硬约束）在 cp310 有官方 wheel，
#      cp311 起无 wheel 必须源码编译（需 gcc + cython，构建慢且易碎）。
#      ARG BASE_IMAGE 可切其它基座（切 3.11+ 时需自补编译工具链）。
#   2. pyqlib 钉死版本（requirements.lock），不做 git+main。
#   3. 配置在**启动时**由 entrypoint.sh 用环境变量渲染，而非构建期 sed ——
#      镜像与环境解耦，compose 只改 env 即可。
#
# 运行平台：compose 里 platform: linux/amd64（Apple Silicon 走 Rosetta 2）。
# ============================================================================
ARG BASE_IMAGE=python:3.10-slim

FROM ${BASE_IMAGE} AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
# 先只拷锁文件，命中层缓存
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
# server 源码来自 vendored 快照（钉死 commit，构建不访问网络）
# --no-deps：setup.py 的 install_requires 已被 requirements.lock 完全覆盖且钉死
COPY vendor/qlib-server /tmp/qlib-server
RUN pip install --no-cache-dir --no-deps /tmp/qlib-server \
    && rm -rf /tmp/qlib-server

FROM ${BASE_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 qlibsrv
WORKDIR /app
COPY --from=builder /usr/local /usr/local
COPY vendor/qlib-server/main.py /app/main.py
COPY vendor/qlib-server/config_template.yaml /app/config_template.yaml
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /qlib_data \
    && chown -R qlibsrv:qlibsrv /app /qlib_data
USER qlibsrv
EXPOSE 9710
ENTRYPOINT ["/app/entrypoint.sh"]
