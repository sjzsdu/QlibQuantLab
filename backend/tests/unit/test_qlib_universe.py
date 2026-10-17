"""股票池解析与提交期校验（阶段 6 D6）。

- ``read_universe``：2 列/3 列行容错、去重保文件序、``#`` 注释行跳过、
  非法池名（路径穿越）拒绝、空池报错、未知池名列出可用项；
- ``ensure_universe``：all 未导入放行 / 非 all 未导入 422 / 已导入按文件校验 /
  越出 org 目录 404（fail-closed）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_settings
from qqlab.core.errors import NotFoundError, UnprocessableInputError
from qqlab.core.qlib_data import DataPathError, list_universes, read_universe
from qqlab.services.base import ensure_universe


def _write_instruments(root: Path, files: dict[str, str]) -> None:
    inst = root / "instruments"
    inst.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (inst / f"{name}.txt").write_text(content)


class TestReadUniverse:
    def test_two_column_and_dedup_preserve_file_order(self, tmp_path: Path) -> None:
        _write_instruments(
            tmp_path,
            {"csi300": "SH600000\t浦发银行\nSZ000001\t平安银行\nSH600000\t浦发银行（重复行）\n"},
        )
        assert read_universe(tmp_path, "csi300") == ["SH600000", "SZ000001"]

    def test_three_column_segments_are_static_constituents(self, tmp_path: Path) -> None:
        """3 列分段（START/END）只取第 1 列，多段去重保留文件序（静态成分语义）。"""
        _write_instruments(
            tmp_path,
            {
                "csi300": (
                    "SH600000\t2005-01-01\t2010-12-31\n"
                    "SH600004\t2018-12-17\t2020-09-25\n"
                    "SH600000\t2015-01-01\t2020-09-25\n"
                )
            },
        )
        assert read_universe(tmp_path, "csi300") == ["SH600000", "SH600004"]

    def test_comment_and_blank_lines_skipped(self, tmp_path: Path) -> None:
        _write_instruments(tmp_path, {"all": "# 注释行\n\nSH600000\n\n#另一个注释\nSZ000001\n"})
        assert read_universe(tmp_path, "all") == ["SH600000", "SZ000001"]

    def test_illegal_name_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(DataPathError, match="非法股票池名"):
            read_universe(tmp_path, "../evil")
        with pytest.raises(DataPathError, match="非法股票池名"):
            read_universe(tmp_path, "")

    def test_unknown_name_lists_available(self, tmp_path: Path) -> None:
        _write_instruments(tmp_path, {"all": "SH600000\n", "csi300": "SH600000\n"})
        with pytest.raises(DataPathError) as exc:
            read_universe(tmp_path, "bogus")
        assert "股票池不存在：bogus" in str(exc.value)
        assert "all" in str(exc.value) and "csi300" in str(exc.value)

    def test_empty_pool_raises(self, tmp_path: Path) -> None:
        _write_instruments(tmp_path, {"empty": "\n#只有注释\n"})
        with pytest.raises(DataPathError, match="股票池为空"):
            read_universe(tmp_path, "empty")

    def test_list_universes_sorted(self, tmp_path: Path) -> None:
        _write_instruments(tmp_path, {"csi500": "A\n", "all": "A\n", "csi300": "A\n"})
        assert list_universes(tmp_path) == ["all", "csi300", "csi500"]

    def test_missing_instruments_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DataPathError, match="标的目录不存在"):
            list_universes(tmp_path)


class TestEnsureUniverse:
    def _setup(self, tmp_path: Path, files: dict[str, str] | None = None) -> tuple:
        settings = make_settings(QLIB_DATA_ROOT=str(tmp_path))
        org_dir = tmp_path / "dev-org" / "cn_data"
        if files is not None:
            _write_instruments(org_dir, files)
        return settings, str(org_dir)

    def test_all_without_storage_passes(self, tmp_path: Path) -> None:
        settings, _ = self._setup(tmp_path)
        ensure_universe(settings, org_id="dev-org", storage_uri=None, universe="all")

    def test_non_all_without_storage_rejected(self, tmp_path: Path) -> None:
        settings, _ = self._setup(tmp_path)
        with pytest.raises(UnprocessableInputError, match="尚未导入"):
            ensure_universe(settings, org_id="dev-org", storage_uri=None, universe="csi300")

    def test_valid_universe_passes(self, tmp_path: Path) -> None:
        settings, org_dir = self._setup(tmp_path, {"all": "SH600000\n", "csi300": "SH600000\n"})
        ensure_universe(settings, org_id="dev-org", storage_uri=org_dir, universe="csi300")
        ensure_universe(settings, org_id="dev-org", storage_uri=org_dir, universe="all")

    def test_unknown_universe_rejected_with_available(self, tmp_path: Path) -> None:
        settings, org_dir = self._setup(tmp_path, {"all": "SH600000\n", "csi300": "SH600000\n"})
        with pytest.raises(UnprocessableInputError) as exc:
            ensure_universe(settings, org_id="dev-org", storage_uri=org_dir, universe="zzz")
        assert exc.value.code == 1011
        assert "all" in str(exc.value) and "csi300" in str(exc.value)

    def test_storage_outside_org_root_rejected(self, tmp_path: Path) -> None:
        settings, org_dir = self._setup(tmp_path, {"csi300": "SH600000\n"})
        other = tmp_path / "other-org" / "cn_data"
        with pytest.raises(NotFoundError, match="数据目录不属于当前组织"):
            ensure_universe(settings, org_id="dev-org", storage_uri=str(other), universe="csi300")
        assert org_dir  # 组织目录存在也不能越界访问他组织路径
