# 阶段 7 · Casdoor OIDC 接入 + 生产部署文档

> 一句话：**把「可插拔认证」的 Casdoor 分支实装并全链路实测**（授权码 + PKCE S256 + JWKS RS256 + fail-closed 身份映射 +
> 登录限流 + 审计），**补齐生产部署欠账**（模式 B 定稿、Traefik 长连接 R9、Redis 拆分 R11、Casdoor 部署指南），
> 并关闭阶段 6 必做项 **R6-2（worker 孤儿任务回收）** —— mock → casdoor 切换仍只改环境变量，前后端代码零改动。

## 交付物

| # | 交付物 | 状态 | 验证 |
|---|--------|------|------|
| `CasdoorAuthProvider` 全量实装（OIDC 授权码 + PKCE S256 无状态派生 + JWKS RS256 缓存 + claim 三形态归一） | ✅ | `test_casdoor_provider.py`（433 行）+ 冒烟 RS256/JWKS 实测 |
| 身份映射 fail-closed（空角色/未知角色 401）+ owner 组织直通 + ensure_org rename 守卫 | ✅ | `test_identity_ensure_org.py` + 冒烟轮 2 |
| 登录限流全覆盖 `/api/v1/auth*`（发起+回调各计、身份=会话 or IP） | ✅ | `test_ratelimit.py` + 冒烟三轮错峰实测 |
| 登录页 `auth_provider` 自适应（D7-10：casdoor 隐藏 mock 选择器） | ✅ | e2e 01-auth + 冒烟 `/system/info` |
| 失败登录安全事件：结构化日志补强（`audit_skipped_no_org` 含 detail/ip） | ✅ | 冒烟轮 3 docker logs 断言 |
| R6-2 worker 启动回收孤儿 `running`（`WORKER_STALE_JOB_MINUTES=10`，单副本前提写明） | ✅ | `test_worker_recover.py` 6 例 |
| gzip 字节级确定性（`mtime=0`，揪出并根治测试 flake） | ✅ | 444 × 3 连跑零 flake |
| 生产部署定稿：模式 B 验证 + R9 Traefik 静态/动态双侧 + R11 Redis 拆分 + 切换清单 | ✅ | prod compose config/build 通过（03/04） |
| Casdoor 部署指南 + dev 声明式种子（`deploy/casdoor/`） | ✅ | 双连启动幂等零 panic + 全链路冒烟 |
| stage7 冒烟 17 项（三轮错峰黑盒） | ✅ | `scripts/stage7_smoke.py` **17/17** |

**测试基线：401 → 444 passed + 1 skipped（×3 连跑）；stage6 smoke 34/34（复跑）+ stage7 smoke 17/17 + e2e 11/11（复跑）+ 前端 lint/tsc/build 全绿 + prod compose config/build 通过。**

## 文档导航

| 文档 | 内容 |
|------|------|
| [01-goal-and-tree.md](./01-goal-and-tree.md) | 阶段目标、决策记录（D7-2/3/5/7/8/10 + 评审 3 点落地）、范围裁剪、文件树 |
| [02-casdoor-integration.md](./02-casdoor-integration.md) | OIDC 全链路：端口契约、时序、PKCE 无状态派生、iss 双白名单（casdoor#1622）、JWKS、fail-closed 映射、限流、审计、登出 |
| [03-production-deployment.md](./03-production-deployment.md) | 模式 B 定稿（compose 验证）、R9 Traefik 静态+动态双侧、R11 Redis 拆分、生产切换清单（stage1/07 §4 的实测校准版）、镜像源附录 |
| [04-testing.md](./04-testing.md) | 实机记录：444×3、stage7 smoke 17/17 设计与结果、冒烟揪出的 3 个真实缺陷、dev 数据卷重置事故处置、casdoor 探测记录 |
| [05-casdoor-deployment.md](./05-casdoor-deployment.md) | Casdoor 部署：dev 种子拓扑（D7-7 双地址）、`init_data.json` 语义与坑、镜像 digest、R7-2 实测回写、生产指南、排查表 |
| [06-risks.md](./06-risks.md) | R6-2 ✅ 关闭（单副本前提）、新登记 R7-1…R7-5、R9/R11 跟踪状态 |

## 验收清单

- [x] 后端 `uv run --extra dev pytest -q` → **444 passed + 1 skipped**（三连跑）；`ruff check` 全绿
- [x] `python3 scripts/stage7_smoke.py` → **17/17**（真 Casdoor：PKCE/JWKS 验签、fail-closed、审计、logout 302 落地）
- [x] `python3 scripts/stage6_smoke.py` → **34/34**（回归：真实 qlib 因子计算/回测/复用训练）
- [x] `pnpm e2e` → **11 passed**（复跑）；前端 `pnpm lint && tsc --noEmit && pnpm build` 全绿
- [x] `docker compose -f docker-compose.prod.yml config --quiet` 通过；`build backend frontend worker` 通过
- [x] casdoor 双连启动幂等（init_data.json 零 panic）；mock ↔ casdoor 切换只用 env（`.env` 未动）
- [x] R6-2：worker 启动回收孤儿任务（单副本前提 + 阈值可配写入代码注释与 06-risks）
- [x] 生产禁 mock 守卫、casdoor 缺配置启动即失败（fail-fast）均有单测
- [x] 全程未 push；工作树改动全部落在阶段 7 声明的文件树内（01 §4）
