# 05 · 前端四页

## 导航

`AppShell` 新增四入口：模型训练 `/models`（RobotOutlined）、策略管理 `/strategies`（AimOutlined）、回测分析 `/backtests`（LineChartOutlined）、任务中心 `/jobs`（OrderedListOutlined）；父级路径高亮同步扩展。

## 1. `/models` + `/models/[id]`（模型训练）

**列表**：名称（→详情）、项目、数据集、算法 Tag、状态 Tag（未训练/训练中/已训练/失败）、因子数、最近训练（job 状态 Tooltip）、创建人、更新时间；`model.write` 才显示「新建模型」。

**创建 Modal**：项目 → 数据集（仅已导入有区间的可选，标注 `start ~ end`）→ 名称 → 算法（catalog 下拉）→ **特征因子多选**（按项目过滤，展示 `name — expression`）→ 可选超参（n_estimators / learning_rate）。提交提示「因子表达式已快照」。

**详情页**：

- 基本信息 Descriptions（目标表达式 Tooltip / 超参 / 登记人）+ 状态 Tag；
- **提交训练**（`train.submit`）：Modal 内「自定义切分」Checkbox —— 不勾 = 后端默认 70/30；勾选则训练/验证两个 RangePicker（校验由后端 400/422 反馈）+ `max_instruments`；
- 提交后 `job_id` 进入 **2s 轮询**（`refetchInterval` 终态即停）→ 进度条 + 状态 Tag + 错误 Alert + 「查看任务日志」跳 `/jobs/{id}`；终态自动 invalidate 模型/训练记录/列表；
- **特征因子（快照）表** + 说明文案（创建时刻固化）；
- **训练记录表**：提交时间 / 状态 / `train_ic` / `valid_ic` / `valid_ir` / `artifact` / 完成时间；展开行 = **四标注**（训练|验证区间、引擎、因子数、数据源/供应商、授权依据 code、允许用途、局限 Alert）。

## 2. `/strategies`（策略管理）

- 列表：名称、项目、**信号源 Tag**（规则=动量 N 日 / 模型=紫色 + 绑定模型 Tooltip）、绑定模型、可见性（已发布 vN 绿 Tag / 私有）、创建人、更新时间；
- 创建/编辑 Modal：项目（仅创建）→ 名称/描述 → **信号源 Select**（`Form.useWatch` 联动）→ model 分支出「绑定模型」下拉（标注 `name（status）`），rule 分支出「动量回看窗口」数字框；
- **发布**：`Popconfirm` 二次确认（文案明示组织外可见）→ `POST …/publish?confirm=true`；`strategy.publish`（admin）门控，viewer 按钮不渲染；
- `strategy.write` 门控新建/编辑。

## 3. `/backtests` + `/backtests/[id]`（回测分析）

**列表**：策略（→详情）、数据集、信号源 Tag、任务状态 Tag、总收益/夏普/最大回撤（完成前「—」）、提交时间；`backtest.submit` 才显示「提交回测」。

**提交 Modal**：策略（下拉标注 模型/规则）→ 数据集（仅已导入）→ 基准（默认 SH000300）→ 可选区间 → Top-K → **费用三件套数字框（全必填，标注换算示例「万三」）** → 底部风险提示文案；提交成功直接 `router.push` 详情页。后端 409（模型未训练）/422 透传为 message.error。

**详情页**：

- 头部 Card：策略名、基准 Tag、任务状态 + `job_id` 2s 轮询（进度条）+「查看任务日志」；
- 完成后：**6 张 Statistic 卡**（总收益红绿着色、夏普、最大回撤、年化、交易次数、信号来源）；
- **净值曲线卡**：`next/dynamic` 懒加载 `NavCurveChart`（`echarts/core` 按需引入 Line/Grid/Tooltip/Legend/DataZoom + CanvasRenderer；ResizeObserver 自适应；≤1500 点降采样标注）+ 免责文案；
- **四标注卡**：① 数据区间 Descriptions ② 数据来源/授权（vendor · dataset · `license_ref` code · 允许用途）③ 费用假设表（7 项逐条，100% 透传）+ 数据区间明细表 ④ 局限说明 Alert（pre-wrap）；
- 未完成时轮询等待文案；失败/取消 → 错误 Alert 指向任务中心重试。

## 4. `/jobs` + `/jobs/[id]`（任务中心）

**列表**：任务短 ID（Tooltip 全量 + 点击进详情）、类型（中文映射：数据导入/模型训练/回测）、状态 Tag、进度条（失败 exception）、尝试 `n/max`、提交人、入队/结束时间、错误（截断 Tooltip）；类型 Select + 状态 CheckableTag 服务端过滤；整行可点；列表 3s 轻轮询。

**详情页**：

- 操作区：刷新、**取消任务**（Popconfirm，`job.control`，终态不显示）、**重试任务**（仅 failed/canceled 显示）；
- 信息 Card：类型/提交人/尝试/三个时间戳、进度条 + 显示 `since_seq=N`、错误 Alert、**payload JSON 代码块**；
- **执行日志卡**：深色等宽面板，逐行 `[seq] HH:mm:ss message`（error 红 / warn 黄），自动滚底；
  - 轮询：`GET /jobs/{id}/logs?since_seq={nextSeq}&limit=200`，**2s** `refetchInterval`，响应 `status` 终态即停；
  - 客户端累积：`items.length>0 && next_seq>nextSeq` 才推进（防重复/倒退），key 变更触发下一次拉取，天然自排空；
- 取消反馈：`canceled` → 「任务已取消」；`cancel_requested` → 「已置取消标记：任务将在下一个进度检查点停止」；重试成功 → 跳转新任务页。

## 5. 质量门

`pnpm lint`（0 error/warning）、`pnpm typecheck`、`pnpm build` 全绿（18 路由，echarts 按需引入后曲线页 First Load 412 kB）。
