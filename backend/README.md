# qqlab-backend

QlibQuantLab 后端：FastAPI 服务（`qqlab-api`）与异步任务 worker（`qqlab-worker`）共用同一份代码、同一个镜像，通过启动命令区分。

- **API 进程绝不 import qlib**；只有 `qqlab/worker/qlib_env.py` 会（见 `docs/stage1/06-qlib-integration.md`）。
- 所有外部依赖通过环境变量注入，见仓库根目录 `.env.example`。
- 分层与端口设计见 `docs/stage1/05-ports-adapters.md`。

## 常用命令

```bash
uv sync --extra dev        # 安装依赖
uv run pytest              # 跑测试
uv run uvicorn qqlab.main:app --reload   # 本地起 API
uv run qqlab-worker        # 本地起 worker
```
