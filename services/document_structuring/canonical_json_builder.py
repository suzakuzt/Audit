from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .block_merger import BlockMergerConfig, merge_blocks
from .kv_pair_builder import KVBuilderConfig, build_kv_candidates
from .reading_order import assign_reading_order
from .schemas import CanonicalDocument, KVCandidate, MergedBlock, RawBlock, TableCandidate
from .table_structurer import TableStructurerConfig, build_table_candidates
from .utils import flatten_paddle_blocks, infer_document_type, is_amount_like, is_date_like, normalize_text


@dataclass(slots=True)
class CanonicalJSONBuildResult:
    canonical: CanonicalDocument
    raw_blocks: list[RawBlock]
    merged_blocks: list[MergedBlock]
    reading_order_blocks: list[MergedBlock]
    kv_candidates: list[KVCandidate]
    table_candidates: list[TableCandidate]

    def to_debug_payload(self) -> dict[str, Any]:
        return {
            "raw_blocks": [item.model_dump() for item in self.raw_blocks],
            "merged_blocks": [item.model_dump() for item in self.merged_blocks],
            "reading_order": [item.model_dump() for item in self.reading_order_blocks],
            "kv_candidates": [item.model_dump() for item in self.kv_candidates],
            "table_candidates": [item.model_dump() for item in self.table_candidates],
            "canonical": self.canonical.model_dump(),
        }


class CanonicalJSONBuilder:
    def __init__(
        self,
        block_merger_config: BlockMergerConfig | None = None,
        kv_builder_config: KVBuilderConfig | None = None,
        table_structurer_config: TableStructurerConfig | None = None,
    ) -> None:
        self.block_merger_config = block_merger_config or BlockMergerConfig()
        self.kv_builder_config = kv_builder_config or KVBuilderConfig()
        self.table_structurer_config = table_structurer_config or TableStructurerConfig()

    def build_from_raw(self, raw_payload: dict[str, Any], doc_id: str | None = None) -> CanonicalJSONBuildResult:
        raw_blocks = flatten_paddle_blocks(raw_payload)
        merged_blocks = merge_blocks(raw_blocks, self.block_merger_config)
        ordered_blocks = assign_reading_order(merged_blocks)
        kv_candidates = build_kv_candidates(ordered_blocks, self.kv_builder_config)
        table_candidates = build_table_candidates(ordered_blocks, self.table_structurer_config)
        canonical = self._build_canonical_document(
            doc_id=doc_id or str(uuid4()),
            blocks=ordered_blocks,
            kv_candidates=kv_candidates,
            tables=table_candidates,
        )
        return CanonicalJSONBuildResult(
            canonical=canonical,
            raw_blocks=raw_blocks,
            merged_blocks=merged_blocks,
            reading_order_blocks=ordered_blocks,
            kv_candidates=kv_candidates,
            table_candidates=table_candidates,
        )

    def build_deepseek_payload(self, canonical: CanonicalDocument) -> dict[str, Any]:
        # DeepSeek input adapter: strips polygon noise and constrains model to choose from candidates.
        candidate_pool = [
            {
                "candidate_id": item.candidate_id,
                "label_text": item.label_text,
                "value_text": item.value_text,
                "page": item.page,
                "bbox": item.bbox,
                "source_block_ids": item.source_block_ids,
                "score": item.score,
            }
            for item in canonical.field_candidates
        ]
        return {
            "task": "field_normalization_from_candidates_only",
            "constraints": {
                "must_select_from_candidates_only": True,
                "missing_value_should_be_null": True,
                "no_hallucination": True,
                "output_must_include_evidence_and_confidence": True,
            },
            "document_context": {
                "doc_id": canonical.doc_id,
                "document_type_candidate": canonical.document_type_candidate,
                "pages": canonical.pages,
            },
            "candidate_pool": candidate_pool,
            "table_candidates": [table.model_dump() for table in canonical.table_candidates],
            "expected_output_schema": {
                "fields": "dict[str, {value: str | null, evidence_candidate_id: str | null, confidence: float}]",
                "document_type": "str | null",
            },
        }

    def _build_canonical_document(
        self,
        *,
        doc_id: str,
        blocks: list[MergedBlock],
        kv_candidates: list[KVCandidate],
        tables: list[TableCandidate],
    ) -> CanonicalDocument:
        full_text = "\n".join(item.text for item in blocks)
        doc_type = infer_document_type(full_text)
        page_count = max((item.page for item in blocks), default=0)

        header_blocks: list[MergedBlock] = []
        party_blocks: list[MergedBlock] = []
        address_blocks: list[MergedBlock] = []
        footer_blocks: list[MergedBlock] = []

        for block in blocks:
            text_lower = normalize_text(block.text).lower()
            y_top = block.bbox[1] if len(block.bbox) >= 2 else 0
            y_bottom = block.bbox[3] if len(block.bbox) >= 4 else 0
            if y_top <= 220 or any(token in text_lower for token in ("invoice", "contract", "date", "no.", "no ", "ref")):
                header_blocks.append(block)
            if any(token in text_lower for token in ("buyer", "seller", "consignee", "shipper", "notify", "client")):
                party_blocks.append(block)
            if _looks_like_address(text_lower):
                address_blocks.append(block)
            if y_bottom >= 1200 or any(token in text_lower for token in ("payment", "remark", "declaration", "terms", "note")):
                footer_blocks.append(block)

        amount_candidates = [item for item in kv_candidates if is_amount_like(item.value_text)]
        date_candidates = [item for item in kv_candidates if is_date_like(item.value_text)]
        raw_trace = [
            {
                "merged_block_id": block.block_id,
                "page": block.page,
                "bbox": block.bbox,
                "source_block_ids": block.source_block_ids,
            }
            for block in blocks
        ]

        return CanonicalDocument(
            doc_id=doc_id,
            document_type_candidate=doc_type,
            pages=page_count,
            header_blocks=header_blocks,
            party_blocks=_dedupe_blocks(party_blocks),
            address_blocks=_dedupe_blocks(address_blocks),
            field_candidates=kv_candidates,
            table_candidates=tables,
            amount_candidates=amount_candidates,
            date_candidates=date_candidates,
            footer_blocks=_dedupe_blocks(footer_blocks),
            raw_trace=raw_trace,
        )


def _looks_like_address(text_lower: str) -> bool:
    return any(
        token in text_lower
        for token in (
            "address",
            "addr",
            "road",
            "street",
            "district",
            "city",
            "province",
            "room",
            "floor",
            "china",
            "usa",
        )
    )


def _dedupe_blocks(blocks: list[MergedBlock]) -> list[MergedBlock]:
    seen: set[str] = set()
    result: list[MergedBlock] = []
    for block in blocks:
        if block.block_id in seen:
            continue
        seen.add(block.block_id)
        result.append(block)
    return result

