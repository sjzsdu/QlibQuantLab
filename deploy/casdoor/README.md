# deploy/casdoor —— Casdoor 种子与镜像操作手册（dev/冒烟用）

> 面向**开发栈**（模式 A + `--profile casdoor`）。生产 Casdoor 部署指南在
> [`docs/stage7/05-casdoor-deployment.md`](../../docs/stage7/05-casdoor-deployment.md)；
> 接入实现与全链路时序在 [`docs/stage7/02-casdoor-integration.md`](../../docs/stage7/02-casdoor-integration.md)。

## 1. 起服务

```bash
docker compose --profile casdoor up -d casdoor
# 宿主 8001 → 容器 8000；启动时自动应用本目录 init_data.json（幂等）
curl -s http://localhost:8001/.well-known/openid-configuration | head -3   # discovery 200 = 健康
```

登录页：`http://localhost:8001/login`（种子 UI 管理员 `built-in/admin` / `Casdoor-Dev-Admin-123`，仅供 dev）。

切应用侧（backend → casdoor，不改 `.env`）：

```bash
docker compose -f docker-compose.yml -f docker-compose.casdoor-smoke.yml up -d backend
python3 scripts/stage7_smoke.py        # 17 项黑盒冒烟
docker compose up -d backend           # 还原（默认文件不含覆盖 env）
```

`docker-compose.casdoor-smoke.yml` 即「切 casdoor 的最小环境清单」：`AUTH_PROVIDER=casdoor` +
`CASDOOR_ISSUER=http://localhost:8001`（浏览器）+ `CASDOOR_INTERNAL_URL=http://casdoor:8000`（容器）+
client id/secret/redirect + `ORG_ID_CLAIM=owner` + `ROLE_MAP/ORG_MAP={}`（直通）。

## 2. `init_data.json` 语义

casdoor 启动时读取 `/init_data.json`（只读挂载），`initDataNewOnly=false` = **新建+更新**（幂等，双连启动零 panic 实测）。
内容清单：orgs（`admin/built-in` + `admin/qqlab`）、app `admin/app-qqlab`
（client `qqlab-dev-client` / secret `qqlab-dev-secret-0123456789abcdef`，4 条 redirectUris）、
5 个角色、5 个已知密码的用户（smoke-admin/viewer/norole/unknown 供冒烟三轮）。

**坑位规则（全部实测踩过，改文件前必读）**：

| 规则 | 说明 |
|------|------|
| org/application 的 `owner` 必须 `"admin"` | casdoor 归一 owner → admin；写组织名会触发重启 UNIQUE 约束 panic 循环 |
| 组织靠 `name` 字段 | `{"owner": "admin", "name": "qqlab"}`；用户/角色的 owner 用组织名 `qqlab` |
| `signinMethods` 字段名是 `name` | `{"name":"Password","displayName":"Password","rule":"All"}` |
| 省略 `themeData` / `formCss` | 该版本类型改为 object，给字符串会不匹配 |
| `grantTypes` 含 `password` | ROPC 仅 dev 用来探测 JWT 内嵌 claim 形态（roles 对象数组 / owner / aud 数组） |
| redirectUris 含 `/login` 落地 | post-logout 回跳依赖（宽松匹配）；缺它 logout 302 不成立 |

## 3. 镜像：manifest 探测 + digest 拉取（Docker Hub 不可达环境）

阶段 6/7 两次实测配方（镜像源以 `docker.1ms.run` 为例，可替换）：

