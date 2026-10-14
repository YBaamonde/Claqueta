from __future__ import annotations


class ServiceError(Exception):
    """Error de una integración externa con mensaje apto para mostrar al usuario."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status


class NotConfigured(ServiceError):
    pass
