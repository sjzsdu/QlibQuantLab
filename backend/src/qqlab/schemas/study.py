"""研究域 schema：因子（阶段 4：表达式 CRUD + 静态校验 + 发布）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FactorCreateIn(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=200)
    expression: str = Field(min_length=1, max_length=500)
    factor_type: str = Field(default="expression", max_length=32)
    description: str | None = None
    params: dict = Field(default_factory=dict)


class FactorUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    expression: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    params: dict | None = None


class FactorOut(BaseModel):
    id: str
    project_id: str
    project_name: str | None = None
    name: str
    expression: str
    factor_type: str
    description: str | None = None
    params: dict = Field(default_factory=dict)
    version: int
    visibility: str
    created_by: str = "（空）"
    created_at: datetime
    updated_at: datetime


class ExpressionCheckIn(BaseModel):
    expression: str = Field(min_length=1, max_length=500)


class ExpressionCheckOut(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)


__all__ = [
    "ExpressionCheckIn",
    "ExpressionCheckOut",
    "FactorCreateIn",
    "FactorOut",
    "FactorUpdateIn",
]
