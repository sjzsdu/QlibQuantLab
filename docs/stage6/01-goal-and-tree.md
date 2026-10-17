# 阶段 6 · 目标与决策记录

## 阶段目标

阶段 1–5 把「项目 → 数据 → 因子 → 训练 → 回测 → 可视化 → 任务」的研究闭环打通后，留下三类欠账：

1. **合规欠账**：审计只能在页面上看，不能导出存档；合规文本只有详情页没有索引；结果页缺股票池维度标注。
2. **可验证性欠账**：RBAC 只有单元/集成测试点状覆盖，没有「全量路由 × 权限」的结构性保证；没有浏览器级 e2e；因子计算与训练复用在前端不可见。
3. **范围裁剪收回**（stage-5 遗留的三项 deferral + 两项能力）：factor compute + IC 预览、报告导出 + 持仓明细、universe 股票池。

约束不变：API 进程零 qlib；业务代码只依赖 `qqlab.ports`；自定义费用 100% 透传；所有结果携带四标注；敏感动作二次确认 + 审计留痕。

## 集成点决策记录（用户已确认）

| # | 决策 | 要点 |
|---|------|------|
| D6-1 | 审计 CSV 流式导出 | `GET /audit-logs/export`；keyset 分页（`page_for_export`）边查边发不占内存；`confirm=true` 闸门（缺省 400/1007）；导出动作记 `audit.export`；前端带当前筛选条件二次确认下载 |
| D6-2 | RBAC 路由扫描测试 | `require_permission()` 给路由处理函数打 `__qqlab_permission__` 属性；架构测试遍历 FastAPI 全量路由，断言每条业务路由要么公开、要么带权限点 —— 新增路由忘挂权限直接测试失败 |
| D6-3 | 合规页 meta 驱动 | `/legal` 索引页与 `/legal/[code]` 详情页的文档清单/标题/版本/404 文案全部来自 `GET /legal/meta`，前端零硬编码；打印 = 纯客户端 `window.print()`（不做服务端 PDF），print CSS 隐藏操作按钮并补 `.print-only` 风险声明页脚 |
| D6-4 | Playwright e2e | `channel: "chrome"` 用系统 Chrome（不下载内核、离线可跑）；`testDir: frontend/e2e`；**不起 webServer** —— 冒烟对象是在跑的部署栈；三项目（setup 共享 storageState / app 复用 / auth 独立登录门）把整套登录命中压到限流阈值内（见 05-testing §4） |
| D6-5 | 因子计算落库 | `JobKind.FACTOR_COMPUTE` + `factor_compute_runs` 表（迁移 0004）；`ComputePort.compute_factor()` 双对象：`values.csv.gz`（gzip，`MAX_VALUES_ROWS=1_000_000` 上限）+ `ic.csv`（明文）；IC 统计共享于 `core/ic.py`（`MIN_DAILY_SAMPLES=5`，`ic_ir` 分母 1e-12 护栏）；同因子已有活跃任务 → 409；入队失败补偿删除 run 行 |
| D6-6 | 回测持仓快照 | 模拟器逐步记录 `positions_history`（每个交易日收盘快照）；`positions_csv()` 输出 `date,instrument,shares`（UTF-8 无 BOM，空快照也给表头，明确表达「无成交/无持仓」） |
| D6-7 | 导出路由 | `GET /backtests/{id}/export?format=csv&section=report|positions&confirm=true`；**先取对象再记审计**（导出失败不留假留痕）；记 `backtest.export`；`BacktestOut.positions_uri` 作为前端持仓按钮的开关（旧回测无快照则禁用） |
| D6-8 | universe 股票池 | `BacktestCreateIn` / `TrainSubmitIn` / `FactorComputeSubmitIn` 三处同名 `universe` 字段（锚定正则 `^[a-z0-9_-]+$`，防路径穿越）；`ensure_universe()` 统一落 `params["universe"]`；qlib 侧 `_resolve_instruments()` 解析池文件；`data_range["universe"]` + `_with_universe_limitation()` 进四标注；池名不存在 → 422/1011 且消息列出可用池；**API 默认 `all`（不改变存量行为），前端下拉默认 `csi300`（提示已排除指数）** |
| D6-9 | 训练复用因子值 | `TrainSubmitIn.reuse_factor_values: bool = False`（显式 opt-in，默认重算、行为不变）；逐因子按 `data_range["version"]` 匹配 `factor_compute_runs`（succeeded 且 values_uri 非空）；任一因子无匹配 → **400/1005（`ValidationAppError`，非 422）** 且消息可执行，**不静默回退重算**；payload 携带 `reuse_factor_values` + `factor_value_sources`；训练 run 的 `data_range` 记 `reuse_factor_values` + `factor_value_runs`；**y（标签）永远来自 qlib `D.features`，只有 X 复用** |
| D6-10 | 导出形态 | 报告 = CSV（`section,key,value` 三列，UTF-8 BOM，末尾 `disclaimer.*` 行）；持仓 = CSV 原样透传；打印版 = 浏览器打印 + print CSS 页脚；**不做服务端 PDF**（无 headless 浏览器依赖） |
| D6-11 | ops 降级项 | 因子计算的「预览」不另建任务：计算 + IC 预览 + 落库复用同一 `FACTOR_COMPUTE` 任务；报告导出先 CSV；universe 默认 `all`；运维风险只评估并写入 `06-risks.md`（worker 镜像 libgomp1 固化等 Docker Hub 恢复后再做） |

