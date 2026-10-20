# 02 · 镜像发布与追溯回滚（A 项 · 发版记录）

## 1. 发版链路

```bash
# 构建并推送四个镜像（tag 自动 = sha-<git 短 sha>[-dirty]；需先 docker login）
IMAGE_PREFIX=sjzsdu make deploy-images          # = scripts/build_push_images.sh
# 产物：deploy/image-manifest.json（tag / git_sha / 每镜像 digest）—— 已 gitignore，
# 发版事实以本文件记录为准（清单每次构建覆盖）。
# 生产侧拉取：IMAGE_TAG=<tag> make deploy-pull   （tag 见 manifest 或本文件）
```

要点（脚本头注为准）：
- **tag 绑定 git 提交**：工作区有未提交改动（含构建上下文里的未跟踪文件）自动加 `-dirty`
  后缀 —— 拒绝把脏树构建冒充成某个提交；
- `--no-push` / `--only=<name,…>` 局部构建；`RETRIES` 对 docker.io 间歇 EOF 重试（3 次，
  5s/10s/15s）；`TARGET_PLATFORM=linux/amd64`（qlib-server 硬依赖 x86，Apple Silicon 交叉构建）；
- **回滚 = 用清单里的 tag（或 digest）重新 pull + up**，无需重建。

## 2. 发版记录（2026-10-19）

| 字段 | 值 |
|------|----|
| `generated_at` | 2026-10-19T07:22:57Z |
| `git_sha` | `185797d0e404df8c943c10361b2cecf222f35900`（commit `[1]`：`build_push_images.sh` 入库） |
| `git_dirty` | **true**（阶段 9 实现尚未提交时构建 → tag 带 `-dirty`） |
| `tag` | `sha-185797d0e404-dirty` |
| `tag_source` | `auto(git)` |
| `target_platform` | `linux/amd64` |

四镜像（Docker Hub `sjzsdu/*`）与 digest：

| 镜像 | ref | digest（sha256） |
|------|-----|------------------|
| backend | `sjzsdu/qqlab-backend:sha-185797d0e404-dirty` | `00ab0df2cd379c8c8e1f720ecf82af5cd721e8c788041373ac7fb1574abe2dd3` |
| frontend | `sjzsdu/qqlab-frontend:sha-185797d0e404-dirty` | `55557b0de13634885983dd1ba4adf8665d9b76d53056bd846b9e34205400483c` |
| qlib-server | `sjzsdu/qqlab-qlib-server:sha-185797d0e404-dirty` | `64e7e6c912e2b61ca5f6178c5c42a279d778ded22b4ef7ec331fef4b098d7908` |
| worker | `sjzsdu/qqlab-worker:sha-185797d0e404-dirty` | `f65b55c52f50e8b258a92197bca744e388200506a6fa9d0ff5999d0bbf99f65e` |

**digest 对账**：`docker buildx imagetools inspect` 与清单 digest 一致（阶段 9 实测；
后续复检时本机网络到 registry-1.docker.io 不可达 —— 与「docker.io 间歇 EOF/不可达」的
既有现实一致，不影响已推送事实，复检命令附下）：

```bash
docker buildx imagetools inspect sjzsdu/qqlab-backend:sha-185797d0e404-dirty | head
```

## 3. 演练栈与该 tag 的关系

- `rehearsal_up.sh` 从 manifest 读 tag 并 export（shell 环境优先于 `--env-file`）——
  **走脚本永远与 manifest 一致**（D9-3）；
- `deploy/rehearsal/env.rehearsal` 的 `IMAGE_TAG=sha-185797d0e404-dirty` 是「直接
  `docker compose --env-file` 调用」的回退值，与 manifest 同值（当前演练栈运行中的镜像）；
- `rehearsal_up.sh` 先 pull 失败不致命（回退本地已有镜像）—— docker.io 不稳时可接受。

## 4. 下次发版流程

1. 提交阶段 9 全部改动（`-dirty` 消失的前提）；
2. `IMAGE_PREFIX=sjzsdu make deploy-images` → 生成新 manifest（新 tag = `sha-<新短 sha>`）；
3. 更新 `deploy/rehearsal/env.rehearsal` 的 `IMAGE_TAG` 为新 tag（回退值同步；或依赖脚本覆盖）；
4. 本文件追加新一节发版记录（tag/git_sha/digest）；
5. `./scripts/rehearsal_up.sh down && ./scripts/rehearsal_up.sh up` 按新 tag 拉起复验。

> 注意：当前 `-dirty` tag（`sha-185797d0e404-dirty`）对应**未提交的阶段 9 实现**。
> 提交后必须按上述流程重建干净镜像 —— 脏树 tag 不应进入正式环境（脚本的 `-dirty`
> 后缀就是为此设计）。
