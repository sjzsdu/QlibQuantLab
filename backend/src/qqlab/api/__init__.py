"""API 层：路由、依赖注入、响应信封。"""

from qqlab.api.deps import failure, success
from qqlab.api.router import api_router

__all__ = ["api_router", "failure", "success"]
