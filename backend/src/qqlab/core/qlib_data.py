"""qlib 数据目录**只读**访问（纯标准库，API 进程不 import qlib）。

阶段 4 决策：数据集预览在 API 容器内完成 —— backend 挂载 ``qlib_data`` 只读卷，
用 ``array``/``struct`` 直接解析 ``dump_bin`` 产物：

- 日历：``calendars/day.txt``（每行一个 ``YYYY-MM-DD``）
- 标的：``instruments/all.txt``（每行 ``NAME\tDISPLAY_NAME`` 或裸 ``NAME``）
- 行情：``features/{instrument}/{freq}/{field}.{freq}.bin``
  —— qlib ``dump_bin`` 按**列**存 ``float32``，每个字段一个文件

安全约束（与 worker 同源，fail-closed）：
- 组织目录由服务端从 ``CurrentUser.org_id`` 派生，**绝不**接受请求传入；
- instrument / 字段名做白名单正则校验 + ``resolve()`` 后强制 ``is_relative_to`` 数据根，
  杜绝 ``../`` 路径穿越；
- 只读：本模块不提供任何写接口。
"""

from __future__ import annotations

import re
from array import array
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path

#: dump_bin 标准列（顺序即预览表列序）
OHLCV_FIELDS = ("open", "high", "low", "close", "volume", "factor")

#: instrument 名白名单（A 股 6 位代码 / SH.600000 / SH600000 等形式）
_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
#: freq 白名单（防止拼路径注入）
_FREQ_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


class DataPathError(ValueError):
    """路径不合法（穿越/非法字符）或数据目录缺失。"""


@dataclass
class PreviewRow:
    date: str
    values: dict[str, float]  # 字段 → 数值（float32 解析结果）


def _safe_instrument(data_root: Path, instrument: str) -> Path:
    name = (instrument or "").strip()
    if not _INSTRUMENT_RE.fullmatch(name):
        raise DataPathError(f"非法标的代码：{instrument!r}")
    features = (data_root / "features").resolve()
    # 存储目录名小写（qlib 约定），all.txt 里可能是大写（SH600000）
    for candidate in (name, name.lower()):
        target = (features / candidate).resolve()
        if not target.is_relative_to(features):  # noqa: UP038 - 语义清晰优先
            raise DataPathError(f"标的路径越界：{instrument!r}")
        if target.is_dir():
            return target
    raise DataPathError(f"标的目录不存在：{instrument!r}")


def _field_bin_path(instrument_dir: Path, field: str, freq: str) -> Path | None:
    """按 dump_bin 实际布局定位字段文件。

    实测（qlib 官方 GetData zip，2026-10）为**平铺**：``features/{inst}/{field}.{freq}.bin``；
    部分旧版 dump 会多一层频率子目录 ``features/{inst}/{freq}/{field}.{freq}.bin``，
    两种布局都支持（平铺优先）。
    """
    flat = instrument_dir / f"{field}.{freq}.bin"
    if flat.exists():
        return flat
    nested = instrument_dir / freq / f"{field}.{freq}.bin"
    if nested.exists():
        return nested
    return None


def read_calendar(data_root: Path, *, start: str | None = None, end: str | None = None) -> list[str]:
    """读日历（可按 [start, end] 闭区间裁剪）。文件缺失 → DataPathError。"""
    path = data_root / "calendars" / "day.txt"
    if not path.exists():
        raise DataPathError(f"日历文件不存在：{path}（先执行 make qlib-data 导入数据）")
    dates = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    lo = bisect_left(dates, start) if start else 0
    hi = bisect_right(dates, end) if end else len(dates)
    return dates[lo:hi]


