"""qlib 数据目录只读解析单测：日历 / 标的 / OHLCV bin（float32 列文件）。"""

from __future__ import annotations

from array import array
from pathlib import Path

import pytest

from qqlab.core.qlib_data import (
    DataPathError,
    read_calendar,
    read_instruments,
    read_ohlcv,
)

DATES = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
FIELDS = ("open", "high", "low", "close", "volume", "factor")


def _write_dataset(
    root: Path, *, late_instrument: str | None = None, nested: bool = False
) -> Path:
    """构造 dump_bin 目录：calendars + instruments + features/{inst}/{field}.{freq}.bin。

    ``nested=False``（默认）为实测平铺布局（qlib 官方 GetData zip）；
    ``nested=True`` 为带 ``day/`` 子目录的旧版 dump 布局（解析器两者兼容）。
    """
    (root / "calendars").mkdir(parents=True)
    (root / "instruments").mkdir(parents=True)
    (root / "calendars" / "day.txt").write_text("\n".join(DATES) + "\n")
    (root / "instruments" / "all.txt").write_text("AAA.XSHE\t平安银行\nBBB.XSHG\n")

    for instrument, values in (("AAA.XSHE", 10.0), ("BBB.XSHG", 20.0)):
        days = len(DATES) - (1 if instrument == late_instrument else 0)
        inst_dir = root / "features" / instrument / ("day" if nested else "")
        inst_dir.mkdir(parents=True)
        for i, field in enumerate(FIELDS):
            col = array("f", [values + i + d * 0.1 for d in range(days)])
            (inst_dir / f"{field}.day.bin").write_bytes(col.tobytes())
    return root


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    return _write_dataset(tmp_path / "cn_data")


def test_read_calendar_full_and_range(data_root: Path) -> None:
    assert read_calendar(data_root) == DATES
    assert read_calendar(data_root, start="2024-01-03", end="2024-01-04") == DATES[1:3]
    assert read_calendar(data_root, start="2025-01-01") == []


def test_read_instruments_with_and_without_display(data_root: Path) -> None:
    items = read_instruments(data_root)
    assert items == [
        {"instrument": "AAA.XSHE", "display_name": "平安银行"},
        {"instrument": "BBB.XSHG", "display_name": "BBB.XSHG"},
    ]


def test_read_ohlcv_values_and_pagination(data_root: Path) -> None:
    rows, total = read_ohlcv(data_root, "AAA.XSHE", limit=10)
    assert total == 4
    assert len(rows) == 4
    assert rows[0].date == "2024-01-02"
    assert rows[0].values["open"] == pytest.approx(10.0)
    assert rows[0].values["close"] == pytest.approx(13.0)  # 基价 10 + close 列下标 3 + 首日 0*0.1
    assert rows[1].values["close"] == pytest.approx(13.1)  # 次日 +0.1

    page2, total2 = read_ohlcv(data_root, "AAA.XSHE", limit=2, offset=2)
    assert total2 == 4
    assert [r.date for r in page2] == DATES[2:4]

    windowed, total3 = read_ohlcv(data_root, "AAA.XSHE", start="2024-01-03", end="2024-01-04", limit=10)
    assert total3 == 2
    assert [r.date for r in windowed] == DATES[1:3]


def test_late_listed_instrument_truncates_to_shortest_column(tmp_path: Path) -> None:
    root = _write_dataset(tmp_path / "cn_data", late_instrument="BBB.XSHG")
    rows, total = read_ohlcv(root, "BBB.XSHG", limit=10)
    assert total == 3  # 上市晚一天 → 尾部对齐，首日无数据
    assert [r.date for r in rows] == DATES[1:]


def test_missing_data_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(DataPathError, match="日历文件不存在"):
        read_calendar(tmp_path / "nope")
    with pytest.raises(DataPathError, match="标的文件不存在"):
        read_instruments(tmp_path / "nope")


@pytest.mark.parametrize("bad_instrument", ["../etc", "A/B", "", "a b", "$x"])
def test_path_traversal_rejected(data_root: Path, bad_instrument: str) -> None:
    with pytest.raises(DataPathError):
        read_ohlcv(data_root, bad_instrument, limit=1)


def test_missing_field_file_raises(data_root: Path) -> None:
    (data_root / "features" / "AAA.XSHE" / "close.day.bin").unlink()
    with pytest.raises(DataPathError, match="缺少字段文件"):
        read_ohlcv(data_root, "AAA.XSHE", limit=1)


def test_nested_freq_layout_supported(tmp_path: Path) -> None:
    root = _write_dataset(tmp_path / "cn_data", nested=True)
    rows, total = read_ohlcv(root, "AAA.XSHE", limit=10)
    assert total == 4
    assert rows[0].values["close"] == pytest.approx(13.0)


def test_uppercase_instrument_resolves_lowercase_dir(tmp_path: Path) -> None:
    """all.txt 记 SH600000（大写），存储目录为小写 sh600000（qlib 约定），两种输入都要可读。"""
    root = tmp_path / "cn_data"
    (root / "calendars").mkdir(parents=True)
    (root / "instruments").mkdir(parents=True)
    (root / "calendars" / "day.txt").write_text("\n".join(DATES) + "\n")
    (root / "instruments" / "all.txt").write_text("SH600000\t浦发银行\n")
    inst_dir = root / "features" / "sh600000"
    inst_dir.mkdir(parents=True)
    for i, field in enumerate(FIELDS):
        col = array("f", [8.0 + i + d * 0.1 for d in range(len(DATES))])
        (inst_dir / f"{field}.day.bin").write_bytes(col.tobytes())

    for name in ("SH600000", "sh600000"):
        rows, total = read_ohlcv(root, name, limit=10)
        assert total == 4
        assert rows[0].values["open"] == pytest.approx(8.0)


def test_unknown_instrument_dir_raises(data_root: Path) -> None:
    with pytest.raises(DataPathError, match="标的目录不存在"):
        read_ohlcv(data_root, "SH999999", limit=1)


def test_bad_freq_rejected(data_root: Path) -> None:
    with pytest.raises(DataPathError, match="非法频率"):
        read_ohlcv(data_root, "AAA.XSHE", freq="../../etc", limit=1)
