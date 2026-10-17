"""Errors shared by backend services and HTTP handlers."""


class SessionError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