## 范围裁剪（明确不做）

- **服务端 PDF**：无 headless 浏览器依赖，打印版走浏览器（D6-10）。
- **前端按权限隐藏按钮**：RBAC 以后端为准（403 兜底），前端不做权限树（阶段 7 与 Casdoor 一起评估）。
- **e2e 的真实训练/回测提交**：e2e 只开训练弹窗验表单结构（队列时序不可控）；真实计算路径由 `stage6_smoke.py` 覆盖。
- **审计导出 ZIP/JSON 格式**：先 CSV（唯一格式），其他格式等真实需求。

## 文件树（新增/改动）

```
backend/
├── alembic/versions/0004_factor_compute_runs.py   ★ 迁移（纯 op.sa，不用 op.sa 模块属性）
├── src/qqlab/
│   ├── api/v1/audit.py            + 导出路由（confirm + keyset 流式）
│   ├── api/v1/factors.py          + compute 提交 / compute-runs 列表 / ic-curve
│   ├── api/v1/backtests.py        + export 路由（report|positions）
│   ├── core/ic.py                 ★ rank-IC / ICIR 共享统计（纯函数）
│   ├── core/qlib_data.py          + read_universe（跳过 # 注释行）
│   ├── models/study.py            + FactorComputeRun 表
│   ├── ports/audit.py · compute.py  + export_iter / compute_factor
│   ├── repositories/audit.py      + keyset 分页 page_for_export
│   ├── repositories/study.py      + FactorComputeRunRepository（succeeded_for 版本匹配）
│   ├── schemas/study.py           + FactorComputeSubmitIn / RunOut / IcCurveOut；三处 universe
│   ├── services/base.py           + ensure_universe（统一 422/1011）
│   ├── services/audit_service.py  + stream_csv 生成器
│   ├── services/backtest_service.py + 导出（先取对象再留痕）
│   ├── services/factor_service.py + 提交/列表/曲线
│   ├── services/model_service.py  + 复用解析（payload / 审计 / TrainSpec）
│   ├── worker/handlers/factor_compute.py  ★ 新 handler
│   ├── worker/handlers/train.py   + 复用面板管线（_load_reused_panel → _fetch_panel）
│   └── adapters/compute/
│       ├── qlib_compute.py        + panel_from_values_csv / slice_panel 纯函数 + compute_factor
│       ├── simulator.py           + positions_history / positions_csv
│       └── stub_compute.py        + stub 版 compute_factor（测试用）
└── tests/
    ├── architecture/test_route_permissions.py   ★ RBAC 全量路由扫描
    ├── api/test_admin_and_audit.py              M 导出用例
    ├── api/test_backtest_export.py  test_factor_compute_api.py
    ├── api/test_train_reuse.py      test_universe_api.py   ★ 新
    └── unit/test_audit_export.py test_ic_stats.py
        test_qlib_universe.py                       ★ 新

frontend/
├── playwright.config.ts           ★ 三项目配置（setup / app / auth）
├── e2e/                           ★ 9 个 spec（setup + 8 旅程）+ helpers
├── src/app/legal/page.tsx         ★ /legal meta 驱动索引
├── src/app/legal/[code]/page.tsx  M meta 驱动 tab + 打印 + print-only 页脚
├── src/app/audit/page.tsx         M detail 对象渲染修复（e2e 实测发现）
├── src/app/models/[id]/page.tsx   M 复用 Checkbox + 训练记录「因子值来源」
├── src/app/factors/[id]/page.tsx  M 计算 IC + IC 曲线 + 运行表
├── src/components/IcCurveChart.tsx ★ ECharts IC 曲线
├── src/components/AppShell.tsx    M 合规文本组 + 「全部文件」索引入口
└── src/lib/api.ts · types.ts      M CSV 下载 / 新类型

scripts/stage6_smoke.py            ★ 实机 smoke（34 项断言，可选 --e2e）
docs/stage6/                       ★ 本文档
```
