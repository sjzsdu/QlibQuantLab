"""服务层：业务编排（不 import FastAPI，也不 import adapters）。"""

from qqlab.services.admin_service import AdminService
from qqlab.services.audit_service import AuditService
from qqlab.services.auth_service import AuthService, LoginStart, SessionBundle, safe_redirect
from qqlab.services.base import AuditContext
from qqlab.services.data_service import DataLicenseService, DatasetService, DataSourceService
from qqlab.services.factor_service import FactorService
from qqlab.services.job_query_service import JobQueryService
from qqlab.services.job_service import JobService
from qqlab.services.legal_service import LEGAL_DOCS, legal_doc, legal_meta
from qqlab.services.project_service import ProjectService

__all__ = [
    "AdminService",
    "AuditContext",
    "AuditService",
    "AuthService",
    "DataLicenseService",
    "DataSourceService",
    "DatasetService",
    "FactorService",
    "JobQueryService",
    "JobService",
    "LEGAL_DOCS",
    "LoginStart",
    "ProjectService",
    "SessionBundle",
    "legal_doc",
    "legal_meta",
    "safe_redirect",
]
