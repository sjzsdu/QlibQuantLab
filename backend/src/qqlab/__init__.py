"""QlibQuantLab 后端。

- ``qqlab.api`` / ``qqlab.services`` / ``qqlab.repositories`` / ``qqlab.models`` / ``qqlab.core``：
  业务代码，只依赖 ``qqlab.ports``；
- ``qqlab.adapters``：具体实现（redis / aio-pika / boto3 / qlib / casdoor）；
- ``qqlab.container``：唯一的装配点。
"""

__version__ = "0.1.0"