```bash
MIRROR=docker.1ms.run
NAME=library/casbin/casdoor-all-in-one   # 镜像源的仓库路径（library/ 前缀按源规则）

# ① token（字段名因源而异：access_token / token）
TOKEN=$(curl -fsS "https://${MIRROR}/openapi/v1/auth/token?service=${MIRROR}&scope=repository:${NAME}:pull" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("access_token") or d.get("token"))')

# ② manifest list → 读目标架构 digest（必须带全部 Accept，否则拿不到多架构清单）
curl -fsS -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  "https://${MIRROR}/v2/${NAME}/manifests/latest" | python3 -m json.tool

# ③ 按 digest 拉（不吃 --platform 的错架构坑）→ retag 回规范名
docker pull "${MIRROR}/${NAME}@sha256:<目标架构digest>"
docker tag  "${MIRROR}/${NAME}@sha256:<目标架构digest>" casbin/casdoor-all-in-one:latest
```

**为什么不直接 `--platform`**：镜像源对 tag 的按平台拉取可能命中本地缓存或错发架构（阶段 6 实测拿过 arm64）；
BuildKit 即使本地有同 tag 也会出网解析 manifest —— 按 digest 拉、本地 digest 匹配才可靠。

### 已固化 digest（2026-10-18 实测）

| 镜像 | 架构 | digest |
|------|------|--------|
| `casbin/casdoor-all-in-one` | **linux/amd64**（本栈 `platform` 默认） | `sha256:ba602519188c5f5c31e77efa5b7b53dcc758bb3625122dd6e33ac5ef25c4772e` |
| `casbin/casdoor-all-in-one` | linux/arm64 | `sha256:6238df5d4b9d4a86de22b173c544fd4d766e08d41132b3eeb375c98e0ff38154` |
| `python:3.12-slim`（backend） | linux/amd64 | `sha256:2b4f19dae3a777dfc3b76730bda1e82e1f66ab2a2686fa93ca78edbfb4f04ffe` |
| `python:3.11-slim`（worker，pyqlib 0.9.7 无 arm64） | linux/amd64 | `sha256:e529028…`（阶段 5 记录，见 `docs/stage5/06-risks.md` S5-12） |
| `docker/dockerfile:1`（BuildKit frontend） | linux/amd64 | `sha256:7b32114e84ca21aeb2d6f871a0b62b3a0762193f75d9afd048ee4cbe889f3148` |
| `node:22-alpine`（frontend） | linux/amd64 | `sha256:2c752226d477b4a886378baa95b9af252be59301b725fdb0b7e15208131505a8` |

## 4. 本栈相关的行为事实（R7-2 实测回写）

对 dev 实跑镜像的探测结论（升级镜像后先跑 `scripts/stage7_smoke.py` 再上量）：

- **iss 按请求 Host 派生**（casdoor#1622）：经 `http://casdoor:8000` 兑换 token → id_token iss 为
  `http://casdoor:8000` → 平台侧 iss 白名单 = `CASDOOR_ISSUER` + `CASDOOR_INTERNAL_URL` 双收。
- `/login/oauth/authorize` **无服务端路由**（SPA 承接 query 参数）；冒烟用 `/api/login`（`type=login` →
  `type=code`）直接模拟浏览器。
- `/api/logout`（落点已注册时）**不要求 `id_token_hint`** —— 带/不带都 302 到落地页（与主干源码行为不同，
  升级必复测）。
- JWKS：RSA/RS256，kid `cert-built-in`；discovery issuer = 请求 Host。

## 5. 排查

| 症状 | 处置 |
|------|------|
| 容器反复重启 / 日志 panic UNIQUE | 种子 owner 字段踩坑（§2）；改回 `"admin"` 后 `docker compose --profile casdoor restart casdoor` |
| healthcheck 不过 | `docker logs qqlab-casdoor-1`；`curl -fsS http://localhost:8001/.well-known/openid-configuration` |
| 登录 401 授权码兑换失败 | backend 用的 `CASDOOR_INTERNAL_URL` 是否 `http://casdoor:8000`（容器网络内不可用宿主端口）；redirect_uri 逐字符一致 |
| 数据要重置 | `docker compose --profile casdoor down`（**不要带 `-v`**，会删全项目命名卷）后重新 up，种子自动重放 |
