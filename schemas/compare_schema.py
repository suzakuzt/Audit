from __future__ import annotations

from pydantic import BaseModel, Field


class CompareSummarySchema(BaseModel):
    match_status: str
    overall_conclusion: str
    total_mismatches: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int


class MismatchEvidenceSchema(BaseModel):
    document_a: list[str] = Field(default_factory=list)
    document_b: list[str] = Field(default_factory=list)


class MismatchItemSchema(BaseModel):
    field_name: str
    field_path: str
    document_a_value: str | None = None
    document_b_value: str | None = None
    difference_type: str
    risk_level: str
    confidence: str
    reason: str
    evidence: MismatchEvidenceSchema = Field(default_factory=MismatchEvidenceSchema)


class MatchedFieldSchema(BaseModel):
    field_name: str
    field_path: str
    value: str | None = None


class UncertainItemSchema(BaseModel):
    field_name: str
    reason: str


class CompareSchema(BaseModel):
    summary: CompareSummarySchema
    mismatch_list: list[MismatchItemSchema] = Field(default_factory=list)
    matched_fields: list[MatchedFieldSchema] = Field(default_factory=list)
    uncertain_items: list[UncertainItemSchema] = Field(default_factory=list)
