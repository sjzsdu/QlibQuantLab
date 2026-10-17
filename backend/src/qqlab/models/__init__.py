"""ORM 模型汇总。导入本包即完成所有表的元数据注册（alembic 依赖此副作用）。"""

from qqlab.models.base import Base, JSONType, TenantMixin, TimestampMixin, UUIDPk
from qqlab.models.data import DataLicense, Dataset, DataSource
from qqlab.models.identity import Organization, OrgMember, User
from qqlab.models.job import Job, JobKind, JobLog, JobStatus
from qqlab.models.project import Project, ProjectMember
from qqlab.models.project import Visibility as ProjectVisibility
from qqlab.models.study import (
    Backtest,
    Factor,
    FactorComputeRun,
    MLModel,
    Strategy,
    TrainingRun,
)
from qqlab.models.study import (
    Visibility as StudyVisibility,
)
from qqlab.models.system import AuditLog, SystemConfig

#: 含 org_id 的业务表 —— tests/architecture/test_tenant_columns.py 用它做全量断言
TENANT_MODELS: tuple[type, ...] = (
    Project,
    ProjectMember,
    DataSource,
    DataLicense,
    Dataset,
    Factor,
    FactorComputeRun,
    MLModel,
    TrainingRun,
    Strategy,
    Backtest,
    Job,
    JobLog,
    AuditLog,
    SystemConfig,
    OrgMember,
)

#: 不含 org_id 的表（全局身份）
NON_TENANT_MODELS: tuple[type, ...] = (Organization, User)

ALL_MODELS: tuple[type, ...] = TENANT_MODELS + NON_TENANT_MODELS

__all__ = [
    "ALL_MODELS",
    "AuditLog",
    "Backtest",
    "Base",
    "DataLicense",
    "DataSource",
    "Dataset",
    "Factor",
    "FactorComputeRun",
    "JSONType",
    "Job",
    "JobKind",
    "JobLog",
    "JobStatus",
    "MLModel",
    "NON_TENANT_MODELS",
    "OrgMember",
    "Organization",
    "Project",
    "ProjectMember",
    "ProjectVisibility",
    "Strategy",
    "StudyVisibility",
    "SystemConfig",
    "TENANT_MODELS",
    "TenantMixin",
    "TimestampMixin",
    "TrainingRun",
    "UUIDPk",
    "User",
]
