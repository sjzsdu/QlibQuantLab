---
title: 因子
sidebar_label: 因子
description: 因子指南：表达式语法与白名单、静态校验、版本号规则、发布、IC 计算任务与 rank-IC 曲线、权限与错误码。
---

# 因子

因子（Factor）在这个平台里是**一条表达式 + 一个版本号**。表达式落库前会被静态校验，不是「先存进去再说」。

![因子库列表](/img/screens/factors.webp)

## 新建因子

在 `因子` 页点 **新建因子**，选项目、填名称、写表达式。

| 字段 | 说明 | 约束 |
| --- | --- | --- |
| `project_id` | 所属项目 | 必填，必须是你有权限的项目 |
| `name` | 因子名，如 `5 日反转` | 必填，≤200 字符 |
| `expression` | 表达式，如 `Ref($close, 5) / $close - 1` | 必填，≤500 字符 |
| `factor_type` | 类型 | 默认 `expression` |
| `description` / `params` | 描述与参数 | 可空 |

## 表达式语法

平台只接受 qlib 表达式的一个**子集**，其余一律在静态校验阶段拒绝。

### 允许

| 类别 | 允许的取值 |
| --- | --- |
| 字段 | `$open` `$high` `$low` `$close` `$volume` `$factor` `$vwap` |
| 字面量 | 整数 / 小数 / 负数 |
| 运算 | `+ - * /` 与比较 `> < >= <=` |
| 函数 | `Ref` `Mean` `Std` `Max` `Min` `Sum` `Rank` `MedRank` `Quantile` `Argmax` `Argmin` `Abs` `Sign` `Log` `Power` `If` `Gt` 等（参数个数有约束） |
| 其他 | 括号嵌套（≤10 层）、`None` 作为默认参数（如 `Rank($close, None)`） |

### 不允许（会被明确拒绝）

- 字符串字面量；
- 属性访问 `a.b`、下标 `a[0]`；
- 赋值、分号、多语句；
- 长度 > 500 字符，或嵌套 > 10 层。

:::note 静态校验不保证数值意义
校验器只保证**结构合法**：字段拼错、函数参数个数不对会在这一步拦下；但「这个因子的经济含义成不成立」它不负责。`$vwap` 在缺少该列的数据集上会在执行期报错，静态层不拦。
:::

### 单独校验表达式（不落库）

```bash
curl -s -X POST localhost:8000/api/v1/factors/validate \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" -b cookies.txt \
  -d '{"expression": "Ref($close, 5) / $close - 1"}'
```

返回 `valid`、`errors`（逐条原因）、以及解析出的 `fields` 与 `functions` —— 后者适合在前端做「这个因子用到了什么」的提示。

## 版本号

**表达式一变更，`version` 自动 +1**。改名、改描述、改参数都不会。

这条规则是「可复现」的基础：回测与训练记录里引用因子时会带上快照，所以你能回答「这份结果用的是哪一版表达式」。

## 发布因子

把因子可见性切到 `public`：`POST /api/v1/factors/{id}/publish?confirm=true`，**仅 admin**。

发布不是「上线」，它只是让因子在本组织内可被发现；真正对外暴露需要另外的决策。

## 计算 IC

### 提交

在因子详情页提交计算任务（或走接口），参数：

| 参数 | 说明 |
| --- | --- |
| `dataset_id` | 在哪个数据集上算，必填 |
| `start_date` / `end_date` | 区间；缺省用数据集自身区间（同一套夹紧校验） |
| `universe` | 股票池，默认 `all`（全市场，含指数代码） |
| `max_instruments` | 标的截断，0 = 全量；小样本预览用 |

```bash
curl -s -X POST localhost:8000/api/v1/factors/$FID/compute \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" -b cookies.txt \
  -d '{"dataset_id": "'$DSID'", "universe": "csi300", "max_instruments": 50}'
```

提交后得到一条计算记录（`factor_compute_runs`）与一个任务 id。任务状态通过 `GET /api/v1/jobs/{id}` 轮询。

### 看结果

```bash
curl -s "localhost:8000/api/v1/factors/$FID/compute-runs" -b cookies.txt
curl -s "localhost:8000/api/v1/factors/$FID/compute-runs/$RID/ic-curve" -b cookies.txt
```

`metrics` 里的字段：

| 指标 | 含义 |
| --- | --- |
| `coverage` | 因子有值的标的占比 |
| `ic_mean` | 日度 rank-IC 均值 |
| `ic_std` | 标准差 |
| `ic_ir` | `ic_mean / ic_std` |
| `ic_positive_ratio` | IC 为正的天数占比 |
| `n_days` | 参与统计的交易日数 |

`ic-curve` 返回 `[[date, ic], ...]`，降采样到 ≤1500 点（`downsampled` 会告诉你是否降过），但汇总指标基于全量数据和。

:::caution 指标不是结论
IC 高不高只说明「这个因子在这段数据上和未来收益的秩相关」，不构成任何投资建议。样本外表现、费用、容量都还没进来 —— 那是回测该做的事。
:::

## 权限速查

| 动作 | admin | researcher | viewer | auditor |
| --- | --- | --- | --- | --- |
| 读因子 | ✅ | ✅ | ✅ | ✅ |
| 新建 / 编辑 / 删除 | ✅ | ✅ | — | — |
| 提交计算 | ✅ | ✅ | — | — |
| 发布（public） | ✅ | — | — | — |

删除因子需要 `?confirm=true`；发布同理。

## 常见错误码

| code | 在这里的含义 | 怎么办 |
| --- | --- | --- |
| `1005` | 表达式校验失败（字段不在白名单、参数个数不对、超长） | 看 `data.errors` 逐条修 |
| `1011` | 入参不可处理（如区间超出数据集范围、`universe` 不存在） | 用数据集的 `calendar` / `universes` 接口核对 |
| `1009` | 依赖不可用（worker 或存储没起来） | 检查任务状态与 `docker compose ps` |
| `1007` | 高危操作缺 `?confirm=true` | 补参数 |

## 相关

- [核心概念 · IC](/docs/concepts#ic)
- [项目](/docs/guides/projects)
- [回测](/docs/guides/backtests) —— 因子的下游消费者
