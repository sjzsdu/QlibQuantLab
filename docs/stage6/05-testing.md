# 05-testing · 实机验证记录（阶段 6）

## 1. 自动化测试基线

| 套件 | 基线 | 阶段 6 后 | 增量 |
|------|------|-----------|------|
| 后端 pytest（含 arch 45） | 304 passed + 1 skipped | **401 passed + 1 skipped**（13.2s） | +97 |
| 前端 lint / typecheck / build | ✓ | ✓（18 路由 + `/legal` 索引） | — |
| Playwright e2e | — | **11 passed**（24.9s / 23.5s，两遍） | +11 |
| `scripts/stage6_smoke.py` | — | **34/34** | +34 |

## 2. 实机 smoke（`python3 scripts/stage6_smoke.py [--e2e]`）

栈前置：`docker compose up -d`（backend :8000 / worker / qlib-server / frontend :3000）、`AUTH_PROVIDER=mock`、`COMPUTE_BACKEND=qlib`、worker 重启加载阶段 6 代码。

**登录限流预算**：脚本只用 admin + viewer 两个 profile（各 2 次 auth 命中 = 4 ≤ 5/分钟），不引入第三个 profile（auditor 登录会 429）。

### 34 项断言分节

| 节 | 断言要点（实测值） |
|----|--------------------|
| §0 队列排空 | running=queued=0 才开跑（180s 上限） |
| §1 合规文件 | meta 3 篇（terms/risk/disclaimer）标题/版本/生效齐全；terms 正文 590 字符；未知 code → 404/1003 |
| §2 审计导出 | 无 confirm → 400/1007；CSV 表头 10 列正确、209 行、含 `auth.login` 紧凑 JSON 行；`audit.export` 留痕 total=1 |
| §3 资源准备 | 数据集 active + 授权引用（Yahoo 条款）；规则策略创建；**csi999 → 422/1011 且消息列出可用池** |
| §4 因子计算 | viewer → 403/1002；qlib 计算 succeeded；ic_mean=0.031779 / ic_ir=0.179637 / coverage=0.968 / 484 日×690 只；四标注 universe=csi300+vendor+version；values_uri/ic_uri 非空；IC 曲线 484 点 |
| §5 csi300 回测 | 485 交易日 succeeded；`data_range.universe=csi300`；报告导出无 confirm → 400/1007；报告 CSV = BOM + `section,key,value` + 63 行 + `data_range,source.vendor` / `disclaimer,limitations` 行；持仓 CSV `date,instrument,shares` 2320 行；`backtest.export` 留痕 |
| §6 训练复用 | 负例（无计算记录 + reuse）→ 400/1005「无同版本的已完成计算记录…请先在因子页计算 IC」；正例 payload 含 `reuse_factor_values` + `factor_value_sources`（run/uri）；succeeded train_ic=0.129/valid_ic=-0.018/n_train=17587；`data_range.factor_value_runs==[计算 run]`；`train.submit` 审计 detail 记 reuse=True |

首跑 33/34：唯一失败是**冒烟脚本自己的断言口径**（报告 CSV 的 key 前缀写成了 `source.vendor`，实际三列结构下是 `data_range,source.vendor`）—— 改断言后两遍 34/34。产品代码零改动。

## 3. Playwright e2e

`pnpm e2e`：setup（1 登录）→ app（7 旅程复用登录态）→ auth（登录门 2 命中）。连跑两遍均 11/11。e2e **实测抓到真实 bug**（`/audit` 崩溃，见 05-frontend §2）—— 冒烟体系的直接价值证明。

## 4. 浏览器 DOM 检查（5 页）

| 页面 | 断言 |
|------|------|
| `/legal` 索引 | 3 张文档卡（meta 驱动）+ 风险 Alert |
| `/legal/terms` | 「查看全文」可达；「打印」按钮（no-print）；print-only 页脚 |
| `/legal/not-a-doc` | 404 且列出可用文档 |
| `/audit` | 修复后不再崩溃；detail 单元格渲染紧凑 JSON；导出 CSV 按钮 |
| 回测详情 `ba5eedaa…` | 四标注卡；① 数据区间；③ 费用假设（100% 透传三件套数值可见）；csi300；导出报告 CSV / 持仓明细 CSV（启用）/ 打印版 |
| 因子详情 `e5a6fb79…` | 计算 IC 按钮；运行表 3 行；点「IC 曲线」→ canvas 挂载「日度 rank-IC 曲线（…计算）」 |
| 模型详情 `6d4c3fc3…` | 训练记录展开行含「因子值来源：复用已计算的因子值（与因子页 IC 预览同源）：41603faa」+ 授权依据 |

## 5. 现场事故与处置（诚实记录）

| 事故 | 处置 |
|------|------|
| OrbStack 守护进程 hang（阶段 5 收尾） | `orbctl stop && orbctl start` 恢复全栈；worker 镜像 libgomp1 固化改为容器内热修（Dockerfile 已改，待 Docker Hub 可达重建 —— S5-12） |
| 孤儿任务 | OrbStack hang 留下 1 个 10 小时前的 `running` backtest（消费者已死）。API cancel 只能置 `cancel_requested`（需 worker 检查点确认）→ **dev 库人工收敛**：`UPDATE jobs SET status='canceled'`，后续冒烟队列排空即刻通过 |
| 登录限流 | e2e 朴素写法（每 spec 独立登录）必 429 → 三项目共享 storageState（D6-4，见 05-frontend §4）；冒烟限制为 2 profile |
| npm registry 不可达 | `registry.npmmirror.com` 可用：宿主/容器统一走 npmmirror；宿主 `pnpm build` 会破坏容器 dev server → 重建后 `docker compose restart frontend` |

## 6. 复现清单（验收人视角）

```bash
docker compose up -d --build && docker compose run --rm migrate
cd backend && uv run pytest -q          # 401 passed + 1 skipped
python3 scripts/stage6_smoke.py         # 34/34（需 :8000 栈在跑；占 4 次登录额度）
cd frontend && pnpm e2e                 # 11 passed（需 :3000 在跑；占 4 次登录额度，错峰执行）
pnpm lint && pnpm typecheck && pnpm build
```
