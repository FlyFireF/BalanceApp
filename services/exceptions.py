"""服务层异常：UI 统一捕获并显示中文提示（需求 §49）。"""

from __future__ import annotations


class ServiceError(Exception):
    """服务层业务异常的基类。"""


class ValidationError(ServiceError, ValueError):
    """输入不合法：金额无效、实体不存在/已停用、类型不匹配等。

    message 为可直接展示给用户的中文提示。
    同时继承 ValueError，便于 UI 层统一捕获客户端与服务端校验错误。
    """


class NotFoundError(ServiceError):
    """目标记录不存在（如删除不存在的交易）。"""
