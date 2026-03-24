from __future__ import annotations

import re
from typing import Any

from .schemas import RawBlock


DATE_PATTERN = re.compile(r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b")
AMOUNT_PATTERN = re.compile(r"\b(?:USD|CNY|EUR|RMB|US\$|\$|¥)?\s?\d{1,3}(?:,\d{3})*(?:\.\d{1,4})?\b", re.I)
PERCENT_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%\b")
CODE_PATTERN = re.compile(r"\b[A-Z0-9][A-Z0-9._/\-]{2,}\b", re.I)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def ensure_bbox(value: Any) -> list[float]:
    if isinstance(value, list) and len(value) >= 4:
        return [safe_float(value[0]), safe_float(value[1]), safe_float(value[2]), safe_float(value[3])]
    return [0.0, 0.0, 0.0, 0.0]


def bbox_width(bbox: list[float]) -> float:
    return max(0.0, safe_float(bbox[2]) - safe_float(bbox[0]))


def bbox_height(bbox: list[float]) -> float:
    return max(0.0, safe_float(bbox[3]) - safe_float(bbox[1]))


def bbox_center_x(bbox: list[float]) -> float:
    return (safe_float(bbox[0]) + safe_float(bbox[2])) / 2.0


def bbox_center_y(bbox: list[float]) -> float:
    return (safe_float(bbox[1]) + safe_float(bbox[3])) / 2.0


def union_bbox(*bboxes: list[float]) -> list[float]:
    valid = [ensure_bbox(item) for item in bboxes if isinstance(item, list) and len(item) >= 4]
    if not valid:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        min(item[0] for item in valid),
        min(item[1] for item in valid),
        max(item[2] for item in valid),
        max(item[3] for item in valid),
    ]


def y_overlap_ratio(a: list[float], b: list[float]) -> float:
    a1, a2 = safe_float(a[1]), safe_float(a[3])
    b1, b2 = safe_float(b[1]), safe_float(b[3])
    overlap = max(0.0, min(a2, b2) - max(a1, b1))
    base = max(1.0, min(max(0.0, a2 - a1), max(0.0, b2 - b1)))
    return overlap / base


def x_overlap_ratio(a: list[float], b: list[float]) -> float:
    a1, a2 = safe_float(a[0]), safe_float(a[2])
    b1, b2 = safe_float(b[0]), safe_float(b[2])
    overlap = max(0.0, min(a2, b2) - max(a1, b1))
    base = max(1.0, min(max(0.0, a2 - a1), max(0.0, b2 - b1)))
    return overlap / base


def is_date_like(value: str) -> bool:
    return bool(DATE_PATTERN.search(str(value or "")))


def is_amount_like(value: str) -> bool:
    text = str(value or "")
    return bool(AMOUNT_PATTERN.search(text)) and not bool(PERCENT_PATTERN.search(text))


def is_percent_like(value: str) -> bool:
    return bool(PERCENT_PATTERN.search(str(value or "")))


def is_identifier_like(value: str) -> bool:
    text = normalize_text(value)
    return bool(CODE_PATTERN.search(text))


def infer_document_type(text: str) -> str:
    lowered = str(text or "").lower()
    if "proforma invoice" in lowered or "invoice" in lowered:
        return "invoice"
    if "contract" in lowered:
        return "contract"
    if "packing list" in lowered:
        return "packing_list"
    if "bill of lading" in lowered or "b/l" in lowered:
        return "bill_of_lading"
    return "unknown"


def flatten_paddle_blocks(raw_payload: dict[str, Any]) -> list[RawBlock]:
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    layout_results = result.get("layoutParsingResults") if isinstance(result, dict) else None
    if not isinstance(layout_results, list):
        layout_results = payload.get("layoutParsingResults") if isinstance(payload.get("layoutParsingResults"), list) else []
    blocks: list[RawBlock] = []
    for page_index, page_item in enumerate(layout_results, start=1):
        page_dict = page_item if isinstance(page_item, dict) else {}
        pruned = page_dict.get("prunedResult") if isinstance(page_dict.get("prunedResult"), dict) else {}
        parsing_list = pruned.get("parsing_res_list") if isinstance(pruned.get("parsing_res_list"), list) else []
        for idx, block in enumerate(parsing_list, start=1):
            if not isinstance(block, dict):
                continue
            block_text = normalize_text(block.get("block_content") or block.get("text") or "")
            if not block_text:
                continue
            bbox = ensure_bbox(block.get("block_bbox") or block.get("bbox") or [])
            polygon = block.get("polygon") if isinstance(block.get("polygon"), list) else []
            block_id = f"raw_{page_index}_{idx}"
            blocks.append(
                RawBlock(
                    block_id=block_id,
                    block_type=str(block.get("block_label") or block.get("block_type") or "text"),
                    text=block_text,
                    page=page_index,
                    bbox=bbox,
                    polygon=polygon,
                    metadata={
                        "raw_index": idx,
                        "width": pruned.get("width"),
                        "height": pruned.get("height"),
                    },
                )
            )
    if blocks:
        return blocks
    # fallback: try generic blocks array from preview payload
    preview_blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    for idx, block in enumerate(preview_blocks, start=1):
        if not isinstance(block, dict):
            continue
        text = normalize_text(block.get("text", ""))
        if not text:
            continue
        bbox = [
            safe_float(block.get("x0")),
            safe_float(block.get("top")),
            safe_float(block.get("x1")),
            safe_float(block.get("bottom")),
        ]
        blocks.append(
            RawBlock(
                block_id=f"raw_1_{idx}",
                block_type=str(block.get("label") or "text"),
                text=text,
                page=1,
                bbox=bbox,
                metadata={"raw_index": idx},
            )
        )
    return blocks

