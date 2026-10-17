# 05 · 前端合规与 e2e（D6-3 / D6-4）

## 1. 合规页 meta 驱动（切片⑦）

### `/legal` 索引（新页面）

- 卡片清单、标题、版本、生效日期、摘要**全部来自 `GET /v1/legal/meta`** —— 前端零硬编码；后端新增/下线文档，前端自动跟随；
- 页首固定风险 Alert（「不构成任何投资建议」口径，与免责声明一致）。

### `/legal/[code]` 详情（重构为 meta 驱动）

- tab 列表、文档标题/版本/生效日期、未知 code 的 404 文案（列出可用文档）全部由 meta 推导 —— 原来散在组件里的写死 tab 移除；
- 「打印」按钮（`no-print`，`window.print()`）+ `.print-only` 打印页脚：文档标题/编号/版本/生效日期 + 风险声明（print CSS 与回测打印版共用口径）。

### AppShell

`LEGAL_KEYS` 收录 `/legal` 路径；侧栏「合规文本」组新增「全部文件」入口（`/legal`），既有 terms/risk/disclaimer 三项保留。

## 2. `/audit` 详情列崩溃修复（e2e 实测发现的真实 bug）

**现象**：`/audit` 页面整页崩溃（React 报「Objects are not valid as a React child {roles, provider}」）。

**根因**：后端列表 API 的 `detail` 是 **dict**（`audit_service.py`，审计语义保留结构化）；前端把 `detail` 直接塞进表格单元格渲染 —— dict 作为 React child 非法。

**修复（前端侧）**：`detail` 列改紧凑 `JSON.stringify` 渲染（`JSON.stringify(detail)`，长对象截断）；`types.ts` 的 `detail?: unknown`。**后端 dict 契约保持不动**（测试断言 dict 访问；CSV 导出另行 `json.dumps`）。

> 这是 Playwright 冒烟的第一个实战产出：单元测试测的是 API JSON（dict 合法），只有真实渲染才暴露崩溃。

## 3. 因子 IC 曲线组件

`IcCurveChart.tsx`（动态 import，ECharts）：日度 rank-IC 柱状/折线，≤1500 点由后端降采样；因子详情页选中某条计算记录（「IC 曲线」按钮 → `selectedRunId`）后才挂载图表（`enabled` 门控避免无 run 时空请求）。

## 4. Playwright e2e（D6-4）

### 配置（`frontend/playwright.config.ts`）

- `channel: "chrome"` —— 用系统 Chrome，不下载 Playwright 内核（离线/受限网络可跑）；
- `testDir: "e2e"`；**不起 webServer** —— 冒烟对象是在跑的部署栈（:3000/:8000），与 `pnpm dev` 并存；
- `timeout: 90_000`、`retries: 1`（Next dev 按需编译是唯一 flake 源，见 §5）；
- `.gitignore` += `e2e/.auth/`（共享登录态不入库）。

### 登录限流对策（三项目结构）

后端 `RateLimitMiddleware`：`RATE_LIMIT_LOGIN_PER_MIN = 5`，**所有 `/api/v1/auth/*` 每分钟每 IP 计数**（含 mock/enter）。朴素写法（每 spec 独立登录）必 429。三项目分工：

| project | 作用 | 登录命中 |
|---------|------|----------|
| `setup` | 登录一次 → 存 `e2e/.auth/state.json`（storageState） | 1 |
| `app` | `use: { storageState }` 复用 cookie；跑 02–08 共 7 个旅程 spec（`testIgnore` 掉 01 与 setup） | 0 |
| `auth` | 01-auth 门禁 spec（先跳转断言、再真实登录 2 次验菜单） | 2 |

整套 4 次命中（≤5），且 auth 项目天然排在 app 之后 → 跨 ≥2 个限流窗口，预算稳定。

### 帮助层（`e2e/helpers.ts`）

- 登录竞态处理：cookie jar 写入与 `waitForURL` 竞态下先 GET `/v1/me` 确认会话，再回列表页；
- 导航等待：`/login → GET /api/v1/auth/mock/enter (302) → /` 全链完成前不算就绪 —— URL 判定**同时排除 `/login` 与 `/api`**，导航等待 40s（dev 首编译可能 >20s）；
- `openFirstRowButton` / `openByName`：路由导航一律走**名称列 link 按钮**（实测：projects 列表**没有**整行点击进详情的交互 —— spec 注释已固化此事实）；
- 选择器作用域：`.ant-tabs-tabpane-active`（如 `/data` 默认 tab 是「数据源」，数据集 spec 先切 tab 再找元素，避免隐藏面板元素误匹配）。

### 8 条关键旅程（11 测试）

| spec | 旅程 | 关键断言 |
|------|------|----------|
| 01-auth | 登录门 | 未登录跳 `/login`；登录后菜单含项目/数据/因子/模型/策略/回测/任务/审计/合规**全部文件** |
| 02-projects | 项目列表 | 列（名称/描述/创建人）；「新建」modal 字段；无行点击导航（注释固化） |
| 03-data | 数据集详情 | tab 切「数据集」；详情页数据源/授权依据/数据区间 |
| 04-factors | 因子详情 | `s6-ma20-ic`；「计算 IC」按钮；`$close` 表达式 |
| 05-models | 模型详情 | `s6-reuse-lgb`；训练弹窗含复用 Checkbox/切分/股票池 |
| 06-strategies | 策略列表 | 列与「新建」modal 字段 |
| 07-backtests | 回测详情 | 四标注卡；① 数据区间；③ 费用假设（100% 透传）；导出报告 CSV/打印版按钮 |
| 08-legal-audit | 合规 + 审计 | `/legal` 索引卡 → 查看全文 → 打印按钮；未知 code 404；审计列表 + 导出 CSV |

## 5. e2e flake 说明

唯一 flake 源：**共享模块（如 `types.ts`）编辑后 Next dev 使整个模块图失效，首次导航触发全量重编译（可能 >20s）**。对策已内建：40s 导航等待 + `retries: 1`。本阶段实机连跑两遍 11/11（24.9s / 23.5s）。