def read_instruments(data_root: Path) -> list[dict[str, str]]:
    """读标的列表（all.txt：每行 ``NAME`` 或 ``NAME\\tDISPLAY_NAME``，无日期列）。"""
    path = data_root / "instruments" / "all.txt"
    if not path.exists():
        raise DataPathError(f"标的文件不存在：{path}（先执行 make qlib-data 导入数据）")
    items: list[dict[str, str]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        name = parts[0]
        display = parts[1] if len(parts) > 1 else name
        items.append({"instrument": name, "display_name": display})
    return items


# ------------------------------------------------------------------ 股票池（阶段 6）
#: 股票池文件名白名单（防 ``../`` / 绝对路径注入：不允许任何分隔符）
#: 股票池名合法形态（API schema 的 ``pattern`` 与文件解析共用，防路径穿越）。
#: Pydantic ``pattern`` 是 ``re.search`` 语义，schema 侧须用带锚点的全串变体。
UNIVERSE_NAME_PATTERN = r"[A-Za-z0-9._\-]{1,64}"
UNIVERSE_NAME_ANCHORED_PATTERN = rf"^{UNIVERSE_NAME_PATTERN}$"
_UNIVERSE_NAME_RE = re.compile(UNIVERSE_NAME_ANCHORED_PATTERN)


def list_universes(data_root: Path) -> list[str]:
    """数据集可用股票池名（``instruments/*.txt`` 基名，含 ``all``，字典序）。"""
    inst_dir = data_root / "instruments"
    if not inst_dir.is_dir():
        raise DataPathError(f"标的目录不存在：{inst_dir}（先执行 make qlib-data 导入数据）")
    return sorted(p.stem for p in inst_dir.glob("*.txt") if p.is_file())


def read_universe(data_root: Path, name: str) -> list[str]:
    """读股票池标的列表（去重、保文件序）。

    行格式容错 2 列（``NAME[\\tDISPLAY]``）与 3 列（``NAME\\tSTART\\tEND``，
    qlib 指数成分文件的标准形态）—— 只取第 1 列。

    **静态成分语义**（阶段 6 D6 决策）：START/END 分段区间**不参与过滤**，
    同一标的多段区间行去重后保留 —— 成分按文件快照静态处理，非时点化成分；
    调用方须把该局限写进 data_range / limitations。
    """
    if not _UNIVERSE_NAME_RE.fullmatch(name or ""):
        raise DataPathError(f"非法股票池名：{name!r}")
    path = (data_root / "instruments" / f"{name}.txt").resolve()
    instruments_dir = (data_root / "instruments").resolve()
    if not path.is_relative_to(instruments_dir):  # noqa: UP038 - fail-closed 双保险
        raise DataPathError(f"股票池路径越界：{name!r}")
    if not path.exists():
        available = ", ".join(list_universes(data_root)) or "（无）"
        raise DataPathError(f"股票池不存在：{name}（可用：{available}）")
    names: list[str] = []
    seen: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):  # # 开头为注释行（qlib 生态惯例，容错跳过）
            continue
        first = line.split("\t", 1)[0].strip()
        if first and first not in seen:
            seen.add(first)
            names.append(first)
    if not names:
        raise DataPathError(f"股票池为空：{name}")
    return names


def read_ohlcv(
    data_root: Path,
    instrument: str,
    *,
    freq: str = "day",
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PreviewRow], int]:
    """读某标的 [start, end] 区间 OHLCV（float32 列文件）。

    返回 ``(切片后的行, 区间内总行数)``。

    对齐语义（与 qlib dump_bin 一致）：迟到上市的标的列文件更短，按**日历尾部
    对齐** —— 列的第 0 行对应 ``dates[len(dates) - len(column)]``；某日任一字段
    缺失则该日不出行。
    """
    if not _FREQ_RE.fullmatch(freq or ""):
        raise DataPathError(f"非法频率：{freq!r}")
    instrument_dir = _safe_instrument(data_root, instrument)

    dates = read_calendar(data_root)
    lo = bisect_left(dates, start) if start else 0
    hi = bisect_right(dates, end) if end else len(dates)
    window = dates[lo:hi]
    if not window:
        return [], 0

    columns: dict[str, array] = {}
    for name in OHLCV_FIELDS:
        bin_path = _field_bin_path(instrument_dir, name, freq)
        if bin_path is None:
            raise DataPathError(f"标的 {instrument} 缺少字段文件：{name}.{freq}.bin")
        buf = array("f")
        with bin_path.open("rb") as fh:
            buf.fromfile(fh, bin_path.stat().st_size // 4)
        columns[name] = buf

    # 尾部对齐：每列从「日历末尾 - 列长」处开始有值
    starts = {name: len(dates) - len(col) for name, col in columns.items()}
    first_data_idx = max(starts.values())  # 全字段都有值的起始日历下标

    rows: list[PreviewRow] = []
    total = 0
    for k in range(max(lo, first_data_idx), hi):
        values = {name: float(columns[name][k - starts[name]]) for name in OHLCV_FIELDS}
        total += 1
        if offset <= total - 1 < offset + limit:
            rows.append(PreviewRow(date=dates[k], values=values))
    return rows, total


__all__ = [
    "DataPathError",
    "OHLCV_FIELDS",
    "UNIVERSE_NAME_ANCHORED_PATTERN",
    "UNIVERSE_NAME_PATTERN",
    "PreviewRow",
    "list_universes",
    "read_calendar",
    "read_instruments",
    "read_ohlcv",
    "read_universe",
]
