---
title: 回测
sidebar_label: 回测
description: 回测指南：策略与信号源、提交参数、费用三件套必填的含义、四标注、净值曲线、CSV 导出与审计、权限与错误码。
---

# 回测

回测是策略在某个数据集上的一次具体执行。这个平台对回测的核心要求是**可复核**：每个结果都必须带齐「数据区间、引擎、费用、局限性」。

## 先有策略

回测必须指定策略（`strategy_id`）。策略描述「怎么用信号下单」，两种信号源：

| `signal_source` | 含义 | 关键参数 |
| --- | --- | --- |
| `rule` | 纯规则信号（如 N 日动量排序） | `lookback`（1–250，默认 20） |
| `model` | 用训练好的模型出信号 | `model_id` 必填（`signal_source=model` 时缺它就是校验失败） |

策略属于某个项目，也具有 `visibility` 与 `version`。发布策略（`strategy.publish`）是 admin 专属的高危动作。

## 提交回测

在 `回测` 页点 **提交回测**。表单字段与接口一一对应：

| 参数 | 说明 | 约束 |
| --- | --- | --- |
| `strategy_id` | 策略 | 必填 |
| `dataset_id` | 数据集（必须是已导入完成的） | 必填 |
| `benchmark` | 基准 | 默认 `SH000300` |
| `start_date` / `end_date` | 区间；可空 = 数据集全区间 | 起不能晚于止 |
| `topk` | 持仓数量 | 1–500，默认 50 |
| `max_instruments` | 标的截断（0 = 全量） | 预览/冒烟时用 |
| `universe` | 股票池；`all` = 全市场 | 必须在数据集的 `instruments/` 下存在 |
| `cost_config` | 费用三件套 | **缺失即 422** |

```bash
curl -s -X POST localhost:8000/api/v1/backtests \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" -b cookies.txt \
  -d '{
    "strategy_id": "'$SID'",
    "dataset_id": "'$DSID'",
    "benchmark": "SH000300",
    "topk": 50,
    "universe": "csi300",
    "cost_config": {
      "commission_rate": 0.0003,
      "slippage_value": 5,
      "impact_rate_per_million": 0.0001
    }
  }'
```

### 费用三件套为什么必填

| 字段 | 含义 | 为什么不能有默认值 |
| --- | --- | --- |
| `commission_rate` | 佣金费率（按成交额） | 不同券商差异可达数倍 |
| `slippage_value` | 滑点（基点） | 直接决定「回测能不能成交在这个价」 |
| `impact_rate_per_million` | 冲击成本（费率/成交额） | 小市值 + 大资金最容易在这里失真 |

平台把这三项 **100% 透传**给模拟器，不用任何「qlib 默认值」兜底 —— 因为一份不写清费用假设的回测报告，数字再漂亮也无法复核。其余费率（`min_commission`、`settlement_fee_rate`、`stamp_duty_sell`）有交易所常规默认值，可覆盖。

## 结果

回测详情返回 `metrics`、`data_range`、`limitations`、`cost_config` 与 `split_config`，以及产物 URI（曲线、持仓明细）。

### 净值曲线

```bash
curl -s "localhost:8000/api/v1/backtests/$BID/curve" -b cookies.txt
```

返回 `[[date, nav], ...]`，降采样到 **≤1500 点**（`downsampled` 标明是否降过），足够前端图表直接消费。

### 四标注

| 标注 | 内容 |
| --- | --- |
| 数据区间与来源 | 起止日期 + 数据集引用的授权台账 |
| 引擎 | `stub`（合成数据）或 `qlib`（真实取数） |
| 费用 | 三件套 + 其余费率 |
| 局限性 | 这次回测没覆盖的部分（样本外、幸存者偏差、流动性…） |

四标注不是可选项：它跟着结果一起返回，导出报告时也会带上。

### 导出

```bash
# 报告
curl -s "localhost:8000/api/v1/backtests/$BID/export?section=report&confirm=true" \
  -b cookies.txt -o report.csv

# 持仓明细（该回测有 positions 产物时才可导）
curl -s "localhost:8000/api/v1/backtests/$BID/export?section=positions&confirm=true" \
  -b cookies.txt -o positions.csv
```

导出是敏感操作：必须 `confirm=true`，需要 `backtest.export` 权限（admin / researcher / auditor），**每次导出都会写一条审计**（动作、区间、字节数、request_id）。

:::caution 不要把回测结果当预测
回测是「给定数据、给定参数、给定费用假设」下的历史统计呈现。它不构成投资建议，也不代表未来收益。发布任何基于回测的结论前，请先读 [风险提示](/legal/risk)。
:::

## 权限速查

| 动作 | admin | researcher | viewer | auditor |
| --- | --- | --- | --- | --- |
| 读回测与曲线 | ✅ | ✅ | ✅ | ✅ |
| 提交回测 | ✅ | ✅ | — | — |
| 导出 CSV | ✅ | ✅ | — | ✅ |

## 常见错误码

| code | 在这里的含义 | 怎么办 |
| --- | --- | --- |
| `1005` | 缺费用三件套、`topk` 越界、区间颠倒 | 看 `message` 里点名的字段 |
| `1011` | `universe` 不存在、区间超出数据集范围 | 先查数据集的 `universes` / `calendar` |
| `1007` | 导出缺 `confirm=true` | 补参数 |
| `1009` | 计算依赖不可用（worker / qlib-server） | 看任务状态与 worker 日志 |
| `1004` | 数据集还没导入完成就想回测 | 等导入任务 `succeeded` 再提交 |

## 相关

- [核心概念 · 费用三件套与四标注](/docs/concepts)
- [因子](/docs/guides/factors)
- [部署（模式 A / B）](/docs/deployment) —— 生产环境里 worker 的并发与资源
