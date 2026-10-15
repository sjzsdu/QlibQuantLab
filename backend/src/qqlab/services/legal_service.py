"""静态法务文档：用户协议 / 风险提示 / 免责声明。

**只读**：不存库、不可由 API 修改、租户不可编辑（合规要求：发布前需法务审阅）。
源文件放在 ``qqlab/legal/*.md``，随包分发。
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

from qqlab.core.errors import NotFoundError
from qqlab.schemas import LegalDocOut, LegalMetaOut

#: code → (标题, 生效日期, 文件名)
LEGAL_DOCS: dict[str, tuple[str, str, str]] = {
    "terms": ("用户协议", "2026-10-14", "terms.md"),
    "risk": ("风险提示", "2026-10-14", "risk.md"),
    "disclaimer": ("免责声明", "2026-10-14", "disclaimer.md"),
}

_VERSION = "v1"


@lru_cache(maxsize=1)
def _root():  # noqa: ANN201
    return resources.files("qqlab").joinpath("legal")


def _read(filename: str) -> str:
    return _root().joinpath(filename).read_text(encoding="utf-8")


def legal_meta() -> list[LegalMetaOut]:
    return [
        LegalMetaOut(code=code, title=title, version=_VERSION, effective_at=effective)
        for code, (title, effective, _) in LEGAL_DOCS.items()
    ]


def legal_doc(code: str) -> LegalDocOut:
    entry = LEGAL_DOCS.get(code)
    if entry is None:
        raise NotFoundError(f"未知的法务文档: {code}")
    title, effective, filename = entry
    return LegalDocOut(
        code=code,
        title=title,
        version=_VERSION,
        effective_at=effective,
        content=_read(filename),
    )


__all__ = ["LEGAL_DOCS", "legal_doc", "legal_meta"]
