"""数据集 probe 的降级路径（阶段 8 · D8-12）。

- ``COMPUTE_BACKEND=stub`` → **不触网**，直接文件系统解析（镜像里装了 qlib 也一样）；
- ``COMPUTE_BACKEND=qlib`` → 走 qlib 探测；未装 qlib（ImportError）才回落文件系统。
"""

from __future__ import annotations

from pathlib import Path

from conftest import make_settings
from qqlab.worker.handlers import dataset_import
from qqlab.worker.qlib_env import data_dir_for


def _write_fake_data(root: Path) -> None:
    data = root / "dev-org" / "cn_data"
    (data / "calendars").mkdir(parents=True)
    (data / "instruments").mkdir(parents=True)
    (data / "calendars" / "day.txt").write_text("2018-01-01\n2018-01-02\n", encoding="utf-8")
    (data / "instruments" / "all.txt").write_text("STUB0000.XSHE\n", encoding="utf-8")


def test_stub_probe_uses_filesystem_and_never_touches_qlib(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _write_fake_data(tmp_path)
    settings = make_settings(COMPUTE_BACKEND="stub", QLIB_DATA_ROOT=str(tmp_path))

    def _boom(*_args, **_kwargs):  # noqa: ANN001, ANN202
        raise AssertionError("stub 模式不得进入 qlib 探测")

    monkeypatch.setattr("qqlab.worker.qlib_env.probe_dataset_via_qlib", _boom)
    stats = dataset_import.probe_dataset(settings, "dev-org")
    assert stats["via"] == "filesystem"
    assert stats["start"] == "2018-01-01"
    assert stats["instrument_count"] == 1


def test_qlib_probe_path_used_and_importerror_falls_back(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _write_fake_data(tmp_path)
    settings = make_settings(COMPUTE_BACKEND="qlib", QLIB_DATA_ROOT=str(tmp_path))
    called: list[str] = []

    def _qlib_ok(*_args, **_kwargs):  # noqa: ANN001, ANN202
        called.append("qlib")
        return {"instrument_count": 30, "start": "2018-01-01", "end": "2018-01-02", "via": "qlib"}

    monkeypatch.setattr("qqlab.worker.qlib_env.probe_dataset_via_qlib", _qlib_ok)
    assert dataset_import.probe_dataset(settings, "dev-org")["via"] == "qlib"
    assert called == ["qlib"]

    def _no_qlib(*_args, **_kwargs):  # noqa: ANN001, ANN202
        raise ImportError("qlib 未安装")

    monkeypatch.setattr("qqlab.worker.qlib_env.probe_dataset_via_qlib", _no_qlib)
    stats = dataset_import.probe_dataset(settings, "dev-org")
    assert stats["via"] == "filesystem"
    assert Path(data_dir_for(settings, "dev-org")).exists()
