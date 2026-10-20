#!/usr/bin/env python3
"""备份异地同步（阶段 9 · E 项）—— S3 接口 + 配置驱动。

由 scripts/sync_backups_s3.sh 在 backend 运行镜像内调起（boto3 现成）。
环境变量（全部经 shell 封装注入）：
  BACKUP_S3_BUCKET / BACKUP_S3_ACCESS_KEY / BACKUP_S3_SECRET_KEY  必填
  BACKUP_S3_ENDPOINT  可选（R2/B2/MinIO 兼容端点；空 = AWS 默认解析）
  BACKUP_S3_REGION    默认 us-east-1
  BACKUP_S3_PREFIX    默认 qqlab（对象键 = <prefix>/<文件名>）
  BACKUP_MODE         push | pull | list
  BACKUP_ARG          pull 时可指定文件名（缺省 = 远端最新一个）

语义：
  push —— 幂等：已有同名对象且大小一致则跳过；上传后 head 校验大小，
          对象元数据带 sha256（异地后可校验传输完整性）。
  pull —— 拉回到 /backups/（默认取远端最新对象；覆盖前拒绝，文件名冲突即报错）。
  list —— 列远端对象（名称/大小/时间）。
任一失败 → 退出码非 0（cron/告警可感知）。
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import boto3
from boto3.exceptions import S3UploadFailedError
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

BACKUP_DIR = Path("/backups")


def _client():
    endpoint = os.environ.get("BACKUP_S3_ENDPOINT", "").strip() or None
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["BACKUP_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["BACKUP_S3_SECRET_KEY"],
        region_name=os.environ.get("BACKUP_S3_REGION", "us-east-1"),
        config=Config(signature_version="s3v4"),
    )


def _key_prefix() -> str:
    return os.environ.get("BACKUP_S3_PREFIX", "qqlab").strip("/")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_bucket(client, bucket: str) -> None:
    """push 前确保桶存在：不存在则自动建（首跑体验；403 无权限时原样抛错不静默）。

    AWS 非 us-east-1 必须带 LocationConstraint；MinIO/R2 等兼容端点不接受该字段
    → 仅当「没配自定义 endpoint 且 region 非 us-east-1」时附加。
    """
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        if status not in (404, 400):
            raise
    region = os.environ.get("BACKUP_S3_REGION", "us-east-1")
    endpoint = os.environ.get("BACKUP_S3_ENDPOINT", "").strip()
    params: dict = {"Bucket": bucket}
    if not endpoint and region != "us-east-1":
        params["CreateBucketConfiguration"] = {"LocationConstraint": region}
    print(f"[sync] 桶 s3://{bucket} 不存在 → 自动建桶（region={region}）")
    client.create_bucket(**params)


def do_push(client, bucket: str) -> int:
    dumps = sorted(BACKUP_DIR.glob("*.dump"))
    if not dumps:
        print("[sync] ! /backups 下没有 .dump —— 先跑备份", file=sys.stderr)
        return 1
    failed = 0
    for dump in dumps:
        key = f"{_key_prefix()}/{dump.name}"
        size = dump.stat().st_size
        try:
            head = client.head_object(Bucket=bucket, Key=key)
            if head["ContentLength"] == size:
                print(f"[sync] skip {dump.name}（远端已存在且大小一致）")
                continue
            print(f"[sync] ! {dump.name} 远端大小不一致（{head['ContentLength']} != {size}）→ 重传")
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise
        print(f"[sync] push {dump.name}（{size} bytes）…")
        client.upload_file(
            str(dump),
            bucket,
            key,
            ExtraArgs={"Metadata": {"sha256": _sha256(dump), "source": "qqlab-backup"}},
        )
        verify = client.head_object(Bucket=bucket, Key=key)
        if verify["ContentLength"] != size:
            print(f"[sync] ✗ {dump.name} 上传后大小不符", file=sys.stderr)
            failed += 1
        else:
            print(f"[sync] ✓ {dump.name} → s3://{bucket}/{key}（head 校验一致）")
    return 1 if failed else 0


def do_list(client, bucket: str) -> int:
    resp = client.list_objects_v2(Bucket=bucket, Prefix=_key_prefix() + "/")
    for obj in resp.get("Contents", []):
        print(f"[sync] {obj['Key']}  {obj['Size']} bytes  {obj['LastModified']}")
    if not resp.get("Contents"):
        print("[sync] 远端为空")
    return 0


def do_pull(client, bucket: str) -> int:
    name = os.environ.get("BACKUP_ARG", "").strip()
    if name:
        key = f"{_key_prefix()}/{name}"
    else:
        resp = client.list_objects_v2(Bucket=bucket, Prefix=_key_prefix() + "/")
        objects = [o for o in resp.get("Contents", []) if o["Key"].endswith(".dump")]
        if not objects:
            print("[sync] ✗ 远端没有可拉取的 .dump", file=sys.stderr)
            return 1
        key = max(objects, key=lambda o: o["LastModified"])["Key"]
    dest = BACKUP_DIR / Path(key).name
    if dest.exists():
        print(f"[sync] ✗ 本地已有同名文件，拒绝覆盖：{dest}", file=sys.stderr)
        return 1
    print(f"[sync] pull s3://{bucket}/{key} → {dest} …")
    client.download_file(bucket, key, str(dest))
    head = client.head_object(Bucket=bucket, Key=key)
    if dest.stat().st_size != head["ContentLength"]:
        print("[sync] ✗ 拉回后大小不符", file=sys.stderr)
        return 1
    meta = head.get("Metadata", {})
    if "sha256" in meta and _sha256(dest) != meta["sha256"]:
        print("[sync] ✗ 拉回后 sha256 与上传元数据不符", file=sys.stderr)
        return 1
    print(f"[sync] ✓ 拉回完成并通过完整性校验：{dest}")
    return 0


def main() -> int:
    bucket = os.environ.get("BACKUP_S3_BUCKET", "").strip()
    if not bucket:
        print("[sync] ✗ 缺 BACKUP_S3_BUCKET（连同 ACCESS/SECRET 必填）", file=sys.stderr)
        return 2
    mode = os.environ.get("BACKUP_MODE", "push")
    client = _client()
    try:
        if mode == "push":
            _ensure_bucket(client, bucket)
            return do_push(client, bucket)
        if mode == "pull":
            return do_pull(client, bucket)
        if mode == "list":
            return do_list(client, bucket)
        print(f"[sync] ✗ 未知模式 {mode}（合法值: push|pull|list）", file=sys.stderr)
        return 2
    # S3UploadFailedError 是 upload_file 的包装异常（非 ClientError 子类），
    # 漏捕会把裸 traceback 吐给 cron（阶段 9 审查实测）—— 显式并入。
    except (BotoCoreError, ClientError, S3UploadFailedError) as exc:
        print(f"[sync] ✗ S3 操作失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
