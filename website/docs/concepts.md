---
title: 核心概念
sidebar_label: 核心概念
description: QlibQuantLab 的术语表与对象关系：组织、项目、数据源与授权台账、数据集、因子、模型、策略、回测、任务、universe、四标注、费用三件套、IC。
---

# 核心概念

平台里的名词不多，但每个都对应一个真实约束。这一页是后面所有模块指南的前置阅读。

## 对象关系一览

```text
组织 (org)
 └── 项目 (project)                     ← 可见性 private / org / public
      ├── 数据集 (dataset) ── 必须挂 ── 数据源 (data_source)
      │        └── 标的 / 股票池 / 交易日历
      ├── 因子 (factor)                 ← 表达式 + 版本号
      ├── 模型 (model)                  ← 引用因子，创建时快照表达式
      │        └── 训练 (training_run)
      ├── 策略 (strategy)
      └── 回测 (backtest)               ← 策略 + 数据集 + 费用三件套
                └── 净值曲线 / 持仓明细 / 四标注

任务 (job) —— 导入 / 计算 / 训练 / 回测统一入队，带日志与状态
审计 (audit_log) —— 写入、导出、删除留痕，与 request_id 串联
```

## 组织（Organization）

多租户的边界。**所有业务表都带 `org_id`**（15 张，缺一不可，架构测试强制），而 `org_id` 只来自会话 —— 客户端无法通过参数切换组织。跨组织的读、改、删统一返回 `404`，而不是 `403`：不泄露「这个 id 是否存在」。

## 角色与权限

四种角色，对应 29 项权限：

| 角色 | 能做什么 | 典型账号 |
| --- | --- | --- |
| `admin` | 全部，含删除、发布、可见性切换、授权台账变更、成员管理 | 平台负责人 |
| `researcher` | 研究链路写入：项目 / 数据 / 因子 / 模型 / 训练 / 回测 / 任务控制 | 研究员 |
| `viewer` | 只读（项目、数据、因子、模型、策略、回测、任务、法务） | 观察者、外部评审 |
| `auditor` | 只读 + 审计查看与导出 | 合规 / 风控 |

几条硬规则：

- **高危动作仅 admin，且必须二次确认**：`project.delete`、`resource.delete`、`factor.publish`、`strategy.publish`、`project.visibility`。二次确认的实现是显式的 `?confirm=true`，漏了就 422。
- **导出也是权限**：`backtest.export` / `audit.export` 面向 admin、researcher、auditor，且每次导出都会写入一条审计。
- 前端不自己判断权限：页面渲染与按钮可见性都来自 `GET /api/v1/me/permissions`。

## 项目（Project）

研究内容的最小容器。新建默认 **private**，此外还有 **org**（组织内可见）与 **public**。项目成员按 `viewer` / `researcher` / `admin` 单独授权，成员必须是本组织用户。

> 项目可见性切换与删除都是 admin + 二次确认。这不是为了折腾你，而是防止一次误点让整个团队的策略对外可见。

## 数据源（Data Source）与数据授权台账（Data License）

平台不相信「我记得这个数据可以用」。要让数据进入平台，必须先回答两个问题：

1. **它从哪来** —— 数据源：名称、类型（`market` / 其他）、厂商、主页、备注。
2. **我能用它做什么** —— 授权台账：引用哪份协议（`license_ref`）、允许用途（`allowed_use`）、是否允许再分发（`redistribution_allowed`）、授予方与授予时间、失效时间（`expires_at`）、凭证 URI（`evidence_uri`，指向合同或邮件存档）。

台账是**强制的**：创建数据集时必须挂一份**有效**台账（未过期、未吊销），否则创建失败。台账只有 admin 能登记与变更，续期和吊销都会留审计。

## 数据集（Dataset）

一份可被计算引用的行情数据，绑定「数据源 + 授权台账 + 项目 + 频率 + 区域」。

- 数据本体由**导入任务**写入对象存储，进度通过 `GET /api/v1/jobs/{id}` 轮询；
- 数据集可以只读解析出标的列表、可用股票池（`instruments/*.txt`）、交易日历与 OHLCV 预览 —— 这些都不触发计算。

## 因子（Factor）

一条表达式，加上名字、类型、描述与参数。

- 落库前做**静态校验**：语法、字段白名单、函数白名单。校验接口是独立的（`POST /api/v1/factors/validate`），不落库；
- **表达式一变更，版本号 +1**。这条规则让「这份回测用的到底是哪版因子」有据可查；
- 因子可发布（`visibility → public`，仅 admin + 二次确认）；
- 因子可以提交计算任务，产出覆盖率与 IC 汇总，以及日度 rank-IC 曲线。

