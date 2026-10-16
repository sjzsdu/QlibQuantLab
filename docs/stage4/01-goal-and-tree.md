# 01 · 目标与文件树

## 目标

1. **数据合规链闭环**：数据源 → 授权台账 → 数据集三层落库；没有挂有效（active 未过期）台账的数据集一律拒绝创建（400 / code 1005）。台账的创建、更新、吊销仅 `data.license.manage`（admin）。
2. **API 进程零 qlib**：数据集预览在 API 容器内用**纯标准库**解析 qlib `dump_bin` 产物（`array`/`struct` 读 float32 列文件），不 `import qlib`；架构测试强制（`test_stage4_core_modules_are_stdlib_only`）。
3. **租户边界 fail-closed**：预览/标的/日历的读取路径强制 `{QLIB_DATA_ROOT}/{org_id}/` 前缀，由服务端从 `CurrentUser.org_id` 派生，绝不接受请求传入；越界即 404。
4. **导入复用既有任务体系**：数据集导入走 `JobService.enqueue`（阶段 3 的幂等入队 + 活跃态去重 409）；worker 侧 `dataset_import` handler 支持「回填既有数据集」与「阶段 3 种子模式」双模。
5. **因子只做定义与校验**：表达式 CRUD + 静态校验（词法/语法/白名单，**不执行**）+ 版本 +1 + 发布（可见性升级 public）；真实求值 / IC 分析属阶段 5。
6. **只读任务端点**：新增 `GET /v1/jobs`、`GET /v1/jobs/{id}` 供前端轮询导入进度；完整任务中心（取消/重试/日志/SSE）属阶段 5。
7. **写路径 read-your-writes**：变更型服务方法在审计后显式 `commit`，消除「创建后立刻读」读不到的竞态。

## 阶段 4 决策记录

| # | 决策 | 理由 |
|---|------|------|
| D4-1 | 因子 = 表达式 CRUD + 静态校验 + 发布；真实计算/因子预览 → 阶段 5 | 与路线图一致；本阶段先把「定义」这条链做对 |
| D4-2 | 回测公共 API 按路线图移到阶段 5；本阶段只补只读 `/jobs` | 前端导入需要轮询；回测 API 与训练/可视化同属阶段 5 闭环 |
| D4-3 | 数据集预览 = API 只读挂载 `qlib_data` 卷 + 纯标准库 bin 解析 | 不把 qlib 引入 Web 进程；~200 行 stdlib 解析够用 |
| D4-4 | 预览对齐语义 = **日历尾部对齐**；任一字段缺失则该日不出行 | 迟到上市标的列文件更短，与 qlib `dump_bin` 一致 |
| D4-5 | bin 布局：**平铺优先** + `day/` 子目录兜底；标的目录名做小写解析 | 实测官方 zip 为平铺 `features/{inst}/{field}.{freq}.bin`；`all.txt` 记大写 `SH600000` 而目录是 `sh600000` |
| D4-6 | `dataset_import` 双模式：payload 带 `dataset_id` → 回填模式；不带 → 阶段 3 种子模式原样保留 | 阶段 3 smoke 与既有测试零改动 |
| D4-7 | 导入去重 = 活跃态 `(org_id, payload_hash)` 唯一索引 → 409 | 复用阶段 3 机制，不新增代码 |
| D4-8 | 写路径显式 `commit`（read-your-writes） | 实测暴露：请求级 session 的 teardown 在响应发出后才提交，「创建后立刻 GET」会读不到 |
| D4-9 | 因子发布 = 可见性升级 public + `?confirm=true`；表达式变更 version+1 | 两步确认写审计；版本历史可追溯 |
| D4-10 | 无新迁移 | `project_members`/`data_sources`/`data_licenses`/`datasets`/`factors` 全部来自 `0001` |

## 文件树（新增 / 改动）

```
backend/src/qqlab/
├── core/
│   ├── qlib_expr.py                    # [新增] 表达式静态校验器（stdlib）
│   └── qlib_data.py                    # [新增] dump_bin 只读解析器（stdlib）
├── ports/audit.py                      # [改] +4 actions
├── repositories/
│   ├── data.py  factor.py              # [新增] DataSource/DataLicense/Dataset、Factor
│   ├── job.py  project.py              # [改] +list()、+ProjectMemberRepository
├── schemas/
│   ├── data.py  study.py  job.py  project.py  # [新增] 阶段 4 DTO
│   └── common.py                       # [改] 移除旧 DatasetCreateIn（迁至 data.py）
├── services/
│   ├── data_service.py                 # [新增] 源/台账/数据集 + 合规 + 预览 + 显式提交
│   ├── factor_service.py               # [新增] 表达式 CRUD + 静态校验 + 版本 + 发布
│   ├── job_query_service.py            # [新增] 只读任务查询
│   └── project_service.py              # [改] +成员管理 +可见性切换 +显式提交
├── api/v1/
│   ├── data.py  factors.py  jobs.py    # [新增] 阶段 4 路由
│   └── projects.py                     # [改] +members / +visibility
└── worker/handlers/dataset_import.py   # [改] 双模式（回填 / 种子）

backend/tests/
├── unit/test_qlib_expr.py  test_qlib_bin.py          # [新增]
├── api/test_data_api.py  test_factors_api.py         # [新增]
│            test_jobs_api.py  test_project_members_api.py
├── unit/test_worker_handlers.py       # [改] +回填模式用例（独立 DB 文件）
└── architecture/test_import_boundaries.py  # [改] +stdlib-only 断言

frontend/src/
├── app/data/page.tsx                   # [新增] 数据源 / 台账 / 数据集三 Tab
├── app/data/datasets/[id]/page.tsx     # [新增] 导入 + 2s 轮询 + 三预览 Tab
├── app/factors/page.tsx  [id]/page.tsx # [新增] 因子库 / 因子详情
├── app/projects/[id]/page.tsx          # [新增] 成员管理 + 可见性
├── components/ExpressionValidator.tsx  # [新增] 表达式校验反馈组件
├── components/AppShell.tsx             # [改] +导航 +父级高亮
└── lib/types.ts                        # [改] +阶段 4 类型

docker-compose.yml                      # [改] backend +qlib_data:/qlib_data:ro
.gitignore                              # [改] 放行 frontend/src/app/data/
```
