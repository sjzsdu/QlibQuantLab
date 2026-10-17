# 03 · universe 股票池 + 回测导出/持仓/打印版（D6-6…D6-8 / D6-10）

## 1. universe 股票池

### 口径

数据集 `instruments/` 目录下每个池是一个文本文件（每行一个标的，`#` 开头行跳过 —— `read_universe()` 处理注释）。开发集实测：`all`=3875（含指数代码）、`csi100`=220、`csi300`=690（683 只有可用行情）、`csi500`=1540。

### 提交端（三处同名字段）

`BacktestCreateIn` / `TrainSubmitIn` / `FactorComputeSubmitIn` 均有：

```python
universe: str = Field(default="all", pattern=UNIVERSE_NAME_ANCHORED_PATTERN, max_length=64)
```

- **锚定正则** `^[a-z0-9_-]+$`：防路径穿越（池名直接拼文件名），schema 层 422/1422 拒绝非法字符；
- **默认 `all`**：不改变存量请求的行为（D6-8）；前端下拉默认 `csi300` 并提示「已排除指数代码」；
- 统一入口 `ensure_universe()`（`services/base.py`）：校验池文件存在 → 落 `params["universe"]`；**不存在 → 422 code 1011，消息列出全部可用池**（实测：`股票池不存在：csi999（可用：all, csi100, csi300, csi500）`）。

### 执行端与四标注

- qlib：`_resolve_instruments()` 读池文件与 qlib instruments 求交集，交集为空 → 明确报错（不静默退化全市场）；
- 回测/训练/因子计算的 `data_range` 均记 `universe`，前端四标注展示；`_with_universe_limitation()` 在局限说明里补充「股票池截断」口径；
- 回归保护：全市场 vs csi300 的 bit-exact 指标差异由测试固化（`total_return=-0.49177878740188563`）。

## 2. 持仓快照（D6-6）

模拟器逐步记录 `positions_history: list[tuple[date, dict[instrument, shares]]]`（每个交易日收盘快照，含空仓日 → 空 dict）。

`positions_csv()`（`adapters/compute/simulator.py`）：

- 表头 `date,instrument,shares`，UTF-**无** BOM（原始数据透传，Excel 打开由用户自理）；
- **空快照也输出表头** —— 导出端拿到空表即可明确表达「该回测无成交/无持仓」，而不是 404。

## 3. 导出路由（D6-7 / D6-10）

```
GET /api/v1/backtests/{id}/export?format=csv&section=report|positions&confirm=true
  权限：backtest.export（admin + researcher + auditor）
  缺省 confirm → 400 code 1007；section 非法 → 422
```

- **先取对象、再记审计**：对象缺失/无权限先失败，不留「假导出」留痕；成功后记 `backtest.export`（detail 含 section 与行数）；
- 报告 CSV：`section,key,value` 三列，**UTF-8 BOM**（Excel 直接双击可读中文），内容 = meta（含 universe/engine）/ param / metric / cost / split / data_range（含 `source.*` 授权链）/ `disclaimer.limitations` + `disclaimer.risk` 固定收尾行；
- 持仓 CSV：模拟器输出原样透传；
- `BacktestOut.positions_uri` 非空才允许导持仓 —— 旧回测（功能上线前）无快照，前端按钮禁用并提示原因。

## 4. 打印版（D6-10）

不做服务端 PDF（无 headless 浏览器依赖）。「打印版」= 详情页 `window.print()` + 既有 print CSS（`.print-only` 屏幕隐藏、`@media print` 隐藏侧栏/头部/操作按钮），打印件自动补页脚：报告编号 / 打印时间 / 数据集 / 固定风险声明。

## 5. 前端

- 回测详情：四标注卡 + 「导出报告 CSV」「持仓明细 CSV」（`positions_uri` 开关）+「打印版」；两个导出都走二次确认 Modal（明示会记审计）；
- 列表/详情选择器：回测列表进详情靠**策略名 link 按钮**（无整行点击导航 —— e2e 依据此实际交互编写）。

## 6. 测试

`test_universe_api.py`：四池可解析、未知池 422/1011、非法字符 422/1422、`params.universe` 落库、四标注含 universe。
`test_backtest_export.py`：无 confirm 400/1007、report BOM/表头/`disclaimer` 行/`data_range,source.vendor` 行、positions 表头与行数、`positions_uri` 门控、`backtest.export` 留痕、viewer 403。
实机（smoke §5）：csi300 2018–2019 回测 485 交易日、报告 63 行、持仓 2320 行、审计留痕累计。
