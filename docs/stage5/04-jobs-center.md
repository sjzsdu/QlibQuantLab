# 04 · 任务中心（日志 / 取消 / 重试）

## 1. 增量日志（D5-11，2s 轮询不做 SSE）

`GET /api/v1/jobs/{id}/logs?since_seq=N&limit=200` → `{items: [seq, level, message, created_at…], next_seq, status, progress}`：

- **worker 独立会话 `JobLogSink`**（`handlers/base.py`）：与任务主事务分离的独立 DB session，`seq = max(seq)+1`，**每行立即 commit** —— 任务主事务回滚不会吞掉已写日志；sink 自身失败只打 warning 不影响任务；
- progress 检查点顺序：查取消标记 → 心跳 → **任务 session 显式 commit** → sink 写日志；
- 前端每 2s 拉一次：`since_seq` 单调推进，客户端累积；**响应内 `status` 为终态即自动停**；`next_seq` 供下次请求；
- 权限 `job.read`（viewer 可读）；跨租户 404。

## 2. 取消（D5-12，双通道）

`POST /api/v1/jobs/{id}/cancel`（`job.control`，viewer 403）：

| 读到的状态 | 动作 | 返回 |
|------------|------|------|
| `queued` | `JobRepository.mark_canceled_if_queued`：Core `UPDATE jobs SET status='canceled' … WHERE org_id=? AND id=? AND status='queued'` + rowcount 判定（原子 CAS；`session.expire_all()` 失效身份映射）→ append_log + 审计 | `{status:"canceled"}` |
| `queued` 但 CAS 失败（worker 抢走）/ `running` | **绝不直接 UPDATE jobs**（worker 单事务持锁，S3-15 不变式）→ 只置缓存标记 `job:{id}:cancel`（TTL 21600s） | `{status:"cancel_requested"}` |
| 终态（succeeded/failed/canceled） | ConflictError | 409 |

worker 侧协作落终态（`handlers/base.py`）：

- `run_job` 取到任务后**开跑前**再查一次标记（覆盖 mark_running 之后、首个 progress 之前）；
- 每个 **progress 检查点**先查标记 → 命中抛 `JobCanceled`；
- `_honor_cancel`：清标记 → `mark_canceled`（同款 Core CAS WHERE status='running'，rowcount=0 则说明已被并发处理）→ commit → 返回 `{"canceled": True}`（**正常 ack，不进重试**）；
- 审计 detail 固化 `status_before`（CAS 前读取的值，避免 `expire_all` 后回读成新值）。

## 3. 重试（retry = 复制 payload 重新入队）

`POST /api/v1/jobs/{id}/retry`（`job.control`）：

- 仅 `failed / canceled` 可重试（`RETRYABLE`），其余 409「仅失败/已取消的任务可重试」；
- **复制原 payload + 追加 `retry_of=<原 job_id>`** → `JobService.enqueue`（hash 不同，不撞活跃态去重）→ 返回**新 job**（原任务行不变）；
- 返回 `{id: 新id, status:"queued"}`，前端跳转新任务详情页。

## 4. 读取端点（阶段 4 基础上扩展）

- `GET /jobs?kind=&status=&page=`（列表，前端 3s 轻轮询）；
- `GET /jobs/{id}`（详情：payload 全量展示、attempts、时间戳）；
- `GET /jobs/{id}/logs`（增量，见 §1）；
- 全部 org 强制过滤，跨租户 404。

## 5. 不变式对照（worker）

| 不变式 | 实现 |
|--------|------|
| 业务行单事务 + 进度检查点显式 commit | `run_job`：mark_running 立即 commit；progress 内任务 session 显式 commit |
| running 取消只走缓存 | API 侧零 running UPDATE；worker 协作检查 |
| 日志独立会话 | `JobLogSink(database, org_id, job_id)` 专用 session |
| enqueue 先 commit 再 publish | `JobService.enqueue` 沿用阶段 3；训练/回测提交再前推一步「run 行先落库」 |
