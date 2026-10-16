# 阶段 4 · 项目 / 数据 / 因子

> 一句话：**把「授权台账 → 数据集 → 导入 → 预览」的合规数据链路和「因子表达式 → 静态校验 → 版本 → 发布」的研究定义链路做成可用功能** —— API 侧纯标准库解析 qlib `dump_bin`（进程零 qlib），数据集必须挂有效授权台账才能入库，因子只做定义与校验（真实求值属阶段 5）。

## 交付物

| # | 交付物 | 状态 | 验证 |
|---|--------|------|------|
| 数据源 / 授权台账 / 数据集 CRUD + 合规链 | ✅ | `test_data_api.py`；live smoke：无有效台账 → 400/1005 |
| 数据集导入（复用 job 幂等入队 + worker 双模式回填） | ✅ | `test_worker_handlers.py`；live smoke：3875 标的回填、去重 409 |
| 预览三件套（标的 / 日历 / OHLCV，org 前缀 fail-closed） | ✅ | `test_qlib_bin.py` + API 测试；live smoke：真实 cn_data 读 SH600000 |
| 因子表达式静态校验器（词法/语法/白名单，零执行） | ✅ | `test_qlib_expr.py`；live smoke：`Evil()` → 400 |
| 因子 CRUD / 版本 +1 / 发布（`?confirm=true`） | ✅ | `test_factors_api.py`；live smoke：v1 → v2 → public |
| 项目成员管理 + 可见性切换 | ✅ | `test_project_members_api.py`；UI 冒烟 |
| 只读任务端点 `GET /jobs`、`/jobs/{id}`（导入轮询用） | ✅ | `test_jobs_api.py` |
| 前端四域页面（数据 / 数据集详情 / 因子库 / 因子详情 / 项目详情） | ✅ | lint ✓ typecheck ✓ build ✓ + 浏览器冒烟 |
| 写路径显式提交（read-your-writes） | ✅ | live smoke：创建后立即 GET 即时可见 |

## 文档导航

| 文档 | 内容 |
|------|------|
| [01-goal-and-tree.md](./01-goal-and-tree.md) | 阶段目标、决策记录（D4-1…D4-10）、文件树 |
| [02-data-compliance.md](./02-data-compliance.md) | 数据源 / 台账 / 数据集 / 导入 / 预览与合规链 |
| [03-factors-projects.md](./03-factors-projects.md) | 因子表达式校验与版本发布、项目成员与可见性 |
| [04-frontend.md](./04-frontend.md) | 前端页面与交互（含 2s 任务轮询） |
| [05-testing.md](./05-testing.md) | 测试分层、实测结果、live smoke 全记录 |
| [06-risks.md](./06-risks.md) | 已知风险（S4-1…S4-8）+ 验收清单（A4-1…A4-10）+ 偏差说明 |

## 快速验证

```bash
# 后端
cd backend && uv run ruff check src tests && uv run pytest -q   # 247 passed, 1 skipped

# 前端
cd frontend && pnpm lint && pnpm typecheck && pnpm build

# 实机（栈已起、qlib 数据已导入）
# 数据集 → 导入 → 轮询任务至 succeeded → 预览页签出现真实 OHLCV
curl -s localhost:8000/api/v1/datasets/<id>/preview?instrument=SH600000
```
