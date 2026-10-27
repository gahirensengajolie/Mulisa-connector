"""Schemas for what we send BACK to the core system."""

from typing import Literal

from pydantic import BaseModel

Decision = Literal["cleared", "flagged", "unavailable"]
Action = Literal["release", "hold"]
Reason = Literal[
    "timeout",
    "upstream_error",
    "upstream_rejected",
    "upstream_unreachable",
    "upstream_bad_response",
]


class ScreenResponse(BaseModel):
    reference: str
    decision: Decision
    recommended_action: Action
    screening_id: str | None = None
    risk_score: float | None = None
    matched_rules: list[str] = []
    policy_applied: Literal["fail_open", "fail_closed"] | None = None  # only when unavailable
    reason: Reason | None = None  # only when unavailable
    replayed: bool
    attempts: int
    request_id: str


class ErrorDetail(BaseModel):
    field: str
    code: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[ErrorDetail] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody
