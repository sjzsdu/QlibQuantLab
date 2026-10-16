# 05 · 测试与实机验证

## 1. 测试分层

| 层 | 文件 | 覆盖 |
|----|------|------|
| unit | `test_qlib_expr.py`(5) | 词法/语法/白名单/深度长度上限/永不抛异常 |
| unit | `test_qlib_bin.py`(15) | 日历/标的/OHLCV 值与分页、尾部对齐、平铺+嵌套布局、大小写目录、路径穿越 |
| unit | `test_worker_handlers.py`(9,含新增) | `dataset_import` 回填模式（探测→回填→active）、未知数据集失败、种子模式回归 |
| api | `test_data_api.py`(17) | 源/台账/数据集 CRUD、合规校验(1005)、RBAC(1002)、跨租户 404、导入去重 409、预览三件套+穿越+org 前缀 |
| api | `test_factors_api.py`(12) | 静态校验 400、version+1、发布 confirm、跨租户 |
| api | `test_jobs_api.py`(4) | 只读列表/详情、跨租户 404 |
| api | `test_project_members_api.py`(8) | 增删成员、禁止移除自己、可见性 confirm、RBAC |
| architecture | `test_import_boundaries.py`(19,含新增) | +`test_stage4_core_modules_are_stdlib_only`：`core/qlib_expr.py`、`core/qlib_data.py` 仅 stdlib |

**结果：`uv run pytest -q` → 247 passed, 1 skipped**（阶段 3 为 183；净增 64，其中新增文件 61 条）。`ruff check` ✓。

## 2. 前端验证

```
pnpm lint ✓      pnpm typecheck ✓      pnpm build ✓（9 路由）
```
浏览器冒烟：`/data`（三 Tab+表格）、`/factors`（列表+v2/已发布标签）、`/data/datasets/[id]`（信息卡+导入按钮+三预览 Tab+真实标的表）、`/projects/[id]`（信息+可见性+成员管理）全部正常渲染。

## 3. 实机 live smoke（2026-10-16，真实 cn_data）

前置：栈全绿（backend healthy、worker `COMPUTE_BACKEND=qlib`、qlib-server healthy、`/qlib_data/dev-org/cn_data` 3875 标的）。脚本 `stage4_smoke.py`（纯 stdlib，对 `localhost:8000`）。

**结果：29 通过 / 0 失败**，覆盖：

| 链路 | 断言 |
|------|------|
| 合规链 | 建源 → 建台账 → 建数据集（pending）；跨源台账 → 400/1005；重名 → 409 |
| read-your-writes | 台账/数据集创建后**立即 GET** 即时可见 |
| 导入 | 入队 → 重复入队 409（或任务已秒完的竞态注记）→ 轮询 succeeded → 回填 `1999-11-10~2020-09-25`、3875 标的、`storage_uri=/qlib_data/dev-org/cn_data` |
| 任务端点 | `GET /jobs` 列表含当前任务；`GET /jobs/{id}` 轮询 |
| 预览 | 标的 total=3875；日历 total=4943；`SH600000` 末 3 日 OHLCV 数值合理（尾对齐、平铺布局、大小写目录） |
| 因子 | 创建 v1 private → 表达式变更 v2 → 发布 public；`Evil()` → 400；关键词搜索 |
| 负例 | `../../etc/passwd` → 400；不存在标的 → 400；数据源 id 访问数据集 → 404；viewer 建源/台账 → 403/1002；viewer 只读预览可用；未登录 → 401/1001 |
| 静态校验 | `Ref($close,5)/Mean($close,20)-1` → fields=[close] functions=[Mean,Ref] |

复现：
```bash
cd backend && uv run pytest -q                 # 247 passed, 1 skipped
python3 stage4_smoke.py                        # 栈 + qlib 数据就绪后；29/29
```

## 4. smoke 期间发现并修复的问题

1. **预览 400「缺少字段文件」**：解析器原按 `day/` 子目录找 bin，实测官方 zip 为平铺 → D4-5 修复（平铺优先 + 兜底 + 小写目录）。
2. **创建后立即 GET 404**：请求级 session teardown 在响应后提交 → D4-8 显式 commit 修复。
3. **worker AMQP 连接卡死**（宿主休眠后 `Server connection was stuck`，robust 重连未自愈）→ `docker compose restart worker` 恢复；登记为 S4-4。
