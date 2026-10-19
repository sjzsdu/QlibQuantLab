"""CI/stub 用的最小 qlib 数据目录伪造（阶段 8 · F 项，随 scripts/seed_dev.sh --ci 调用）。

在**worker 容器内**执行（需挂载 qlib_data 卷，rw）：
    docker compose exec -T worker python /scripts/fabricate_ci_data.py

只写**缺失或为空**的文件，绝不覆盖真实数据 —— 因此对 dev 栈重复执行是安全的：

- ``calendars/day.txt``   2018-01-01 ~ 2019-12-31 的工作日（dataset 导入 probe 用首末行定区间）
- ``instruments/all.txt`` 30 只占位标的（dataset 导入的标的数；stub 回测不按池过滤）
- ``instruments/csi300.txt`` 同上 —— e2e 种子回测用 ``universe=csi300``（stage6_smoke 同款）

目录根由环境变量拼装（与 qlib_env.data_dir_for 同式）：
    $QLIB_DATA_ROOT / $MOCK_ORG_ID / $QLIB_DATA_SUBDIR
缺失的变量回退到容器内默认值（compose env_file 已注入）。
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

STUB_INSTRUMENTS = 30
CAL_START = datetime.date(2018, 1, 1)
CAL_END = datetime.date(2019, 12, 31)


def data_root() -> Path:
    root = os.environ.get("QLIB_DATA_ROOT", "/qlib_data")
    org = os.environ.get("MOCK_ORG_ID", "dev-org")
    subdir = os.environ.get("QLIB_DATA_SUBDIR", "cn_data")
    return Path(root) / org / subdir


def write_if_missing(path: Path, content: str) -> str:
    """缺失或为空才写；返回 'written' / 'exists'。"""
    if path.exists() and path.read_text(encoding="utf-8").strip():
        return "exists"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "written"


def main() -> int:
    root = data_root()
    days: list[str] = []
    day = CAL_START
    while day <= CAL_END:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += datetime.timedelta(days=1)

    pool_rows = "\n".join(
        f"STUB{i:04d}.XSHE\tSTUB{i:04d}.XSHE" for i in range(STUB_INSTRUMENTS)
    )

    targets = {
        root / "calendars" / "day.txt": "\n".join(days) + "\n",
        root / "instruments" / "all.txt": pool_rows + "\n",
        root / "instruments" / "csi300.txt": pool_rows + "\n",
    }
    for path, content in targets.items():
        state = write_if_missing(path, content)
        print(f"[fabricate] {path}: {state}")
    print(f"[fabricate] root = {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
