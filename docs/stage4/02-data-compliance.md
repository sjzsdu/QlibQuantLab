# 02 · 数据与合规链路

> 覆盖 `data_service.py`、`core/qlib_data.py`、`api/v1/data.py`、`worker/handlers/dataset_import.py`。

## 1. 三层数据模型（阶段 1 §4 的落地）

| 实体 | 关键字段 | 说明 |
|------|----------|------|
| `data_sources` | `name`(唯一) / `kind` / `vendor` / `status` | 数据从哪来；删除时若有关联数据集 → 409 |
| `data_licenses` | `data_source_id` / `license_ref` / `allowed_use` / `redistribution_allowed` / `expires_at` / `status` | **授权台账**：谁授权、授权范围、是否可再分发、有效期 |
| `datasets` | `data_source_id` / `license_id` / `qlib_region` / `freq` / `storage_uri` / 区间 / 标的数 | 具体一份数据；必须挂台账 |

**合规硬约束**（`data_service.DatasetService.create`）：
```
license 必须存在 + 属于该数据源 + status=active 且未过期
   否则 → ValidationAppError（HTTP 400 / code 1005）
```
这条链保证平台**不可能**在没有授权记录的情况下入库任何数据。台账吊销/过期后，已有数据集不受影响，但**不能再新建**引用它的数据集。

## 2. 导入链路（复用阶段 3 任务体系）

`POST /v1/datasets/{id}/import` → `DatasetService.enqueue_import` → `JobService.enqueue`（两阶段：先落库 commit，再发 MQ 消息，保证 worker 查得到 job）。

worker 侧 `dataset_import` handler **双模式**（D4-6）：
- payload 含 `dataset_id` → **回填模式**：探测该 org 的 qlib 数据目录（`COMPUTE_BACKEND=qlib` 时经 `D.features`，否则纯文件系统探测），回填 `storage_uri` / 区间 / 标的数，status pending → active。
- payload 不含 `dataset_id` → **阶段 3 种子模式**原样保留（幂等 seed 数据源/台账/数据集快照），既有 smoke 与测试零改动。

**幂等去重**：活跃态 `(org_id, payload_hash)` 唯一索引 → 重复入队 409（`JobService.enqueue` 捕获 `IntegrityError` 转 `ConflictError`）。任务完成后允许再次导入（重新探测回填）。

## 3. 预览三件套（org fail-closed）

`GET /v1/datasets/{id}/instruments|calendar|preview`。读取路径由 `_data_root` 派生并强校验：
```python
root     = (QLIB_DATA_ROOT / CurrentUser.org_id).resolve()   # 服务端派生，不接受请求传入
target   = Path(dataset.storage_uri).resolve()
target.is_relative_to(root)  else → 404 「数据目录不属于当前组织」
```

`core/qlib_data.py`（**纯标准库**，API 进程永不 import qlib）：
- 日历 `calendars/day.txt`；标的 `instruments/all.txt`（`NAME\tDISPLAY` 或裸 `NAME`）。
- 行情 `features/{inst}/{field}.{freq}.bin`：qlib `dump_bin` 按**列**存 float32，每字段一文件；实测官方 zip 为**平铺**布局，兼容旧版 `day/` 子目录（D4-5）。
- 标的目录名按 qlib 约定做小写解析（`all.txt` 记 `SH600000`，目录为 `sh600000`）。
- **尾部对齐**（D4-4）：迟到上市标的列更短，列第 0 行对应 `dates[len(dates)-len(col)]`；某日任一字段缺失则该日不出行。

**安全**：instrument / freq 走白名单正则 + `resolve()` 后强制 `is_relative_to`，杜绝 `../` 穿越（live smoke 已验证 `../../etc/passwd` → 400）。

## 4. read-your-writes（D4-8）

实机 smoke 暴露：请求级 session 由 FastAPI 依赖 teardown 提交，而 teardown 在**响应发出之后**才执行 → 「创建后立刻 GET」的下一个请求读不到（台账创建后立即 GET 404，数百 ms 后才可见）。

修复：所有变更型服务方法（源/台账/数据集/因子/项目/成员/可见性/配置）在写审计后显式 `await self._session.commit()`。审计写入本就走 `DbAuditWriter` 的独立 session，不受影响。回归：live smoke 的 `read-your-writes` 断言（创建后立即 GET）。

## 5. 审计动作（`ports/audit.py` +4）

`DATA_SOURCE_UPDATE` / `DATA_SOURCE_DELETE` / `DATA_LICENSE_UPDATE` / `DATASET_CREATE`（另有继承的 `DATA_SOURCE_CREATE` / `DATA_LICENSE_CREATE` / `DATA_LICENSE_REVOKE` / `DATASET_IMPORT`）。全部写 `audit_logs`，可在 `/audit` 页查询。
