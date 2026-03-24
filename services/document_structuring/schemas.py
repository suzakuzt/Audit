from __future__ import annotations

from pydantic import BaseModel, Field


class RawBlock(BaseModel):
    block_id: str
    block_type: str = "text"
    text: str = ""
    page: int = 1
    bbox: list[float] = Field(default_factory=list)
    polygon: list[float] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class MergedBlock(BaseModel):
    block_id: str
    block_type: str = "text"
    text: str = ""
    page: int = 1
    bbox: list[float] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)
    reading_order_index: int | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class KVCandidate(BaseModel):
    candidate_id: str
    label_text: str
    value_text: str
    page: int
    bbox: list[float] = Field(default_factory=list)
    score: float = 0.0
    relation_type: str = "inline"
    label_block_id: str | None = None
    value_block_id: str | None = None
    source_block_ids: list[str] = Field(default_factory=list)


class TableCell(BaseModel):
    text: str
    row_index: int
    col_index: int
    page: int
    bbox: list[float] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)


class TableRow(BaseModel):
    row_index: int
    cells: list[TableCell] = Field(default_factory=list)


class TableCandidate(BaseModel):
    table_id: str
    page: int
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    cells: list[TableCell] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)
    bbox: list[float] = Field(default_factory=list)
    confidence: float = 0.0


class CanonicalDocument(BaseModel):
    doc_id: str = ""
    document_type_candidate: str = "unknown"
    pages: int = 0
    header_blocks: list[MergedBlock] = Field(default_factory=list)
    party_blocks: list[MergedBlock] = Field(default_factory=list)
    address_blocks: list[MergedBlock] = Field(default_factory=list)
    field_candidates: list[KVCandidate] = Field(default_factory=list)
    table_candidates: list[TableCandidate] = Field(default_factory=list)
    amount_candidates: list[KVCandidate] = Field(default_factory=list)
    date_candidates: list[KVCandidate] = Field(default_factory=list)
    footer_blocks: list[MergedBlock] = Field(default_factory=list)
    raw_trace: list[dict[str, object]] = Field(default_factory=list)

