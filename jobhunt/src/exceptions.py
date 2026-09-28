"""
exceptions.py — typed, structured errors (RFC 7807).
"""

from __future__ import annotations

class JobHuntError(Exception):
    status: int = 500
    code: str = "internal_error"
    def to_dict(self) -> dict:
        return {"error": self.code, "message": str(self), "status": self.status}

class NotFound(JobHuntError):
    status = 404
    code = "not_found"

class ValidationError(JobHuntError):
    status = 422
    code = "validation_error"

class Conflict(JobHuntError):
    status = 409
    code = "conflict"

class RateLimited(JobHuntError):
    status = 429
    code = "rate_limited"
