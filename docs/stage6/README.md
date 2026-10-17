# 阶段 6 · 合规与可验证性补齐

> 一句话：**把阶段 1–5 留下的合规与可验证性欠账一次补齐** —— 审计 CSV 流式导出（二次确认 + 留痕）、RBAC 全量路由扫描、universe 股票池、回测报告/持仓导出与打印版、因子计算落库 + IC 预览、训练复用因子值（opt-in）、合规页 meta 化 + Playwright e2e 冒烟 —— 全程 API 进程依旧零 qlib，复用链路真跑 qlib。

## 交付物

| # | 交付物 | 状态 | 验证 |
|---|--------|------|------|
| RBAC 路由扫描测试（77 路由：11 公开 + 3 仅会话 + 63 守卫） | ✅ | `tests/architecture/test_route_permissions.py` |
| 审计 CSV 流式导出（keyset 分页 + confirm 闸门 + `audit.export` 留痕） | ✅ | `test_admin_and_audit.py` + `test_audit_export.py` |
| universe 股票池（提交三端 + 422/1011 + 四标注落 `data_range.universe`） | ✅ | `test_universe_api.py` + qlib 解析测试 |
| 回测导出：报告 CSV（BOM + 四标注行）/ 持仓 CSV（逐日快照）+ 打印版 | ✅ | `test_backtest_export.py` + 浏览器打印页脚 |
| 因子计算落库（`factor_compute_runs` + values.csv.gz + IC CSV + ≤1500 点 IC 曲线） | ✅ | `test_factor_compute_api.py` + `test_ic_stats.py` |
| 训练复用因子值（opt-in、版本匹配、无记录 400/1005 不静默回退） | ✅ | `test_train_reuse.py` + qlib 实机 |
| 合规页 meta 驱动（`/legal` 索引 + 详情 tab/404 全部来自 `/legal/meta`）+ 打印页脚 | ✅ | 浏览器 DOM 检查 3 页 |
| Playwright e2e（11 测试 / 8 关键旅程，共享 storageState 规避登录限流） | ✅ | `pnpm e2e` 11 passed ×2 |
| 前端修复：`/audit` detail 对象渲染崩溃（e2e 实测发现）+ 训练记录「因子值来源」展示 | ✅ | 浏览器复核 |

**测试基线：304 → 401 passed（+97）+ 1 skipped，arch 45 全绿；实机 smoke 34/34（`scripts/stage6_smoke.py`）+ e2e 11/11 + 浏览器检查 5 页。**

## 文档导航

| 文档 | 内容 |
|------|------|
| [01-goal-and-tree.md](./01-goal-and-tree.md) | 阶段目标、**11 个决策记录（D6-1…D6-11）**、范围裁剪、文件树 |
| [02-audit-export-rbac.md](./02-audit-export-rbac.md) | 审计 CSV 流式导出（keyset / confirm / 留痕）+ RBAC 路由扫描测试 |
| [03-universe-exports.md](./03-universe-exports.md) | universe 股票池口径 + 回测报告/持仓导出 + 打印版 |
| [04-factor-compute-reuse.md](./04-factor-compute-reuse.md) | 因子计算落库与 IC 预览 + 训练复用因子值（含复用面板管线） |
| [05-frontend-compliance.md](./05-frontend-compliance.md) | 合规页 meta 化、审计页崩溃修复、复用 UI、Playwright 三项目结构 |
| [05-testing.md](./05-testing.md) | 实机验证记录：smoke 34/34 + e2e 11/11 + 浏览器 5 页 + 现场事故处置 |
| [06-risks.md](./06-risks.md) | 残余风险与后续动作（worker 镜像固化、登录限流与 e2e、e2e 数据依赖） |

## 验收清单

- [x] 后端 `uv run pytest -q` → **401 passed + 1 skipped**；`ruff check` 全绿
- [x] `python3 scripts/stage6_smoke.py` → **34/34**（真实 qlib：因子计算 484 日×690 只、csi300 回测 485 日、复用训练 train_ic=0.129）
- [x] `pnpm e2e` → **11 passed**（setup 共享登录 + 8 关键旅程 + 登录门；连跑两遍均过）
- [x] 前端 `pnpm lint && pnpm typecheck && pnpm build` 全绿（18 路由 + `/legal` 索引）
- [x] 浏览器 DOM 检查：`/legal` 索引/详情/404、`/audit`（修复后不再崩溃）、回测详情（四标注/双导出/打印）、因子详情（IC 曲线）、模型详情（因子值来源）
- [x] 全部导出/复用动作均有审计留痕（`audit.export` / `backtest.export` / `train.submit detail.reuse_factor_values`）
