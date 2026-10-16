# 06 · 已知风险、验收清单与偏差说明

## 1. 已知风险（阶段 4 视角）

| # | 风险 | 影响 | 本阶段处置 | 状态 |
|---|------|------|------------|------|
| S4-1 | **预览直读容器内文件而非经 qlib 语义**：解析器读的是 `dump_bin` 原始列（复权后价格），与 `qlib D.features` 的窗口加工输出可能有差异 | 预览数值与阶段 5 因子计算口径不同 | 预览定位为「数据体检」（看原始列是否存在/量级对不对）；阶段 5 因子计算统一走 qlib D.features；文档明示口径 | ⚠️ 设计如此 |
| S4-2 | **预览依赖共享卷挂载**：API 多副本（K8s）时 `qlib_data` 需 RWX 或本地盘 | 水平扩容时预览不可用 | 单机 compose 无碍；K8s 方案属阶段 7 生产部署 | ⏳ 阶段 7 |
| S4-3 | **`qlib_data` 卷无备份策略**（继承 S3-11） | 宿主级灾难丢数据 | 阶段 5+ 评估对象存储归档 | ⏳ 后续 |
| S4-4 | **worker AMQP 连接卡死不自愈**：宿主休眠/网络抖动后 `Server connection was stuck. No frames received`，aio_pika robust 重连循环但不消费（实测需 `docker compose restart worker`） | 任务停在 queued 不被消费 | 实机 smoke 期间踩到并恢复；阶段 5 评估心跳/强制重连参数 + 任务积压告警 | ⚠️ 已知 |
| S4-5 | **活跃态去重只挡 queued/running**：任务完成后允许再次导入同一数据集 | 重复导入 = 重新探测回填（幂等，无害） | 设计如此：回填幂等，重复执行只是刷新快照 | ✅ 设计如此 |
| S4-6 | **SQLite ≠ Postgres**（继承 S3-8） | 测试通过 ≠ 生产库通过 | 生产链路阶段 5/7 用真实 Postgres 回归 | ⚠️ 已知取舍 |
| S4-7 | **静态校验 ≠ 语义正确**：白名单表达式可能语义错误（如未来函数、全 NaN） | 因子发布后计算才暴露问题 | 阶段 5 真实求值 + IC 检验补上；本阶段 UI 明示「只做静态校验」 | ⏳ 阶段 5 |
| S4-8 | **AutoComplete 交互无法被合成事件驱动**（浏览器自动化限制） | UI 冒烟覆盖不到「输入→选标的→出表」这段 | 数据链路已由 API smoke 覆盖；交互段留人工实机验收（A4-10） | ⚠️ 工具限制 |

## 2. 验收清单（阶段 4）

> 对应 `docs/stage1/08-risks-and-roadmap.md` §4 阶段 4 交付。✅ = 已用测试/命令验证。

| # | 验收项 | 状态 | 验证方式 |
|---|--------|------|----------|
| A4-1 | 数据源/台账/数据集 CRUD + RBAC（台账仅 admin） | ✅ | `test_data_api.py`；live smoke viewer 403/1002 |
| A4-2 | 无有效台账不能创建数据集（1005）；吊销/过期/跨源均拒绝 | ✅ | `test_data_api.py` 合规用例；live smoke 跨源 400/1005 |
| A4-3 | 导入入队 → worker 探测回填 → active；重复入队 409 | ✅ | `test_worker_handlers.py`；live smoke 3875 标的回填 + 去重 409 |
| A4-4 | 预览三件套真实 cn_data 可读；org 前缀 fail-closed；穿越拒绝 | ✅ | `test_qlib_bin.py` + API 测试；live smoke SH600000 OHLCV |
| A4-5 | API 进程零 qlib import（stdlib-only 断言） | ✅ | `test_stage4_core_modules_are_stdlib_only` + import 边界 19 用例 |
| A4-6 | 因子表达式静态校验（白名单/上限；非法 400） | ✅ | `test_qlib_expr.py`；live smoke `Evil()` → 400 |
| A4-7 | 表达式变更 version+1；发布 = public（`?confirm=true`） | ✅ | `test_factors_api.py`；live smoke v1→v2→public |
| A4-8 | 项目成员增删（禁移除自己）+ 可见性 confirm | ✅ | `test_project_members_api.py` |
| A4-9 | 只读 `/jobs`、`/jobs/{id}` 供轮询 | ✅ | `test_jobs_api.py`；live smoke 轮询至 succeeded |
| A4-10 | 前端四域页面可用；lint/typecheck/build 绿 | ✅ | build 9 路由 ✓；浏览器冒烟 ✓；「输入标的→出预览表」交互段待人工点验（S4-8） |

## 3. 与阶段 1/3 设计的偏差

| 项 | 原设计 | 实际 | 原因 |
|----|--------|------|------|
| 回测公共 API | S3-12 计划「阶段 4 补」 | **移到阶段 5** | 按路线图，回测 API 与训练/可视化同属阶段 5 闭环；阶段 4 只补导入所需的只读 `/jobs`。已回改 `docs/stage3/06-risks.md` S3-12 措辞 |
| bin 布局 | 初版实现按 `day/` 子目录 | 平铺优先 + 兜底 | 实测官方 GetData zip 为平铺（D4-5） |
| 提交时机 | 依赖 teardown 提交 | 写路径显式 commit | teardown 在响应后执行，读己之写竞态（D4-8） |
| `.gitignore` | `data/` 忽略运行期数据 | +`!frontend/src/app/data/` | 否则阶段 4 前端路由目录被误吞，`git status` 不可见 |
