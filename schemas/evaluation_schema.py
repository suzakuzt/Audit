from __future__ import annotations

from pydantic import BaseModel, Field


class EvaluationDetail(BaseModel):
    standard_field: str
    expected_value: str = ''
    ai_value: str = ''
    status: str


class EvaluationResult(BaseModel):
    total_fields: int
    correct_fields: int
    missing_fields: int
    wrong_fields: int
    accuracy: float
    details: list[EvaluationDetail] = Field(default_factory=list)
