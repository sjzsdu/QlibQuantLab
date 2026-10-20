# 阶段 9 · 镜像发布与生产演练

> 一句话：把系统从「可上线」推到「**发布可追溯、演练已实测、告警可回执、备份有异地、交接有手册**」——
> 镜像发布与回滚（A）、模式 B 生产栈一键演练（B）、Traefik 演练定稿与表 A 实测（C）、
> 告警链与 Grafana（D）、备份异地同步（E）、运营交接与审查缺陷修复（F）。
> 前端**零改动**；仓库 `.env` 一行未改；dev 栈全程零影响。

## 交付物

| 项 | 交付物 | 状态 | 验证 |
|----|--------|------|------|
| **A** 镜像发布 | `build_push_images.sh`（tag 绑定 git、`-dirty` 防冒充、manifest/digest 清单）+ `make deploy-images/deploy-pull` | ✅ | 四镜像推送 + digest 对账一致；发版记录 [02](./02-image-release.md) |
| **B** 演练编排 | `rehearsal_up.sh`（①–⑨ 步）+ `infra-sim` 四件套 compose + 演练 override/env | ✅ | 冷启动 ×2 迁移幂等（head=0005、20 表）；全栈 healthy；dev 栈零影响 |
| **C** Traefik 定稿 | `traefik.prod-rehearsal.yml`（v3.7.15，`serversTransport` 字段实测修正）+ 自签证书 file provider | ✅ | **表 A A1–A6 实测全过**（[stage7/03 §5.4](../stage7/03-production-deployment.md)）；dashboard 7 routers 0 errors |
| **D** 告警链 | Alertmanager + `notify_bridge.py`（通道扇出/本地 sink）+ Grafana provisioning + 演练形态 Prometheus | ✅ | 2 targets up、5 规则、`firing→resolved` 回执闭环、看板 uid `qqlab-overview`、metrics 401/200 |
| **E** 备份异地 | `sync_backups_s3.py/.sh`（自动建桶、sha256 对账、显式失败语义） | ✅ | 演练 MinIO 完整回环（推/幂等/列/拉回/错误注入）；ruff 全绿 |
| **F** 运营交接 | 本七件套 + 表 A 回填 + 判据修正 + stage1/08 台账回写 + 审查缺陷修复 | ✅ | 3 阻断缺陷 + 卫生项全修（[06](./06-risks.md) §2）；ruff/pytest/bash -n/compose config 回归 |

**A6 定性（阶段 9 核心发现）**：worker 取数走**本地共享卷**，qlib-server 不在数据路径上
（证伪实验钉死，[stage1/06 §8.6](../stage1/06-qlib-integration.md)）；原判据「worker 日志出现
`calendar_response`」双层不可达成 → 新判据（事件往返 + `qlib_server_probe ok=true` + 真实回测）
已实测达成（[03](./03-rehearsal-validation.md) §4）。

## 文档导航

| 文档 | 内容 |
|------|------|
| [01-goal-and-tree.md](./01-goal-and-tree.md) | 阶段目标、决策记录（D9-1…D9-7）、范围裁剪、文件树 |
| [02-image-release.md](./02-image-release.md) | A 项发版链路与**发版记录**（tag/digest 对账、回滚、下次发版流程） |
| [03-rehearsal-validation.md](./03-rehearsal-validation.md) | B/C 项编排①–⑨与详细验证表、**A6 定性证据链**、R11 复验、事故处置 |
| [04-alerting-backup.md](./04-alerting-backup.md) | D 项告警链架构与实测、E 项备份异地脚本与回环 |
| [05-operations-runbook.md](./05-operations-runbook.md) | F 项运维手册：演练栈操作、cron、**WS/轮询语义记录**、告警 SOP、发版速查 |
| [06-risks.md](./06-risks.md) | R9/R11 状态、**审查缺陷修复记录**、新登记 S9-1…S9-6 |

## 验收清单

- [x] 表 A（R9）A1–A6 演练栈实测全过，回写 stage7/03 §5.4（原「待运维环境执行」清除）
- [x] `rehearsal_up.sh` 冷启动 ×2 迁移幂等（动态 head=0005、20 表）+ 全栈 healthy
- [x] 真实回测/数据导入 succeeded/100；事件往返经 Traefik 1.9s status=0（180 交易日）
- [x] 告警 firing→回执→resolved 闭环；Grafana 看板/数据源 provisioning 生效
- [x] 备份异地回环全过（含失败语义 exit=2 / S3UploadFailedError 注入）
- [x] 审查 3 阻断缺陷 + 卫生项全修（gitignore / CI working-directory / MODE bug / A6 断链 …）
- [x] 台账回写：stage1/08 R9/R11 状态单元格 + README 进度表阶段 9 行
- [x] 回归：backend `ruff` + `pytest` 全量、改过的 `.sh` 均 `bash -n`、两栈 `compose config` 校验