## 模型（Model）与训练（Training Run）

模型是「一组因子 + 一组超参 + 一个数据集」的组合。

- 创建模型时**引用因子即快照**：`factor_snapshot` 保存当时的表达式，之后改因子不会悄悄改变已有模型的含义；
- 训练是一个任务，结果包含本次运行的指标与切分配置；
- 可选算法由 `GET /api/v1/models/catalog` 下发，前端不硬编码。

## 策略（Strategy）与回测（Backtest）

策略描述「怎么用信号下单」（例如动量 topk），回测是策略在一个数据集上的一次具体执行。

回测请求里必须给：

| 参数 | 含义 |
| --- | --- |
| `strategy_id` / `dataset_id` | 跑哪个策略、在哪份数据上跑 |
| `start_date` / `end_date` | 区间（缺省用数据集自身区间） |
| `topk` | 持仓数量（1–500） |
| `universe` | 股票池；`all` = 全市场（含指数代码） |
| `benchmark` | 基准，默认 `SH000300` |
| `cost_config` | **费用三件套，缺一即 422** |

### 费用三件套

| 字段 | 含义 | 备注 |
| --- | --- | --- |
| `commission_rate` | 佣金费率（按成交额） | 必填 |
| `slippage_value` | 滑点（基点，`fixed_bp`） | 必填 |
| `impact_rate_per_million` | 冲击成本费率 / 成交额 | 必填 |
| `min_commission` | 最低佣金 | 默认 5.0 |
| `settlement_fee_rate` | 结算费 | 默认 0.00002 |
| `stamp_duty_sell` | 卖出印花税 | 默认 0.0005 |

三个必填项 **100% 透传**进模拟器，平台不会用「qlib 默认值」替你兜底 —— 默认值只在字段未提供时生效，而三个必填项没有默认值。

### 四标注

每份回测结果都带四标注，用来回答「这个结论是在什么前提下得出的」：

1. **数据区间与来源**：起止日期 + 数据集引用的授权台账；
2. **引擎**：`stub`（合成）还是 `qlib`（真实取数）；
3. **费用假设**：三件套与其余费率；
4. **局限性（limitations）**：这次回测没覆盖到的部分（如样本外、幸存者偏差、流动性）。

> 没有四标注的回测报告无法被复核，因此平台把它做成结果的一部分，而不是让你手写。

## 股票池（Universe）

数据集 `instruments/` 目录下的一个池名（如 `csi300`），或者 `all` 表示全市场。因子的 IC 计算、回测的选股范围都以它为准 —— 换个池子，结论可能完全不同，所以它出现在每一次计算的入参和四标注里。

## IC

信息系数（Information Coefficient），这里特指**日度 rank-IC**：每天计算因子值与次日收益的截面秩相关系数，再对时间序列汇总。

| 指标 | 含义 |
| --- | --- |
| `coverage` | 因子有值的标的占比 |
| `ic_mean` | rank-IC 均值 |
| `ic_std` | rank-IC 标准差 |
| `ic_ir` | `ic_mean / ic_std`，信息比率 |
| `ic_positive_ratio` | IC 为正的天数占比 |
| `n_days` | 参与统计的交易日数 |

曲线接口把序列降采样到 **≤1500 点**（前端图表不需要更多），但汇总指标基于全量计算。

## 任务（Job）

凡是需要算力的动作都是任务：数据导入、因子计算、训练、回测。统一四个状态：`queued` / `running` / `succeeded` / `failed`（可取消到 `cancelled`）。

- 日志是增量的：`GET /api/v1/jobs/{id}/logs` 只返回新的一段，适合轮询；
- **取消**：`queued` 直接取消；`running` 是协作式取消（worker 在检查点退出）；
- **重试**：复制原 payload 重新入队，不会复用旧任务的产物。

`QLIB_WORKER_CONCURRENCY=1` 意味着同一时刻只有一个 qlib 任务在跑，其余排队 —— 所以先看任务状态，再怀疑数据。

## request_id

统一响应信封是 `{ code, message, data, request_id }`。`request_id` 同时出现在：

- 响应头 `X-Request-ID`；
- 结构化日志的每一行；
- 审计表 `audit_logs`。

遇到问题把 `request_id` 抄下来，这三处就能对上同一次请求。

## 下一步

- [项目指南](/docs/guides/projects)
- [因子指南](/docs/guides/factors)
- [回测指南](/docs/guides/backtests)
- [部署（模式 A / B）](/docs/deployment)
